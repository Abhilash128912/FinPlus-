import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  TouchableOpacity,
} from "react-native";
import { theme } from "../theme";
import { fetchAlerts, AlertsResponse, AlertRecord } from "../api";

export const AlertsScreen: React.FC = () => {
  const [data, setData] = useState<AlertsResponse | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAlerts = async () => {
    try {
      setError(null);
      const res = await fetchAlerts();
      setData(res);
    } catch (e: any) {
      setError(e.message || "Failed to load signal alerts");
    }
  };

  useEffect(() => {
    loadAlerts();
  }, []);

  const onRefresh = async () => {
    setIsRefreshing(true);
    await loadAlerts();
    setIsRefreshing(false);
  };

  const stats = data?.stats?.overall;
  const recentAlerts: AlertRecord[] = data?.recent || [];

  const getOutcomeBadge = (outcome: string) => {
    if (outcome === "target") {
      return { label: "WIN / TARGET", color: theme.colors.green, bg: theme.colors.greenBg };
    }
    if (outcome === "stop") {
      return { label: "STOP HIT", color: theme.colors.red, bg: theme.colors.redBg };
    }
    return { label: "OPEN TRADE", color: theme.colors.accent, bg: theme.colors.primaryGlow };
  };

  return (
    <View style={styles.container}>
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

        {/* Statistical Performance Hero */}
        <View style={styles.statsCard}>
          <Text style={styles.cardHeader}>SIGNAL ENGINE PERFORMANCE (JOURNAL)</Text>
          <View style={styles.statsGrid}>
            <View style={styles.statBox}>
              <Text style={styles.statLabel}>WIN RATE</Text>
              <Text
                style={[
                  styles.statVal,
                  { color: stats?.win_rate && stats.win_rate >= 50 ? theme.colors.green : theme.colors.yellow },
                ]}
              >
                {stats?.win_rate !== null && stats?.win_rate !== undefined
                  ? `${stats.win_rate}%`
                  : "—"}
              </Text>
            </View>

            <View style={styles.statBox}>
              <Text style={styles.statLabel}>EXPECTANCY (R)</Text>
              <Text style={[styles.statVal, { color: theme.colors.accent }]}>
                {stats?.expectancy_r !== null && stats?.expectancy_r !== undefined
                  ? `${stats.expectancy_r > 0 ? "+" : ""}${stats.expectancy_r} R`
                  : "—"}
              </Text>
            </View>

            <View style={styles.statBox}>
              <Text style={styles.statLabel}>RESOLVED</Text>
              <Text style={styles.statVal}>{stats?.resolved ?? 0}</Text>
            </View>

            <View style={styles.statBox}>
              <Text style={styles.statLabel}>OPEN SETUPS</Text>
              <Text style={[styles.statVal, { color: theme.colors.purple }]}>
                {stats?.open ?? 0}
              </Text>
            </View>
          </View>
        </View>

        {/* Recent Signal Triggers */}
        <Text style={styles.sectionTitle}>RECENT SIGNAL LOGS</Text>

        {recentAlerts.length === 0 ? (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyText}>No signal history recorded in journal yet.</Text>
          </View>
        ) : (
          recentAlerts.map((rec, i) => {
            const badge = getOutcomeBadge(rec.outcome);
            const isBuy = rec.direction === "BUY";

            return (
              <View key={i} style={styles.alertCard}>
                <View style={styles.alertTop}>
                  <View style={styles.symbolRow}>
                    <View
                      style={[
                        styles.dirTag,
                        {
                          backgroundColor: isBuy ? theme.colors.greenBg : theme.colors.redBg,
                          borderColor: isBuy ? theme.colors.greenBorder : theme.colors.redBorder,
                        },
                      ]}
                    >
                      <Text
                        style={[
                          styles.dirText,
                          { color: isBuy ? theme.colors.green : theme.colors.red },
                        ]}
                      >
                        {rec.direction}
                      </Text>
                    </View>
                    <Text style={styles.symbolText}>{rec.symbol}</Text>
                  </View>

                  <View
                    style={[
                      styles.outcomeBadge,
                      { backgroundColor: badge.bg, borderColor: badge.color },
                    ]}
                  >
                    <Text style={[styles.outcomeText, { color: badge.color }]}>
                      {badge.label}
                    </Text>
                  </View>
                </View>

                {rec.setup && (
                  <Text style={styles.setupText}>Setup: {rec.setup}</Text>
                )}

                <View style={styles.levelsRow}>
                  <View style={styles.lvlItem}>
                    <Text style={styles.lvlLabel}>ENTRY</Text>
                    <Text style={styles.lvlVal}>₹{rec.entry}</Text>
                  </View>
                  <View style={styles.lvlItem}>
                    <Text style={styles.lvlLabel}>STOP</Text>
                    <Text style={[styles.lvlVal, { color: theme.colors.red }]}>
                      ₹{rec.stop}
                    </Text>
                  </View>
                  <View style={styles.lvlItem}>
                    <Text style={styles.lvlLabel}>TARGET 1</Text>
                    <Text style={[styles.lvlVal, { color: theme.colors.green }]}>
                      ₹{rec.target1}
                    </Text>
                  </View>
                </View>

                <View style={styles.cardFooter}>
                  <Text style={styles.timeText}>
                    Triggered: {rec.opened_at ? rec.opened_at.slice(0, 16).replace("T", " ") : "—"}
                  </Text>
                  {rec.rr && (
                    <Text style={styles.rrText}>R:R {rec.rr.toFixed(1)}</Text>
                  )}
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
    textAlign: "center",
  },
  statVal: {
    fontSize: 15,
    fontWeight: "800",
    color: theme.colors.text,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: theme.colors.textMuted,
    letterSpacing: 0.8,
    marginBottom: theme.spacing.md,
  },
  emptyCard: {
    padding: 30,
    alignItems: "center",
  },
  emptyText: {
    color: theme.colors.textDim,
    fontSize: 13,
  },
  alertCard: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.md,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  alertTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 6,
  },
  symbolRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  dirTag: {
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
  },
  dirText: {
    fontSize: 11,
    fontWeight: "900",
  },
  symbolText: {
    fontSize: 15,
    fontWeight: "800",
    color: theme.colors.text,
  },
  outcomeBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: theme.radius.sm,
    borderWidth: 0.5,
  },
  outcomeText: {
    fontSize: 10,
    fontWeight: "800",
  },
  setupText: {
    fontSize: 11,
    color: theme.colors.textMuted,
    marginBottom: 8,
  },
  levelsRow: {
    flexDirection: "row",
    backgroundColor: theme.colors.surfaceLight,
    padding: theme.spacing.sm,
    borderRadius: theme.radius.md,
    justifyContent: "space-around",
  },
  lvlItem: {
    alignItems: "center",
  },
  lvlLabel: {
    fontSize: 9,
    fontWeight: "700",
    color: theme.colors.textDim,
  },
  lvlVal: {
    fontSize: 13,
    fontWeight: "800",
    color: theme.colors.text,
    marginTop: 2,
  },
  cardFooter: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 8,
    paddingHorizontal: 2,
  },
  timeText: {
    fontSize: 10,
    color: theme.colors.textDim,
  },
  rrText: {
    fontSize: 10,
    fontWeight: "700",
    color: theme.colors.accent,
  },
});
