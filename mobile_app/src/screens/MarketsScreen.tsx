import React, { useState, useEffect, useRef } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  AppState,
  TouchableOpacity,
} from "react-native";
import { theme } from "../theme";
import { fetchMarkets, fetchFastLtp, MarketsResponse } from "../api";
import { Header } from "../components/Header";
import { SignalBadge } from "../components/SignalBadge";
import { MiniSparkline } from "../components/MiniSparkline";

export const MarketsScreen: React.FC = () => {
  const [data, setData] = useState<MarketsResponse | null>(null);
  const [fastLtp, setFastLtp] = useState<Record<string, number>>({});
  const [fastChange, setFastChange] = useState<Record<string, number>>({});
  const [sparkMap, setSparkMap] = useState<Record<string, number[]>>({});
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAll = async () => {
    try {
      setError(null);
      const res = await fetchMarkets();
      setData(res);
      if (res.fast_ltp) setFastLtp(res.fast_ltp);
      if (res.fast_change) setFastChange(res.fast_change);
      if (res.spark) setSparkMap(res.spark);
    } catch (e: any) {
      setError(e.message || "Failed to connect to server");
    }
  };

  const onRefresh = async () => {
    setIsRefreshing(true);
    await loadAll();
    setIsRefreshing(false);
  };

  useEffect(() => {
    loadAll();

    // 3s Fast LTP Polling (Visibility-aware: pauses when app in background)
    let timer: any = null;
    const startPolling = () => {
      if (timer) clearInterval(timer);
      timer = setInterval(async () => {
        if (AppState.currentState !== "active") return;
        try {
          const fast = await fetchFastLtp();
          if (fast.ltp) setFastLtp(fast.ltp);
          if (fast.change) setFastChange(fast.change);
          if (fast.spark) setSparkMap(fast.spark);
        } catch (_) {}
      }, 3000);
    };

    startPolling();
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active") startPolling();
      else if (timer) clearInterval(timer);
    });

    return () => {
      if (timer) clearInterval(timer);
      sub.remove();
    };
  }, []);

  const marketCards = [
    { key: "nifty", label: "NIFTY 50", icon: "📈", kind: "index" },
    { key: "banknifty", label: "BANK NIFTY", icon: "🏦", kind: "index" },
    { key: "crude", label: "CRUDE OIL (MCX)", icon: "🛢️", kind: "commodity" },
    { key: "natgas", label: "NATURAL GAS (MCX)", icon: "⚡", kind: "commodity" },
    { key: "reliance", label: "RELIANCE", icon: "🔷", kind: "stock" },
  ];

  const formatPrice = (val?: number) => {
    if (val === undefined || val === null) return "—";
    return val.toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
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

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>LIVE TICKERS & SIGNALS</Text>
          <View style={styles.liveTag}>
            <View style={styles.livePulse} />
            <Text style={styles.liveTagText}>3s STREAMING</Text>
          </View>
        </View>

        {marketCards.map((item) => {
          const ltp = fastLtp[item.key] || data?.signals?.[item.key]?.live_ltp;
          const change = fastChange[item.key] || data?.signals?.[item.key]?.change || 0;
          const isUp = change >= 0;
          const sig = data?.signals?.[item.key];
          const spark = sparkMap[item.key] || [];

          return (
            <View key={item.key} style={styles.card}>
              <View style={styles.cardTop}>
                <View style={styles.symbolRow}>
                  <Text style={styles.itemIcon}>{item.icon}</Text>
                  <View>
                    <Text style={styles.symbolName}>{item.label}</Text>
                    <Text style={styles.itemKind}>{item.kind.toUpperCase()}</Text>
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
                    {isUp ? "+" : ""}
                    {change ? change.toFixed(2) : "0.00"}%
                  </Text>
                </View>
              </View>

              <View style={styles.cardMiddle}>
                <View style={styles.sparkCol}>
                  <Text style={styles.metaLabel}>TICK HISTORY</Text>
                  <MiniSparkline data={spark} />
                </View>

                <View style={styles.signalCol}>
                  <Text style={styles.metaLabel}>SIGNAL (1H)</Text>
                  <SignalBadge
                    signal={sig?.srv_signal || "NONE"}
                    setup={sig?.srv_setup}
                  />
                </View>
              </View>

              {/* S/R levels breakdown */}
              {(sig?.r1 || sig?.s1) && (
                <View style={styles.srRow}>
                  <Text style={styles.srText}>
                    S1: <Text style={styles.srVal}>₹{formatPrice(sig?.s1)}</Text>
                  </Text>
                  <Text style={styles.srText}>
                    R1: <Text style={styles.srVal}>₹{formatPrice(sig?.r1)}</Text>
                  </Text>
                  {sig?.srv_target1 && (
                    <Text style={styles.srText}>
                      T1: <Text style={styles.targetVal}>₹{formatPrice(sig?.srv_target1)}</Text>
                    </Text>
                  )}
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
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    backgroundColor: "rgba(16, 185, 129, 0.12)",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: theme.radius.full,
    borderWidth: 1,
    borderColor: theme.colors.greenBorder,
  },
  livePulse: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: theme.colors.green,
  },
  liveTagText: {
    fontSize: 9,
    fontWeight: "800",
    color: theme.colors.green,
    letterSpacing: 0.5,
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
    fontSize: 24,
  },
  symbolName: {
    fontSize: 15,
    fontWeight: "800",
    color: theme.colors.text,
  },
  itemKind: {
    fontSize: 10,
    fontWeight: "700",
    color: theme.colors.textDim,
    marginTop: 2,
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
    fontWeight: "700",
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
    fontWeight: "700",
    color: theme.colors.textDim,
    marginBottom: 4,
    textTransform: "uppercase",
  },
  srRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: theme.spacing.xs,
    paddingHorizontal: 4,
  },
  srText: {
    fontSize: 11,
    color: theme.colors.textMuted,
  },
  srVal: {
    fontWeight: "700",
    color: theme.colors.text,
  },
  targetVal: {
    fontWeight: "700",
    color: theme.colors.green,
  },
});
