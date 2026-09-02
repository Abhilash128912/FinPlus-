import json
import sqlite3
import os

restored_trades = [
  {
    "id": 1,
    "uuid": "fp_mryv9p",
    "symbol": "CRUDEOIL",
    "instrument_type": "Crude Oil Options",
    "entry_price": 275.0,
    "quantity": 10,
    "exit_price": 265.25,
    "status": "CLOSED",
    "gross_pnl": -97.5,
    "net_pnl": -150.97,
    "created_at": "2026-07-24T11:38:24.549Z"
  },
  {
    "id": 2,
    "uuid": "fp_mrypn7",
    "symbol": "TMPV",
    "instrument_type": "Intraday Short",
    "entry_price": 319.55,
    "quantity": 38,
    "exit_price": 319.55,
    "status": "CLOSED",
    "gross_pnl": 0.0,
    "net_pnl": -12.88,
    "created_at": "2026-07-24T09:00:56.923Z"
  },
  {
    "id": 3,
    "uuid": "fp_mrypm5",
    "symbol": "NIFTY 24100",
    "instrument_type": "Nifty Options",
    "entry_price": 30.0,
    "quantity": 65,
    "exit_price": 28.05,
    "status": "CLOSED",
    "gross_pnl": -126.75,
    "net_pnl": -178.3,
    "created_at": "2026-07-24T09:00:06.931Z"
  },
  {
    "id": 4,
    "uuid": "fp_mrypl4",
    "symbol": "NIFTY 24050",
    "instrument_type": "Nifty Options",
    "entry_price": 35.15,
    "quantity": 260,
    "exit_price": 38.05,
    "status": "CLOSED",
    "gross_pnl": 754.0,
    "net_pnl": 684.03,
    "created_at": "2026-07-24T08:59:18.901Z"
  },
  {
    "id": 5,
    "uuid": "fp_mrypk2",
    "symbol": "NIFTY 24000",
    "instrument_type": "Nifty Options",
    "entry_price": 35.7,
    "quantity": 65,
    "exit_price": 33.7,
    "status": "CLOSED",
    "gross_pnl": -130.0,
    "net_pnl": -182.41,
    "created_at": "2026-07-24T08:58:30.399Z"
  },
  {
    "id": 6,
    "uuid": "fp_mrypj2",
    "symbol": "NIFTY 23950",
    "instrument_type": "Nifty Options",
    "entry_price": 36.9,
    "quantity": 65,
    "exit_price": 38.45,
    "status": "CLOSED",
    "gross_pnl": 100.75,
    "net_pnl": 47.75,
    "created_at": "2026-07-24T08:57:42.787Z"
  },
  {
    "id": 7,
    "uuid": "fp_mrypey",
    "symbol": "NIFTY 23350",
    "instrument_type": "Nifty Options",
    "entry_price": 31.95,
    "quantity": 65,
    "exit_price": 29.9,
    "status": "CLOSED",
    "gross_pnl": -133.25,
    "net_pnl": -185.08,
    "created_at": "2026-07-24T08:54:31.779Z"
  },
  {
    "id": 8,
    "uuid": "fp_mryilq",
    "symbol": "BHEL",
    "instrument_type": "Intraday Short",
    "entry_price": 402.95,
    "quantity": 29,
    "exit_price": 404.46,
    "status": "CLOSED",
    "gross_pnl": -43.79,
    "net_pnl": -56.2,
    "created_at": "2026-07-24T05:43:50.633Z"
  },
  {
    "id": 9,
    "uuid": "fp_mryil5",
    "symbol": "TMPV",
    "instrument_type": "Intraday Short",
    "entry_price": 319.55,
    "quantity": 38,
    "exit_price": 319.75,
    "status": "CLOSED",
    "gross_pnl": -7.6,
    "net_pnl": -20.48,
    "created_at": "2026-07-24T05:43:23.232Z"
  },
  {
    "id": 10,
    "uuid": "fp_20260723_trade1",
    "symbol": "NATGASMINI 275 CE",
    "instrument_type": "Natural Gas Options",
    "entry_price": 14.47,
    "quantity": 250,
    "exit_price": 10.05,
    "status": "CLOSED",
    "gross_pnl": -1105.0,
    "net_pnl": -1158.71,
    "created_at": "2026-07-23T14:27:48.540Z"
  }
]

# Write to screener_journal_data.json
json_path = r"d:\FINPLUS PNL APP\screener_journal_data.json"
with open(json_path, "w") as f:
    json.dump(restored_trades, f, indent=2)

print(f"[Restore Script] Restored {len(restored_trades)} trades into {json_path}")

# Write to trades_backup.db trades table
db_path = r"d:\FINPLUS PNL APP\trades_backup.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            entry_price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            stop_loss REAL,
            target_price REAL,
            exit_price REAL,
            instrument_type TEXT,
            status TEXT,
            created_at TEXT
        )
    """)
    for t in restored_trades:
        sym = t["symbol"]
        entry_p = t["entry_price"]
        qty = t["quantity"]
        exit_p = t["exit_price"]
        inst = t["instrument_type"]
        st = t["status"]
        ca = t["created_at"]
        existing = conn.execute("SELECT id FROM trades WHERE symbol = ? AND created_at = ?", (sym, ca)).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO trades (symbol, entry_price, quantity, exit_price, instrument_type, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (sym, entry_p, qty, exit_p, inst, st, ca))
    conn.commit()
    conn.close()
    print("[Restore Script] Successfully updated depth_scans.db SQLite trades table.")
