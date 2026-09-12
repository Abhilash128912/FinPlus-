"""
INDmoney/MCX pair-trading signal dashboard.

Four background threads, each on the cadence that actually matches what it
watches -- there's no point recomputing an hourly-candle signal every 3
seconds, and there's no point leaving NIFTY/BANK NIFTY's displayed price 60
seconds stale when a single batched LTP call is nearly free:
  - MCX bar recorder (every 180s, MCX session hours only): samples the live
    MCX snapshot and folds it into mcx_bars.json -- MCX publishes no
    historical intraday candles, so this IS the only source of history.
  - Signal refresher (every REFRESH_SECONDS): recomputes all 4 instruments'
    sr_volume signal from fresh 1H candles.
  - Fast LTP poller (every FAST_POLL_SECONDS = 3s): NIFTY + BANK NIFTY live
    price only, one batched INDmoney call, no candle refetch -- updates the
    page's displayed price via a small JS poll against /api/fast_ltp
    without a full page reload.
  - Equity scanner (every EQUITY_SCAN_INTERVAL_SECONDS): the Nifty-universe
    BUY/SELL/WATCH scan (equity_scan.py) across all liquidity-gated
    candidates. Runs for a few minutes each time, so it stays well off the
    3s/60s cadences.

Local-only for now: no git push, no Render deploy, no mobile wrapper.
Run: python app.py  ->  http://127.0.0.1:5850
"""
import json
import os
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, request, url_for

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env_file(path: str) -> None:
    """indmoney.env isn't a real environment file the OS loads -- read it
    ourselves at startup so indmoney_feed.py's os.environ.get() finds the
    token. Never overwrites a variable already set in the real environment
    (e.g. if this app moves to a host where the token is set properly)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env_file(os.path.join(BASE_DIR, "indmoney.env"))
_load_env_file(r"D:\FINPLUS WORKSPACE\indmoney_shared.env")

import yfinance as yf  # noqa: E402

import equity_scan  # noqa: E402  (must follow the env load above)
import indmoney_feed  # noqa: E402
import mcx_feed  # noqa: E402
import signal_engine  # noqa: E402
import signal_journal  # noqa: E402
import token_manager  # noqa: E402
import trend_engine  # noqa: E402
import swing_engine  # noqa: E402
import lt_engine  # noqa: E402
import penny_engine  # noqa: E402
import screener_views  # noqa: E402
import fundamental_engine  # noqa: E402
import options_views  # noqa: E402
import option_strategy_engine  # noqa: E402
import totp_auth  # noqa: E402

# Pre-import here, from the main thread, before any background thread
# starts. Both _trend_refresh_loop and _equity_scan_loop lazily
# `import screener_engine` on first use (see trend_engine._screener_engine()
# and equity_scan.load_liquid_candidates()), and both fire at process
# startup within the same second. Two threads racing to first-import the
# same not-yet-loaded module is a known Python deadlock class -- caught
# live on 2026-09-11: the equity scan sat with zero outbound connections
# for 45+ minutes, not erroring, not progressing, because it was blocked
# on the import lock the trend thread held. Importing it once, up front,
# turns every later `import screener_engine` into a safe sys.modules
# lookup instead of a race.
import sys
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
_screener_fallback = r"D:\STOCK SCREENER APP"
if os.path.exists(_screener_fallback) and _screener_fallback not in sys.path:
    sys.path.append(_screener_fallback)
import screener_engine  # noqa: E402,F401

app = Flask(__name__)

REFRESH_SECONDS = 60
MCX_SAMPLE_INTERVAL_SEC = 180
FAST_POLL_SECONDS = 3
EQUITY_SCAN_INTERVAL_SECONDS = 20 * 60
MOMENTUM_SCAN_INTERVAL_SECONDS = 3 * 60  # ~3s/pass, so this can run far tighter than the S/R scan's 20 min
TREND_REFRESH_SECONDS = 30 * 60  # daily-timeframe trend doesn't move intraday; no point refreshing faster
INDEX_UNDERLYINGS = ("NIFTY", "BANKNIFTY")

TREND_ITEMS = [
    {"id": "crude", "name": "Crude Oil (MCX)", "icon": "\U0001F6E2️", "kind": "commodity", "key": "CRUDEOIL"},
    {"id": "natgas", "name": "Natural Gas (MCX)", "icon": "⚡", "kind": "commodity", "key": "NATURALGAS"},
    {"id": "nifty", "name": "NIFTY 50", "icon": "\U0001F4C8", "kind": "index", "key": "NIFTY"},
    {"id": "banknifty", "name": "BANK NIFTY", "icon": "\U0001F3E6", "kind": "index", "key": "BANKNIFTY"},
]

_state_lock = threading.Lock()
_state = {"signals": {}, "updated_at": None, "error": None}

_fast_lock = threading.Lock()
_fast_state = {"ltp": {}, "depth": {}, "change": {}, "updated_at": None, "error": None}
SPARK_MAXLEN = 150  # ~7.5 min of history at the 3s poll cadence -- enough for a pocket sparkline
# Keyed by card id ("crude"/"natgas"/"nifty"/"banknifty"/"reliance") throughout
_spark_buffers = {cid: deque(maxlen=SPARK_MAXLEN) for cid in ("crude", "natgas", "nifty", "banknifty", "reliance")}
COMMODITY_CARD_IDS = {"CRUDEOIL": "crude", "NATURALGAS": "natgas"}

_equity_lock = threading.Lock()
_equity_state = {"result": None, "updated_at": None, "error": None, "running": False}

_momentum_lock = threading.Lock()
_momentum_state = {"result": None, "updated_at": None, "error": None, "running": False}

_momentum_fast_lock = threading.Lock()
_momentum_fast_state = {"quotes": {}, "updated_at": None, "error": None}
MOMENTUM_FAST_POLL_SECONDS = 3  # matches the Dashboard cards' cadence -- max 3s staleness as requested

_trend_lock = threading.Lock()
_trend_state = {"trends": {}, "updated_at": None, "error": None}

SWING_SCAN_INTERVAL_SECONDS = 10 * 60
LT_SCAN_INTERVAL_SECONDS = 30 * 60
PENNY_SCAN_INTERVAL_SECONDS = 15 * 60
FUNDAMENTALS_WARM_INTERVAL_SECONDS = 4 * 3600  # re-check for stale/missing entries every 4h; a fresh pass no-ops fast

_swing_lock = threading.Lock()
_swing_state = {"result": None, "updated_at": None, "error": None, "running": False}

def _load_initial_cohort_state(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            return {
                "result": {
                    "monthly_cohort": saved,
                    "picks": saved.get("picks", []),
                    "monthly_sip_budget": saved.get("monthly_sip_budget", 200.0),
                },
                "updated_at": datetime.now(timezone.utc),
                "error": None,
                "running": False,
            }
        except Exception:
            pass
    return {"result": None, "updated_at": None, "error": None, "running": False}

_lt_lock = threading.Lock()
_lt_state = _load_initial_cohort_state(lt_engine.LT_MONTHLY_PICKS_FILE)

_penny_lock = threading.Lock()
_penny_state = _load_initial_cohort_state(penny_engine.PENNY_MONTHLY_PICKS_FILE)

_fund_warm_lock = threading.Lock()
_fund_warm_state = {"running": False, "last_refreshed_count": 0, "updated_at": None, "error": None}


def _mcx_bar_recorder_loop():
    while True:
        try:
            time.sleep(MCX_SAMPLE_INTERVAL_SEC)
            if not mcx_feed.is_commodity_session_open():
                continue
            state = mcx_feed.record_mcx_sample(mcx_feed.load_mcx_bars())
            mcx_feed.save_mcx_bars(state)
            # Score any open journalled signals against the bars just recorded
            # -- new bars are exactly what resolve a trade to target or stop.
            for _sym in mcx_feed.MCX_SYMBOLS:
                signal_journal.evaluate(_sym, mcx_feed.bars_dataframe(_sym, state))
        except Exception:
            traceback.print_exc()


def _signal_refresh_loop():
    while True:
        try:
            signals = signal_engine.compute_all_signals()
            with _state_lock:
                _state["signals"] = signals
                _state["updated_at"] = datetime.now(timezone.utc)
                _state["error"] = None
        except Exception as exc:
            with _state_lock:
                _state["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        time.sleep(REFRESH_SECONDS)


def _fast_ltp_loop():
    """Price shown to the user for NIFTY/BANK NIFTY is the SPOT index
    (NSE_40000001 / _40000003) -- what INDmoney's own app and every broker
    terminal calls "NIFTY 50" / "BANK NIFTY", and what Abhilash was
    comparing against when the futures price looked "wrong" by ~70 points
    (that gap is the futures basis, a real premium, not a bug -- confirmed
    2026-09-11: spot 23398.1 vs futures 23470.3). The futures contract keeps
    doing everything it was already doing in the background -- order-book
    depth (spot indices carry no depth/volume at all, INDmoney returns null
    for both) and, via signal_engine, the actual sr_volume signal,
    entry/stop/target. One batched /market/quotes/full call covers both
    spot and futures scrip codes for both symbols per tick.

    Crude/natgas ride the same 3s tick for a consistent change%/sparkline
    across all four cards, but through mcx_feed.fetch_mcx_futures() (real
    MCX price, no NYMEX proxy involved) -- that call has its own 55s
    internal cache, so polling it every 3s costs nothing extra.

    All per-underlying dicts here are keyed by card id ("crude"/"natgas"/
    "nifty"/"banknifty"), not by the feed's own symbol constants -- the
    frontend just lowercases whatever key it receives to find the matching
    DOM element, so these have to already be the card ids.

    Sparkline buffers (_spark_buffers) are a bounded, in-memory trace of
    "since this server started" -- reset on restart, exist to show
    *direction and recent shape*, not to be an archive."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            ltp_by_card, depth_by_card, change_by_card = {}, {}, {}

            contracts = {u: indmoney_feed.get_front_month_contract(u) for u in INDEX_UNDERLYINGS}
            spot_codes = {u: trend_engine.INDEX_SECURITY_IDS[u] for u in INDEX_UNDERLYINGS}
            fut_codes = [c["scrip_code"] for c in contracts.values() if c]
            all_codes = fut_codes + list(spot_codes.values()) + ["NSE_2885"]
            if all_codes:
                quotes_by_code = indmoney_feed.get_quotes_full_many(all_codes)
                for u in INDEX_UNDERLYINGS:
                    card_id = u.lower()
                    spot_q = quotes_by_code.get(spot_codes[u])
                    fut_c = contracts.get(u)
                    fut_q = quotes_by_code.get(fut_c["scrip_code"]) if fut_c else None

                    if spot_q:
                        ltp_by_card[card_id] = spot_q["ltp"]
                        change_by_card[card_id] = {
                            "change": spot_q["day_change"], "change_pct": spot_q["day_change_pct"],
                            "day_open": spot_q["day_open"], "day_high": spot_q["day_high"],
                            "day_low": spot_q["day_low"], "prev_close": spot_q["prev_close"],
                        }
                        if spot_q["ltp"] is not None:
                            _spark_buffers[card_id].append(spot_q["ltp"])
                    if fut_q:
                        depth_by_card[card_id] = fut_q["depth"]

                # Reliance Live Quote & Depth
                rel_q = quotes_by_code.get("NSE_2885")
                if rel_q:
                    ltp_by_card["reliance"] = rel_q["ltp"]
                    change_by_card["reliance"] = {
                        "change": rel_q["day_change"], "change_pct": rel_q["day_change_pct"],
                        "day_open": rel_q["day_open"], "day_high": rel_q["day_high"],
                        "day_low": rel_q["day_low"], "prev_close": rel_q["prev_close"],
                    }
                    if rel_q["ltp"] is not None:
                        _spark_buffers["reliance"].append(rel_q["ltp"])
                    if rel_q.get("depth"):
                        depth_by_card["reliance"] = rel_q["depth"]

            for mcx_symbol, card_id in COMMODITY_CARD_IDS.items():
                q = mcx_feed.fetch_mcx_futures(mcx_symbol)
                if not q or q.get("mcx_ltp") is None:
                    continue
                ltp_by_card[card_id] = q["mcx_ltp"]
                change_by_card[card_id] = {"change": q.get("mcx_change"), "change_pct": q.get("mcx_pct")}
                _spark_buffers[card_id].append(q["mcx_ltp"])

            with _fast_lock:
                _fast_state["ltp"] = ltp_by_card
                _fast_state["depth"] = depth_by_card
                _fast_state["change"] = change_by_card
                _fast_state["updated_at"] = now
                _fast_state["error"] = None
        except Exception as exc:
            with _fast_lock:
                _fast_state["error"] = f"{type(exc).__name__}: {exc}"
        time.sleep(FAST_POLL_SECONDS)


def _trend_refresh_loop():
    """Daily-timeframe trend per instrument. For the indices, the freshest
    known LTP (from the fast poller) is passed in so the classification
    reflects right-now price vs. the daily MAs, not yesterday's close. For
    commodities this deliberately does NOT pass the MCX INR price -- the
    daily series here is yfinance's USD-quoted NYMEX proxy, and mixing an
    INR price into a USD-based EMA/MA comparison would silently misclassify
    every reading. trend_engine falls back to the series' own last close.

    Waits briefly before its first pass so _fast_ltp_loop has time to
    populate _fast_state at least once first -- both loops fire immediately
    on thread start, and if this one's first pass won the race, it locked
    in the daily-close fallback (effectively yesterday's price) for a full
    TREND_REFRESH_SECONDS before trying again. Caught 2026-09-11: BANK
    NIFTY's trend card showed 56471.95 (prev_close) for 30+ minutes while
    the live card correctly showed 56921."""
    time.sleep(10)
    while True:
        try:
            with _fast_lock:
                fast_ltp = dict(_fast_state["ltp"])
            trends = {}
            for item in TREND_ITEMS:
                if item["kind"] == "commodity":
                    trends[item["id"]] = trend_engine.get_commodity_trend(item["key"])
                elif item["kind"] == "equity":
                    trends[item["id"]] = trend_engine.get_equity_trend(item["key"], fast_ltp.get(item["id"]))
                else:
                    trends[item["id"]] = trend_engine.get_index_trend(item["key"], fast_ltp.get(item["id"]))
            with _trend_lock:
                _trend_state["trends"] = trends
                _trend_state["updated_at"] = datetime.now(timezone.utc)
                _trend_state["error"] = None
        except Exception as exc:
            with _trend_lock:
                _trend_state["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        time.sleep(TREND_REFRESH_SECONDS)


def _equity_scan_loop():
    while True:
        try:
            with _equity_lock:
                _equity_state["running"] = True
            result = equity_scan.scan_universe(top_n=10)
            with _equity_lock:
                _equity_state["result"] = result
                _equity_state["updated_at"] = datetime.now(timezone.utc)
                _equity_state["error"] = None
        except Exception as exc:
            with _equity_lock:
                _equity_state["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            with _equity_lock:
                _equity_state["running"] = False
        time.sleep(EQUITY_SCAN_INTERVAL_SECONDS)


def _momentum_scan_loop():
    """The screener's own compute_intraday_picks() scoring (day-move +
    volume + RSI + momentum + relative strength), run with live INDmoney
    price/volume instead of the screener's yfinance-polled snapshot. ~3s
    per full-universe pass (2-3 batched /quotes/full calls vs the S/R
    scan's 145 sequential historical-candle calls), so this can run on a
    much tighter interval than the S/R tab without hammering anything."""
    while True:
        try:
            with _momentum_lock:
                _momentum_state["running"] = True
            result = equity_scan.scan_intraday_momentum(top_n=10)
            with _momentum_lock:
                _momentum_state["result"] = result
                _momentum_state["updated_at"] = datetime.now(timezone.utc)
                _momentum_state["error"] = None
        except Exception as exc:
            with _momentum_lock:
                _momentum_state["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            with _momentum_lock:
                _momentum_state["running"] = False
        time.sleep(MOMENTUM_SCAN_INTERVAL_SECONDS)


def _momentum_fast_poll_loop():
    """3s price/change refresh for whichever 20 symbols the momentum scan
    currently has picked -- separate from the 3-minute full rescan above,
    which still owns the score/rank/entry/stop/target (those need fresh
    RSI/volume-spike math, not just a price tick). One batched
    /quotes/full call per tick for the current pick list, same shape as
    the Dashboard cards' fast poll."""
    while True:
        try:
            with _momentum_lock:
                result = _momentum_state["result"]
            symbols = []
            if result:
                symbols = [p["symbol"] for p in result.get("buy", [])] + [p["symbol"] for p in result.get("sell", [])]

            if symbols:
                quotes = equity_scan.fetch_live_quotes_for_symbols(symbols)
                with _momentum_fast_lock:
                    _momentum_fast_state["quotes"] = quotes
                    _momentum_fast_state["updated_at"] = datetime.now(timezone.utc)
                    _momentum_fast_state["error"] = None
        except Exception as exc:
            with _momentum_fast_lock:
                _momentum_fast_state["error"] = f"{type(exc).__name__}: {exc}"
        time.sleep(MOMENTUM_FAST_POLL_SECONDS)


def _swing_scan_loop():
    while True:
        try:
            with _swing_lock:
                _swing_state["running"] = True
            result = swing_engine.scan_swing_candidates(top_n=30)
            with _swing_lock:
                _swing_state["result"] = result
                _swing_state["updated_at"] = datetime.now(timezone.utc)
                _swing_state["error"] = None
        except Exception as exc:
            with _swing_lock:
                _swing_state["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            with _swing_lock:
                _swing_state["running"] = False
        time.sleep(SWING_SCAN_INTERVAL_SECONDS)


def _lt_scan_loop():
    while True:
        try:
            with _lt_lock:
                _lt_state["running"] = True
            result = lt_engine.scan_lt_discovery(top_n=30)
            with _lt_lock:
                _lt_state["result"] = result
                _lt_state["updated_at"] = datetime.now(timezone.utc)
                _lt_state["error"] = None
        except Exception as exc:
            with _lt_lock:
                _lt_state["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            with _lt_lock:
                _lt_state["running"] = False
        time.sleep(LT_SCAN_INTERVAL_SECONDS)


def _penny_scan_loop():
    while True:
        try:
            with _penny_lock:
                _penny_state["running"] = True
            result = penny_engine.scan_penny_picks(top_n=30, monthly_sip=200.0)
            with _penny_lock:
                _penny_state["result"] = result
                _penny_state["updated_at"] = datetime.now(timezone.utc)
                _penny_state["error"] = None
        except Exception as exc:
            with _penny_lock:
                _penny_state["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            with _penny_lock:
                _penny_state["running"] = False
        time.sleep(PENNY_SCAN_INTERVAL_SECONDS)


def _fundamentals_warm_loop():
    """Populates fundamental_engine's shared cache with real data
    (Tickertape + screener.in, rate-limited) for the full screener_data.json
    universe -- the lt/penny/swing scans all read that same in-process
    cache via get_fundamentals(allow_network=False), so they pick up real
    numbers as this fills in, no extra wiring needed. A full first pass
    over ~2500 symbols at the default 1.5s pace takes on the order of an
    hour; subsequent passes skip anything already fresh (30-day TTL) and
    finish almost immediately, which is why this re-checks every few hours
    rather than once a day -- newly-listed or previously-failed symbols
    get picked up promptly instead of waiting a full day."""
    while True:
        try:
            symbols = []
            if os.path.exists(equity_scan.SCREENER_DATA_PATH):
                with open(equity_scan.SCREENER_DATA_PATH, encoding="utf-8") as f:
                    rows = json.load(f)
                symbols = [r["symbol"] for r in rows if r.get("symbol")]

            with _fund_warm_lock:
                _fund_warm_state["running"] = True
            count = fundamental_engine.refresh_stale(symbols, pace_sec=1.5) if symbols else 0
            with _fund_warm_lock:
                _fund_warm_state["last_refreshed_count"] = count
                _fund_warm_state["updated_at"] = datetime.now(timezone.utc)
                _fund_warm_state["error"] = None
        except Exception as exc:
            with _fund_warm_lock:
                _fund_warm_state["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            with _fund_warm_lock:
                _fund_warm_state["running"] = False
        time.sleep(FUNDAMENTALS_WARM_INTERVAL_SECONDS)


def _options_scan_loop():
    """Refreshes the Top 10 options screener on a schedule. The refresh itself
    fetches a handful of live option chains to check real OI/PCR before a
    stock qualifies -- too slow (and too fragile to any API hiccup) to run
    inline inside a page request, so it runs here instead; /options just
    reads whatever this last computed via option_strategy_engine.scan_top_options_stocks()."""
    while True:
        try:
            option_strategy_engine.refresh_top_options_stocks()
        except Exception:
            traceback.print_exc()
        time.sleep(option_strategy_engine._TOP_OPTIONS_TTL_SEC)


def _options_heatmap_loop():
    """Refreshes the sector heatmap on a schedule, same reasoning as the
    options scan loop above -- keeps /options page loads instant."""
    while True:
        try:
            option_strategy_engine.refresh_sector_heatmap()
        except Exception:
            traceback.print_exc()
        time.sleep(option_strategy_engine._HEATMAP_TTL_SEC)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@app.route("/api/<path:dummy>", methods=["OPTIONS"])
def api_options_handler(dummy):
    return "", 200


@app.route("/api/markets")
def api_markets():
    with _state_lock:
        signals = dict(_state["signals"])
        signals_updated = _state["updated_at"].isoformat() if _state["updated_at"] else None
    with _fast_lock:
        fast_ltp = dict(_fast_state["ltp"])
        fast_change = dict(_fast_state["change"])
        fast_depth = dict(_fast_state["depth"])
        spark = {u: list(buf) for u, buf in _spark_buffers.items()}
    with _trend_lock:
        trends = dict(_trend_state.get("trends", {}))

    tok = token_manager.get_token_status()
    return jsonify({
        "success": True,
        "signals": signals,
        "signals_updated_at": signals_updated,
        "fast_ltp": fast_ltp,
        "fast_change": fast_change,
        "fast_depth": fast_depth,
        "spark": spark,
        "trends": trends,
        "token_status": tok,
    })


@app.route("/api/commodities")
def api_commodities():
    with _state_lock:
        signals = dict(_state["signals"])
    with _fast_lock:
        fast_ltp = dict(_fast_state["ltp"])
        fast_change = dict(_fast_state["change"])
        spark = {u: list(buf) for u, buf in _spark_buffers.items() if u in ("crude", "natgas")}

    mcx_bars_path = os.path.join(BASE_DIR, "mcx_bars.json")
    mcx_bars = {}
    if os.path.exists(mcx_bars_path):
        try:
            with open(mcx_bars_path, "r", encoding="utf-8") as f:
                mcx_bars = json.load(f)
        except Exception:
            pass

    crude_dict = mcx_bars.get("CRUDEOIL", {}) if isinstance(mcx_bars, dict) else {}
    crude_bars = crude_dict.get("bars", []) if isinstance(crude_dict, dict) else []

    natgas_dict = mcx_bars.get("NATURALGAS", {}) if isinstance(mcx_bars, dict) else {}
    natgas_bars = natgas_dict.get("bars", []) if isinstance(natgas_dict, dict) else []

    return jsonify({
        "success": True,
        "crude": {
            "signal": signals.get("crude", {}),
            "ltp": fast_ltp.get("crude"),
            "change": fast_change.get("crude"),
            "spark": spark.get("crude", []),
            "bars": crude_bars[-40:] if isinstance(crude_bars, list) else [],
        },
        "natgas": {
            "signal": signals.get("natgas", {}),
            "ltp": fast_ltp.get("natgas"),
            "change": fast_change.get("natgas"),
            "spark": spark.get("natgas", []),
            "bars": natgas_bars[-40:] if isinstance(natgas_bars, list) else [],
        },
    })



@app.route("/api/screener/all")
def api_screener_all():
    with _swing_lock:
        swing = _swing_state.get("result")
    with _lt_lock:
        lt = _lt_state.get("result")
    with _penny_lock:
        penny = _penny_state.get("result")
    with _momentum_lock:
        momentum = _momentum_state.get("result")
    with _equity_lock:
        equity = _equity_state.get("result")
    return jsonify({
        "success": True,
        "swing": swing,
        "lt": lt,
        "penny": penny,
        "momentum": momentum,
        "equity": equity,
    })


@app.route("/api/alerts")
def api_alerts():
    records = signal_journal._load()
    recent = list(reversed(records[-100:])) if records else []
    overall_stats = signal_journal.stats()
    crude_stats = signal_journal.stats("CRUDEOIL")
    natgas_stats = signal_journal.stats("NATURALGAS")
    setup_stats = signal_journal.stats_by_setup()
    return jsonify({
        "success": True,
        "recent": recent,
        "stats": {
            "overall": overall_stats,
            "crude": crude_stats,
            "natgas": natgas_stats,
            "by_setup": setup_stats,
        },
    })


@app.route("/api/fast_ltp")
def api_fast_ltp():
    with _fast_lock:
        spark = {u: list(buf) for u, buf in _spark_buffers.items()}
        return jsonify({
            "ltp": _fast_state["ltp"],
            "depth": _fast_state["depth"],
            "change": _fast_state["change"],
            "spark": spark,
            "updated_at": _fast_state["updated_at"].isoformat() if _fast_state["updated_at"] else None,
            "error": _fast_state["error"],
        })


@app.route("/api/token_status")
def api_token_status():
    status = token_manager.get_token_status()
    totp_val = totp_auth.get_current_totp()
    status["totp_configured"] = bool(os.environ.get("INDMONEY_TOTP_SECRET"))
    status["current_totp"] = totp_val
    return jsonify(status)


@app.route("/api/token/refresh_totp", methods=["GET", "POST"])
def api_token_refresh_totp():
    ok, msg = totp_auth.refresh_token_using_totp()
    status = token_manager.get_token_status()
    return jsonify({
        "success": ok,
        "message": msg,
        "status": status,
        "current_totp": totp_auth.get_current_totp(),
    })


@app.route("/api/option_chain/<underlying>")
def api_option_chain(underlying):
    exp = request.args.get("expiry")
    data = indmoney_feed.get_option_chain(underlying, expiry=exp)
    if not data:
        return jsonify({"success": False, "error": f"No option chain data available for {underlying}"}), 404
    return jsonify({"success": True, "data": data})


@app.route("/api/option_expiries/<underlying>")
def api_option_expiries(underlying):
    expiries = indmoney_feed.get_option_expiries(underlying)
    return jsonify({"success": True, "underlying": underlying.upper(), "expiries": expiries})


@app.route("/api/momentum_fast_ltp")
def api_momentum_fast_ltp():
    with _momentum_fast_lock:
        return jsonify({
            "quotes": _momentum_fast_state["quotes"],
            "updated_at": _momentum_fast_state["updated_at"].isoformat() if _momentum_fast_state["updated_at"] else None,
            "error": _momentum_fast_state["error"],
        })


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    message, message_kind = "", ""

    if request.method == "POST":
        new_token = (request.form.get("token") or "").strip()
        if not new_token:
            message, message_kind = "Paste a token before saving.", "err"
        else:
            ok, detail = token_manager.test_token(new_token)
            if not ok:
                message, message_kind = f"Not saved -- INDmoney rejected it: {detail}", "err"
            else:
                token_manager.save_token(new_token, BASE_DIR)
                return redirect(url_for("settings_page", saved="1"))

    if request.args.get("saved") == "1":
        message, message_kind = "Token saved and applied -- no restart needed, it's live now.", "ok"

    status = token_manager.get_token_status()
    if not status["has_token"]:
        status_html = '<div class="status-pill status-bad">No token set</div>'
    elif status["is_expired"]:
        status_html = '<div class="status-pill status-bad">Current token has expired</div>'
    else:
        mins = status["expires_in_min"]
        cls = "status-warn" if mins is not None and mins < 60 else "status-ok"
        expiry_txt = (f"expires in {int(mins)} min" if mins is not None and mins < 180
                      else f"expires in {round(mins / 60, 1)}h" if mins is not None else "expiry unknown")
        status_html = f'<div class="status-pill {cls}">Token active &middot; {expiry_txt}</div>'

    msg_html = f'<div class="settings-msg settings-msg-{message_kind}">{message}</div>' if message else ""

    return f"""<!DOCTYPE html>
<html><head>
  <meta charset="utf-8">
  <title>Settings &mdash; INDmoney Token</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>{STYLE}
    .settings-wrap{{max-width:560px;margin:48px auto;padding:0 24px}}
    .settings-card{{background:linear-gradient(180deg,var(--panel) 0%,var(--panel-2) 100%);
      border:1px solid var(--border);border-radius:18px;padding:32px}}
    .settings-card h1{{margin:0 0 6px;font-size:22px}}
    .settings-card p{{color:var(--muted);font-size:14px;line-height:1.6}}
    .status-pill{{display:inline-block;padding:6px 14px;border-radius:100px;font-size:13px;font-weight:700;margin:10px 0 20px}}
    .status-ok{{background:var(--green-bg);color:var(--green)}}
    .status-warn{{background:rgba(234,179,8,.12);color:var(--amber)}}
    .status-bad{{background:var(--red-bg);color:var(--red)}}
    textarea{{width:100%;min-height:90px;background:var(--bg);color:var(--text);border:1px solid var(--border);
      border-radius:10px;padding:12px;font-family:monospace;font-size:13px;resize:vertical}}
    .btn{{margin-top:14px;background:linear-gradient(180deg,#6366f1,#4f46e5);color:#fff;border:none;
      padding:12px 22px;border-radius:10px;font-weight:700;font-size:14.5px;cursor:pointer}}
    .btn:hover{{filter:brightness(1.08)}}
    .settings-msg{{margin-top:16px;padding:10px 14px;border-radius:10px;font-size:13.5px}}
    .settings-msg-ok{{background:var(--green-bg);color:var(--green)}}
    .settings-msg-err{{background:var(--red-bg);color:var(--red)}}
    a.back{{color:var(--muted);font-size:13px;text-decoration:none}}
    a.back:hover{{color:var(--text)}}
  </style>
</head>
<body>
  <div class="settings-wrap">
    <p><a class="back" href="/">&larr; Back to dashboard</a></p>
    <div class="settings-card">
      <h1>INDmoney Access Token</h1>
      <p>INDmoney has no programmable login (unlike Kite Connect's request-token exchange) --
        tokens are generated manually on their <a href="https://www.indstocks.com/app/api-trading/access-tokens"
        target="_blank" style="color:#a5b4fc">access-tokens page</a> and expire every 24h. Paste a fresh one
        below; it's tested against a live call before saving, and takes effect immediately &mdash; no restart.</p>
      {status_html}
      <form method="post">
        <textarea name="token" placeholder="Paste the new token here" autofocus></textarea><br>
        <button class="btn" type="submit">Test &amp; Save</button>
      </form>
      {msg_html}
    </div>
  </div>
</body></html>"""


# ─── Presentation ──────────────────────────────────────────────────────────

CALL_META = {
    "CE": ("call-ce", "▲", "BUY CE"),
    "PE": ("call-pe", "▼", "BUY PE"),
}
NO_CALL_META = ("call-none", "●", "NO SIGNAL")

STYLE = """
:root{
  --bg:#0a0b0f; --panel:#12141c; --panel-2:#161923; --border:#232733;
  --text:#f3f5f9; --muted:#b8c0d4; --dim:#8890a6;
  --green:#22c55e; --green-bg:rgba(34,197,94,.12);
  --red:#ef4444; --red-bg:rgba(239,68,68,.12);
  --lime:#a3e635; --lime-bg:rgba(163,230,53,.10);
  --orange:#fb923c; --orange-bg:rgba(251,146,60,.10);
  --amber:#eab308;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  margin:0;padding:0 0 60px}

.top-nav{display:flex;align-items:center;gap:4px;padding:14px 32px;border-bottom:1px solid var(--border);
  background:var(--panel-2)}
.top-nav .brand{font-weight:800;font-size:14.5px;color:var(--text);margin-right:20px;letter-spacing:-.01em}
.top-nav a{color:var(--muted);text-decoration:none;font-size:14px;font-weight:700;padding:8px 16px;
  border-radius:100px;transition:background .15s ease,color .15s ease}
.top-nav a:hover{color:var(--text);background:rgba(255,255,255,.04)}
.top-nav a.active{color:#fff;background:linear-gradient(180deg,#6366f1,#4f46e5)}

.header{padding:32px 32px 20px;border-bottom:1px solid var(--border);
  background:radial-gradient(1200px 300px at 10% -20%, rgba(99,102,241,.10), transparent)}
.header h1{margin:0 0 6px;font-size:29px;font-weight:800;letter-spacing:-.02em}
.header p{margin:0;color:var(--muted);font-size:15.5px;line-height:1.65;max-width:900px}
.meta-row{display:flex;align-items:center;gap:16px;margin-top:14px;flex-wrap:wrap}
.meta-pill{display:inline-flex;align-items:center;gap:7px;background:var(--panel-2);
  border:1px solid var(--border);border-radius:100px;padding:6px 14px;font-size:13.5px;color:var(--muted)}
.meta-pill-link{text-decoration:none;transition:border-color .2s ease,color .2s ease}
.meta-pill-link:hover{border-color:#3a4053;color:var(--text)}
.meta-pill-warn{background:rgba(234,179,8,.12);color:var(--amber);border-color:rgba(234,179,8,.3)}
.meta-pill-bad{background:var(--red-bg);color:var(--red);border-color:rgba(239,68,68,.35)}
.pulse{width:7px;height:7px;border-radius:50%;background:var(--green);
  box-shadow:0 0 0 0 rgba(34,197,94,.5);animation:pulse 1.8s infinite}
@keyframes pulse{
  0%{box-shadow:0 0 0 0 rgba(34,197,94,.55)}
  70%{box-shadow:0 0 0 7px rgba(34,197,94,0)}
  100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}
}
.err-banner{margin:16px 32px 0;background:var(--red-bg);border:1px solid rgba(239,68,68,.35);
  color:#fca5a5;padding:10px 16px;border-radius:10px;font-size:13px}

.section{position:relative;margin:24px 32px 0;padding:30px 30px 34px;border-radius:22px;
  background:linear-gradient(180deg,rgba(255,255,255,.025) 0%,rgba(255,255,255,0) 100%),var(--bg);
  border:1px solid var(--border);
  box-shadow:0 1px 0 rgba(255,255,255,.03) inset,0 20px 40px -28px rgba(0,0,0,.6)}
.section::before{content:"";position:absolute;top:-1px;left:22px;right:22px;height:2px;border-radius:2px;
  background:linear-gradient(90deg,transparent,#6366f1,#818cf8,#6366f1,transparent);opacity:.55}
.section:last-child{margin-bottom:24px}
.section-head{display:flex;align-items:baseline;gap:10px;margin-bottom:4px}
.section-head h2{margin:0;font-size:21px;font-weight:700;letter-spacing:-.01em}
.section-bar{width:4px;height:20px;border-radius:2px;background:linear-gradient(180deg,#818cf8,#6366f1);
  box-shadow:0 0 12px rgba(99,102,241,.5)}
.section p.desc{color:var(--muted);font-size:14.5px;line-height:1.55;margin:4px 0 18px;max-width:900px}

.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px;perspective:1200px}

/* Real 3D card: JS drives rotateX/rotateY/translateZ per-frame from cursor
   position (see the tilt script at the bottom) and writes the matching
   shadow + glare-position custom properties; this block only owns the
   resting state and the transition back to it on mouse-leave. */
.card-3d{
  transform-style:preserve-3d;
  transition:transform .5s cubic-bezier(.22,1,.36,1),box-shadow .5s cubic-bezier(.22,1,.36,1),border-color .3s ease;
  box-shadow:0 2px 3px rgba(0,0,0,.3),0 14px 26px -10px rgba(0,0,0,.6),0 30px 54px -24px rgba(0,0,0,.55),
    inset 0 1px 0 rgba(255,255,255,.07),inset 0 -1px 0 rgba(0,0,0,.25);
}
.card-3d::after{
  content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;z-index:2;
  background:radial-gradient(480px circle at var(--glare-x,50%) var(--glare-y,0%),rgba(255,255,255,.14),transparent 55%);
  opacity:0;transition:opacity .4s ease;
}
.card-3d.tilting::after{opacity:1}
.card-3d.tilting{transition:box-shadow .05s linear}
.card{background:linear-gradient(180deg,var(--panel) 0%,var(--panel-2) 100%);
  border:1px solid var(--border);border-radius:16px;padding:22px;position:relative}
.card:hover{border-color:#3a4053}
.card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:2px}
.card-title{display:flex;align-items:center;gap:8px;font-size:17px;font-weight:700;color:#d6dae5}
.live-dot{width:7px;height:7px;border-radius:50%;background:var(--green);animation:pulse 1.8s infinite}
.ltp{font-size:37px;font-weight:800;letter-spacing:-.02em;margin:10px 0 2px;font-variant-numeric:tabular-nums}
.ltp-sub{color:var(--muted);font-size:12.5px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}

.ltp-head{display:flex;justify-content:space-between;align-items:flex-end;gap:10px}
.chg{font-size:16px;font-weight:700;display:flex;align-items:center;gap:5px;margin-bottom:14px;min-height:20px}
.chg.up{color:var(--green)}
.chg.down{color:var(--red)}
.chg .arrow{font-size:12px}
.spark-wrap{flex-shrink:0;margin-bottom:14px;opacity:.9}

.mcx-compare{display:block;color:var(--text);font-size:19px;font-weight:700;margin-top:4px}
.mcx-compare .lab{color:var(--muted);font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-right:6px}

.badge{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:100px;
  font-weight:700;font-size:14.5px;letter-spacing:.01em}
.call-ce{background:var(--green-bg);color:var(--green);border:1px solid rgba(34,197,94,.3)}
.call-pe{background:var(--red-bg);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.call-none{background:rgba(139,147,167,.10);color:var(--muted);border:1px solid var(--border)}

/* Trend badges reuse TREND_STATES' own class names (badge-green etc.) from
   screener_engine.py directly -- no separate mapping table to drift out of sync. */
.badge-green{background:var(--green-bg);color:var(--green);border:1px solid rgba(34,197,94,.3)}
.badge-red{background:var(--red-bg);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.badge-yellow{background:rgba(234,179,8,.10);color:var(--amber);border:1px solid rgba(234,179,8,.3)}
.badge-purple{background:rgba(129,140,248,.10);color:#a5b4fc;border:1px solid rgba(129,140,248,.3)}

.trend-card{background:linear-gradient(180deg,var(--panel) 0%,var(--panel-2) 100%);
  border:1px solid var(--border);border-radius:16px;padding:20px;position:relative}
.trend-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.trend-top h3{margin:0;font-size:17px;font-weight:700}
.trend-levels{display:flex;flex-direction:column;gap:7px;margin-top:14px}
.trend-level-row{display:flex;justify-content:space-between;font-size:14.5px}
.trend-level-row .l{color:var(--muted)}
.trend-level-row .v{font-variant-numeric:tabular-nums;color:var(--text);font-weight:600}
.trend-level-row .v.above{color:var(--green)}
.trend-level-row .v.below{color:var(--red)}

.reason{color:var(--muted);font-size:14px;margin:12px 0 4px;line-height:1.55;min-height:36px}
.warm{color:var(--amber);font-size:13px;margin-top:2px;font-weight:600}

.rangebar{margin:16px 0 6px;height:7px;border-radius:4px;background:#1c202b;position:relative;overflow:visible}
.rangebar .fill{position:absolute;top:0;bottom:0;border-radius:4px;background:linear-gradient(90deg,#6366f1,#818cf8)}
.rangebar .dot{position:absolute;top:-3.5px;width:14px;height:14px;border-radius:50%;
  background:var(--text);border:2px solid var(--bg);transform:translateX(-50%)}
.range-labels{display:flex;justify-content:space-between;font-size:12.5px;color:var(--muted);margin-top:6px;font-weight:600}

.kv{width:100%;border-collapse:collapse;font-size:14.5px;margin-top:14px}
.kv td{padding:6px 0;border-top:1px solid rgba(255,255,255,.04)}
.kv td:first-child{color:var(--muted)}
.kv td:last-child{text-align:right;font-variant-numeric:tabular-nums;color:var(--text);font-weight:600}

.stat-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.stat-tile{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px 16px}
.stat-tile .n{font-size:26px;font-weight:800}
.stat-tile .l{font-size:12.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:2px;font-weight:600}

.table-wrap{background:var(--panel);border:1px solid var(--border);border-radius:14px;overflow:hidden}
table.list{width:100%;border-collapse:collapse;font-size:14.5px}
table.list thead th{text-align:left;color:var(--muted);font-size:12.5px;text-transform:uppercase;
  letter-spacing:.06em;padding:11px 14px;border-bottom:1px solid var(--border);background:var(--panel-2);font-weight:700}
table.list td{padding:10px 14px;border-bottom:1px solid rgba(255,255,255,.03);font-variant-numeric:tabular-nums}
table.list tbody tr:last-child td{border-bottom:none}
table.list tbody tr:hover{background:rgba(255,255,255,.02)}
table.list .sym{font-weight:700}
table.list .reason-cell{color:var(--muted);font-size:13px;font-variant-numeric:normal}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:6px}
@media (max-width:800px){.two-col{grid-template-columns:1fr}}

.tab-bar{display:flex;gap:8px;margin-bottom:18px;border-bottom:1px solid var(--border)}
.tab-btn{background:none;border:none;color:var(--muted);font-family:inherit;font-size:14.5px;font-weight:700;
  padding:10px 4px;margin-right:20px;cursor:pointer;border-bottom:2px solid transparent}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{color:var(--text);border-bottom-color:#6366f1}
.tab-panel[hidden]{display:none}

.mom-subhead{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:700;margin:18px 0 12px}
.mom-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.mom-card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px 16px;position:relative}
.mom-card.buy{border-left:3px solid var(--green)}
.mom-card.sell{border-left:3px solid var(--red)}
.mom-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px}
.mom-sym{font-weight:800;font-size:15.5px}
.mom-score{font-size:13px;font-weight:800;padding:3px 10px;border-radius:100px}
.mom-score.buy{background:var(--green-bg);color:var(--green)}
.mom-score.sell{background:var(--red-bg);color:var(--red)}
.mom-live-row{display:flex;align-items:baseline;gap:8px;margin:4px 0 2px}
.mom-live-price{font-size:19px;font-weight:800;font-variant-numeric:tabular-nums}
.mom-live-chg{font-size:12px;font-weight:700}
.mom-live-chg.up{color:var(--green)}
.mom-live-chg.down{color:var(--red)}
.mom-chg{font-size:13px;font-weight:700;margin-bottom:10px}
.mom-chg.buy{color:var(--green)}
.mom-chg.sell{color:var(--red)}
.mom-levels{display:grid;grid-template-columns:1fr 1fr;gap:4px 14px;font-size:12.5px;color:var(--muted)}
.mom-levels b{color:var(--text);font-variant-numeric:tabular-nums}
.mom-reason{font-size:12px;color:var(--muted);margin-top:10px;line-height:1.45}
.empty{padding:18px 14px;color:var(--muted);font-size:14px}
.subhead{display:flex;align-items:center;gap:8px;font-size:14.5px;font-weight:700;margin:0 0 10px}
.dotlabel{width:9px;height:9px;border-radius:50%}

.depth-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:18px;perspective:1200px}
.depth-card{background:linear-gradient(180deg,var(--panel) 0%,var(--panel-2) 100%);
  border:1px solid var(--border);border-radius:16px;padding:20px;position:relative}
.depth-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px}
.depth-top h3{margin:0;font-size:17px;font-weight:700}
.depth-mid{font-size:13.5px;color:var(--muted)}
.split-bar{height:9px;border-radius:5px;background:var(--red);overflow:hidden;display:flex;margin-bottom:7px}
.split-bar .buy{background:var(--green)}
.split-labels{display:flex;justify-content:space-between;font-size:13px;color:var(--muted);margin-bottom:16px;font-weight:600}
.bidask{display:flex;justify-content:space-between;margin-bottom:12px}
.bidask .side{font-size:22px;font-weight:800;font-variant-numeric:tabular-nums}
.bidask .lab{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.depth-rows{display:flex;flex-direction:column;gap:4px}
.depth-row{display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:13.5px;font-variant-numeric:tabular-nums;font-weight:600}
.depth-cell{position:relative;padding:4px 8px;border-radius:4px;overflow:hidden;display:flex;justify-content:space-between}
.depth-cell .bar{position:absolute;top:0;bottom:0;z-index:0}
.depth-cell.bid .bar{right:0;background:rgba(34,197,94,.16)}
.depth-cell.ask .bar{left:0;background:rgba(239,68,68,.16)}
.depth-cell span{position:relative;z-index:1}
.depth-cell.bid{color:#86efac}
.depth-cell.ask{color:#fca5a5}

/* Option Trading Window */
.opt-window{margin-top:14px;background:rgba(18,20,28,.7);border:1px solid #282d3f;border-radius:12px;padding:12px}
.opt-win-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.opt-win-title{font-size:11px;font-weight:800;letter-spacing:.06em;color:#a5b4fc;display:flex;align-items:center;gap:5px}
.opt-prem{font-size:13px;font-weight:600;color:var(--text);margin-bottom:8px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px}
.opt-metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;background:rgba(0,0,0,.35);
  border:1px solid rgba(255,255,255,.04);border-radius:8px;padding:7px 8px;margin-bottom:10px}
.opt-metrics .l{display:block;font-size:10px;color:var(--dim);text-transform:uppercase;font-weight:600;letter-spacing:.03em}
.opt-metrics .v{font-size:12px;font-weight:700;color:var(--text);font-variant-numeric:tabular-nums}
.btn-view-chain{width:100%;background:linear-gradient(180deg,#3730a3,#2e2675);border:1px solid #4f46e5;
  color:#e0e7ff;font-size:12.5px;font-weight:700;padding:8px 12px;border-radius:8px;cursor:pointer;
  transition:all .2s ease;display:flex;align-items:center;justify-content:center;gap:6px}
.btn-view-chain:hover{background:linear-gradient(180deg,#4f46e5,#4338ca);border-color:#818cf8;color:#fff;
  box-shadow:0 0 14px rgba(99,102,241,.4)}

/* Option Chain Modal */
.modal-backdrop{position:fixed;inset:0;background:rgba(5,7,12,.85);backdrop-filter:blur(10px);
  z-index:9999;display:none;align-items:center;justify-content:center;padding:20px}
.modal-box{background:#0d0f17;border:1px solid #23283b;border-radius:20px;width:100%;max-width:1240px;
  max-height:90vh;display:flex;flex-direction:column;box-shadow:0 24px 64px rgba(0,0,0,.85),inset 0 1px 0 rgba(255,255,255,.06);
  overflow:hidden}
.modal-header{display:flex;justify-content:space-between;align-items:center;padding:18px 24px;background:#131724;
  border-bottom:1px solid #23283b;gap:16px;flex-wrap:wrap}
.modal-title-group h2{margin:0 0 4px;font-size:20px;font-weight:800;letter-spacing:-.01em}
.oc-sub-bar{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.oc-stat{font-size:13px;color:var(--muted);font-weight:500}
.oc-stat b{color:var(--text);font-weight:700}
.modal-actions{display:flex;align-items:center;gap:10px}
.oc-select{background:#1a1e2e;border:1px solid #323850;color:var(--text);padding:7px 12px;border-radius:8px;
  font-size:13px;font-weight:600;outline:none;cursor:pointer}
.oc-select:focus{border-color:#6366f1}
.oc-btn-refresh{background:#1a1e2e;border:1px solid #323850;color:var(--text);padding:7px 11px;border-radius:8px;
  cursor:pointer;font-size:14px;transition:background .15s ease}
.oc-btn-refresh:hover{background:#252b42}
.modal-close{background:none;border:none;color:var(--muted);font-size:24px;cursor:pointer;line-height:1;
  padding:4px 8px;border-radius:6px}
.modal-close:hover{color:var(--text);background:rgba(255,255,255,.06)}
.modal-body{padding:0;overflow:auto;flex:1}
.oc-table-wrap{width:100%}
.oc-table{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums;text-align:right}
.oc-table th{padding:8px 7px;position:sticky;top:0;z-index:10;background:#161a29;border-bottom:1px solid #262c42;
  font-weight:700;font-size:11px;letter-spacing:.03em}
.oc-table th.th-call-grp{text-align:center;background:rgba(34,197,94,.14);color:#4ade80;border-bottom:1px solid rgba(34,197,94,.3)}
.oc-table th.th-put-grp{text-align:center;background:rgba(239,68,68,.14);color:#f87171;border-bottom:1px solid rgba(239,68,68,.3)}
.oc-table th.th-strike-grp{text-align:center;background:#1e2336;color:#fbbf24;border-bottom:1px solid #384060}
.oc-table th.th-strike{text-align:center;background:#1a1f30;color:#fbbf24;font-weight:800}
.oc-table td{padding:6px 7px;border-bottom:1px solid rgba(255,255,255,.03)}
.oc-table tr:hover{background:rgba(255,255,255,.04)!important}
.oc-table td.td-strike{text-align:center;font-weight:800;color:#fbbf24;background:rgba(0,0,0,.25);
  border-left:1px solid #23283b;border-right:1px solid #23283b;font-size:12.5px}
.oc-table .itm-call{background:rgba(34,197,94,.05)}
.oc-table .itm-put{background:rgba(239,68,68,.05)}
.oc-table tr.tr-atm{background:rgba(234,179,8,.08)!important;border-top:1px solid rgba(234,179,8,.4);
  border-bottom:1px solid rgba(234,179,8,.4)}
.oc-table tr.tr-atm td.td-strike{background:rgba(234,179,8,.2);color:#fef08a;box-shadow:0 0 10px rgba(234,179,8,.3)}
.atm-pill{display:inline-block;padding:1px 4px;background:#eab308;color:#000;border-radius:4px;
  font-size:8.5px;font-weight:800;margin-left:3px;vertical-align:middle}
.cx-extra{margin-top:8px;padding-top:8px;border-top:1px dashed rgba(255,255,255,.10);font-size:11.5px}
.cx-row{display:flex;justify-content:space-between;gap:8px;padding:2px 0}
.cx-l{color:var(--muted)}
.cx-v{color:#cdd3e3;text-align:right}
.cx-sub{color:var(--muted);font-size:10.5px;padding:1px 0 1px 6px;opacity:.85}
.cx-banner{margin:6px 0;padding:5px 8px;border-radius:6px;font-size:11px;font-weight:700}
.cx-warn{background:rgba(234,179,8,.14);color:#fde68a;border:1px solid rgba(234,179,8,.35)}
"""


def _fmt(x, decimals=2):
    if x is None:
        return "—"
    try:
        return f"{float(x):.{decimals}f}"
    except (TypeError, ValueError):
        return str(x)


_usdinr_cache = {"rate": None, "at": 0.0}
USDINR_TTL_SEC = 300


def _get_usdinr_rate() -> float:
    """Cached 5 min -- FX doesn't move fast enough to justify fetching it
    every render, and this is only used to convert a USD trend series to
    an INR-comparable display figure, not to price anything."""
    if _usdinr_cache["rate"] is not None and time.time() - _usdinr_cache["at"] < USDINR_TTL_SEC:
        return _usdinr_cache["rate"]
    try:
        hist = yf.Ticker("USDINR=X").history(period="1d", interval="1m")
        rate = float(hist["Close"].iloc[-1]) if not hist.empty else 88.0
    except Exception:
        rate = _usdinr_cache["rate"] or 88.0
    _usdinr_cache["rate"] = rate
    _usdinr_cache["at"] = time.time()
    return rate


def _range_bar_html(ltp, support, resistance) -> str:
    if ltp is None or support is None or resistance is None or resistance <= support:
        return ""
    pct = max(0.0, min(100.0, (ltp - support) / (resistance - support) * 100))
    return f"""
    <div class="rangebar">
      <div class="fill" style="left:0;width:{pct:.1f}%;opacity:.35"></div>
      <div class="dot" style="left:{pct:.1f}%"></div>
    </div>
    <div class="range-labels"><span>S {_fmt(support)}</span><span>R {_fmt(resistance)}</span></div>"""


def _card_html(card_id: str, sig: dict, live: bool = False) -> str:
    css_cls, icon, label = CALL_META.get(sig.get("option_call"), NO_CALL_META)
    srv_signal = sig.get("srv_signal", "NO_DATA")
    bars_line = ""
    if sig.get("bars_needed") and sig.get("bars_recorded", 0) < sig["bars_needed"]:
        bars_line = f'<div class="warm">Warming up · {sig["bars_recorded"]}/{sig["bars_needed"]} bars recorded</div>'

    live_dot = '<span class="live-dot"></span>' if live else ""
    range_bar = _range_bar_html(sig.get("ltp"), sig.get("srv_support"), sig.get("srv_resistance"))

    # Change (▲/▼ + %) and the pocket sparkline are populated by JS on each
    # 3s poll (see pollFastLtp) -- these are just the empty mount points.
    chg_html = f'<div class="chg" id="chg-{card_id}">&nbsp;</div>' if live else ""
    spark_html = (f'<div class="spark-wrap"><svg viewBox="0 0 100 34" preserveAspectRatio="none" width="100" height="34">'
                  f'<polyline id="spark-{card_id}" fill="none" stroke="#8890a6" stroke-width="2" points=""/></svg></div>'
                  if live else "")

    return f"""
    <div class="card card-3d">
      <div class="card-top">
        <div class="card-title">{sig.get('icon','')} {sig.get('name','')} {live_dot}</div>
      </div>
      <div class="ltp-head">
        <div>
          <div class="ltp" id="ltp-{card_id}">{_fmt(sig.get('ltp'))}</div>
          <div class="ltp-sub">Last traded price</div>
          {chg_html}
        </div>
        {spark_html}
      </div>
      <span class="badge {css_cls}">{icon} {label}</span>
      <div class="reason">{sig.get('srv_reason') or sig.get('reason') or f'Signal: {srv_signal}'}</div>
      {bars_line}
      {range_bar}
      <table class="kv">
        <tr><td>Entry</td><td>{_fmt(sig.get('srv_entry'))}</td></tr>
        <tr><td>Stop</td><td>{_fmt(sig.get('srv_stop'))}</td></tr>
        <tr><td>Target 1</td><td>{_fmt(sig.get('srv_target1'))}</td></tr>
        <tr><td>Target 2</td><td>{_fmt(sig.get('srv_target2'))}</td></tr>
        <tr><td>R:R</td><td>{_fmt(sig.get('srv_rr'))}</td></tr>
        <tr><td>Strength</td><td>{_fmt(sig.get('srv_strength'), 0)}</td></tr>
      </table>
      {_commodity_extra_html(card_id, sig)}
    </div>"""


def _commodity_extra_html(card_id: str, sig: dict) -> str:
    """The crude/natural-gas-only enrichment block: event clock, daily-trend
    alignment, open interest, session weighting, multi-timeframe confluence,
    move decomposition, a position-size suggestion, and the measured
    hit-rate. Renders nothing for non-commodity cards (they carry none of
    these fields)."""
    if card_id not in ("crude", "natgas"):
        return ""
    symbol = {"crude": "CRUDEOIL", "natgas": "NATURALGAS"}[card_id]

    rows = []

    # Event clock / blackout banner.
    if sig.get("srv_event_blackout"):
        phase = sig.get("srv_blackout_phase", "")
        rows.append(f'<div class="cx-banner cx-warn">⚠ Inventory report {phase} — signal held, wait for the number</div>')
    if sig.get("srv_next_event"):
        imp = sig.get("srv_next_event_impact", "")
        dot = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(imp, "•")
        rows.append(f'<div class="cx-row"><span class="cx-l">{dot} Next event</span>'
                    f'<span class="cx-v">{sig["srv_next_event"]} · in {_fmt(sig.get("srv_next_event_in_h"),1)}h</span></div>')

    # Confidence: base vs adjusted, with the reasoning trail.
    if sig.get("srv_base_strength") is not None and sig.get("srv_signal") in ("BUY", "SELL"):
        base_s = sig.get("srv_base_strength")
        adj_s = sig.get("srv_strength")
        arrow = "→"
        rows.append(f'<div class="cx-row"><span class="cx-l">Confidence</span>'
                    f'<span class="cx-v">{_fmt(base_s,0)} {arrow} <b>{_fmt(adj_s,0)}</b></span></div>')
        for f in (sig.get("srv_confidence_factors") or []):
            rows.append(f'<div class="cx-sub">· {f}</div>')

    # Signal source (which series fired it) + two-series agreement.
    if sig.get("srv_source"):
        agree = ' · both series agree' if sig.get("srv_series_agree") else ''
        rows.append(f'<div class="cx-row"><span class="cx-l">Source</span>'
                    f'<span class="cx-v">{sig["srv_source"]}{agree}</span></div>')

    # Daily-trend alignment.
    if sig.get("srv_daily_trend"):
        al = sig.get("srv_trend_aligned")
        tag = ("<span style='color:var(--green)'>aligned</span>" if al is True
               else "<span style='color:var(--red)'>counter-trend</span>" if al is False
               else "neutral")
        rows.append(f'<div class="cx-row"><span class="cx-l">Daily trend</span>'
                    f'<span class="cx-v">{sig["srv_daily_trend"]} · {tag}</span></div>')

    # Multi-timeframe confluence.
    if sig.get("srv_confluence"):
        rows.append(f'<div class="cx-row"><span class="cx-l">HTF confluence</span>'
                    f'<span class="cx-v">daily level near {_fmt(sig["srv_confluence"])}</span></div>')

    # Open interest.
    if sig.get("srv_oi_read"):
        rows.append(f'<div class="cx-row"><span class="cx-l">Open interest</span>'
                    f'<span class="cx-v">{sig["srv_oi_read"]}'
                    f'{" · " + _fmt(sig.get("srv_oi_pct"),1) + "%" if sig.get("srv_oi_pct") is not None else ""}</span></div>')

    # Move decomposition.
    if sig.get("srv_move_commodity_pct") is not None:
        rows.append(f'<div class="cx-row"><span class="cx-l">Move breakdown</span>'
                    f'<span class="cx-v">commodity {_fmt(sig.get("srv_move_commodity_pct"),2)}% · '
                    f'₹ {_fmt(sig.get("srv_move_fx_pct"),2)}%</span></div>')

    # Session.
    if sig.get("srv_session"):
        rows.append(f'<div class="cx-row"><span class="cx-l">Session</span>'
                    f'<span class="cx-v">{sig["srv_session"]}</span></div>')

    # Position sizing suggestion.
    ps = sig.get("srv_position")
    if ps and ps.get("suggested"):
        rows.append(f'<div class="cx-row"><span class="cx-l">Size (₹{_fmt(ps.get("risk_budget_inr"),0)} risk)</span>'
                    f'<span class="cx-v"><b>{ps["suggested"]}</b> · risks ₹{_fmt(ps.get("suggested_risk"),0)}</span></div>')
    elif ps and ps.get("note"):
        rows.append(f'<div class="cx-sub">Size: {ps["note"]}</div>')

    # Measured hit-rate for this instrument.
    try:
        st = signal_journal.stats(symbol)
        if st.get("resolved"):
            wr = st.get("win_rate")
            exp = st.get("expectancy_r")
            rows.append(f'<div class="cx-row"><span class="cx-l">Track record</span>'
                        f'<span class="cx-v">{_fmt(wr,0)}% of {st["resolved"]} · exp {_fmt(exp,2)}R · {st.get("open",0)} open</span></div>')
        elif st.get("open"):
            rows.append(f'<div class="cx-sub">Track record: {st["open"]} open, none resolved yet</div>')
    except Exception:
        pass

    if not rows:
        return ""
    return f'<div class="cx-extra">{"".join(rows)}</div>'


def _trend_card_html(item: dict, t: dict, mcx_live_ltp: float | None = None) -> str:
    if not t.get("available"):
        return f"""<div class="trend-card card-3d"><div class="trend-top"><h3>{item['icon']} {item['name']}</h3></div>
          <p class="empty">{t.get('reason', 'Not available yet.')}</p></div>"""

    # trend_engine runs entirely in the NYMEX proxy's native USD -- RSI and
    # the above/below-MA comparisons are scale-invariant, so converting only
    # the *displayed* numbers to INR here doesn't touch the classification
    # itself. mcx_live_ltp (the real, tradeable MCX price) is shown alongside
    # so a big gap between "derived from yesterday's NY close" and "what MCX
    # is actually quoting right now" is visible at a glance, not hidden.
    is_commodity = item["kind"] == "commodity"
    rate = _get_usdinr_rate() if is_commodity else 1.0

    def conv(val):
        return None if val is None else val * rate

    ltp = conv(t.get("ltp"))
    ema20, ma50, ma200, week_high_52 = (conv(t.get(k)) for k in ("ema20", "ma50", "ma200", "week_high_52"))

    def level_row(label, val):
        if val is None:
            return f'<div class="trend-level-row"><span class="l">{label}</span><span class="v">—</span></div>'
        cls = "above" if (ltp is not None and ltp >= val) else "below"
        return f'<div class="trend-level-row"><span class="l">{label}</span><span class="v {cls}">{_fmt(val)}</span></div>'

    dist_52h = (f"{(ltp - week_high_52) / week_high_52 * 100:.1f}%"
                if ltp and week_high_52 else "—")

    mcx_compare = (f'<div class="mcx-compare"><span class="lab">MCX live</span>{_fmt(mcx_live_ltp)}</div>'
                   if is_commodity and mcx_live_ltp is not None else "")
    currency_note = ('<div class="ltp-sub" style="margin-top:2px">Derived price, INR-equivalent from the daily '
                      'USD series</div>' if is_commodity else "")

    return f"""
    <div class="trend-card card-3d">
      <div class="trend-top">
        <h3>{item['icon']} {item['name']}</h3>
        <span class="badge {t['class']}">{t['badge']}</span>
      </div>
      <div class="ltp" style="font-size:26px;margin:4px 0">{_fmt(ltp)}</div>
      {currency_note}
      {mcx_compare}
      <div class="trend-levels">
        {level_row('EMA 20', ema20)}
        {level_row('MA 50', ma50)}
        {level_row('MA 200', ma200)}
        <div class="trend-level-row"><span class="l">RSI (14)</span><span class="v">{_fmt(t.get('rsi'), 1)}</span></div>
        <div class="trend-level-row"><span class="l">Volume vs 10d avg</span><span class="v">{_fmt(t.get('volume_spike'))}x</span></div>
        <div class="trend-level-row"><span class="l">52w High</span><span class="v">{_fmt(week_high_52)} ({dist_52h})</span></div>
      </div>
    </div>"""


def _trend_section_html() -> str:
    with _trend_lock:
        trends = dict(_trend_state["trends"])
        updated_at = _trend_state["updated_at"]
        error = _trend_state["error"]
    with _state_lock:
        live_signals = dict(_state["signals"])

    status = f"Updated {updated_at.strftime('%H:%M:%S')} UTC" if updated_at else "Not run yet"
    if error:
        status += f" · last error: {error}"

    if not trends:
        return f'<p class="desc">{status}</p>'

    cards = "".join(
        _trend_card_html(item, trends[item["id"]], mcx_live_ltp=live_signals.get(item["id"], {}).get("ltp"))
        for item in TREND_ITEMS if item["id"] in trends
    )
    return f'<p class="desc">{status} &middot; daily timeframe, rechecked every {TREND_REFRESH_SECONDS // 60} min</p><div class="card-grid">{cards}</div>'


def _equity_row_html(r: dict, kind: str) -> str:
    color = {"buy": "var(--green)", "sell": "var(--red)", "watch_buy": "var(--lime)", "watch_sell": "var(--orange)"}[kind]
    extra = (f"str {_fmt(r.get('srv_strength'), 0)}" if kind in ("buy", "sell")
             else f"dist {_fmt(r.get('dist_to_level'))}")
    return f"""<tr>
      <td class="sym" style="color:{color}">{r['symbol']}</td>
      <td>{_fmt(r.get('ltp'))}</td>
      <td style="color:var(--muted)">{extra}</td>
      <td class="reason-cell">{r.get('srv_reason','')}</td>
    </tr>"""


def _equity_table(rows, kind, empty_msg) -> str:
    if not rows:
        return f'<div class="table-wrap"><div class="empty">{empty_msg}</div></div>'
    body = "".join(_equity_row_html(r, kind) for r in rows)
    return f"""<div class="table-wrap"><table class="list">
      <thead><tr><th>Symbol</th><th>LTP</th><th></th><th>Reason</th></tr></thead>
      <tbody>{body}</tbody></table></div>"""


def _momentum_card_html(pick: dict, kind: str) -> str:
    score = pick.get("intraday_score", 0)
    chg = pick.get("day_chg_pct")
    chg_txt = f"{'+' if chg and chg >= 0 else ''}{_fmt(chg)}%" if chg is not None else "—"
    symbol = pick["symbol"]
    return f"""
    <div class="mom-card {kind}">
      <div class="mom-top">
        <span class="mom-sym">{symbol}</span>
        <span class="mom-score {kind}">{_fmt(score, 0)}</span>
      </div>
      <div class="mom-live-row">
        <span class="mom-live-price" id="mom-ltp-{symbol}">{_fmt(pick.get('ltp'))}</span>
        <span class="mom-live-chg" id="mom-chg-{symbol}">&nbsp;</span>
      </div>
      <div class="mom-chg {kind}">{chg_txt} at scan &middot; RSI {_fmt(pick.get('rsi'), 0)} &middot; vol {_fmt(pick.get('volume_spike'))}x</div>
      <div class="mom-levels">
        <div>Entry <b>{_fmt(pick.get('ltp'))}</b></div>
        <div>Stop <b>{_fmt(pick.get('stop_loss'))}</b></div>
        <div>Target 1 <b>{_fmt(pick.get('target1'))}</b></div>
        <div>Target 2 <b>{_fmt(pick.get('target2'))}</b></div>
      </div>
      <div class="mom-reason">{pick.get('rationale', '')}</div>
    </div>"""


def _momentum_section_html() -> str:
    with _momentum_lock:
        result = _momentum_state["result"]
        updated_at = _momentum_state["updated_at"]
        error = _momentum_state["error"]
        running = _momentum_state["running"]

    status_bits = []
    status_bits.append(f"Updated {updated_at.strftime('%H:%M:%S')} UTC" if updated_at else "Not run yet")
    if running:
        status_bits.append("scan in progress…")
    if error:
        status_bits.append(f"last error: {error}")

    if not result:
        return f'<p class="desc">{" · ".join(status_bits)}</p>'

    status_bits.append(f"{result['scanned']} liquid, circuit-safe stocks scanned "
                        f"({result.get('stale_ltp_count', 0)} stale)")
    stats = [
        ("BUY QUALIFIED", result["buy_qualified"], "var(--green)"),
        ("SELL QUALIFIED", result["sell_qualified"], "var(--red)"),
        ("BUY SHOWN", len(result["buy"]), "var(--muted)"),
        ("SELL SHOWN", len(result["sell"]), "var(--muted)"),
    ]
    stat_html = "".join(
        f'<div class="stat-tile"><div class="n" style="color:{c}">{n}</div><div class="l">{label}</div></div>'
        for label, n, c in stats
    )

    def cards(picks, kind, empty_msg):
        if not picks:
            return f'<div class="table-wrap"><div class="empty">{empty_msg}</div></div>'
        return f'<div class="mom-grid">{"".join(_momentum_card_html(p, kind) for p in picks)}</div>'

    return f"""
    <p class="desc">{" · ".join(status_bits)}</p>
    <div class="stat-strip">{stat_html}</div>
    <div class="mom-subhead" style="color:var(--green)">BUY — top {len(result['buy'])}</div>
    {cards(result['buy'], 'buy', 'No BUY candidates qualified right now.')}
    <div class="mom-subhead" style="color:var(--red)">SELL — top {len(result['sell'])}</div>
    {cards(result['sell'], 'sell', 'No SELL candidates qualified right now.')}"""


def _equity_section_html() -> str:
    with _equity_lock:
        result = _equity_state["result"]
        updated_at = _equity_state["updated_at"]
        error = _equity_state["error"]
        running = _equity_state["running"]

    status_bits = []
    if updated_at:
        status_bits.append(f"Updated {updated_at.strftime('%H:%M:%S')} UTC")
    else:
        status_bits.append("Not run yet")
    if running:
        status_bits.append("scan in progress…")
    if error:
        status_bits.append(f"last error: {error}")

    if not result:
        return f'<p class="desc">{" · ".join(status_bits)}</p>'

    status_bits.append(f"{result['scanned']} liquid, circuit-safe stocks scanned")
    stats = [
        ("BUY", result["buy_qualified"], "var(--green)"),
        ("SELL", result["sell_qualified"], "var(--red)"),
        ("WATCH BUY", result["watch_buy_qualified"], "var(--lime)"),
        ("WATCH SELL", result["watch_sell_qualified"], "var(--orange)"),
    ]
    stat_html = "".join(
        f'<div class="stat-tile"><div class="n" style="color:{c}">{n}</div><div class="l">{label}</div></div>'
        for label, n, c in stats
    )

    def dot(color):
        return f'<span class="dotlabel" style="background:{color}"></span>'

    return f"""
    <p class="desc">{" · ".join(status_bits)}</p>
    <div class="stat-strip">{stat_html}</div>
    <div class="two-col">
      <div><div class="subhead">{dot('var(--green)')}BUY — confirmed</div>
        {_equity_table(result['buy'], 'buy', 'No confirmed BUY setups right now.')}</div>
      <div><div class="subhead">{dot('var(--red)')}SELL — confirmed</div>
        {_equity_table(result['sell'], 'sell', 'No confirmed SELL setups right now.')}</div>
      <div><div class="subhead">{dot('var(--lime)')}WATCH — near support</div>
        {_equity_table(result['watch_buy'], 'watch_buy', 'Nothing sitting near a support level right now.')}</div>
      <div><div class="subhead">{dot('var(--orange)')}WATCH — near resistance</div>
        {_equity_table(result['watch_sell'], 'watch_sell', 'Nothing sitting near a resistance level right now.')}</div>
    </div>"""


def _nav_bar(active: str) -> str:
    def link(path, label, key):
        cls = "active" if key == active else ""
        return f'<a href="{path}" class="{cls}">{label}</a>'
    return f"""<div class="top-nav">
      <span class="brand">INDMONEY TERMINAL</span>
      {link("/", "📊 Dashboard", "dashboard")}
      {link("/options", "⚡ Options", "options")}
      {link("/scan", "⚡ Intraday Scan", "scan")}
      {link("/swing", "🎯 Swing Screen", "swing")}
      {link("/lt", "💎 Long Term", "lt")}
      {link("/penny", "🪙 Penny Screen", "penny")}
      {link("/settings", "⚙️ Settings", "settings")}
    </div>"""


@app.route("/")
def dashboard():
    with _state_lock:
        signals = dict(_state["signals"])
        updated_at = _state["updated_at"]
        error = _state["error"]

    if not signals:
        cards_html = '<p class="desc">Still computing the first signal &mdash; refresh in a few seconds.</p>'
    else:
        order = ["crude", "natgas", "nifty", "banknifty"]
        live_ids = {"crude", "natgas", "nifty", "banknifty"}
        cards = "".join(_card_html(k, signals[k], live=k in live_ids) for k in order if k in signals)
        cards_html = f'<div class="card-grid">{cards}</div>'

    error_html = f'<div class="err-banner">Last refresh failed: {error}</div>' if error else ""
    updated_pill = (f'<span class="meta-pill"><span class="pulse"></span>Live · '
                     f'refreshes every {REFRESH_SECONDS}s</span>'
                     if updated_at else "")
    fast_pill = f'<span class="meta-pill">Live 3s streaming &middot; NIFTY / BANK NIFTY</span>'

    tok_status = token_manager.get_token_status()
    if not tok_status["has_token"] or tok_status["is_expired"]:
        token_pill = '<a href="/settings" class="meta-pill meta-pill-link meta-pill-bad">⚠ Token expired &mdash; update it</a>'
    else:
        mins = tok_status["expires_in_min"]
        if mins is not None and mins < 60:
            token_pill = f'<a href="/settings" class="meta-pill meta-pill-link meta-pill-warn">Token expires in {int(mins)} min &mdash; update soon</a>'
        else:
            token_pill = '<a href="/settings" class="meta-pill meta-pill-link">Token settings</a>'

    return f"""<!DOCTYPE html>
<html><head>
  <meta charset="utf-8"><meta http-equiv="refresh" content="120">
  <title>INDmoney / MCX Pair Trading Signal</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>{STYLE}</style>
</head>
<body>
  {_nav_bar("dashboard")}
  <div class="header">
    <h1>Pair Trading &mdash; CE/PE Signal</h1>
    <p>Crude Oil / Natural Gas: real MCX futures prices. NIFTY / BANK NIFTY: front-month NFO futures
      via INDmoney. Same volume-backed support/resistance model on both. Direction only &mdash;
      check your broker terminal for the actual strike/premium before acting.</p>
    <div class="meta-row">{updated_pill}{fast_pill}{token_pill}</div>
  </div>

  {error_html}

  <div class="section">
    <div class="section-head"><span class="section-bar"></span><h2>Live Signals</h2></div>
    {cards_html}
  </div>

  <div class="section">
    <div class="section-head"><span class="section-bar"></span><h2>Trend Analyzer</h2></div>
    <p class="desc">Daily-timeframe structure (EMA20/MA50/MA200/RSI/52-week high), using the same
      trend classification your live screener uses for stocks. NIFTY/BANK NIFTY run on the spot
      index (not futures, to avoid monthly-rollover discontinuities in the moving averages);
      crude/natgas run on the NYMEX proxy series.</p>
    {_trend_section_html()}
  </div>

  <div class="section">
    <div class="section-head"><span class="section-bar"></span><h2>Market Depth</h2></div>
    <p class="desc">Live 5-level order book, NIFTY &amp; BANK NIFTY front-month futures. Updates every
      {FAST_POLL_SECONDS}s alongside the price above. MCX has no free depth feed (its market-watch API
      returns zero for every bid/ask field), so crude/natgas aren't shown here.</p>
    <div class="depth-grid" id="depth-grid">
      <div class="depth-card card-3d"><p class="empty">Waiting for first depth snapshot&hellip;</p></div>
      <div class="depth-card card-3d"><p class="empty">Waiting for first depth snapshot&hellip;</p></div>
    </div>
  </div>

  <script>
  const DEPTH_NAMES = {{nifty: 'NIFTY 50', banknifty: 'BANK NIFTY'}};

  function depthRowHtml(bid, ask, maxQty) {{
    const bidPct = bid && maxQty ? Math.min(100, (bid.buy_qty / maxQty) * 100) : 0;
    const askPct = ask && maxQty ? Math.min(100, (ask.sell_qty / maxQty) * 100) : 0;
    return `<div class="depth-row">
      <div class="depth-cell bid"><span class="bar" style="width:${{bidPct}}%"></span>
        <span>${{bid ? bid.buy_qty.toFixed(0) : '—'}}</span><span>${{bid ? bid.buy_price.toFixed(2) : '—'}}</span></div>
      <div class="depth-cell ask"><span class="bar" style="width:${{askPct}}%"></span>
        <span>${{ask ? ask.sell_price.toFixed(2) : '—'}}</span><span>${{ask ? ask.sell_qty.toFixed(0) : '—'}}</span></div>
    </div>`;
  }}

  function renderDepthCard(key, depth) {{
    if (!depth || !depth.levels || !depth.levels.length) {{
      return `<div class="depth-card card-3d"><div class="depth-top"><h3>${{DEPTH_NAMES[key] || key}}</h3></div>
        <p class="empty">No depth data yet.</p></div>`;
    }}
    const maxQty = Math.max(...depth.levels.map(l => Math.max(l.buy_qty || 0, l.sell_qty || 0)));
    const rows = depth.levels.map(l => depthRowHtml(l, l, maxQty)).join('');
    const buyPct = depth.buy_pct != null ? depth.buy_pct : 50;
    return `<div class="depth-card card-3d">
      <div class="depth-top"><h3>${{DEPTH_NAMES[key] || key}}</h3>
        <span class="depth-mid">spread ${{depth.spread != null ? depth.spread.toFixed(2) : '—'}}</span></div>
      <div class="split-bar"><div class="buy" style="width:${{buyPct}}%"></div></div>
      <div class="split-labels"><span>Buy ${{buyPct.toFixed(1)}}%</span><span>Sell ${{(100-buyPct).toFixed(1)}}%</span></div>
      <div class="bidask">
        <div><div class="side" style="color:var(--green)">${{depth.best_bid != null ? depth.best_bid.toFixed(2) : '—'}}</div><div class="lab">Best Bid</div></div>
        <div style="text-align:right"><div class="side" style="color:var(--red)">${{depth.best_ask != null ? depth.best_ask.toFixed(2) : '—'}}</div><div class="lab">Best Ask</div></div>
      </div>
      <div class="depth-rows">${{rows}}</div>
    </div>`;
  }}

  function updateChange(keyLower, change) {{
    const el = document.getElementById('chg-' + keyLower);
    if (!el) return;
    if (!change || change.change == null || change.change_pct == null) {{ el.innerHTML = '&nbsp;'; return; }}
    const up = change.change >= 0;
    el.className = 'chg ' + (up ? 'up' : 'down');
    const sign = up ? '+' : '';
    el.innerHTML = `${{sign}}${{change.change.toFixed(2)}} `
      + `(<span class="arrow">${{up ? '▲' : '▼'}}</span>${{Math.abs(change.change_pct).toFixed(2)}}%)`;
  }}

  function updateSpark(keyLower, values) {{
    const line = document.getElementById('spark-' + keyLower);
    if (!line || !values || values.length < 2) return;
    const min = Math.min(...values), max = Math.max(...values);
    const range = (max - min) || (min * 0.001) || 1;
    const w = 100, h = 34, pad = 3;
    const pts = values.map((v, i) => {{
      const x = (i / (values.length - 1)) * w;
      const y = h - pad - ((v - min) / range) * (h - pad * 2);
      return `${{x.toFixed(1)}},${{y.toFixed(1)}}`;
    }}).join(' ');
    line.setAttribute('points', pts);
    line.setAttribute('stroke', values[values.length - 1] >= values[0] ? '#22c55e' : '#ef4444');
  }}

  async function pollFastLtp() {{
    try {{
      const r = await fetch('/api/fast_ltp');
      const d = await r.json();
      for (const [key, val] of Object.entries(d.ltp || {{}})) {{
        const el = document.getElementById('ltp-' + key.toLowerCase());
        if (el && val != null) el.textContent = Number(val).toFixed(2);
      }}
      for (const [key, change] of Object.entries(d.change || {{}})) {{
        updateChange(key.toLowerCase(), change);
      }}
      for (const [key, values] of Object.entries(d.spark || {{}})) {{
        updateSpark(key.toLowerCase(), values);
      }}
      const grid = document.getElementById('depth-grid');
      if (grid && d.depth) {{
        grid.innerHTML = Object.entries(d.depth).map(([k, v]) => renderDepthCard(k.toLowerCase(), v)).join('');
      }}
    }} catch (e) {{ /* transient poll failure, try again next tick */ }}
  }}
  setInterval(pollFastLtp, {FAST_POLL_SECONDS * 1000});
  pollFastLtp();

  // Real 3D tilt: rotates the card toward the cursor (perspective + rotateX/
  // rotateY) and moves a glare highlight to match, like a physical card
  // catching light. Event delegation on document (not per-card listeners)
  // so it keeps working on the depth cards even though those get fully
  // replaced via innerHTML every {FAST_POLL_SECONDS}s.
  (function() {{
    let activeCard = null;
    const MAX_TILT = 10;

    function applyTilt(card, clientX, clientY) {{
      const rect = card.getBoundingClientRect();
      const px = (clientX - rect.left) / rect.width;
      const py = (clientY - rect.top) / rect.height;
      const rotateY = (px - 0.5) * MAX_TILT * 2;
      const rotateX = (0.5 - py) * MAX_TILT * 2;
      card.classList.add('tilting');
      card.style.transform = `perspective(900px) rotateX(${{rotateX.toFixed(2)}}deg) `
        + `rotateY(${{rotateY.toFixed(2)}}deg) translateY(-6px) translateZ(10px) scale(1.02)`;
      card.style.setProperty('--glare-x', (px * 100).toFixed(1) + '%');
      card.style.setProperty('--glare-y', (py * 100).toFixed(1) + '%');
      const shadowX = (-rotateY * 1.4).toFixed(1);
      const shadowY = (Math.abs(rotateX) * 1.2 + 14).toFixed(1);
      card.style.boxShadow = `${{shadowX}}px ${{shadowY}}px 26px -8px rgba(0,0,0,.55), `
        + `0 34px 64px -26px rgba(0,0,0,.6), inset 0 1px 0 rgba(255,255,255,.08)`;
    }}

    function resetTilt(card) {{
      card.classList.remove('tilting');
      card.style.transform = '';
      card.style.boxShadow = '';
    }}

    document.addEventListener('mousemove', (e) => {{
      const card = e.target.closest('.card-3d');
      if (card !== activeCard) {{
        if (activeCard) resetTilt(activeCard);
        activeCard = card;
      }}
      if (card) applyTilt(card, e.clientX, e.clientY);
    }});
    document.addEventListener('mouseleave', () => {{
      if (activeCard) {{ resetTilt(activeCard); activeCard = null; }}
    }});
  }})();
  </script>
</body></html>"""


@app.route("/options")
def options_page():
    underlying = request.args.get("underlying", "RELIANCE").upper().strip()
    expiry = request.args.get("expiry")
    chain_data = indmoney_feed.get_option_chain(underlying, expiry=expiry) or {}
    expiries = indmoney_feed.get_option_expiries(underlying)

    with _state_lock:
        sig_dict = _state["signals"].get(underlying.lower())
    with _trend_lock:
        trend_dict = _trend_state["trends"].get(underlying.lower())

    return options_views.render_options_page(
        underlying=underlying,
        chain_data=chain_data,
        expiries=expiries,
        signal_dict=sig_dict,
        trend_dict=trend_dict,
        nav_bar_fn=_nav_bar,
        base_style=STYLE,
    )


@app.route("/scan")
def scan_page():
    return f"""<!DOCTYPE html>
<html><head>
  <meta charset="utf-8"><meta http-equiv="refresh" content="120">
  <title>Intraday Scan &mdash; Nifty Universe</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>{STYLE}</style>
</head>
<body>
  {_nav_bar("scan")}
  <div class="header">
    <h1>Nifty-Universe Intraday Scan</h1>
    <p>Every liquid, circuit-safe stock in the screener's scan universe
      (MTF/large-cap/mid-cap, &ge;₹5Cr traded value), two ways.</p>
  </div>

  <div class="section">
    <div class="tab-bar">
      <button class="tab-btn active" onclick="showScanTab('momentum', this)">Momentum (live INDmoney)</button>
      <button class="tab-btn" onclick="showScanTab('srlevel', this)">S/R Levels</button>
    </div>
    <div id="tab-momentum" class="tab-panel">
      <p class="desc">The screener's own intraday scoring (day-move + volume + RSI + momentum + relative
        strength), run against live INDmoney price/volume instead of the screener's own yfinance-polled
        snapshot, which goes stale between refreshes. Rescans every {MOMENTUM_SCAN_INTERVAL_SECONDS // 60} min.</p>
      {_momentum_section_html()}
    </div>
    <div id="tab-srlevel" class="tab-panel" hidden>
      <p class="desc">Volume-backed support/resistance model (same as the commodity/index cards on the
        Dashboard tab) &mdash; fires only on a confirmed turn at a defended level, so it's sparser but
        higher-conviction. Rescans every {EQUITY_SCAN_INTERVAL_SECONDS // 60} min.</p>
      {_equity_section_html()}
    </div>
  </div>

  <script>
  function showScanTab(name, btn) {{
    document.querySelectorAll('.tab-panel').forEach(p => p.hidden = (p.id !== 'tab-' + name));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  }}

  // 3s live price/change on the momentum cards' current top-20 -- separate
  // from the 3-min full rescan, which owns score/entry/stop/target.
  async function pollMomentumLtp() {{
    try {{
      const r = await fetch('/api/momentum_fast_ltp');
      const d = await r.json();
      for (const [symbol, q] of Object.entries(d.quotes || {{}})) {{
        const priceEl = document.getElementById('mom-ltp-' + symbol);
        if (priceEl && q.ltp != null) priceEl.textContent = Number(q.ltp).toFixed(2);
        const chgEl = document.getElementById('mom-chg-' + symbol);
        if (chgEl && q.change != null && q.change_pct != null) {{
          const up = q.change >= 0;
          chgEl.className = 'mom-live-chg ' + (up ? 'up' : 'down');
          const sign = up ? '+' : '';
          chgEl.innerHTML = `${{sign}}${{q.change.toFixed(2)}} (<span>${{up ? '▲' : '▼'}}</span>${{Math.abs(q.change_pct).toFixed(2)}}%)`;
        }}
      }}
    }} catch (e) {{ /* transient poll failure, try again next tick */ }}
  }}
  setInterval(pollMomentumLtp, {MOMENTUM_FAST_POLL_SECONDS * 1000});
  pollMomentumLtp();
  </script>
</body></html>"""


@app.route("/swing")
def swing_page():
    with _swing_lock:
        state = dict(_swing_state)
    if state.get("result") is None and not state.get("running"):
        try:
            res = swing_engine.scan_swing_candidates(top_n=30)
            with _swing_lock:
                _swing_state["result"] = res
                _swing_state["updated_at"] = datetime.now(timezone.utc)
                state = dict(_swing_state)
        except Exception as e:
            traceback.print_exc()
    return screener_views.render_swing_page(state, _nav_bar, STYLE)


@app.route("/lt")
def lt_page():
    with _lt_lock:
        state = dict(_lt_state)
    if state.get("result") is None and not state.get("running"):
        try:
            res = lt_engine.scan_lt_discovery(top_n=30)
            with _lt_lock:
                _lt_state["result"] = res
                _lt_state["updated_at"] = datetime.now(timezone.utc)
                state = dict(_lt_state)
        except Exception as e:
            traceback.print_exc()
    return screener_views.render_lt_page(state, _nav_bar, STYLE)


@app.route("/penny")
def penny_page():
    with _penny_lock:
        state = dict(_penny_state)
    if state.get("result") is None:
        if os.path.exists(penny_engine.PENNY_MONTHLY_PICKS_FILE):
            try:
                with open(penny_engine.PENNY_MONTHLY_PICKS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                state["result"] = {
                    "monthly_cohort": saved,
                    "picks": saved.get("picks", []),
                    "monthly_sip_budget": saved.get("monthly_sip_budget", 200.0),
                }
            except Exception:
                pass
    if state.get("result") is None and not state.get("running"):
        try:
            res = penny_engine.scan_penny_picks(top_n=30, monthly_sip=200.0)
            with _penny_lock:
                _penny_state["result"] = res
                _penny_state["updated_at"] = datetime.now(timezone.utc)
                state = dict(_penny_state)
        except Exception as e:
            traceback.print_exc()
    return screener_views.render_penny_page(state, _nav_bar, STYLE)


@app.route("/api/swing")
def api_swing():
    with _swing_lock:
        return jsonify(_swing_state)


@app.route("/api/lt")
def api_lt():
    with _lt_lock:
        return jsonify(_lt_state)


@app.route("/api/penny")
def api_penny():
    with _penny_lock:
        return jsonify(_penny_state)


_background_started = False
_background_lock = threading.Lock()


def start_all_background_threads():
    global _background_started
    with _background_lock:
        if _background_started:
            return
        _background_started = True
        threading.Thread(target=_mcx_bar_recorder_loop, daemon=True).start()
        threading.Thread(target=_signal_refresh_loop, daemon=True).start()
        threading.Thread(target=_fast_ltp_loop, daemon=True).start()
        threading.Thread(target=_equity_scan_loop, daemon=True).start()
        threading.Thread(target=_momentum_scan_loop, daemon=True).start()
        threading.Thread(target=_momentum_fast_poll_loop, daemon=True).start()
        threading.Thread(target=_trend_refresh_loop, daemon=True).start()
        threading.Thread(target=_swing_scan_loop, daemon=True).start()
        threading.Thread(target=_lt_scan_loop, daemon=True).start()
        threading.Thread(target=_penny_scan_loop, daemon=True).start()
        threading.Thread(target=_fundamentals_warm_loop, daemon=True).start()
        threading.Thread(target=_options_scan_loop, daemon=True).start()
        threading.Thread(target=_options_heatmap_loop, daemon=True).start()
        totp_auth.start_totp_refresher_thread()


# Auto-start loops on import (for Gunicorn / Render)
start_all_background_threads()

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    print(f"🚀 Server running on http://{host}:5850 (accessible on LAN / Tailscale)")
    app.run(host=host, port=5850, debug=False, threaded=True)
