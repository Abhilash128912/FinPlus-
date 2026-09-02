import json
import sqlite3
import os

path = r"d:\FINPLUS PNL APP\screener_journal_data.json"
backup_path = r"d:\FINPLUS PNL APP\screener_journal_mirror.json"
db_path = r"d:\FINPLUS PNL APP\trades_backup.db"

trades_map = {}

# 1. Read existing screener_journal_data.json if present
if os.path.exists(path):
    try:
        existing = json.load(open(path, "r"))
        for t in existing:
            key = f"{t.get('symbol')}_{t.get('entry_price')}_{t.get('created_at')}"
            trades_map[key] = t
    except Exception:
        pass

# 2. Read from depth_scans.db
if os.path.exists(db_path):
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM trades").fetchall()]
        conn.close()
        for t in rows:
            key = f"{t.get('symbol')}_{t.get('entry_price')}_{t.get('created_at')}"
            if key not in trades_map:
                trades_map[key] = t
    except Exception:
        pass

# 3. Read from trades_journal_backup.json
if os.path.exists(backup_path):
    try:
        b_trades = json.load(open(backup_path, "r"))
        for t in b_trades:
            key = f"{t.get('symbol')}_{t.get('entry_price')}_{t.get('created_at')}"
            if key not in trades_map:
                trades_map[key] = t
    except Exception:
        pass

merged = list(trades_map.values())
with open(path, "w") as f:
    json.dump(merged, f, indent=2)

print(f"[Merge Script] Successfully merged {len(merged)} trades into {path}")
