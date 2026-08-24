import os
import json
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
        # Cloud dataset available
        if master_data and len(master_data.get("soldHistory", [])) > len(cloud_data.get("soldHistory", [])):
            # Local has newer sold trades, push local to cloud
            try:
                requests.post("https://finplus.onrender.com/api/backup/save", json=master_data, timeout=5)
                print(" -> Synced local trades up to Render Cloud.")
            except Exception:
                pass
        else:
            master_data = cloud_data
            print(" -> Loaded portfolio dataset from Render Cloud.")
    elif not master_data:
        # Fallback dataset
        master_data = {
            "positions": [
                {"id": "pos_midhani_kite", "ticker": "MIDHANI", "name": "Mishra Dhatu Nigam Limited", "segment": "SWING", "shares": 3, "buyPrice": 433.0, "buyDate": "2026-08-23", "target1": 467.64, "stopLoss": 415.68},
                {"id": "pos_cupid_kite", "ticker": "CUPID", "name": "Cupid Limited", "segment": "SWING", "shares": 6, "buyPrice": 289.95, "buyDate": "2026-08-23", "target1": 313.15, "stopLoss": 278.35},
                {"id": "pos_rvnl_indmoney", "ticker": "RVNL", "name": "Rail Vikas Nigam Limited", "segment": "LT", "shares": 1, "buyPrice": 229.90, "buyDate": "2026-08-23", "target1": 287.38, "stopLoss": 0}
            ],
            "capitalLedger": [
                {"id": "cap_initial_kite", "date": "2026-08-23", "type": "INJECTION", "amount": 5136.10, "segment": "SWING"},
                {"id": "cap_initial_indmoney", "date": "2026-08-23", "type": "INJECTION", "amount": 283.94, "segment": "LT"}
            ],
            "freeCash": {"swing": "2078.90", "lt": "54.04", "penny": "0"},
            "soldHistory": [
                {"id": "sold_kiriindus_1", "ticker": "KIRIINDUS", "name": "Kiri Industries Limited", "segment": "SWING", "shares": 4, "buyPrice": 462.0, "sellPrice": 462.0, "buyDate": "2026-08-23", "sellDate": "2026-08-24", "turnover": 1848.0, "grossPnl": 0.0, "taxes": 18.50, "netPnl": -18.50, "returnPct": 0.0}
            ],
            "budget": "0",
            "split": {"swing": 60, "lt": 30, "penny": 10}
        }

    # Save to local portfolio backup file
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(master_data, f, indent=2)
    print(f" -> Local finplus_portfolio_backup.json updated ({len(master_data.get('positions', []))} active positions).")

    # Update Render Cloud with master dataset
    try:
        requests.post("https://finplus.onrender.com/api/backup/save", json=master_data, timeout=5)
        print(" -> Render Cloud dataset successfully updated.")
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
