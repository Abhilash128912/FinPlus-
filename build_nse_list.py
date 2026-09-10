"""
Build the lightweight NSE stock lookup used by the symbol boxes: [{s, n}].

Source of truth is the local symbol workbook (default D:\\Nifty 500 stocks.xlsx),
which already carries both the symbol and the company name. That workbook is the
ONLY thing this app shares with any other trading app -- no app reads another
app's files, database or API. Point SYMBOL_XLSX somewhere else to override.

Falls back to NSE's public EQUITY_L.csv only when the workbook is unavailable.

Output: public/nse_stocks.json, relative to this file.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SYMBOL_XLSX = os.environ.get("SYMBOL_XLSX", r"D:\Nifty 500 stocks.xlsx")
# The app fetches stock_universe.json first and falls back to nse_stocks.json,
# so both are written from the same source rather than left to drift apart.
OUT_PATHS = (
    os.path.join(HERE, "public", "stock_universe.json"),
    os.path.join(HERE, "public", "nse_stocks.json"),
)

SYMBOL_COLS = ("Symbol", "SYMBOL", "symbol", "Ticker")
NAME_COLS = ("Stock Name", "Company Name", "NAME OF COMPANY", "name", "Name")


def _first_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def from_workbook(path: str):
    """[{s, n}] from the local workbook, or None if it cannot be used."""
    if not os.path.exists(path):
        print(f"Workbook not found: {path}")
        return None
    try:
        import pandas as pd
    except ImportError:
        print("pandas not installed - cannot read the workbook")
        return None
    try:
        df = pd.read_excel(path)
    except Exception as e:
        print(f"Could not read {path}: {e}")
        return None

    sym_col = _first_col(df, SYMBOL_COLS)
    if not sym_col:
        print(f"No symbol column in {path}; looked for {SYMBOL_COLS}")
        return None
    name_col = _first_col(df, NAME_COLS)

    rows = {}
    for _, r in df.iterrows():
        sym = str(r[sym_col]).strip().upper().replace(".NS", "")
        if not sym or sym in ("NAN", "NONE"):
            continue
        name = str(r[name_col]).strip() if name_col and str(r[name_col]).strip().lower() != "nan" else sym
        rows[sym] = name          # dict: later duplicates collapse
    print(f"Read {len(rows)} symbols from {os.path.basename(path)}"
          f"{' (with names)' if name_col else ' (symbols only)'}")
    return [{"s": s, "n": n} for s, n in rows.items()]


def from_nse_csv():
    """Fallback: NSE's public equity list. Network, but no other app involved."""
    import urllib.request
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            content = r.read().decode("utf-8")
    except Exception as e:
        print(f"NSE CSV failed: {e}")
        return None
    rows = {}
    for line in content.split("\n")[1:]:
        parts = line.strip().split(",")
        if len(parts) >= 2 and parts[0].strip():
            rows[parts[0].strip().upper()] = parts[1].strip()
    print(f"Read {len(rows)} symbols from NSE EQUITY_L.csv")
    return [{"s": s, "n": n} for s, n in rows.items()]


def main():
    result = from_workbook(SYMBOL_XLSX) or from_nse_csv()
    if not result:
        raise SystemExit("No symbol source available - nothing written.")

    result.sort(key=lambda x: x["s"])
    for path in OUT_PATHS:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, separators=(",", ":"), ensure_ascii=False)
        print(f"Saved {len(result)} stocks to {path} ({os.path.getsize(path) / 1024:.1f} KB)")
    print("Sample:", result[:3])


if __name__ == "__main__":
    main()
