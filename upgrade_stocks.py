"""
Replace the hardcoded DEFAULT_NIFTY500_STOCKS with a dynamic fetch from
the bundled public/nse_stocks.json (2413 stocks with real names).
Also upgrades the combinedStockList logic to use the bundled file.
"""

content = open(r'd:\FINPLUS PNL APP\src\App.jsx', encoding='utf-8').read()
lines = content.splitlines(keepends=True)

# 1. Find and remove DEFAULT_NIFTY500_STOCKS (lines 38 to 132)
start = None
end = None
for i, l in enumerate(lines):
    if 'const DEFAULT_NIFTY500_STOCKS = [' in l and start is None:
        start = i
    if start and i > start and l.strip() == '];':
        end = i
        break

print(f"DEFAULT_NIFTY500_STOCKS: lines {start+1} to {end+1}")

# 2. Replace with a comment marker we'll use as a placeholder
# (we'll just delete it entirely and update usage below)
new_lines = lines[:start] + lines[end+1:]

# 3. Update combinedStockList to load from bundled JSON instead
old_combined = """  // Combined master stock list merging DEFAULT_NIFTY500_STOCKS and API list
  const combinedStockList = React.useMemo(() => {
    const list = [...DEFAULT_NIFTY500_STOCKS];
    if (nifty500List && nifty500List.length > 0) {
      nifty500List.forEach(s => {
        const clean = (s.symbol || '').replace('.NS', '').toUpperCase();
        if (!list.some(item => item.symbol.toUpperCase() === clean)) {
          list.push({
            symbol: clean,
            name: s.name || clean,
            aliases: [clean.toLowerCase(), (s.name || '').toLowerCase()]
          });
        }
      });
    }
    return list;
  }, [nifty500List]);"""

new_combined = """  // Combined master stock list from bundled NSE stocks JSON + API fallback
  const combinedStockList = React.useMemo(() => {
    // nifty500List is loaded from /nse_stocks.json (bundled, 2413 stocks with real names)
    if (nifty500List && nifty500List.length > 0) {
      return nifty500List.map(s => ({
        symbol: s.s || s.symbol || '',
        name: s.n || s.name || s.s || s.symbol || '',
        aliases: [
          (s.s || s.symbol || '').toLowerCase(),
          (s.n || s.name || '').toLowerCase()
        ]
      }));
    }
    return [];
  }, [nifty500List]);"""

old_fetch = """  useEffect(() => {
    const fetchNifty500 = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/investment/nifty500`);
        if (res.ok) {
          const data = await res.json();
          if (data && data.stocks) {
            setNifty500List(data.stocks);
          }
        }
      } catch (e) {}
    };
    fetchNifty500();
  }, [API_BASE_URL]);"""

new_fetch = """  // Load bundled NSE stock list (2413 stocks with company names) for autocomplete
  useEffect(() => {
    const loadNseStocks = async () => {
      try {
        const res = await fetch('/nse_stocks.json');
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data) && data.length > 0) {
            setNifty500List(data);
          }
        }
      } catch (e) {
        console.warn('Could not load bundled NSE stock list', e);
      }
    };
    loadNseStocks();
  }, []);"""

content2 = ''.join(new_lines)
content2 = content2.replace(old_fetch, new_fetch)
content2 = content2.replace(old_combined, new_combined)

if old_fetch in ''.join(new_lines):
    print("Fetch block replaced OK")
else:
    print("WARNING: fetch block not found - check CRLF")

open(r'd:\FINPLUS PNL APP\src\App.jsx', 'w', encoding='utf-8').write(content2)
print("Done! File saved.")
print(f"New line count: {len(content2.splitlines())}")
