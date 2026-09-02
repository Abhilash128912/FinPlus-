"""
Build a lightweight NSE stock lookup list: [{symbol, name}]
Uses NSE equity symbols from nifty_stocks_auto.json + yfinance for names.
Output: nse_stock_list.json in FINPLUS PNL APP/public/
"""
import json, os, time

# Load symbols
symbols = json.load(open(r'd:\STOCK SCREENER APP\nifty_stocks_auto.json', encoding='utf-8'))
print(f"Total symbols: {len(symbols)}")

# Try to get company names from yfinance info (fast_info is quickest)
try:
    import yfinance as yf
except ImportError:
    os.system("pip install yfinance -q")
    import yfinance as yf

result = []
batch_size = 50
failed = []

for i in range(0, len(symbols), batch_size):
    batch = symbols[i:i+batch_size]
    tickers_str = " ".join([f"{s}.NS" for s in batch])
    try:
        tickers = yf.Tickers(tickers_str)
        for sym in batch:
            try:
                info = tickers.tickers[f"{sym}.NS"].fast_info
                # fast_info doesn't have name, use a fallback
                result.append({"s": sym, "n": sym})  # will update with longName below
            except:
                result.append({"s": sym, "n": sym})
    except:
        for sym in batch:
            result.append({"s": sym, "n": sym})
    
    if i % 200 == 0:
        print(f"Progress: {i}/{len(symbols)}")

# Since yfinance batch name fetch is slow, let's use a smarter approach:
# Load from NSE CSV directly
print("\nTrying NSE CSV for company names...")
import urllib.request

try:
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        content = r.read().decode('utf-8')
    
    sym_to_name = {}
    for line in content.split('\n')[1:]:
        parts = line.strip().split(',')
        if len(parts) >= 2:
            sym_to_name[parts[0].strip()] = parts[1].strip()
    
    print(f"Got {len(sym_to_name)} names from NSE CSV")
    
    result = []
    for sym in symbols:
        name = sym_to_name.get(sym, sym)
        result.append({"s": sym, "n": name})

except Exception as e:
    print(f"NSE CSV failed: {e}")
    print("Using symbol-only fallback")
    result = [{"s": sym, "n": sym} for sym in symbols]

# Sort by symbol
result.sort(key=lambda x: x['s'])

# Save to public folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
out_path = os.path.join(BASE_DIR, 'public', 'nse_stocks.json')
os.makedirs(os.path.dirname(out_path), exist_ok=True)
json.dump(result, open(out_path, 'w', encoding='utf-8'), separators=(',', ':'))
print(f"\nSaved {len(result)} stocks to {out_path}")
print(f"File size: {os.path.getsize(out_path)/1024:.1f} KB")
print("Sample:", result[:5])
