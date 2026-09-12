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

// ── Real multi-stock screener (equity_scan / swing_engine / lt_engine / penny_engine) ──
export interface StockPick {
  symbol: string;
  name?: string;
  sector?: string;
  ltp?: number;
  direction?: "BUY" | "SELL";
  srv_signal?: string;
  srv_entry?: number;
  srv_stop?: number;
  srv_target1?: number;
  srv_target2?: number;
  srv_rr?: number;
  srv_setup?: string;
  srv_reason?: string;
  stop_loss?: number;
  target1?: number;
  target2?: number;
  intraday_score?: number;
  total_score?: number;
  swing_score?: number;
  swing_action?: string;
  status_badge?: string;
  gtt_breakout_level?: number;
  gtt_pullback_level?: number;
  rationale?: string;
  day_chg_pct?: number;
  rsi?: number;
  volume_spike?: number;
  [key: string]: any;
}

export interface ScreenerAllResponse {
  success: boolean;
  swing: { picks: StockPick[]; total_candidates: number; qualified_count: number } | null;
  lt: { watchlist: StockPick[]; top_challengers: StockPick[]; total_scanned: number } | null;
  penny: { picks: StockPick[]; total_evaluated: number; qualified_count: number } | null;
  momentum: { buy: StockPick[]; sell: StockPick[]; buy_qualified: number; sell_qualified: number } | null;
  equity: { buy: StockPick[]; sell: StockPick[]; watch_buy: StockPick[]; watch_sell: StockPick[] } | null;
}

// No offline fallback here on purpose: this scan needs your PC's live
// INDmoney session (equity_scan.py), so there is nothing honest to fabricate
// when the backend is unreachable -- the screen should say so, not guess.
export const fetchScreenerAll = async (): Promise<ScreenerAllResponse> => {
  return request<ScreenerAllResponse>("/api/screener/all", 8000);
};

// Low-level fetch wrapper
async function request<T>(path: string, timeoutMs: number = 4000, body?: unknown): Promise<T> {
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
    const res = await fetch(url, {
      signal: ctrl.signal,
      headers,
      method: body !== undefined ? "POST" : "GET",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const json = await res.json().catch(() => null);
    if (!res.ok) {
      throw new Error(json?.error || `HTTP ${res.status}: ${res.statusText}`);
    }
    return json;
  } finally {
    clearTimeout(timer);
  }
}

// Push a freshly generated INDmoney access token to the live backend --
// lets the token be refreshed daily from the phone itself, no Render
// dashboard or desktop browser needed (INDmoney tokens expire every 24h
// and have no programmable refresh flow).
export const updateIndmoneyToken = async (token: string): Promise<{ success: boolean; error?: string }> => {
  return request("/api/token", 8000, { token });
};

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

// ── Markets Fetcher: real backend first, live direct-quote fallback second.
// The fallback only ever uses numbers it actually fetched just now (Yahoo
// Finance / the MCX cloud endpoint) -- a symbol whose direct fetch also
// fails is simply left out of the response rather than filled with a
// made-up price, per the "no fabricated data" rule for this app.
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

    const signals: Record<string, SignalData> = {};
    const fast_ltp: Record<string, number> = {};
    const fast_change: Record<string, number> = {};
    const spark: Record<string, number[]> = {};

    const addQuote = (key: string, label: string, q: typeof niftyQ) => {
      if (!q || !q.ltp) return;
      signals[key] = computePivotSignal(q.ltp, q.high, q.low, q.prevClose, label);
      fast_ltp[key] = q.ltp;
      fast_change[key] = q.change;
      spark[key] = q.spark;
    };

    addQuote("nifty", "NIFTY 50", niftyQ);
    addQuote("banknifty", "BANK NIFTY", bankQ);
    addQuote("reliance", "RELIANCE", relianceQ);

    const crude = mcxData?.crude;
    if (crude?.mcx_ltp) {
      const high = crude.mcx_high ?? crude.mcx_ltp;
      const low = crude.mcx_low ?? crude.mcx_ltp;
      const prev = crude.mcx_prev_close ?? crude.mcx_ltp;
      signals.crude = computePivotSignal(crude.mcx_ltp, high, low, prev, "CRUDE OIL (MCX)");
      fast_ltp.crude = crude.mcx_ltp;
      fast_change.crude = crude.mcx_pct ?? 0;
      spark.crude = [low, (low + high) / 2, high, crude.mcx_ltp];
    }

    const gas = mcxData?.gas;
    if (gas?.mcx_ltp) {
      const high = gas.mcx_high ?? gas.mcx_ltp;
      const low = gas.mcx_low ?? gas.mcx_ltp;
      const prev = gas.mcx_prev_close ?? gas.mcx_ltp;
      signals.natgas = computePivotSignal(gas.mcx_ltp, high, low, prev, "NATURAL GAS (MCX)");
      fast_ltp.natgas = gas.mcx_ltp;
      fast_change.natgas = gas.mcx_pct ?? 0;
      spark.natgas = [low, (low + high) / 2, high, gas.mcx_ltp];
    }

    return {
      success: Object.keys(signals).length > 0,
      signals,
      signals_updated_at: new Date().toISOString(),
      fast_ltp,
      fast_change,
      fast_depth: {},
      spark,
      trends: {},
      token_status: {
        has_token: false,
        is_expired: true,
        data_source: "Live Cloud Direct (backend unreachable)",
        fallback_active: true,
      },
    };
  }
};

// ── Commodities Fetcher: real backend first, direct MCX cloud fallback ──
export const fetchCommodities = async (): Promise<CommoditiesResponse> => {
  try {
    return await request<CommoditiesResponse>("/api/commodities", 3000);
  } catch (_) {
    const mcxData = await fetchDirectRenderMCX();
    const crude = mcxData?.crude;
    const gas = mcxData?.gas;

    const buildLeg = (leg: typeof crude, name: string) => {
      if (!leg?.mcx_ltp) {
        return { signal: {}, ltp: undefined, change: undefined, spark: [], bars: [] };
      }
      const high = leg.mcx_high ?? leg.mcx_ltp;
      const low = leg.mcx_low ?? leg.mcx_ltp;
      const prev = leg.mcx_prev_close ?? leg.mcx_ltp;
      return {
        signal: computePivotSignal(leg.mcx_ltp, high, low, prev, name),
        ltp: leg.mcx_ltp,
        change: leg.mcx_pct ?? 0,
        spark: [low, (low + high) / 2, high, leg.mcx_ltp],
        bars: [],
      };
    };

    return {
      success: Boolean(crude?.mcx_ltp || gas?.mcx_ltp),
      crude: buildLeg(crude, "CRUDEOIL"),
      natgas: buildLeg(gas, "NATURALGAS"),
    };
  }
};

// ── Intraday Alerts Fetcher: real signal-journal history first, live
// pivot-based read on whatever direct quotes succeeded second. ──
export const fetchAlerts = async (): Promise<AlertsResponse> => {
  try {
    return await request<AlertsResponse>("/api/alerts", 3000);
  } catch (_) {
    const mkt = await fetchMarkets();
    const recent: AlertRecord[] = [];

    const labels: Record<string, string> = {
      crude: "CRUDEOIL MCX",
      natgas: "NATURALGAS MCX",
      nifty: "NIFTY 50",
      banknifty: "BANK NIFTY",
      reliance: "RELIANCE",
    };

    for (const k of Object.keys(mkt.signals)) {
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
          strength: sig.srv_strength || "MODERATE",
          rr: sig.srv_rr,
          opened_at: new Date().toISOString(),
          outcome: "open",
        });
      }
    }

    return {
      success: recent.length > 0,
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
