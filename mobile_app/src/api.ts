import { getApiBaseUrl, getApiKey } from "./config";

export interface SignalData {
  srv_signal?: string;
  srv_entry?: number;
  srv_stop?: number;
  srv_target1?: number;
  srv_target2?: number;
  srv_strength?: string;
  srv_rr?: number;
  srv_reason?: string;
  srv_setup?: string;
  live_ltp?: number;
  change?: number;
  r1?: number;
  r2?: number;
  s1?: number;
  s2?: number;
  pivot?: number;
  high?: number;
  low?: number;
  volume?: number;
  [key: string]: any;
}

export interface MarketsResponse {
  success: boolean;
  signals: Record<string, SignalData>;
  signals_updated_at: string | null;
  fast_ltp: Record<string, number>;
  fast_change: Record<string, number>;
  fast_depth: Record<string, any>;
  spark: Record<string, number[]>;
  trends: Record<string, any>;
  token_status: {
    has_token: boolean;
    is_expired: boolean;
    expires_in_min?: number;
    data_source?: string;
    fallback_active?: boolean;
    totp_configured?: boolean;
  };
}

export interface CommoditiesResponse {
  success: boolean;
  crude: {
    signal: SignalData;
    ltp?: number;
    change?: number;
    spark: number[];
    bars: any[];
  };
  natgas: {
    signal: SignalData;
    ltp?: number;
    change?: number;
    spark: number[];
    bars: any[];
  };
}

export interface AlertRecord {
  symbol: string;
  direction: "BUY" | "SELL";
  setup?: string;
  entry: number;
  stop: number;
  target1: number;
  target2?: number;
  strength?: string;
  rr?: number;
  opened_at: string;
  outcome: "open" | "target" | "stop";
  closed_at?: string | null;
}

export interface AlertsResponse {
  success: boolean;
  recent: AlertRecord[];
  stats: {
    overall: {
      resolved: number;
      open: number;
      wins: number;
      losses: number;
      win_rate: number | null;
      expectancy_r: number | null;
    };
    crude: any;
    natgas: any;
    by_setup: Record<string, { wins: number; losses: number; win_rate: number | null }>;
  };
}

// Low-level fetch wrapper
async function request<T>(path: string, timeoutMs: number = 4000): Promise<T> {
  const url = `${getApiBaseUrl()}${path}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const key = getApiKey();
  if (key) {
    headers["X-Finplus-Key"] = key;
  }
  try {
    const res = await fetch(url, { signal: ctrl.signal, headers });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// Direct Yahoo Finance Fetcher for Autonomous / Away Mode
async function fetchDirectYahooChart(ticker: string): Promise<{
  symbol: string;
  ltp: number;
  change: number;
  high: number;
  low: number;
  prevClose: number;
  spark: number[];
} | null> {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5000);
    const enc = encodeURIComponent(ticker);
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${enc}?interval=15m&range=2d`;
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(timer);
    if (!res.ok) return null;
    const json = await res.json();
    const result = json?.chart?.result?.[0];
    if (!result) return null;
    const meta = result.meta;
    const ltp = meta.regularMarketPrice || meta.chartPreviousClose || 0;
    const prevClose = meta.chartPreviousClose || meta.previousClose || ltp;
    const change = prevClose > 0 ? ((ltp - prevClose) / prevClose) * 100 : 0;
    const quotes = result.indicators?.quote?.[0];
    const closes: number[] = (quotes?.close || []).filter((v: any) => typeof v === "number" && !isNaN(v));
    const highs: number[] = (quotes?.high || []).filter((v: any) => typeof v === "number" && !isNaN(v));
    const lows: number[] = (quotes?.low || []).filter((v: any) => typeof v === "number" && !isNaN(v));

    const high = highs.length ? Math.max(...highs) : (meta.regularMarketDayHigh || ltp);
    const low = lows.length ? Math.min(...lows) : (meta.regularMarketDayLow || ltp);
    const spark = closes.slice(-15);

    return {
      symbol: ticker,
      ltp,
      change,
      high,
      low,
      prevClose,
      spark: spark.length ? spark : [ltp],
    };
  } catch (_) {
    return null;
  }
}

// MCX Cloud Direct Fetcher
async function fetchDirectRenderMCX(): Promise<any | null> {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 4000);
    const res = await fetch("https://finplus-g0b5.onrender.com/api/mcx", { signal: ctrl.signal });
    clearTimeout(timer);
    if (!res.ok) return null;
    return await res.json();
  } catch (_) {
    return null;
  }
}

function computePivotSignal(
  ltp: number,
  high: number,
  low: number,
  prevClose: number,
  name: string
): SignalData {
  const p = (high + low + prevClose) / 3;
  const r1 = 2 * p - low;
  const s1 = 2 * p - high;
  const r2 = p + (high - low);
  const s2 = p - (high - low);

  const isBullish = ltp >= p;
  const signal = isBullish ? "BUY" : "SELL";
  const setup = isBullish ? "Pivot Support Bounce" : "Pivot Resistance Rejection";
  const entry = Number(ltp.toFixed(1));
  const stop = isBullish ? Number((s1 * 0.996).toFixed(1)) : Number((r1 * 1.004).toFixed(1));
  const target1 = isBullish ? Number(r1.toFixed(1)) : Number(s1.toFixed(1));
  const target2 = isBullish ? Number(r2.toFixed(1)) : Number(s2.toFixed(1));
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(target1 - entry);
  const rr = risk > 0 ? Number((reward / risk).toFixed(1)) : 1.8;

  const reason = isBullish
    ? `${name} trading above daily pivot ₹${p.toFixed(1)}. Positive momentum toward R1 ₹${r1.toFixed(1)}.`
    : `${name} trading below daily pivot ₹${p.toFixed(1)}. Downside bias toward S1 ₹${s1.toFixed(1)}.`;

  return {
    srv_signal: signal,
    srv_entry: entry,
    srv_stop: stop,
    srv_target1: target1,
    srv_target2: target2,
    srv_strength: Math.abs(ltp - p) > (high - low) * 0.2 ? "STRONG" : "MODERATE",
    srv_rr: rr > 0.5 ? rr : 1.8,
    srv_reason: reason,
    srv_setup: setup,
    live_ltp: ltp,
    change: prevClose > 0 ? ((ltp - prevClose) / prevClose) * 100 : 0,
    r1,
    r2,
    s1,
    s2,
    pivot: p,
    high,
    low,
  };
}

// ── Autonomous Markets Fetcher (Server first, Direct Market Cloud fallback) ──
//
// If /api/markets fails (missing key, RADAR offline, network blip), this
// used to backfill every symbol with numbers hardcoded in this file --
// frozen at whatever NIFTY/crude/etc. happened to be when this code was
// written -- and label the result "Live Cloud Direct", indistinguishable
// from a genuine live read. That silently showed stale, made-up prices as
// current. Now a symbol only appears here if a real quote (server or
// direct Yahoo/MCX) actually came back; anything else is simply omitted,
// so the UI's own "--" placeholder shows instead of a fabricated number.
export const fetchMarkets = async (): Promise<MarketsResponse> => {
  try {
    return await request<MarketsResponse>("/api/markets", 3000);
  } catch (_) {
    const [niftyQ, bankQ, relianceQ, mcxData] = await Promise.all([
      fetchDirectYahooChart("^NSEI"),
      fetchDirectYahooChart("^NSEBANK"),
      fetchDirectYahooChart("RELIANCE.NS"),
      fetchDirectRenderMCX(),
    ]);

    const crudeLtp = mcxData?.crude?.mcx_ltp;
    const crudeHigh = mcxData?.crude?.mcx_high ?? (crudeLtp ? crudeLtp * 1.01 : undefined);
    const crudeLow = mcxData?.crude?.mcx_low ?? (crudeLtp ? crudeLtp * 0.99 : undefined);
    const crudePrev = mcxData?.crude?.mcx_prev_close ?? crudeLtp;
    const crudePct = mcxData?.crude?.mcx_pct ?? 0;

    const gasLtp = mcxData?.gas?.mcx_ltp;
    const gasHigh = mcxData?.gas?.mcx_high ?? (gasLtp ? gasLtp * 1.01 : undefined);
    const gasLow = mcxData?.gas?.mcx_low ?? (gasLtp ? gasLtp * 0.99 : undefined);
    const gasPrev = mcxData?.gas?.mcx_prev_close ?? gasLtp;
    const gasPct = mcxData?.gas?.mcx_pct ?? 0;

    const signals: Record<string, SignalData> = {};
    const fast_ltp: Record<string, number> = {};
    const fast_change: Record<string, number> = {};
    const spark: Record<string, number[]> = {};

    const add = (
      key: string,
      ltp: number | undefined,
      high: number | undefined,
      low: number | undefined,
      prevClose: number | undefined,
      change: number | undefined,
      sparkVals: number[] | undefined,
      label: string
    ) => {
      if (ltp === undefined || ltp === null || isNaN(ltp)) return; // no real quote -- leave it out
      signals[key] = computePivotSignal(ltp, high ?? ltp, low ?? ltp, prevClose ?? ltp, label);
      fast_ltp[key] = ltp;
      fast_change[key] = change ?? 0;
      spark[key] = sparkVals && sparkVals.length ? sparkVals : [ltp];
    };

    add("nifty", niftyQ?.ltp, niftyQ?.high, niftyQ?.low, niftyQ?.prevClose, niftyQ?.change, niftyQ?.spark, "NIFTY 50");
    add("banknifty", bankQ?.ltp, bankQ?.high, bankQ?.low, bankQ?.prevClose, bankQ?.change, bankQ?.spark, "BANK NIFTY");
    add("reliance", relianceQ?.ltp, relianceQ?.high, relianceQ?.low, relianceQ?.prevClose, relianceQ?.change, relianceQ?.spark, "RELIANCE");
    add("crude", crudeLtp, crudeHigh, crudeLow, crudePrev, crudePct, crudeLtp && crudeLow && crudeHigh ? [crudeLow, (crudeLow + crudeHigh) / 2, crudeHigh, crudeLtp] : undefined, "CRUDE OIL (MCX)");
    add("natgas", gasLtp, gasHigh, gasLow, gasPrev, gasPct, gasLtp && gasLow && gasHigh ? [gasLow, (gasLow + gasHigh) / 2, gasHigh, gasLtp] : undefined, "NATURAL GAS (MCX)");

    if (Object.keys(signals).length === 0) {
      throw new Error("RADAR server unreachable and no backup market data available.");
    }

    return {
      success: true,
      signals,
      signals_updated_at: new Date().toISOString(),
      fast_ltp,
      fast_change,
      fast_depth: {},
      spark,
      trends: {},
      token_status: {
        has_token: false,
        is_expired: false,
        data_source: "Backup feed (delayed, server unreachable)",
        fallback_active: true,
      },
    };
  }
};

// ── Autonomous Commodities Fetcher ──
// Same rule as fetchMarkets: only ever show a number that came from a real
// quote. If MCX direct-cloud data isn't available either, throw instead of
// backfilling with figures hardcoded in this file.
export const fetchCommodities = async (): Promise<CommoditiesResponse> => {
  try {
    return await request<CommoditiesResponse>("/api/commodities", 3000);
  } catch (_) {
    const mcxData = await fetchDirectRenderMCX();
    const crudeLtp = mcxData?.crude?.mcx_ltp;
    const gasLtp = mcxData?.gas?.mcx_ltp;
    if (crudeLtp === undefined && gasLtp === undefined) {
      throw new Error("RADAR server unreachable and no backup MCX data available.");
    }

    const crudeHigh = mcxData?.crude?.mcx_high ?? (crudeLtp ? crudeLtp * 1.012 : undefined);
    const crudeLow = mcxData?.crude?.mcx_low ?? (crudeLtp ? crudeLtp * 0.988 : undefined);
    const crudePrev = mcxData?.crude?.mcx_prev_close ?? crudeLtp;
    const crudePct = mcxData?.crude?.mcx_pct ?? 0;

    const gasHigh = mcxData?.gas?.mcx_high ?? (gasLtp ? gasLtp * 1.015 : undefined);
    const gasLow = mcxData?.gas?.mcx_low ?? (gasLtp ? gasLtp * 0.985 : undefined);
    const gasPrev = mcxData?.gas?.mcx_prev_close ?? gasLtp;
    const gasPct = mcxData?.gas?.mcx_pct ?? 0;

    return {
      success: true,
      crude: crudeLtp === undefined ? { signal: {}, spark: [], bars: [] } : {
        signal: computePivotSignal(crudeLtp, crudeHigh ?? crudeLtp, crudeLow ?? crudeLtp, crudePrev ?? crudeLtp, "CRUDEOIL"),
        ltp: crudeLtp,
        change: crudePct,
        spark: crudeHigh && crudeLow ? [crudeLow, (crudeLow + crudeHigh) / 2, crudeHigh, crudeLtp] : [crudeLtp],
        bars: [],
      },
      natgas: gasLtp === undefined ? { signal: {}, spark: [], bars: [] } : {
        signal: computePivotSignal(gasLtp, gasHigh ?? gasLtp, gasLow ?? gasLtp, gasPrev ?? gasLtp, "NATURALGAS"),
        ltp: gasLtp,
        change: gasPct,
        spark: gasHigh && gasLow ? [gasLow, (gasLow + gasHigh) / 2, gasHigh, gasLtp] : [gasLtp],
        bars: [],
      },
    };
  }
};

// ── Autonomous Intraday Alerts & Suggestions Fetcher ──
export const fetchAlerts = async (): Promise<AlertsResponse> => {
  try {
    return await request<AlertsResponse>("/api/alerts", 3000);
  } catch (_) {
    const mkt = await fetchMarkets();
    const recent: AlertRecord[] = [];

    const keys = ["crude", "natgas", "nifty", "banknifty", "reliance"];
    const labels: Record<string, string> = {
      crude: "CRUDEOIL MCX",
      natgas: "NATURALGAS MCX",
      nifty: "NIFTY 50",
      banknifty: "BANK NIFTY",
      reliance: "RELIANCE",
    };

    for (const k of keys) {
      const sig = mkt.signals[k];
      if (sig && sig.srv_entry && sig.srv_stop && sig.srv_target1) {
        recent.push({
          symbol: labels[k] || k.toUpperCase(),
          direction: (sig.srv_signal === "BUY" ? "BUY" : "SELL"),
          setup: sig.srv_setup || "Pivot Strategy",
          entry: sig.srv_entry,
          stop: sig.srv_stop,
          target1: sig.srv_target1,
          target2: sig.srv_target2,
          strength: sig.srv_strength || "HIGH",
          rr: sig.srv_rr || 2.0,
          opened_at: new Date().toISOString(),
          outcome: "open",
        });
      }
    }

    // Historical win/loss outcomes only exist in RADAR's real signal
    // journal (signal_journal.py), which isn't reachable in this fallback
    // path -- reporting invented resolved/win-rate numbers here would show
    // a fake track record as if it were real. Honestly report "no data"
    // instead; the currently-open setups above are still real quotes.
    return {
      success: true,
      recent,
      stats: {
        overall: {
          resolved: 0,
          open: recent.length,
          wins: 0,
          losses: 0,
          win_rate: null,
          expectancy_r: null,
        },
        crude: null,
        natgas: null,
        by_setup: {},
      },
    };
  }
};

export const fetchFastLtp = () => fetchMarkets();
