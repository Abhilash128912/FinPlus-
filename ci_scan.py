"""The scheduled scan, as a file rather than inline YAML.

It lived as a python -c string inside the workflow, which meant it could not be
run locally, could not be retried without duplicating it, and any change to it was
invisible to the app's own tests. Yahoo rate-limits bursts from cloud IP ranges and
CI always starts cold -- cache/ is gitignored, so all ~2,400 tickers are fetched
fresh on every run -- and when it is throttled every request fails at once, the
scan yields nothing, and the guard below aborts about twenty seconds in. Ten of the
first twenty-four scheduled runs succeeded.

Being a file makes the retry a loop instead of a copy, and lets the whole thing be
exercised on a laptop before it is trusted at 09:15.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetch_and_build as fb  # noqa: E402

# Below this, treat the scan as blocked rather than as a real result: overwriting
# the committed report with a handful of rows would push an empty app to everyone.
MIN_VIABLE_RESULTS = 10


def main() -> int:
    try:
        import download_nse_indices
        print("Updating Nifty stock list from NSE...")
        download_nse_indices.main()
    except Exception as e:
        print(f"  Stock list update skipped: {e}")

    print("Reading stock list...")
    tickers = fb.read_stock_list()
    print(f"  Loaded {len(tickers)} tickers")

    print("Fetching NIFTY 50 benchmark & analyzing Market Regime...")
    nifty_df, nifty_regime = fb.fetch_nifty_history()

    workers = os.environ.get("SCREENER_SCAN_WORKERS", "default")
    print(f"Running scan ({workers} workers)...")
    results = fb.run_scan(tickers)
    if not results or len(results) < MIN_VIABLE_RESULTS:
        got = len(results) if results else 0
        print(f"❌ Scan yielded {got} results, below the {MIN_VIABLE_RESULTS} floor — "
              "almost certainly rate-limited or blocked. Aborting rather than "
              "overwriting the report with empty data.")
        return 1

    print("Computing Mansfield Relative Strength (RS Rating 1-99) vs Nifty...")
    results = fb.compute_relative_strength_ratings(
        results, nifty_df, nifty_regime_status=nifty_regime.get("status", "NEUTRAL")
    )

    print("Processing watchlist...")
    wl_data = fb.process_watchlist(results)

    print("Processing LT watchlist...")
    lt_wl_data = fb.process_lt_watchlist(results)

    print("Fetching commodity signals...")
    commodity_signals = fb.fetch_commodity_signals()

    print("Processing F&O signals...")
    fno_data = fb.process_fno_stocks(results)

    mkt_info = fb.get_market_status()
    mkt_info["nifty"] = nifty_regime

    # Data first: write_scan_json also stamps scan_meta.json with the completion
    # time, and build_html reads that stamp for the page's "Last scan" line. Built
    # the other way round the stamp is missing and the page falls back to render
    # time, which is what let a hours-old deploy read as freshly scanned.
    clean_results = fb.sanitize_for_strict_json(results)
    fb.write_scan_json(clean_results)

    print("Building HTML report (also writes static/app.css, static/app.js)...")
    html = fb.build_html(results, wl_data, lt_wl_data, commodity_signals, mkt_info, fno_data)
    fb.publish_html(html)

    # The phone app loads /mobile, a separate page built from the same results.
    # Without this an automated scan refreshes the desktop page and leaves the app
    # on whatever it had at the last deploy.
    fb.publish_mobile_html(results, lt_wl_data, mkt_info)

    print(f"Scan complete! screener.html ({len(html):,} bytes), mobile.html, "
          f"screener_data.json, scan_meta.json, static/app.css & static/app.js updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
