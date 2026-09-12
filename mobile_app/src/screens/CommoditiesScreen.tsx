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
import { fetchCommodities, CommoditiesResponse } from "../api";
import { SignalBadge } from "../components/SignalBadge";
import { MiniSparkline } from "../components/MiniSparkline";

export const CommoditiesScreen: React.FC = () => {
  const [data, setData] = useState<CommoditiesResponse | null>(null);
  const [activeTab, setActiveTab] = useState<"crude" | "natgas">("crude");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setError(null);
      const res = await fetchCommodities();
      setData(res);
    } catch (e: any) {
      setError(e.message || "Failed to load commodities data");
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, []);

  const onRefresh = async () => {
    setIsRefreshing(true);
    await loadData();
    setIsRefreshing(false);
  };

  const activeData = activeTab === "crude" ? data?.crude : data?.natgas;
  const sig = activeData?.signal;
  const ltp = activeData?.ltp || sig?.live_ltp;
  const change = activeData?.change || sig?.change || 0;
  const isUp = change >= 0;

  return (
    <View style={styles.container}>
      {/* Top Commodity Switcher */}
      <View style={styles.tabSelector}>
        <TouchableOpacity
          style={[styles.tabBtn, activeTab === "crude" && styles.tabBtnActive]}
          onPress={() => setActiveTab("crude")}
        >
          <Text
            style={[
              styles.tabBtnText,
              activeTab === "crude" && styles.tabBtnTextActive,
            ]}
          >
            🛢️ CRUDE OIL (MCX)
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tabBtn, activeTab === "natgas" && styles.tabBtnActive]}
          onPress={() => setActiveTab("natgas")}
        >
          <Text
            style={[
              styles.tabBtnText,
              activeTab === "natgas" && styles.tabBtnTextActive,
            ]}
          >
            ⚡ NATURAL GAS (MCX)
          </Text>
        </TouchableOpacity>
      </View>

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

        {/* Hero Price Tile */}
        <View style={styles.heroCard}>
          <View style={styles.heroTop}>
            <View>
              <Text style={styles.heroTitle}>
                {activeTab === "crude" ? "CRUDEOIL FUTURES" : "NATURALGAS FUTURES"}
              </Text>
              <Text style={styles.heroSub}>MCX Front-Month Contract</Text>
            </View>
            <SignalBadge
              signal={sig?.srv_signal || "NONE"}
              setup={sig?.srv_setup}
            />
          </View>

          <View style={styles.heroPriceRow}>
            <Text style={styles.heroLtp}>
              ₹{ltp ? ltp.toLocaleString("en-IN") : "—"}
            </Text>
            <View
              style={[
                styles.heroChangeBadge,
                { backgroundColor: isUp ? theme.colors.greenBg : theme.colors.redBg },
              ]}
            >
              <Text
                style={[
                  styles.heroChangeText,
                  { color: isUp ? theme.colors.green : theme.colors.red },
                ]}
              >
                {isUp ? "+" : ""}
                {change ? change.toFixed(2) : "0.00"}%
              </Text>
            </View>
          </View>

          <View style={styles.heroSparkWrap}>
            <MiniSparkline
              data={activeData?.spark || []}
              height={32}
              width={260}
            />
          </View>
        </View>

        {/* Trade Setup Levels */}
        <View style={styles.levelsCard}>
          <Text style={styles.cardHeader}>TRADE SETUP LEVELS (1H PIVOTS)</Text>
          <View style={styles.grid2x2}>
            <View style={styles.levelBox}>
              <Text style={styles.levelLabel}>ENTRY LEVEL</Text>
              <Text style={styles.levelVal}>
                ₹{sig?.srv_entry ? sig.srv_entry.toFixed(1) : "—"}
              </Text>
            </View>
            <View style={styles.levelBox}>
              <Text style={styles.levelLabel}>STOP LOSS</Text>
              <Text style={[styles.levelVal, { color: theme.colors.red }]}>
                ₹{sig?.srv_stop ? sig.srv_stop.toFixed(1) : "—"}
              </Text>
            </View>
            <View style={styles.levelBox}>
              <Text style={styles.levelLabel}>TARGET 1</Text>
              <Text style={[styles.levelVal, { color: theme.colors.green }]}>
                ₹{sig?.srv_target1 ? sig.srv_target1.toFixed(1) : "—"}
              </Text>
            </View>
            <View style={styles.levelBox}>
              <Text style={styles.levelLabel}>TARGET 2</Text>
              <Text style={[styles.levelVal, { color: theme.colors.green }]}>
                ₹{sig?.srv_target2 ? sig.srv_target2.toFixed(1) : "—"}
              </Text>
            </View>
          </View>

          {sig?.srv_reason && (
            <View style={styles.reasonBox}>
              <Text style={styles.reasonText}>💡 {sig.srv_reason}</Text>
            </View>
          )}
        </View>

        {/* Recent MCX 3-min Sampling Bars */}
        <View style={styles.barsCard}>
          <Text style={styles.cardHeader}>RECENT MCX SAMPLING (3M BARS)</Text>
          {(!activeData?.bars || activeData.bars.length === 0) ? (
            <Text style={styles.emptyText}>Recording MCX bars during active market hours...</Text>
          ) : (
            <View style={styles.barsTable}>
              <View style={styles.barsTableRowHeader}>
                <Text style={[styles.barCol, styles.barColTime]}>TIME</Text>
                <Text style={styles.barCol}>CLOSE</Text>
                <Text style={styles.barCol}>HIGH</Text>
                <Text style={styles.barCol}>LOW</Text>
              </View>
              {activeData.bars.slice(-8).reverse().map((b: any, idx: number) => (
                <View key={idx} style={styles.barsTableRow}>
                  <Text style={[styles.barCol, styles.barColTime]}>
                    {b.timestamp ? b.timestamp.slice(11, 16) : `T-${idx}`}
                  </Text>
                  <Text style={[styles.barCol, styles.barColBold]}>
                    ₹{b.close || b.c || "—"}
                  </Text>
                  <Text style={styles.barCol}>₹{b.high || b.h || "—"}</Text>
                  <Text style={styles.barCol}>₹{b.low || b.l || "—"}</Text>
                </View>
              ))}
            </View>
          )}
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.bg,
  },
  tabSelector: {
    flexDirection: "row",
    backgroundColor: theme.colors.surface,
    padding: theme.spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.surfaceBorder,
    gap: 8,
  },
  tabBtn: {
    flex: 1,
    paddingVertical: 10,
    alignItems: "center",
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.surfaceLight,
  },
  tabBtnActive: {
    backgroundColor: theme.colors.primary,
  },
  tabBtnText: {
    fontSize: 12,
    fontWeight: "700",
    color: theme.colors.textMuted,
  },
  tabBtnTextActive: {
    color: "#fff",
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
  heroCard: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.xl,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
    marginBottom: theme.spacing.lg,
  },
  heroTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: theme.spacing.md,
  },
  heroTitle: {
    fontSize: 16,
    fontWeight: "800",
    color: theme.colors.text,
  },
  heroSub: {
    fontSize: 11,
    color: theme.colors.textMuted,
    marginTop: 2,
  },
  heroPriceRow: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 12,
    marginBottom: theme.spacing.md,
  },
  heroLtp: {
    fontSize: 28,
    fontWeight: "900",
    color: theme.colors.text,
  },
  heroChangeBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: theme.radius.sm,
  },
  heroChangeText: {
    fontSize: 13,
    fontWeight: "800",
  },
  heroSparkWrap: {
    alignItems: "center",
    marginTop: theme.spacing.sm,
  },
  levelsCard: {
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
  grid2x2: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
  },
  levelBox: {
    flex: 1,
    minWidth: "45%",
    backgroundColor: theme.colors.surfaceLight,
    padding: theme.spacing.md,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  levelLabel: {
    fontSize: 10,
    fontWeight: "700",
    color: theme.colors.textDim,
    marginBottom: 4,
  },
  levelVal: {
    fontSize: 16,
    fontWeight: "800",
    color: theme.colors.text,
  },
  reasonBox: {
    marginTop: theme.spacing.md,
    backgroundColor: "rgba(99, 102, 241, 0.08)",
    padding: theme.spacing.md,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.primaryGlow,
  },
  reasonText: {
    fontSize: 12,
    color: theme.colors.accent,
    lineHeight: 18,
  },
  barsCard: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.lg,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  emptyText: {
    fontSize: 12,
    color: theme.colors.textDim,
    paddingVertical: 10,
  },
  barsTable: {
    marginTop: 4,
  },
  barsTableRowHeader: {
    flexDirection: "row",
    paddingBottom: 6,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.surfaceBorder,
  },
  barsTableRow: {
    flexDirection: "row",
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "rgba(255,255,255,0.04)",
  },
  barCol: {
    flex: 1,
    fontSize: 12,
    color: theme.colors.textMuted,
    textAlign: "right",
  },
  barColTime: {
    textAlign: "left",
    color: theme.colors.textDim,
  },
  barColBold: {
    fontWeight: "700",
    color: theme.colors.text,
  },
});
