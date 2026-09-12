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
import { fetchMarkets, MarketsResponse } from "../api";
import { Header } from "../components/Header";
import { SignalBadge } from "../components/SignalBadge";
import { MiniSparkline } from "../components/MiniSparkline";

export const TrendScreen: React.FC = () => {
  const [data, setData] = useState<MarketsResponse | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setError(null);
      const res = await fetchMarkets();
      setData(res);
    } catch (e: any) {
      setError(e.message || "Failed to load market trends");
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
    { key: "reliance", label: "RELIANCE IND.", icon: "🔷", kind: "HEAVYWEIGHT" },
  ];

  const formatPrice = (val?: number) => {
    if (val === undefined || val === null || isNaN(val)) return "—";
    return val.toLocaleString("en-IN", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 2,
    });
  };

  // Determine overall market bias
  const niftyChange = data?.fast_change?.nifty || data?.signals?.nifty?.change || 0;
  const bankChange = data?.fast_change?.banknifty || data?.signals?.banknifty?.change || 0;
  const avgChange = (niftyChange + bankChange) / 2;
  const marketBias =
    avgChange > 0.3 ? "BULLISH TREND" : avgChange < -0.3 ? "BEARISH TREND" : "SIDEWAYS / NEUTRAL";
  const biasColor =
    avgChange > 0.3 ? theme.colors.green : avgChange < -0.3 ? theme.colors.red : theme.colors.yellow;

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

        {/* Market Trend Overview Banner */}
        <View style={styles.summaryBanner}>
          <View style={styles.summaryTop}>
            <Text style={styles.summaryLabel}>OVERALL MARKET STANCE</Text>
            <View style={[styles.biasPill, { backgroundColor: biasColor + "22", borderColor: biasColor }]}>
              <View style={[styles.biasDot, { backgroundColor: biasColor }]} />
              <Text style={[styles.biasText, { color: biasColor }]}>{marketBias}</Text>
            </View>
          </View>
          <Text style={styles.summaryDesc}>
            Nifty {niftyChange >= 0 ? "+" : ""}{niftyChange.toFixed(2)}% | BankNifty {bankChange >= 0 ? "+" : ""}{bankChange.toFixed(2)}%
          </Text>
        </View>

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>TREND ANALYSER WATCHLIST</Text>
          <Text style={styles.liveTag}>AUTO-REFRESH 6s</Text>
        </View>

        {marketCards.map((item) => {
          const ltp = data?.fast_ltp?.[item.key] || data?.signals?.[item.key]?.live_ltp;
          const change = data?.fast_change?.[item.key] ?? data?.signals?.[item.key]?.change ?? 0;
          const isUp = change >= 0;
          const sig = data?.signals?.[item.key];
          const spark = data?.spark?.[item.key] || [];

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
                  <Text style={styles.ltpText}>₹{formatPrice(ltp)}</Text>
                  <Text
                    style={[
                      styles.changeText,
                      { color: isUp ? theme.colors.green : theme.colors.red },
                    ]}
                  >
                    {isUp ? "▲ +" : "▼ "}
                    {change ? change.toFixed(2) : "0.00"}%
                  </Text>
                </View>
              </View>

              <View style={styles.cardMiddle}>
                <View style={styles.sparkCol}>
                  <Text style={styles.metaLabel}>INTRADAY TRAJECTORY</Text>
                  <MiniSparkline data={spark} />
                </View>

                <View style={styles.signalCol}>
                  <Text style={styles.metaLabel}>TREND STATUS</Text>
                  <SignalBadge
                    signal={sig?.srv_signal || (isUp ? "BUY" : "SELL")}
                    setup={sig?.srv_setup || "Trend Analysis"}
                  />
                </View>
              </View>

              {/* Pivot Levels Row */}
              <View style={styles.pivotRow}>
                <View style={styles.pivotBox}>
                  <Text style={styles.pivotLabel}>SUPPORT (S1)</Text>
                  <Text style={styles.pivotVal}>
                    ₹{formatPrice(sig?.s1 || (ltp ? ltp * 0.992 : 0))}
                  </Text>
                </View>
                <View style={styles.pivotBox}>
                  <Text style={styles.pivotLabel}>PIVOT (P)</Text>
                  <Text style={[styles.pivotVal, { color: theme.colors.accent }]}>
                    ₹{formatPrice(sig?.pivot || ltp)}
                  </Text>
                </View>
                <View style={styles.pivotBox}>
                  <Text style={styles.pivotLabel}>RESISTANCE (R1)</Text>
                  <Text style={[styles.pivotVal, { color: theme.colors.green }]}>
                    ₹{formatPrice(sig?.r1 || (ltp ? ltp * 1.008 : 0))}
                  </Text>
                </View>
              </View>

              {sig?.srv_reason && (
                <View style={styles.reasonBox}>
                  <Text style={styles.reasonText}>💡 {sig.srv_reason}</Text>
                </View>
              )}
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
