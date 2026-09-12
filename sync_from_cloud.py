import os
import json
import time
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "finplus_portfolio_backup.json")
JOURNAL_FILE = os.path.join(BASE_DIR, "finplus_journal_data.json")

API_KEY_FILE = os.path.join(BASE_DIR, "finplus_api_key.txt")

def get_api_key():
    key = os.environ.get("FINPLUS_API_KEY", "").strip()
    if not key and os.path.exists(API_KEY_FILE):
        try:
            with open(API_KEY_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("FINPLUS_API_KEY"):
                        key = line.split("=")[1].strip()
                        break
        except Exception:
            pass
    return key

def sync():
    print("[1/2] Synchronizing with Render Cloud (https://finplus.onrender.com)...")
    api_key = get_api_key()
    headers = {"X-Finplus-Key": api_key} if api_key else {}
    
    # Load current local portfolio backup if present
    master_data = None
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                master_data = json.load(f)
        except Exception:
            master_data = None

    # Try fetching from Render Cloud with cold start handling
    cloud_data = None
    for attempt in range(1, 3):
        try:
            timeout = 15 if attempt == 1 else 35
            if attempt > 1:
                print(" -> Render Cloud is waking up from idle sleep (waiting for cold start)...")
            res = requests.get("https://finplus.onrender.com/api/backup/load", headers=headers, timeout=timeout)
            if res.status_code == 200:
                resp_json = res.json()
                if resp_json and resp_json.get("status") == "success" and resp_json.get("data"):
                    cloud_data = resp_json["data"]
                    break
            elif res.status_code == 401:
                print(" -> Render Cloud requires valid FINPLUS_API_KEY.")
                break
        except requests.exceptions.Timeout:
            if attempt == 1:
                continue
            print(" -> Render Cloud read info: Connection timed out (Render cold start took longer than expected).")
        except Exception as e:
            print(f" -> Render Cloud read info: {e}")
            break

    local_saved_at = int(master_data.get("savedAt", 0)) if master_data else 0
    cloud_saved_at = int(cloud_data.get("savedAt", 0)) if cloud_data else 0

    local_is_fresh = bool(master_data and master_data.get("isFreshStart"))
    cloud_is_fresh = bool(cloud_data and cloud_data.get("isFreshStart"))

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

    # Filter out active positions whose ID exists in soldHistory (strictly by ID, NEVER by ticker)
    sold_history = master_data.get("soldHistory", [])
    sold_keys = set()
    for s in sold_history:
        if isinstance(s, dict) and s.get("id"):
            sold_keys.add(s.get("id"))

    raw_pos = master_data.get("positions", [])
    cleaned_pos = [
        p for p in raw_pos
        if isinstance(p, dict) and p.get("id") and p.get("id") not in sold_keys
    ]
    master_data["positions"] = cleaned_pos
    if cloud_data is not None or local_is_fresh:
        master_data["savedAt"] = max(local_saved_at, cloud_saved_at, int(time.time() * 1000))
    else:
        master_data["savedAt"] = local_saved_at

    # Save to local portfolio backup file
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(master_data, f, indent=2)
    print(f" -> Local finplus_portfolio_backup.json updated ({len(cleaned_pos)} active positions, {len(master_data.get('optionsTrades', []))} options trades).")

    # Update Render Cloud with master dataset if cloud is reachable or fresh start
    if cloud_data is not None or local_is_fresh:
        try:
            cloud_payload = dict(master_data)
            if local_is_fresh:
                cloud_payload["force_reset"] = True
                cloud_payload["reset"] = True
                cloud_payload["isFreshStart"] = True
            requests.post("https://finplus.onrender.com/api/backup/save", json=cloud_payload, headers=headers, timeout=20)
            print(" -> Render Cloud dataset successfully synced.")
        except Exception as e:
            print(f" -> Cloud sync notice: {e}")
    else:
        print(" -> Cloud backend currently unreachable; keeping local copy safe without overwriting cloud.")

    # Write journal file (preserving both active positions and closed trades)
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
            if isinstance(p, dict) and p.get("id")
        ]
        for s in master_data.get("soldHistory", []):
            if isinstance(s, dict) and s.get("id"):
                journal_trades.append({
                    "uuid": s["id"],
                    "symbol": s.get("ticker", ""),
                    "entry_price": s.get("buyPrice", 0),
                    "quantity": s.get("shares", 0),
                    "exit_price": s.get("sellPrice", 0),
                    "target_price": 0,
                    "stop_loss": 0,
                    "instrument_type": "Delivery",
                    "status": "CLOSED",
                    "created_at": s.get("buyDate") or s.get("sellDate", "2026-08-23")
                })
        json.dump(journal_trades, jf, indent=2)

    # Synchronize Risk Desk dataset (finplus_risk_desk.json) so trades are never lost on restart
    try:
        risk_file = os.path.join(BASE_DIR, "finplus_risk_desk.json")
        local_risk = None
        if os.path.exists(risk_file):
            try:
                with open(risk_file, "r", encoding="utf-8") as rf:
                    local_risk = json.load(rf)
            except Exception:
                local_risk = None

        cloud_risk = None
        res = requests.get("https://finplus.onrender.com/api/risk/sync", headers=headers, timeout=20)
        if res.status_code == 200:
            resp_data = res.json()
            if isinstance(resp_data, dict):
                cloud_risk = resp_data

        if cloud_risk or local_risk:
            merged_risk = dict(local_risk or cloud_risk or {})
            if cloud_risk and local_risk:
                local_trades = { t.get("id"): t for t in local_risk.get("trades", []) if isinstance(t, dict) and t.get("id") }
                for ct in cloud_risk.get("trades", []):
                    if isinstance(ct, dict) and ct.get("id"):
                        if ct["id"] not in local_trades:
                            local_trades[ct["id"]] = ct
                        else:
                            c_up = str(ct.get("updated_at") or ct.get("at") or "")
                            l_up = str(local_trades[ct["id"]].get("updated_at") or local_trades[ct["id"]].get("at") or "")
                            if c_up > l_up:
                                local_trades[ct["id"]] = ct
                merged_risk["trades"] = list(local_trades.values())
            
            with open(risk_file, "w", encoding="utf-8") as rf:
                json.dump(merged_risk, rf, indent=2)
            print(f" -> Risk Desk dataset synchronized ({len(merged_risk.get('trades', []))} trades preserved).")
    except Exception as e:
        print(f" -> Risk Desk sync notice: {e}")

if __name__ == "__main__":
    sync()
