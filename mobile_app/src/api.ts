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

export interface ScreenerItem {
  symbol: string;
  name?: string;
  ltp?: number;
  change_pct?: number;
  durability_score?: number;
  dvm_label?: string;
  source?: string;
  pe?: number;
  roce?: number;
  market_cap?: number;
  sector?: string;
  signal?: string;
  setup?: string;
  trigger_reason?: string;
  [key: string]: any;
}

export interface ScreenerAllResponse {
  success: boolean;
  swing?: {
    picks?: ScreenerItem[];
    updated_at?: string;
    error?: string;
  };
  lt?: {
    picks?: ScreenerItem[];
    updated_at?: string;
    error?: string;
  };
  penny?: {
    picks?: ScreenerItem[];
    updated_at?: string;
    error?: string;
  };
  momentum?: {
    picks?: ScreenerItem[];
    top_gainers?: ScreenerItem[];
    updated_at?: string;
    error?: string;
  };
  equity?: {
    candidates?: ScreenerItem[];
    updated_at?: string;
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

async function request<T>(path: string): Promise<T> {
  const url = `${getApiBaseUrl()}${path}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 8000);
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

export const fetchMarkets = () => request<MarketsResponse>("/api/markets");
export const fetchCommodities = () => request<CommoditiesResponse>("/api/commodities");
export const fetchScreenerAll = () => request<ScreenerAllResponse>("/api/screener/all");
export const fetchAlerts = () => request<AlertsResponse>("/api/alerts");
export const fetchFastLtp = () => request<any>("/api/fast_ltp");
export const fetchOptionExpiries = (underlying: string) =>
  request<{ success: boolean; underlying: string; expiries: string[] }>(
    `/api/option_expiries/${encodeURIComponent(underlying)}`
  );
export const fetchOptionChain = (underlying: string, expiry?: string) => {
  const q = expiry ? `?expiry=${encodeURIComponent(expiry)}&analysis=1` : `?analysis=1`;
  return request<any>(`/api/option_chain/${encodeURIComponent(underlying)}${q}`);
};
