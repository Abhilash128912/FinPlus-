import sqlite3
import json
import pandas as pd
from typing import Dict, Any, List, Optional
from config import DB_FILE, DEFAULT_BROKERAGE, DEFAULT_TAX_RATES

def get_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema if it doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create trades table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        segment TEXT NOT NULL,
        action TEXT NOT NULL,
        quantity REAL NOT NULL,
        entry_price REAL NOT NULL,
        exit_price REAL NOT NULL,
        brokerage REAL NOT NULL,
        stt REAL NOT NULL,
        exchange_charges REAL NOT NULL,
        sebi_charges REAL NOT NULL,
        stamp_duty REAL NOT NULL,
        gst REAL NOT NULL,
        total_charges REAL NOT NULL,
        gross_pnl REAL NOT NULL,
        net_pnl REAL NOT NULL,
        strategy TEXT,
        mistake TEXT,
        notes TEXT
    )
    """)
    
    # Create settings table (key-value storage for brokerage rates & tax modifications)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)
    
    conn.commit()
    conn.close()

def get_db_settings(key: str, default_val: Any) -> Any:
    """Fetches a setting by key, returns default if not found."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row['value'])
        except Exception:
            return row['value']
    return default_val

def save_db_setting(key: str, value: Any):
    """Saves a setting key-value pair to the database."""
    conn = get_connection()
    cursor = conn.cursor()
    json_str = json.dumps(value)
    cursor.execute("""
    INSERT INTO settings (key, value)
    VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, json_str))
    conn.commit()
    conn.close()

def get_brokerage_rates() -> Dict[str, Dict[str, float]]:
    """Gets default brokerage rates from DB or falls back to config defaults."""
    return get_db_settings("brokerage_rates", DEFAULT_BROKERAGE)

def save_brokerage_rates(rates: Dict[str, Dict[str, float]]):
    """Saves customized brokerage rates."""
    save_db_setting("brokerage_rates", rates)

def add_trade(trade_data: Dict[str, Any]) -> int:
    """Inserts a completed trade into the database and returns its row ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    columns = [
        "trade_date", "symbol", "segment", "action", "quantity", 
        "entry_price", "exit_price", "brokerage", "stt", 
        "exchange_charges", "sebi_charges", "stamp_duty", "gst", 
        "total_charges", "gross_pnl", "net_pnl", "strategy", "mistake", "notes"
    ]
    
    placeholders = ", ".join(["?"] * len(columns))
    sql = f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})"
    
    values = [trade_data.get(col) for col in columns]
    cursor.execute(sql, values)
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id

def update_trade(trade_id: int, trade_data: Dict[str, Any]):
    """Updates an existing trade in the database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    trade_id = int(trade_id) # Force cast NumPy int64 to standard Python int
    
    columns = [
        "trade_date", "symbol", "segment", "action", "quantity", 
        "entry_price", "exit_price", "brokerage", "stt", 
        "exchange_charges", "sebi_charges", "stamp_duty", "gst", 
        "total_charges", "gross_pnl", "net_pnl", "strategy", "mistake", "notes"
    ]
    
    set_clause = ", ".join([f"{col} = ?" for col in columns])
    sql = f"UPDATE trades SET {set_clause} WHERE id = ?"
    
    values = [trade_data.get(col) for col in columns] + [trade_id]
    cursor.execute(sql, values)
    conn.commit()
    conn.close()

def delete_trade(trade_id: int):
    """Deletes a trade from the database by its ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    trade_id = int(trade_id) # Force cast NumPy int64 to standard Python int
    
    cursor.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()

def fetch_trades_df() -> pd.DataFrame:
    """Fetches all trades and returns them as a pandas DataFrame."""
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM trades ORDER BY trade_date DESC, id DESC", conn)
    conn.close()
    return df

def clear_all_trades():
    """Deletes all trades from the database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    conn.commit()
    conn.close()

# Initialize DB on import
init_db()
