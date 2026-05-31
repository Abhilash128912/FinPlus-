import pandas as pd
import re

url = "https://api.kite.trade/instruments"
try:
    print("Fetching live instruments from Zerodha API...")
    df = pd.read_csv(url)
    fno_df = df[df['segment'] == 'NFO-FUT']
    # Get unique names (underlying assets)
    fno_symbols = sorted(list(set(fno_df['name'].dropna().to_list())))
    print(f"Loaded {len(fno_symbols)} F&O underlying symbols.")
    
    # Path to nifty_tickers.py
    tickers_file_path = "nifty_scanner/nifty_tickers.py"
    
    with open(tickers_file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Format symbols as a python set block
    symbols_str = "FNO_UNDERLYINGS = {\n"
    # Chunk the symbols for clean formatting (8 symbols per line)
    for i in range(0, len(fno_symbols), 8):
        chunk = fno_symbols[i:i+8]
        line = "    " + ", ".join(f'"{sym}"' for sym in chunk)
        if i + 8 < len(fno_symbols):
            line += ","
        symbols_str += line + "\n"
    symbols_str += "}"
    
    # Replace the existing FNO_UNDERLYINGS block in nifty_tickers.py using regex
    pattern = r"FNO_UNDERLYINGS = \{.*?\}"
    new_content = re.sub(pattern, symbols_str, content, flags=re.DOTALL)
    
    with open(tickers_file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    print("Successfully updated nifty_tickers.py with the fresh set of 216 F&O symbols!")
except Exception as e:
    print(f"Error: {e}")
