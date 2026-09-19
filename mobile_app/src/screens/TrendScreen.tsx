import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  AppState,
} from "react-native";
import { theme } from "../theme";
import { fetchMarkets, fetchPulseTrend, MarketsResponse, PulseTrend } from "../api";
import { Header } from "../components/Header";

export const TrendScreen: React.FC = () => {
  const [data, setData] = useState<MarketsResponse | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pulse, setPulse] = useState<PulseTrend | null>(null);
  const [pulseError, setPulseError] = useState<string | null>(null);
  const pulseInFlight = React.useRef(false);

  const loadPulse = async () => {
    if (pulseInFlight.current) return;
    pulseInFlight.current = true;
    try {
      setPulse(await fetchPulseTrend());
      setPulseError(null);
    } catch (e: any) {
      // Keep the last good reading on screen; just flag that it is stale.
      setPulseError(e?.name === "AbortError" ? "Pulse is waking up (free tier) -- retrying" : e?.message || "Pulse unavailable");
    } finally {
      pulseInFlight.current = false;
    }
  };

  useEffect(() => {
    loadPulse();
    const timer = setInterval(() => {
      if (AppState.currentState === "active") loadPulse();
    }, 60000);
    return () => clearInterval(timer);
  }, []);

  // Skip a poll while the previous one is still in flight, so a slow network
  // cannot pile up overlapping requests every 6s.
  const inFlight = React.useRef(false);
  const loadData = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      setError(null);
      const res = await fetchMarkets();
      setData(res);
    } catch (e: any) {
      setError(e.message || "Failed to load market trends");
    } finally {
      inFlight.current = false;
    }
  };

  const onRefresh = async () => {
    setIsRefreshing(true);
    await loadData();
    setIsRefreshing(false);
  };

  useEffect(() => {
    loadData();

    // Auto-refresh every 6s when app is visible
    const timer = setInterval(() => {
      if (AppState.currentState === "active") {
        loadData();
      }
    }, 6000);

    return () => clearInterval(timer);
  }, []);

  const marketCards = [
    { key: "nifty", label: "NIFTY 50", icon: "📈", kind: "INDEX" },
    { key: "banknifty", label: "BANK NIFTY", icon: "🏦", kind: "INDEX" },
    { key: "crude", label: "CRUDE OIL (MCX)", icon: "🛢️", kind: "COMMODITY" },
    { key: "natgas", label: "NATURAL GAS (MCX)", icon: "⚡", kind: "COMMODITY" },
  ];

  const formatPrice = (val?: number | null) => {
    if (val === undefined || val === null || isNaN(val)) return "—";
    return val.toLocaleString("en-IN", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 2,
    });
  };

  // The trend label comes from the server's trend engine (daily EMA20 / MA50 /
  // MA200 / RSI / volume structure) -- the same classification the desktop
  // Trend Analyser shows. It must NOT be inferred from today's % move: a stock
  // index can be up 0.3% today and still be in a daily downtrend.
  const BULLISH = ["Strong Uptrend", "Uptrend", "Accumulation"];
  const BEARISH = ["Downtrend", "Distribution"];
  const trendOf = (key: string): string | null => {
    const t = data?.trends?.[key];
    return t && t.available && typeof t.trend === "string" ? t.trend : null;
  };
  const colorForTrend = (trend: string | null) =>
    trend === null
      ? theme.colors.textDim
      : BULLISH.includes(trend)
      ? theme.colors.green
      : BEARISH.includes(trend)
      ? theme.colors.red
      : theme.colors.yellow;

  const niftyTrend = trendOf("nifty");
  const bankTrend = trendOf("banknifty");
  const pct = (v?: number) => (typeof v === "number" && !isNaN(v) ? v : 0);
  const niftyToday = pct(data?.fast_change?.nifty);
  const bankToday = pct(data?.fast_change?.banknifty);

  let marketBias = "TREND DATA LOADING";
  let biasColor: string = theme.colors.textDim;
  if (niftyTrend && bankTrend) {
    const bothBull = BULLISH.includes(niftyTrend) && BULLISH.includes(bankTrend);
    const bothBear = BEARISH.includes(niftyTrend) && BEARISH.includes(bankTrend);
    const bothSide = niftyTrend === "Consolidation" && bankTrend === "Consolidation";
    if (bothBull) {
      marketBias = "BULLISH TREND";
      biasColor = theme.colors.green;
    } else if (bothBear) {
      marketBias = "BEARISH TREND";
      biasColor = theme.colors.red;
    } else if (bothSide) {
      marketBias = "SIDEWAYS / CONSOLIDATION";
      biasColor = theme.colors.yellow;
    } else {
      marketBias = "MIXED TREND";
      biasColor = theme.colors.yellow;
    }
  }

  const fixText = (s?: string) => (s ? s.split("\u00e2\u201a\u00b9").join("\u20b9") : "");
  const pulseColor = !pulse
    ? theme.colors.textDim
    : pulse.direction === "BULLISH"
    ? theme.colors.green
    : pulse.direction === "BEARISH"
    ? theme.colors.red
    : theme.colors.yellow;
  const pillarColor = (score: number) =>
    score >= 60 ? theme.colors.green : score <= 40 ? theme.colors.red : theme.colors.yellow;

  const levelRow = (label: string, level: number | null | undefined, ltp: number | null | undefined) => {
    const has = typeof level === "number" && !isNaN(level);
    const above = has && typeof ltp === "number" && ltp >= (level as number);
    return (
      <View style={styles.pivotBox}>
        <Text style={styles.pivotLabel}>{label}</Text>
        <Text
          style={[
            styles.pivotVal,
            { color: !has ? theme.colors.textDim : above ? theme.colors.green : theme.colors.red },
          ]}
        >
          {has ? formatPrice(level) : "—"}
        </Text>
      </View>
    );
  };

  return (
    <View style={styles.container}>
      <Header
        tokenStatus={data?.token_status}
        onRefresh={onRefresh}
        isRefreshing={isRefreshing}
      />

      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={onRefresh}
            tintColor={theme.colors.accent}
          />
        }
      >
        {error && (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>⚠ {error}</Text>
          </View>
        )}

        {/* NIFTY intraday bias from FINPLUS PULSE (four-pillar model). A different
            timeframe from the daily EMA/MA trend below, so both are labelled. */}
        <View style={styles.summaryBanner}>
          <View style={styles.summaryTop}>
            <Text style={styles.summaryLabel}>NIFTY INTRADAY BIAS · PULSE</Text>
            {pulse && (
              <View style={[styles.biasPill, { backgroundColor: pulseColor + "22", borderColor: pulseColor }]}>
                <View style={[styles.biasDot, { backgroundColor: pulseColor }]} />
                <Text style={[styles.biasText, { color: pulseColor }]}>{pulse.trend_label}</Text>
              </View>
            )}
          </View>
          {pulse ? (
            <>
              <Text style={styles.summaryDesc}>
                Bullish bias score {typeof pulse.score === "number" ? pulse.score.toFixed(1) : "—"}/100
                {pulse.updated_at ? ` · ${pulse.updated_at}` : ""}
              </Text>
              {!!pulse.market_status && <Text style={styles.summaryDesc}>{pulse.market_status}</Text>}
              {Object.values(pulse.pillars || {}).map((p, i) => (
                <View key={i} style={{ marginTop: 8 }}>
                  <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                    <Text style={styles.summaryDesc}>{p.title} ({p.weight_pct}%)</Text>
                    <Text style={[styles.summaryDesc, { color: pillarColor(p.score), fontWeight: "800" }]}>
                      {typeof p.score === "number" ? p.score.toFixed(1) : "—"}
                    </Text>
                  </View>
                  {!!p.details && <Text style={[styles.summaryDesc, { opacity: 0.7 }]}>{fixText(p.details)}</Text>}
                </View>
              ))}
              {!!pulseError && <Text style={[styles.summaryDesc, { color: theme.colors.yellow }]}>⚠ Showing last reading — {pulseError}</Text>}
            </>
          ) : (
            <Text style={styles.summaryDesc}>
              {pulseError ? `Pulse unavailable: ${pulseError}` : "Loading Pulse bias…"}
            </Text>
          )}
        </View>

        {/* Overall stance -- from the trend engine's daily classification of NIFTY + BANK NIFTY */}
        <View style={styles.summaryBanner}>
          <View style={styles.summaryTop}>
            <Text style={styles.summaryLabel}>DAILY TREND (EMA / MA STRUCTURE)</Text>
            <View style={[styles.biasPill, { backgroundColor: biasColor + "22", borderColor: biasColor }]}>
              <View style={[styles.biasDot, { backgroundColor: biasColor }]} />
              <Text style={[styles.biasText, { color: biasColor }]}>{marketBias}</Text>
            </View>
          </View>
          <Text style={styles.summaryDesc}>
            NIFTY: {niftyTrend ?? "—"} | BANK NIFTY: {bankTrend ?? "—"}
          </Text>
          <Text style={styles.summaryDesc}>
            Today: Nifty {niftyToday >= 0 ? "+" : ""}{niftyToday.toFixed(2)}% | BankNifty {bankToday >= 0 ? "+" : ""}{bankToday.toFixed(2)}%
          </Text>
          <Text style={[styles.summaryDesc, { fontStyle: "italic" }]}>
            Daily trend compares price with the 20/50/200-day averages, so it can differ from today's move and from the intraday bias shown in FINPLUS PULSE.
          </Text>
        </View>

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>TREND ANALYSER</Text>
          <Text style={styles.liveTag}>DAILY TREND · LAST LTP</Text>
        </View>

        {marketCards.map((item) => {
          const ltp = data?.fast_ltp?.[item.key];
          const hasLtp = typeof ltp === "number" && !isNaN(ltp);
          const change = pct(data?.fast_change?.[item.key]);
          const isUp = change >= 0;
          const t = data?.trends?.[item.key];
          const available = !!(t && t.available);
          const d = t?.display;
          const trendColor = colorForTrend(available ? t.trend : null);

          return (
            <View key={item.key} style={styles.card}>
              <View style={styles.cardTop}>
                <View style={styles.symbolRow}>
                  <Text style={styles.itemIcon}>{item.icon}</Text>
                  <View>
                    <Text style={styles.symbolName}>{item.label}</Text>
                    <Text style={styles.itemKind}>{item.kind}</Text>
                  </View>
                </View>

                <View style={styles.priceCol}>
                  <Text style={styles.ltpText}>₹{formatPrice(hasLtp ? ltp : undefined)}</Text>
                  <Text
                    style={[
                      styles.changeText,
                      { color: !hasLtp ? theme.colors.textDim : isUp ? theme.colors.green : theme.colors.red },
                    ]}
                  >
                    {hasLtp ? `${isUp ? "▲ +" : "▼ "}${change.toFixed(2)}%` : "No data"}
                  </Text>
                </View>
              </View>

              <View style={[styles.biasPill, { alignSelf: "flex-start", backgroundColor: trendColor + "22", borderColor: trendColor, marginTop: 10 }]}>
                <View style={[styles.biasDot, { backgroundColor: trendColor }]} />
                <Text style={[styles.biasText, { color: trendColor }]}>
                  {available ? t.trend : "Trend not available yet"}
                </Text>
              </View>

              {available && d && (
                <>
                  <View style={styles.pivotRow}>
                    {levelRow("EMA 20", d.ema20, d.ltp)}
                    {levelRow("MA 50", d.ma50, d.ltp)}
                    {levelRow("MA 200", d.ma200, d.ltp)}
                  </View>
                  <View style={styles.pivotRow}>
                    <View style={styles.pivotBox}>
                      <Text style={styles.pivotLabel}>RSI (14)</Text>
                      <Text style={styles.pivotVal}>{typeof t.rsi === "number" ? t.rsi.toFixed(1) : "—"}</Text>
                    </View>
                    <View style={styles.pivotBox}>
                      <Text style={styles.pivotLabel}>VOL vs 10D</Text>
                      <Text style={styles.pivotVal}>
                        {typeof t.volume_spike === "number" ? `${t.volume_spike.toFixed(2)}x` : "—"}
                      </Text>
                    </View>
                    <View style={styles.pivotBox}>
                      <Text style={styles.pivotLabel}>52W HIGH</Text>
                      <Text style={styles.pivotVal}>
                        {typeof d.dist_52h_pct === "number" ? `${d.dist_52h_pct.toFixed(1)}%` : "—"}
                      </Text>
                    </View>
                  </View>
                  {!!d.note && (
                    <Text style={styles.reasonText}>
                      Levels are {d.note}; price above is the live MCX quote.
                    </Text>
                  )}
                </>
              )}
              {!available && !!t?.reason && <Text style={styles.reasonText}>{t.reason}</Text>}
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.bg,
  },
  scrollContent: {
    padding: theme.spacing.lg,
    paddingBottom: 40,
  },
  errorBox: {
    backgroundColor: theme.colors.redBg,
    borderColor: theme.colors.redBorder,
    borderWidth: 1,
    padding: theme.spacing.md,
    borderRadius: theme.radius.md,
    marginBottom: theme.spacing.md,
  },
  errorText: {
    color: theme.colors.red,
    fontSize: 12,
    fontWeight: "600",
  },
  summaryBanner: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.lg,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
    marginBottom: theme.spacing.lg,
  },
  summaryTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 6,
  },
  summaryLabel: {
    fontSize: 11,
    fontWeight: "800",
    color: theme.colors.textMuted,
    letterSpacing: 0.8,
  },
  biasPill: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 12,
    borderWidth: 1,
    gap: 5,
  },
  biasDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  biasText: {
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 0.5,
  },
  summaryDesc: {
    fontSize: 13,
    fontWeight: "700",
    color: theme.colors.text,
  },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: theme.spacing.md,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: theme.colors.textMuted,
    letterSpacing: 0.8,
  },
  liveTag: {
    fontSize: 10,
    fontWeight: "700",
    color: theme.colors.textDim,
  },
  card: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.lg,
    marginBottom: theme.spacing.md,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  cardTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: theme.spacing.md,
  },
  symbolRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  itemIcon: {
    fontSize: 22,
  },
  symbolName: {
    fontSize: 15,
    fontWeight: "800",
    color: theme.colors.text,
  },
  itemKind: {
    fontSize: 9,
    fontWeight: "800",
    color: theme.colors.textDim,
    marginTop: 2,
    letterSpacing: 0.5,
  },
  priceCol: {
    alignItems: "flex-end",
  },
  ltpText: {
    fontSize: 17,
    fontWeight: "800",
    color: theme.colors.text,
  },
  changeText: {
    fontSize: 12,
    fontWeight: "800",
    marginTop: 2,
  },
  cardMiddle: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: theme.colors.surfaceLight,
    padding: theme.spacing.md,
    borderRadius: theme.radius.md,
    marginBottom: theme.spacing.sm,
  },
  sparkCol: {
    flex: 1,
  },
  signalCol: {
    alignItems: "flex-end",
  },
  metaLabel: {
    fontSize: 9,
    fontWeight: "800",
    color: theme.colors.textDim,
    marginBottom: 4,
    letterSpacing: 0.5,
  },
  pivotRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    backgroundColor: "rgba(0,0,0,0.2)",
    padding: 8,
    borderRadius: theme.radius.md,
    marginTop: 4,
    gap: 6,
  },
  pivotBox: {
    flex: 1,
    alignItems: "center",
  },
  pivotLabel: {
    fontSize: 8,
    fontWeight: "700",
    color: theme.colors.textDim,
    marginBottom: 2,
  },
  pivotVal: {
    fontSize: 11,
    fontWeight: "800",
    color: theme.colors.text,
  },
  reasonBox: {
    marginTop: 8,
    backgroundColor: "rgba(99, 102, 241, 0.07)",
    padding: 8,
    borderRadius: 6,
    borderWidth: 0.5,
    borderColor: "rgba(99, 102, 241, 0.2)",
  },
  reasonText: {
    fontSize: 11,
    color: theme.colors.accent,
    lineHeight: 16,
  },
});
