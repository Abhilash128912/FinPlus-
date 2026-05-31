import sqlite3
import pandas as pd
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nifty500_scanner.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_scanner_db():
    """
    Initializes the SQLite database table for Nifty 500 stock scores.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nifty500_cache (
        ticker TEXT PRIMARY KEY,
        company_name TEXT,
        sector TEXT,
        last_price REAL,
        market_cap_cr REAL,
        pe_ratio REAL,
        industry_pe REAL,
        pb_ratio REAL,
        dividend_yield REAL,
        debt_to_equity REAL,
        roe REAL,
        roce REAL,
        eps_growth_yoy REAL,
        rsi_14 REAL,
        price_vs_20ema REAL,
        price_vs_50ema REAL,
        price_vs_200sma REAL,
        rel_strength_3m REAL,
        vol_ratio_5d_20d REAL,
        fundamental_score REAL,
        momentum_score REAL,
        total_score REAL,
        last_updated TEXT
    )
    """)
    
    conn.commit()
    conn.close()

def save_stock_to_cache(stock_data: dict):
    """
    Saves or updates a single stock's calculated metrics in the SQLite cache database.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    INSERT OR REPLACE INTO nifty500_cache (
        ticker, company_name, sector, last_price, market_cap_cr,
        pe_ratio, industry_pe, pb_ratio, dividend_yield, debt_to_equity,
        roe, roce, eps_growth_yoy, rsi_14, price_vs_20ema,
        price_vs_50ema, price_vs_200sma, rel_strength_3m, vol_ratio_5d_20d,
        fundamental_score, momentum_score, total_score, last_updated
    ) VALUES (
        :ticker, :company_name, :sector, :last_price, :market_cap_cr,
        :pe_ratio, :industry_pe, :pb_ratio, :dividend_yield, :debt_to_equity,
        :roe, :roce, :eps_growth_yoy, :rsi_14, :price_vs_20ema,
        :price_vs_50ema, :price_vs_200sma, :rel_strength_3m, :vol_ratio_5d_20d,
        :fundamental_score, :momentum_score, :total_score, :last_updated
    )
    """, stock_data)
    
    conn.commit()
    conn.close()

def fetch_cached_stocks_df() -> pd.DataFrame:
    """
    Loads all cached stock data from the SQLite database into a Pandas DataFrame.
    """
    if not os.path.exists(DB_PATH):
        init_scanner_db()
        return pd.DataFrame()
        
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM nifty500_cache", conn)
    conn.close()
    return df

def clear_scanner_cache():
    """
    Wipes out all records in the scanner table.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM nifty500_cache")
    conn.commit()
    conn.close()
