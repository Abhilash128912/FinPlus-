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
        res = requests.get("https://finplus.onrender.com/api/backup/load", timeout=5)
        if res.status_code == 200:
            resp_json = res.json()
            if resp_json and resp_json.get("status") == "success" and resp_json.get("data"):
                cloud_data = resp_json["data"]
    except Exception as e:
        print(f" -> Render Cloud read info: {e}")

    # Determine master data priority
    if cloud_data and cloud_data.get("positions"):
        if master_data and len(master_data.get("soldHistory", [])) > len(cloud_data.get("soldHistory", [])):
            pass
        else:
            master_data = cloud_data
            print(" -> Loaded portfolio dataset from Render Cloud.")

    if not master_data:
        master_data = {
            "positions": [],
            "capitalLedger": [],
            "freeCash": {"swing": "734.63", "lt": "367.58", "penny": "0"},
            "soldHistory": [],
            "budget": "0",
            "split": {"swing": 60, "lt": 30, "penny": 10},
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
    master_data["savedAt"] = int(time.time() * 1000)

    # Save to local portfolio backup file
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(master_data, f, indent=2)
    print(f" -> Local finplus_portfolio_backup.json updated ({len(cleaned_pos)} active positions).")

    # Update Render Cloud with master dataset
    try:
        requests.post("https://finplus.onrender.com/api/backup/save", json=master_data, timeout=5)
        print(" -> Render Cloud dataset successfully updated with cleaned positions.")
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
