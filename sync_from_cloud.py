import os
import json
import time
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "finplus_portfolio_backup.json")
JOURNAL_FILE = os.path.join(BASE_DIR, "finplus_journal_data.json")

def sync():
    print("[1/2] Synchronizing with Render Cloud (https://finplus.onrender.com)...")
    
    # Load current local portfolio backup if present
    master_data = None
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                master_data = json.load(f)
        except Exception:
            master_data = None

    # Try fetching from Render Cloud
    cloud_data = None
    try:
        res = requests.get("https://finplus.onrender.com/api/backup/load", timeout=8)
        if res.status_code == 200:
            resp_json = res.json()
            if resp_json and resp_json.get("status") == "success" and resp_json.get("data"):
                cloud_data = resp_json["data"]
    except Exception as e:
        print(f" -> Render Cloud read info: {e}")

    local_saved_at = int(master_data.get("savedAt", 0)) if master_data else 0
    cloud_saved_at = int(cloud_data.get("savedAt", 0)) if cloud_data else 0

    local_is_fresh = bool(master_data and (master_data.get("isFreshStart") or master_data.get("savedAt", 0) >= 1788500000000))
    cloud_is_fresh = bool(cloud_data and (cloud_data.get("isFreshStart") or cloud_data.get("savedAt", 0) >= 1788500000000))

    if cloud_data and not local_is_fresh:
        if not master_data or cloud_saved_at >= local_saved_at:
            master_data = cloud_data
            print(f" -> Loaded portfolio dataset from Render Cloud (Cloud savedAt: {cloud_saved_at} >= Local savedAt: {local_saved_at}).")
        else:
            print(" -> Smart Merging Cloud and Local portfolio datasets...")
            merged_sold = { (s.get("id") or f"{s.get('ticker')}_{s.get('sellDate')}"): s for s in master_data.get("soldHistory", []) if isinstance(s, dict) }
            for s in cloud_data.get("soldHistory", []):
                if isinstance(s, dict):
                    key = s.get("id") or f"{s.get('ticker')}_{s.get('sellDate')}"
                    if key not in merged_sold:
                        merged_sold[key] = s
            master_data["soldHistory"] = list(merged_sold.values())

            merged_opt = { (o.get("id") or f"{o.get('entryDate')}_{o.get('instrument')}"): o for o in master_data.get("optionsTrades", []) if isinstance(o, dict) }
            for o in cloud_data.get("optionsTrades", []):
                if isinstance(o, dict):
                    key = o.get("id") or f"{o.get('entryDate')}_{o.get('instrument')}"
                    if key not in merged_opt:
                        merged_opt[key] = o
            master_data["optionsTrades"] = list(merged_opt.values())

            merged_adj = { (a.get("id") or f"{a.get('date')}_{a.get('amount')}"): a for a in master_data.get("brokerAdjustments", []) if isinstance(a, dict) }
            for a in cloud_data.get("brokerAdjustments", []):
                if isinstance(a, dict):
                    key = a.get("id") or f"{a.get('date')}_{a.get('amount')}"
                    if key not in merged_adj:
                        merged_adj[key] = a
            master_data["brokerAdjustments"] = list(merged_adj.values())

            merged_cap = { (c.get("id") or f"{c.get('date')}_{c.get('amount')}"): c for c in master_data.get("capitalLedger", []) if isinstance(c, dict) }
            for c in cloud_data.get("capitalLedger", []):
                if isinstance(c, dict):
                    key = c.get("id") or f"{c.get('date')}_{c.get('amount')}"
                    if key not in merged_cap:
                        merged_cap[key] = c
            master_data["capitalLedger"] = list(merged_cap.values())

            if not master_data.get("freeCash") and cloud_data.get("freeCash"):
                master_data["freeCash"] = cloud_data["freeCash"]
    elif local_is_fresh:
        print(" -> Clean slate / fresh start active. Preserving fresh 0-state and overriding cloud.")

    if not master_data:
        master_data = {
            "positions": [],
            "capitalLedger": [],
            "freeCash": {"swing": "0", "lt": "0", "penny": "0"},
            "soldHistory": [],
            "budget": "0",
            "split": {"swing": 60, "lt": 30, "penny": 10},
            "isFreshStart": True,
            "savedAt": int(time.time() * 1000)
        }

    # CRITICAL AUDIT PURGE: Filter out any active position whose ID or ticker exists in soldHistory
    sold_history = master_data.get("soldHistory", [])
    sold_keys = set()
    for s in sold_history:
        if isinstance(s, dict):
            if s.get("id"): sold_keys.add(s.get("id"))
            if s.get("ticker"): sold_keys.add(s.get("ticker"))

    raw_pos = master_data.get("positions", [])
    cleaned_pos = [
        p for p in raw_pos
        if isinstance(p, dict) and p.get("id") not in sold_keys and p.get("ticker") not in sold_keys
    ]
    master_data["positions"] = cleaned_pos
    master_data["savedAt"] = max(local_saved_at, cloud_saved_at, int(time.time() * 1000))

    # Save to local portfolio backup file
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(master_data, f, indent=2)
    print(f" -> Local finplus_portfolio_backup.json updated ({len(cleaned_pos)} active positions, {len(master_data.get('optionsTrades', []))} options trades).")

    # Update Render Cloud with master dataset
    try:
        cloud_payload = dict(master_data)
        if local_is_fresh:
            cloud_payload["force_reset"] = True
            cloud_payload["reset"] = True
            cloud_payload["isFreshStart"] = True
        requests.post("https://finplus.onrender.com/api/backup/save", json=cloud_payload, timeout=10)
        print(" -> Render Cloud dataset successfully synced.")
    except Exception as e:
        print(f" -> Cloud sync notice: {e}")

    # Write journal file
    with open(JOURNAL_FILE, "w", encoding="utf-8") as jf:
        journal_trades = [
            {
                "uuid": p["id"],
                "symbol": p["ticker"],
                "entry_price": p["buyPrice"],
                "quantity": p["shares"],
                "target_price": p.get("target1", 0),
                "stop_loss": p.get("stopLoss", 0),
                "instrument_type": "Delivery",
                "status": "ACTIVE",
                "created_at": p.get("buyDate", "2026-08-23")
            }
            for p in master_data.get("positions", [])
        ]
        json.dump(journal_trades, jf, indent=2)

if __name__ == "__main__":
    sync()
