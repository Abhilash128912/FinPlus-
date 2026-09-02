import os
import io
import json
import sys
import pandas as pd
import urllib.request

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Load config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

cfg = {}
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        pass

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.niftyindices.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                text = resp.read().decode("utf-8", errors="ignore")
                df = pd.read_csv(io.StringIO(text))
                df.columns = [c.strip() for c in df.columns]
                print(f"  -> Successfully downloaded {len(df)} rows.")
                return df
    except Exception as e:
        print(f"  [ERROR] Error fetching {index_name}: {e}")
    return None

def download_nse_equity_master() -> pd.DataFrame | None:
    print("\nDownloading Full NSE Listed Equities Master List (2,390+ stocks)...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.nseindia.com/"
    }
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                text = resp.read().decode("utf-8", errors="ignore")
                df = pd.read_csv(io.StringIO(text))
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
    
    # 1. Download Nifty 50, Nifty Next 50, Nifty Midcap 150, Nifty Smallcap 250, Nifty 500
    target_indices = ["Nifty 50", "Nifty Next 50", "Nifty Midcap 150", "Nifty Smallcap 250", "Nifty 500"]
    
    largecap_syms = set()
    midcap_syms = set()
    smallcap_syms = set()
    nifty500_syms = set()
    
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
                sym = str(row[symbol_col]).strip().upper()
                name = str(row[name_col]).strip()
                if sym and sym != "NAN" and sym != "SYMBOL":
                    all_new_stocks.append({
                        "symbol": sym,
                        "name": name
                    })
                    if idx_name in ["Nifty 50", "Nifty Next 50"]:
                        largecap_syms.add(sym)
                    elif idx_name == "Nifty Midcap 150":
                        midcap_syms.add(sym)
                    elif idx_name == "Nifty Smallcap 250":
                        smallcap_syms.add(sym)
                    
                    nifty500_syms.add(sym)
                    
    # Save LargeCap and MidCap constituent JSON files for scanner categorizations
    if largecap_syms:
        with open(os.path.join(BASE_DIR, "nifty_largecap.json"), "w") as f:
            json.dump(sorted(list(largecap_syms)), f, indent=2)
        print(f"[SUCCESS] Saved {len(largecap_syms)} Large Cap tickers to nifty_largecap.json")
    if midcap_syms:
        with open(os.path.join(BASE_DIR, "nifty_midcap.json"), "w") as f:
            json.dump(sorted(list(midcap_syms)), f, indent=2)
        print(f"[SUCCESS] Saved {len(midcap_syms)} Mid Cap tickers to nifty_midcap.json")
    if smallcap_syms:
        with open(os.path.join(BASE_DIR, "nifty_smallcap.json"), "w") as f:
            json.dump(sorted(list(smallcap_syms)), f, indent=2)
        print(f"[SUCCESS] Saved {len(smallcap_syms)} Small Cap tickers to nifty_smallcap.json")
                    
    if not all_new_stocks:
        json_file = os.path.join(BASE_DIR, "nifty_stocks_auto.json")
        if os.path.exists(json_file) or os.path.exists(EXCEL_PATH):
            print("\n[INFO] Unable to download fresh index list from NSE (Access Denied / Network Block).")
            print("       Continuing with existing local stock list file.")
            return
        else:
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
        
    # 2. Download Full NSE Equity Master List for comprehensive active ticker set
    master_df = download_nse_equity_master()
    active_master_symbols = set()
    if master_df is not None:
        sym_col_m = None
        for col in master_df.columns:
            if col.lower() in ["symbol", "ticker"]:
                sym_col_m = col
                break
        if not sym_col_m and len(master_df.columns) > 0:
            sym_col_m = master_df.columns[0]
        if sym_col_m:
            for s in master_df[sym_col_m].dropna():
                clean_s = str(s).strip().upper()
                if clean_s and clean_s != "SYMBOL":
                    active_master_symbols.add(clean_s)

    downloaded_symbols = {s['symbol'].upper() for s in all_new_stocks}
    valid_active_symbols = downloaded_symbols | active_master_symbols

    # Reconcile existing symbols against fresh downloaded active symbol universe
    # Safety Gate: Only prune if fresh active set is non-trivial and >= 80% of existing stock count (or >= 400 stocks)
    # to prevent partial/blocked downloads from wiping out valid active stocks.
    delisted_symbols = set()
    min_safe_threshold = max(400, int(len(existing_symbols) * 0.8)) if existing_symbols else 0
    if existing_symbols and len(valid_active_symbols) >= min_safe_threshold:
        delisted_symbols = existing_symbols - valid_active_symbols
        if delisted_symbols:
            print(f"\n[RECONCILIATION] Identified {len(delisted_symbols)} delisted/inactive symbols to prune: {sorted(list(delisted_symbols))[:10]}...")
            df_existing = df_existing[~df_existing[sym_col_idx].astype(str).str.strip().str.upper().isin(delisted_symbols)]
            existing_symbols = existing_symbols - delisted_symbols
    elif existing_symbols and valid_active_symbols:
        print(f"\n[SAFETY GATE] Fresh symbol universe is unusually small ({len(valid_active_symbols)} < threshold {min_safe_threshold}).")
        print("              Skipping delisting prune step to prevent accidental data loss from partial network fetch.")

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

    # Merge remaining active equity shares from full NSE Master List (EQUITY_L.csv)
    if master_df is not None and sym_col_m in master_df.columns:
        series_col = next((c for c in master_df.columns if c.lower() in ["series", "srs"]), None)
        name_col_m = next((c for c in master_df.columns if col.lower() in ["name of company", "company name", "name"]), None)
        for _, row in master_df.iterrows():
            sym = str(row[sym_col_m]).strip().upper()
            if not sym or sym in ["SYMBOL", "NAN"]:
                continue
            if series_col:
                s_val = str(row[series_col]).strip().upper()
                if s_val not in ["EQ", "BE", "BZ", "SM"]:
                    continue
            if sym in existing_symbols:
                continue
            
            comp_name = str(row[name_col_m]).strip() if name_col_m and name_col_m in row else sym
            new_row = {col: None for col in df_existing.columns}
            new_row[sym_col_idx] = sym
            new_row[name_col_idx] = comp_name
            new_rows.append(new_row)
            existing_symbols.add(sym)
            added += 1
        
    if new_rows or delisted_symbols:
        df_new = pd.DataFrame(new_rows) if new_rows else pd.DataFrame()
        df_updated = pd.concat([df_existing, df_new], ignore_index=True) if not df_new.empty else df_existing.copy()
        
        # Ensure Sr. sequential column exists
        if "Sr." in df_updated.columns:
            df_updated["Sr."] = range(1, len(df_updated) + 1)
        else:
            df_updated.insert(0, "Sr.", range(1, len(df_updated) + 1))
            
        saved = False
        try:
            df_updated.to_excel(EXCEL_PATH, index=False)
            print(f"[SUCCESS] Successfully saved {len(df_updated)} active stocks to main Excel: {EXCEL_PATH}")
            if added > 0:
                print(f"   Added {added} new stocks. Skipped {skipped} duplicates.")
            if delisted_symbols:
                print(f"   Pruned {len(delisted_symbols)} delisted symbols.")
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
        print("[SUCCESS] Stock list is fully synchronized and reconciled. No changes needed.")

if __name__ == "__main__":
    main()
