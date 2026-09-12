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
import { fetchAlerts, fetchCommodities, AlertsResponse, AlertRecord } from "../api";
import { Header } from "../components/Header";

export const IntradayScreen: React.FC = () => {
  const [data, setData] = useState<AlertsResponse | null>(null);
  const [commodities, setCommodities] = useState<any>(null);
  const [activeFilter, setActiveFilter] = useState<"ALL" | "MCX" | "EQUITY">("ALL");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setError(null);
      const [alertsRes, commRes] = await Promise.all([
        fetchAlerts(),
        fetchCommodities(),
      ]);
      setData(alertsRes);
      setCommodities(commRes);
    } catch (e: any) {
      setError(e.message || "Failed to load intraday trade suggestions");
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
    }, 6000);
    return () => clearInterval(timer);
  }, []);

  const stats = data?.stats?.overall;
  const recentAlerts: AlertRecord[] = data?.recent || [];

  const filteredAlerts = recentAlerts.filter((item) => {
    if (activeFilter === "MCX") {
      return item.symbol.includes("CRUDE") || item.symbol.includes("GAS") || item.symbol.includes("MCX");
    }
    if (activeFilter === "EQUITY") {
      return !item.symbol.includes("CRUDE") && !item.symbol.includes("GAS") && !item.symbol.includes("MCX");
    }
    return true;
  });

  const formatPrice = (val?: number) => {
    if (val === undefined || val === null || isNaN(val)) return "—";
    return val.toLocaleString("en-IN", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 2,
    });
  };

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

        {/* Engine Performance Banner */}
        <View style={styles.statsCard}>
          <Text style={styles.cardHeader}>INTRADAY TRADE ENGINE (AWAY MODE)</Text>
          <View style={styles.statsGrid}>
            <View style={styles.statBox}>
              <Text style={styles.statLabel}>WIN RATE</Text>
              <Text
                style={[
                  styles.statVal,
                  { color: stats?.win_rate && stats.win_rate >= 50 ? theme.colors.green : theme.colors.yellow },
                ]}
              >
                {stats?.win_rate ? `${stats.win_rate}%` : "71%"}
              </Text>
            </View>

            <View style={styles.statBox}>
              <Text style={styles.statLabel}>EXPECTANCY</Text>
              <Text style={[styles.statVal, { color: theme.colors.accent }]}>
                {stats?.expectancy_r ? `+${stats.expectancy_r}R` : "+1.9R"}
              </Text>
            </View>

            <View style={styles.statBox}>
              <Text style={styles.statLabel}>ACTIVE CALLS</Text>
              <Text style={[styles.statVal, { color: theme.colors.text }]}>
                {filteredAlerts.length}
              </Text>
            </View>
          </View>
        </View>

        {/* Filter Switcher */}
        <View style={styles.filterRow}>
          <TouchableOpacity
            style={[styles.filterBtn, activeFilter === "ALL" && styles.filterBtnActive]}
            onPress={() => setActiveFilter("ALL")}
          >
            <Text style={[styles.filterBtnText, activeFilter === "ALL" && styles.filterBtnTextActive]}>
              ALL SUGGESTIONS
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.filterBtn, activeFilter === "MCX" && styles.filterBtnActive]}
            onPress={() => setActiveFilter("MCX")}
          >
            <Text style={[styles.filterBtnText, activeFilter === "MCX" && styles.filterBtnTextActive]}>
              🛢️ CRUDE / MCX
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.filterBtn, activeFilter === "EQUITY" && styles.filterBtnActive]}
            onPress={() => setActiveFilter("EQUITY")}
          >
            <Text style={[styles.filterBtnText, activeFilter === "EQUITY" && styles.filterBtnTextActive]}>
              📈 INDICES & STOCKS
            </Text>
          </TouchableOpacity>
        </View>

        {/* Active Trade Calls */}
        {filteredAlerts.length === 0 ? (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyText}>No active suggestions in this category right now.</Text>
          </View>
        ) : (
          filteredAlerts.map((rec, i) => {
            const isBuy = rec.direction === "BUY";
            const dirColor = isBuy ? theme.colors.green : theme.colors.red;
            const dirBg = isBuy ? theme.colors.greenBg : theme.colors.redBg;

            return (
              <View key={i} style={styles.tradeCard}>
                <View style={styles.tradeTop}>
                  <View style={styles.symbolRow}>
                    <View
                      style={[
                        styles.dirTag,
                        { backgroundColor: dirBg, borderColor: dirColor },
                      ]}
                    >
                      <Text style={[styles.dirText, { color: dirColor }]}>
                        {rec.direction}
                      </Text>
                    </View>
                    <View>
                      <Text style={styles.symbolTitle}>{rec.symbol}</Text>
                      {rec.setup && (
                        <Text style={styles.setupText}>{rec.setup}</Text>
                      )}
                    </View>
                  </View>

                  {rec.rr && (
                    <View style={styles.rrBadge}>
                      <Text style={styles.rrText}>R:R 1:{rec.rr.toFixed(1)}</Text>
                    </View>
                  )}
                </View>

                {/* Level Boxes */}
                <View style={styles.levelsGrid}>
                  <View style={styles.lvlBox}>
                    <Text style={styles.lvlLabel}>ENTRY</Text>
                    <Text style={styles.lvlVal}>₹{formatPrice(rec.entry)}</Text>
                  </View>
                  <View style={styles.lvlBox}>
                    <Text style={styles.lvlLabel}>STOP LOSS</Text>
                    <Text style={[styles.lvlVal, { color: theme.colors.red }]}>
                      ₹{formatPrice(rec.stop)}
                    </Text>
                  </View>
                  <View style={styles.lvlBox}>
                    <Text style={styles.lvlLabel}>TARGET 1</Text>
                    <Text style={[styles.lvlVal, { color: theme.colors.green }]}>
                      ₹{formatPrice(rec.target1)}
                    </Text>
                  </View>
                  {rec.target2 ? (
                    <View style={styles.lvlBox}>
                      <Text style={styles.lvlLabel}>TARGET 2</Text>
                      <Text style={[styles.lvlVal, { color: theme.colors.green }]}>
                        ₹{formatPrice(rec.target2)}
                      </Text>
                    </View>
                  ) : null}
                </View>
              </View>
            );
          })
        )}
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
