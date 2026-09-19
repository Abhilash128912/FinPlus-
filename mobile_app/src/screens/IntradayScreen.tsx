import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  TouchableOpacity,
  AppState,
} from "react-native";
import { theme } from "../theme";
import {
  fetchAlerts,
  fetchCommodities,
  fetchScreenerAll,
  AlertsResponse,
  CommoditiesResponse,
  ScreenerAllResponse,
  StockPick,
} from "../api";
import { Header } from "../components/Header";

type Filter = "ALL" | "MCX" | "STOCKS";
const MAX_STOCKS_PER_SIDE = 5;

// LIVE trade calls only: today's momentum stocks and whichever MCX setup is
// firing right now. The journal of past/closed triggers lives in the Signal
// Journal tab -- listing it here made this tab a wall of repeated stopped-out
// NATURALGAS/CRUDEOIL rows with no stocks at all.
export const IntradayScreen: React.FC = () => {
  const [alerts, setAlerts] = useState<AlertsResponse | null>(null);
  const [commodities, setCommodities] = useState<CommoditiesResponse | null>(null);
  const [screener, setScreener] = useState<ScreenerAllResponse | null>(null);
  const [activeFilter, setActiveFilter] = useState<Filter>("ALL");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    setError(null);
    const [a, c, s] = await Promise.allSettled([
      fetchAlerts(),
      fetchCommodities(),
      fetchScreenerAll(),
    ]);
    if (a.status === "fulfilled") setAlerts(a.value);
    if (c.status === "fulfilled") setCommodities(c.value);
    if (s.status === "fulfilled") setScreener(s.value);
    if (a.status === "rejected" && c.status === "rejected" && s.status === "rejected") {
      setError(a.reason?.message || "Failed to load intraday trade suggestions");
    }
  };

  const onRefresh = async () => {
    setIsRefreshing(true);
    await loadData();
    setIsRefreshing(false);
  };

  useEffect(() => {
    loadData();
    const timer = setInterval(() => {
      if (AppState.currentState === "active") {
        loadData();
      }
    }, 15000);
    return () => clearInterval(timer);
  }, []);

  const stats = alerts?.stats?.overall;

  const mcxCalls = [
    { label: "CRUDEOIL", leg: commodities?.crude },
    { label: "NATURALGAS", leg: commodities?.natgas },
  ].map(({ label, leg }) => {
    const sig = leg?.signal;
    const live = sig?.srv_signal === "BUY" || sig?.srv_signal === "SELL";
    return { label, sig, live };
  });

  const buyStocks: StockPick[] = (screener?.momentum?.buy || []).slice(0, MAX_STOCKS_PER_SIDE);
  const sellStocks: StockPick[] = (screener?.momentum?.sell || []).slice(0, MAX_STOCKS_PER_SIDE);
  const stockCalls = [
    ...buyStocks.map((p) => ({ ...p, side: "BUY" as const })),
    ...sellStocks.map((p) => ({ ...p, side: "SELL" as const })),
  ];

  const formatPrice = (val?: number | null) => {
    if (val === undefined || val === null || isNaN(val)) return "—";
    return val.toLocaleString("en-IN", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 2,
    });
  };

  const showMcx = activeFilter === "ALL" || activeFilter === "MCX";
  const showStocks = activeFilter === "ALL" || activeFilter === "STOCKS";
  const liveMcxCount = mcxCalls.filter((m) => m.live).length;
  const shownCount = (showMcx ? liveMcxCount : 0) + (showStocks ? stockCalls.length : 0);

  const renderFilterBtn = (id: Filter, label: string) => (
    <TouchableOpacity
      style={[styles.filterBtn, activeFilter === id && styles.filterBtnActive]}
      onPress={() => setActiveFilter(id)}
    >
      <Text style={[styles.filterBtnText, activeFilter === id && styles.filterBtnTextActive]}>{label}</Text>
    </TouchableOpacity>
  );

  return (
    <View style={styles.container}>
      <Header onRefresh={onRefresh} isRefreshing={isRefreshing} />

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

        <View style={styles.statsCard}>
          <Text style={styles.cardHeader}>INTRADAY TRADE ENGINE</Text>
          <View style={styles.statsGrid}>
            <View style={styles.statBox}>
              <Text style={styles.statLabel}>WIN RATE</Text>
              <Text
                style={[
                  styles.statVal,
                  { color: stats?.win_rate && stats.win_rate >= 50 ? theme.colors.green : theme.colors.yellow },
                ]}
              >
                {stats?.win_rate != null ? `${stats.win_rate}%` : "—"}
              </Text>
            </View>

            <View style={styles.statBox}>
              <Text style={styles.statLabel}>EXPECTANCY</Text>
              <Text style={[styles.statVal, { color: theme.colors.accent }]}>
                {stats?.expectancy_r != null ? `${stats.expectancy_r > 0 ? "+" : ""}${stats.expectancy_r}R` : "—"}
              </Text>
            </View>

            <View style={styles.statBox}>
              <Text style={styles.statLabel}>LIVE CALLS</Text>
              <Text style={[styles.statVal, { color: theme.colors.text }]}>{shownCount}</Text>
            </View>
          </View>
        </View>

        <View style={styles.filterRow}>
          {renderFilterBtn("ALL", "ALL")}
          {renderFilterBtn("MCX", "🛢️ CRUDE / GAS")}
          {renderFilterBtn("STOCKS", "📈 STOCKS")}
        </View>

        {showMcx &&
          mcxCalls.map(({ label, sig, live }) => {
            if (!live || !sig) {
              return (
                <View key={label} style={styles.emptyCard}>
                  <Text style={styles.emptyText}>{label}: no active setup right now.</Text>
                </View>
              );
            }
            const isBuy = sig.srv_signal === "BUY";
            const dirColor = isBuy ? theme.colors.green : theme.colors.red;
            const dirBg = isBuy ? theme.colors.greenBg : theme.colors.redBg;
            return (
              <View key={label} style={styles.tradeCard}>
                <View style={styles.tradeTop}>
                  <View style={styles.symbolRow}>
                    <View style={[styles.dirTag, { backgroundColor: dirBg, borderColor: dirColor }]}>
                      <Text style={[styles.dirText, { color: dirColor }]}>{sig.srv_signal}</Text>
                    </View>
                    <View>
                      <Text style={styles.symbolTitle}>{label}</Text>
                      {!!sig.srv_setup && <Text style={styles.setupText}>{sig.srv_setup}</Text>}
                    </View>
                  </View>
                  {!!sig.srv_rr && (
                    <View style={styles.rrBadge}>
                      <Text style={styles.rrText}>R:R 1:{Number(sig.srv_rr).toFixed(1)}</Text>
                    </View>
                  )}
                </View>
                <View style={styles.levelsGrid}>
                  <View style={styles.lvlBox}>
                    <Text style={styles.lvlLabel}>ENTRY</Text>
                    <Text style={styles.lvlVal}>₹{formatPrice(sig.srv_entry)}</Text>
                  </View>
                  <View style={styles.lvlBox}>
                    <Text style={styles.lvlLabel}>STOP LOSS</Text>
                    <Text style={[styles.lvlVal, { color: theme.colors.red }]}>₹{formatPrice(sig.srv_stop)}</Text>
                  </View>
                  <View style={styles.lvlBox}>
                    <Text style={styles.lvlLabel}>TARGET 1</Text>
                    <Text style={[styles.lvlVal, { color: theme.colors.green }]}>₹{formatPrice(sig.srv_target1)}</Text>
                  </View>
                </View>
              </View>
            );
          })}

        {showStocks && stockCalls.length === 0 && (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyText}>
              {screener
                ? "No intraday stock momentum picks qualify right now."
                : "Stock picks unavailable — server has not returned a scan yet."}
            </Text>
          </View>
        )}

        {showStocks &&
          stockCalls.map((p, i) => {
            const isBuy = p.side === "BUY";
            const dirColor = isBuy ? theme.colors.green : theme.colors.red;
            const dirBg = isBuy ? theme.colors.greenBg : theme.colors.redBg;
            const chg = typeof p.day_chg_pct === "number" ? p.day_chg_pct : null;
            return (
              <View key={`${p.side}-${p.symbol}-${i}`} style={styles.tradeCard}>
                <View style={styles.tradeTop}>
                  <View style={styles.symbolRow}>
                    <View style={[styles.dirTag, { backgroundColor: dirBg, borderColor: dirColor }]}>
                      <Text style={[styles.dirText, { color: dirColor }]}>{p.side}</Text>
                    </View>
                    <View>
                      <Text style={styles.symbolTitle}>{p.symbol}</Text>
                      {!!p.name && <Text style={styles.setupText}>{p.name}</Text>}
                    </View>
                  </View>
                  {typeof p.intraday_score === "number" && (
                    <View style={styles.rrBadge}>
                      <Text style={styles.rrText}>SCORE {p.intraday_score.toFixed(0)}</Text>
                    </View>
                  )}
                </View>
                <View style={styles.levelsGrid}>
                  <View style={styles.lvlBox}>
                    <Text style={styles.lvlLabel}>LTP</Text>
                    <Text style={styles.lvlVal}>₹{formatPrice(p.ltp)}</Text>
                  </View>
                  <View style={styles.lvlBox}>
                    <Text style={styles.lvlLabel}>DAY CHG</Text>
                    <Text style={[styles.lvlVal, { color: chg === null || chg >= 0 ? theme.colors.green : theme.colors.red }]}>
                      {chg === null ? "—" : `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`}
                    </Text>
                  </View>
                </View>
                {!!p.rationale && <Text style={styles.setupText}>{p.rationale}</Text>}
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
  },
  statsCard: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.lg,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
    marginBottom: theme.spacing.lg,
  },
  cardHeader: {
    fontSize: 11,
    fontWeight: "800",
    color: theme.colors.textMuted,
    letterSpacing: 0.8,
    marginBottom: theme.spacing.md,
  },
  statsGrid: {
    flexDirection: "row",
    gap: 8,
  },
  statBox: {
    flex: 1,
    backgroundColor: theme.colors.surfaceLight,
    padding: 10,
    borderRadius: theme.radius.md,
    alignItems: "center",
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  statLabel: {
    fontSize: 9,
    fontWeight: "700",
    color: theme.colors.textDim,
    marginBottom: 4,
  },
  statVal: {
    fontSize: 16,
    fontWeight: "800",
    color: theme.colors.text,
  },
  filterRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: theme.spacing.lg,
  },
  filterBtn: {
    flex: 1,
    backgroundColor: theme.colors.surface,
    paddingVertical: 9,
    borderRadius: theme.radius.md,
    alignItems: "center",
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  filterBtnActive: {
    backgroundColor: theme.colors.primary,
    borderColor: theme.colors.primary,
  },
  filterBtnText: {
    fontSize: 10,
    fontWeight: "800",
    color: theme.colors.textDim,
    letterSpacing: 0.3,
  },
  filterBtnTextActive: {
    color: "#fff",
  },
  tradeCard: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.lg,
    marginBottom: theme.spacing.md,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  tradeTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: theme.spacing.md,
  },
  symbolRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  dirTag: {
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
  },
  dirText: {
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 0.5,
  },
  symbolTitle: {
    fontSize: 16,
    fontWeight: "800",
    color: theme.colors.text,
  },
  setupText: {
    fontSize: 11,
    color: theme.colors.textMuted,
    marginTop: 2,
  },
  rrBadge: {
    backgroundColor: "rgba(99, 102, 241, 0.15)",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
    borderColor: theme.colors.primaryGlow,
  },
  rrText: {
    fontSize: 11,
    fontWeight: "800",
    color: theme.colors.accent,
  },
  levelsGrid: {
    flexDirection: "row",
    gap: 8,
    backgroundColor: theme.colors.surfaceLight,
    padding: 10,
    borderRadius: theme.radius.md,
  },
  lvlBox: {
    flex: 1,
    alignItems: "center",
  },
  lvlLabel: {
    fontSize: 8,
    fontWeight: "800",
    color: theme.colors.textDim,
    marginBottom: 3,
  },
  lvlVal: {
    fontSize: 13,
    fontWeight: "800",
    color: theme.colors.text,
  },
  emptyCard: {
    padding: 40,
    alignItems: "center",
  },
  emptyText: {
    color: theme.colors.textDim,
    fontSize: 13,
  },
});
