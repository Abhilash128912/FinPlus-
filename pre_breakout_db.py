"""
pre_breakout_db.py
==================
SQLite persistence layer for Pre-Breakout technical snapshots.
Stores daily historical indicators per stock to compute trends (e.g. CMF slope, delivery % averages).
Path: cache/pre_breakout_history.db (strictly local, ignored in git/sync).
"""

import os
import json
import sqlite3
from typing import Optional, List, Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "cache")
DB_PATH = os.path.join(DB_DIR, "pre_breakout_history.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                ltp REAL,
                volume INTEGER,
                cmf REAL,
                delivery_pct REAL,
                oi REAL,
                atr_ratio REAL,
                rsi REAL,
                pre_breakout_score REAL,
                raw_metrics TEXT,
                PRIMARY KEY (symbol, date)
            )
        """)
        conn.commit()


def save_daily_snapshot(symbol: str, date_str: str, metrics: dict):
    """
    Saves or updates a daily technical snapshot for a stock.
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO daily_snapshots 
            (symbol, date, ltp, volume, cmf, delivery_pct, oi, atr_ratio, rsi, pre_breakout_score, raw_metrics)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            date_str,
            metrics.get("ltp"),
            metrics.get("volume"),
            metrics.get("cmf"),
            metrics.get("delivery_pct"),
            metrics.get("oi"),
            metrics.get("atr_ratio"),
            metrics.get("rsi"),
            metrics.get("pre_breakout_score"),
            json.dumps(metrics.get("raw_metrics", {}))
        ))
        conn.commit()


def get_history(symbol: str, limit: int = 20) -> List[Dict]:
    """
    Retrieves the last N daily snapshots for a stock sorted by date ascending.
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT symbol, date, ltp, volume, cmf, delivery_pct, oi, atr_ratio, rsi, pre_breakout_score, raw_metrics
            FROM daily_snapshots
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT ?
        """, (symbol, limit))
        rows = cursor.fetchall()
        
    res = []
    for r in reversed(rows):
        d = dict(r)
        if d.get("raw_metrics"):
            try:
                d["raw_metrics"] = json.loads(d["raw_metrics"])
            except Exception:
                d["raw_metrics"] = {}
        res.append(d)
    return res
