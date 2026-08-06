import os
import io
import json
import sys
import pandas as pd
from curl_cffi import requests

# Load config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

if not os.path.exists(CONFIG_FILE):
    print(f"[ERROR] Config file not found at {CONFIG_FILE}")
    sys.exit(1)

with open(CONFIG_FILE) as f:
    cfg = json.load(f)

EXCEL_PATH = cfg.get("excel_path", r"D:\Nifty 500 stocks.xlsx")

# Dict of popular Nifty indices and their constituent CSV links on niftyindices.com
INDICES = {
    "Nifty 500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "Nifty Midcap 150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
    "Nifty Smallcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    "Nifty 50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
    "Nifty Next 50": "https://www.niftyindices.com/IndexConstituent/ind_niftynext50list.csv"
}

def download_index_csv(url: str, index_name: str) -> pd.DataFrame | None:
    print(f"\nDownloading {index_name} constituent list...")
    headers = {
        "Referer": "https://www.niftyindices.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        # Use curl_cffi requests impersonating Chrome to bypass Akamai bot protection
        r = requests.get(url, impersonate="chrome120", headers=headers, timeout=20)
        
        if r.status_code == 200:
            # Parse CSV
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = [c.strip() for c in df.columns]
            print(f"  -> Successfully downloaded {len(df)} rows.")
            return df
        elif r.status_code == 403:
            print("  [WARNING] Access Denied (403).")
            print("  This is normal in cloud/datacenter environments (like Google/AWS IP ranges).")
            print("  Akamai blocks hosting provider IPs. Running this on a local PC will succeed.")
        else:
            print(f"  [WARNING] Failed to download. HTTP Status: {r.status_code}")
    except Exception as e:
        print(f"  [ERROR] Error fetching data: {e}")
    return None

def download_nse_equity_master() -> pd.DataFrame | None:
    print("\nDownloading Full NSE Listed Equities Master List (2,390+ stocks)...")
    headers = {
        "Referer": "https://www.nseindia.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    try:
        r = requests.get(url, impersonate="chrome120", headers=headers, timeout=20)
        if r.status_code == 200:
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = [c.strip() for c in df.columns]
            print(f"  -> Successfully downloaded Full NSE Master List ({len(df)} stocks).")
            return df
    except Exception as e:
        print(f"  [ERROR] Error fetching NSE Master List: {e}")
    return None

def main():
    print("=" * 60)
    print("         Full NSE Listed Equities & Indices Downloader")
    print("         Using curl_cffi browser impersonation")
    print("=" * 60)
    
    all_new_stocks = []
    
    # 1. Download Full NSE Equity Master List (2,390+ stocks)
    df_master = download_nse_equity_master()
    if df_master is not None and "SYMBOL" in df_master.columns:
        for _, row in df_master.iterrows():
            sym = str(row["SYMBOL"]).strip()
            name = str(row.get("NAME OF COMPANY") or row.get("NAME") or sym).strip()
            if sym and sym != "nan" and sym != "SYMBOL":
                all_new_stocks.append({
                    "symbol": sym,
                    "name": name
                })
    
    # 2. Download Nifty 500, Midcap 150, and Smallcap 250
    target_indices = ["Nifty 500", "Nifty Midcap 150", "Nifty Smallcap 250"]
    
    for idx_name in target_indices:
        url = INDICES[idx_name]
        df = download_index_csv(url, idx_name)
        if df is not None:
            symbol_col = None
            name_col = None
            
            for col in df.columns:
                if col.lower() in ["symbol", "ticker"]:
                    symbol_col = col
                if col.lower() in ["company name", "companyname", "stock name", "name"]:
                    name_col = col
            
            if not symbol_col:
                symbol_col = df.columns[2] if len(df.columns) > 2 else df.columns[0]
            if not name_col:
                name_col = df.columns[0]
                
            for _, row in df.iterrows():
                sym = str(row[symbol_col]).strip()
                name = str(row[name_col]).strip()
                if sym and sym != "nan":
                    all_new_stocks.append({
                        "symbol": sym,
                        "name": name
                    })
                    
    if not all_new_stocks:
        print("\n[ERROR] No stock data could be downloaded (Access Denied / Network Issue).")
        print("Please run this script from your local residential machine.")
        return

    print(f"\nTotal unique stocks fetched from downloads: {len({s['symbol'] for s in all_new_stocks})}")
    
    # Update Excel
    if not os.path.exists(EXCEL_PATH):
        # Ensure parent directory exists
        parent_dir = os.path.dirname(EXCEL_PATH)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
            
    print(f"\nTarget Excel file: {EXCEL_PATH}")
    
    if os.path.exists(EXCEL_PATH):
        try:
            df_existing = pd.read_excel(EXCEL_PATH)
            print(f"Existing stock count in Excel: {len(df_existing)}")
        except Exception as e:
            print(f"Error reading existing Excel sheet: {e}")
            df_existing = pd.DataFrame(columns=["Sr.", "Stock Name", "Symbol"])
    else:
        df_existing = pd.DataFrame(columns=["Sr.", "Stock Name", "Symbol"])
        
    # Standardize and identify existing symbols
    existing_symbols = set()
    sym_col_idx = None
    name_col_idx = None
    
    for i, col in enumerate(df_existing.columns):
        if col.lower() == "symbol":
            sym_col_idx = col
        if col.lower() in ["stock name", "company name"]:
            name_col_idx = col
            
    if sym_col_idx is None:
        sym_col_idx = "Symbol" if "Symbol" in df_existing.columns else (df_existing.columns[2] if len(df_existing.columns) > 2 else "Symbol")
    if name_col_idx is None:
        name_col_idx = "Stock Name" if "Stock Name" in df_existing.columns else (df_existing.columns[1] if len(df_existing.columns) > 1 else "Stock Name")
        
    if sym_col_idx in df_existing.columns:
        existing_symbols = {str(s).strip().upper() for s in df_existing[sym_col_idx].dropna()}
        
    new_rows = []
    skipped = 0
    added = 0
    
    for stock in all_new_stocks:
        sym = stock["symbol"].upper()
        if sym in existing_symbols:
            skipped += 1
            continue
            
        new_row = {col: None for col in df_existing.columns}
        new_row[sym_col_idx] = sym
        new_row[name_col_idx] = stock["name"]
        new_rows.append(new_row)
        existing_symbols.add(sym)
        added += 1
        
    if new_rows:
        df_new = pd.DataFrame(new_rows)
        df_updated = pd.concat([df_existing, df_new], ignore_index=True)
        
        # Ensure Sr. sequential column exists
        if "Sr." in df_updated.columns:
            df_updated["Sr."] = range(1, len(df_updated) + 1)
        else:
            df_updated.insert(0, "Sr.", range(1, len(df_updated) + 1))
            
        saved = False
        try:
            df_updated.to_excel(EXCEL_PATH, index=False)
            print(f"[SUCCESS] Successfully saved {len(df_updated)} stocks to main Excel: {EXCEL_PATH}")
            if added > 0:
                print(f"   Added {added} new stocks. Skipped {skipped} duplicates.")
            saved = True
        except PermissionError:
            print(f"[WARNING] Main Excel file is locked (open in Microsoft Excel): {EXCEL_PATH}")
            fallback_excel = os.path.join(BASE_DIR, "nifty_stocks_auto.xlsx")
            try:
                df_updated.to_excel(fallback_excel, index=False)
                print(f"[SUCCESS] Saved updated stock list to fallback Excel file: {fallback_excel}")
                saved = True
            except Exception as e:
                print(f"[ERROR] Failed to save fallback Excel: {e}")
        except Exception as e:
            print(f"[ERROR] Failed to save Excel file: {e}")

        # Save JSON fallback for guaranteed loading
        try:
            json_file = os.path.join(BASE_DIR, "nifty_stocks_auto.json")
            stock_symbols = [str(s).strip().upper() for s in df_updated[sym_col_idx].dropna()]
            with open(json_file, "w") as f:
                json.dump(stock_symbols, f, indent=2)
            print(f"[SUCCESS] Updated fail-safe JSON list: {json_file} ({len(stock_symbols)} stocks)")
        except Exception as e:
            pass
    else:
        print("[SUCCESS] No new stocks to add. All downloaded stocks are already in the list.")

if __name__ == "__main__":
    main()
