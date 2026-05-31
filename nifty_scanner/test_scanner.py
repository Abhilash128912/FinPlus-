import sys
import os

# Append the directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scanner_data_pipeline import fetch_single_stock_metrics
from scanner_database import init_scanner_db, save_stock_to_cache, fetch_cached_stocks_df

def run_test():
    print("==================================================")
    print("RUNNING NIFTY 500 SCANNER PIPELINE DIAGNOSTIC TEST")
    print("==================================================")
    
    # 1. Initialize SQLite Database
    print("\n[Step 1] Initializing SQLite cache database...")
    init_scanner_db()
    print("  [OK] Database initialized successfully.")
    
    # 2. Fetch and Score TCS.NS
    print("\n[Step 2] Fetching, scoring, and auditing TCS.NS...")
    ticker = "TCS.NS"
    nifty_df_3m = 2.5 # Mock Nifty 3-month performance benchmark
    
    metrics = fetch_single_stock_metrics(ticker, nifty_df_3m)
    
    if metrics is None:
        print(f"  [ERROR] Failed to fetch metrics for {ticker}. Check internet connection or yfinance API changes.")
        return False
        
    print(f"  [OK] Successfully retrieved and computed scores for {ticker}:")
    print(f"    - Company Name      : {metrics['company_name']}")
    print(f"    - Sector            : {metrics['sector']}")
    print(f"    - Last Price        : {metrics['last_price']} INR")
    print(f"    - Market Cap        : {metrics['market_cap_cr']} Crores")
    print(f"    - ROE (%)           : {metrics['roe']}%")
    print(f"    - Debt-to-Equity    : {metrics['debt_to_equity']}")
    print(f"    - RSI (14-day)      : {metrics['rsi_14']}")
    print(f"    - Relative Strength : {metrics['rel_strength_3m']}% vs Nifty 50")
    print(f"    - Fundamental Score : {metrics['fundamental_score']}/50")
    print(f"    - Momentum Score    : {metrics['momentum_score']}/50")
    print(f"    - COMPOSITE SCORE   : {metrics['total_score']}/100")
    
    # 3. Save to SQLite Cache
    print("\n[Step 3] Saving entry to SQLite cache table...")
    save_stock_to_cache(metrics)
    print("  [OK] Saved successfully.")
    
    # 4. Verify Read
    print("\n[Step 4] Reading cached DataFrame back from SQLite...")
    df = fetch_cached_stocks_df()
    if df.empty or len(df) == 0:
        print("  [ERROR] SQLite cache read failed. Table is empty.")
        return False
        
    print(f"  [OK] Successfully read cached stock data back! (Found {len(df)} row)")
    print("==================================================")
    print("DIAGNOSTIC TEST COMPLETED SUCCESSFULLY!")
    print("==================================================")
    return True

if __name__ == "__main__":
    run_test()
