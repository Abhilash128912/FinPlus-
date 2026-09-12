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
import { fetchScreenerAll, ScreenerAllResponse, StockPick } from "../api";
import { Header } from "../components/Header";
import { SignalBadge } from "../components/SignalBadge";

type FilterKey = "INTRADAY" | "SWING" | "LONGTERM" | "PENNY";

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "INTRADAY", label: "🎯 INTRADAY" },
  { key: "SWING", label: "📊 SWING" },
  { key: "LONGTERM", label: "🏦 LONG-TERM" },
  { key: "PENNY", label: "🪙 PENNY" },
];

const formatPrice = (val?: number) => {
  if (val === undefined || val === null || isNaN(val)) return "—";
  return val.toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
};

const pickDirection = (p: StockPick): "BUY" | "SELL" | undefined => {
  if (p.direction) return p.direction;
  if (p.srv_signal === "BUY" || p.srv_signal === "SELL") return p.srv_signal;
  if (p.swing_action?.toUpperCase().includes("SELL")) return "SELL";
  if (p.swing_action || p.status_badge?.includes("BUY")) return "BUY";
  return undefined;
};

const pickScore = (p: StockPick): number | undefined =>
  p.intraday_score ?? p.swing_score ?? p.total_score;

const pickEntry = (p: StockPick) => p.srv_entry ?? p.ltp;
const pickStop = (p: StockPick) => p.srv_stop ?? p.stop_loss ?? p.gtt_pullback_level;
const pickTarget = (p: StockPick) => p.srv_target1 ?? p.target1 ?? p.gtt_breakout_level;
const pickReason = (p: StockPick) => p.srv_reason ?? p.rationale ?? p.status_badge ?? p.srv_setup;

const StockCard: React.FC<{ pick: StockPick }> = ({ pick }) => {
  const dir = pickDirection(pick);
  const isBuy = dir !== "SELL";
  const dirColor = dir ? (isBuy ? theme.colors.green : theme.colors.red) : theme.colors.textDim;
  const score = pickScore(pick);
  const entry = pickEntry(pick);
  const stop = pickStop(pick);
  const target = pickTarget(pick);
  const reason = pickReason(pick);

  return (
    <View style={styles.card}>
      <View style={styles.cardTop}>
        <View>
          <Text style={styles.symbol}>{pick.symbol}</Text>
          {pick.name ? <Text style={styles.name}>{pick.name}</Text> : null}
        </View>
        <View style={styles.cardTopRight}>
          <Text style={styles.ltp}>₹{formatPrice(pick.ltp)}</Text>
          {pick.day_chg_pct != null && (
            <Text style={[styles.chg, { color: pick.day_chg_pct >= 0 ? theme.colors.green : theme.colors.red }]}>
              {pick.day_chg_pct >= 0 ? "▲ +" : "▼ "}
              {pick.day_chg_pct.toFixed(2)}%
            </Text>
          )}
        </View>
      </View>

      <View style={styles.badgeRow}>
        {dir && <SignalBadge signal={dir} size="sm" />}
        {score != null && (
          <View style={styles.scoreBadge}>
            <Text style={styles.scoreText}>SCORE {Math.round(score)}</Text>
          </View>
        )}
      </View>

      {(entry != null || stop != null || target != null) && (
        <View style={styles.levelsGrid}>
          <View style={styles.lvlBox}>
            <Text style={styles.lvlLabel}>ENTRY</Text>
            <Text style={styles.lvlVal}>₹{formatPrice(entry)}</Text>
          </View>
          <View style={styles.lvlBox}>
            <Text style={styles.lvlLabel}>STOP</Text>
            <Text style={[styles.lvlVal, { color: theme.colors.red }]}>₹{formatPrice(stop)}</Text>
          </View>
          <View style={styles.lvlBox}>
            <Text style={styles.lvlLabel}>TARGET</Text>
            <Text style={[styles.lvlVal, { color: theme.colors.green }]}>₹{formatPrice(target)}</Text>
          </View>
        </View>
      )}

      {reason ? <Text style={styles.reason}>💡 {reason}</Text> : null}
    </View>
  );
};

export const ScreenerScreen: React.FC = () => {
  const [data, setData] = useState<ScreenerAllResponse | null>(null);
  const [filter, setFilter] = useState<FilterKey>("INTRADAY");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setError(null);
      const res = await fetchScreenerAll();
      setData(res);
    } catch (e: any) {
      setData(null);
      setError(
        e.message?.includes("Abort") || e.name === "AbortError"
          ? "Stock scanner unreachable — connect to your PC/Render backend in Settings (⚙️) to see real picks."
          : e.message || "Failed to load stock suggestions"
      );
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
      if (AppState.currentState === "active") loadData();
    }, 30000);
    return () => clearInterval(timer);
  }, []);

  let buyPicks: StockPick[] = [];
  let sellPicks: StockPick[] = [];
  let watchPicks: StockPick[] = [];
  let qualifiedNote = "";

  if (data) {
    if (filter === "INTRADAY" && data.momentum) {
      buyPicks = data.momentum.buy || [];
      sellPicks = data.momentum.sell || [];
      qualifiedNote = `${data.momentum.buy_qualified ?? 0} buy / ${data.momentum.sell_qualified ?? 0} sell qualified today`;
    } else if (filter === "SWING" && data.swing) {
      buyPicks = data.swing.picks || [];
      qualifiedNote = `${data.swing.qualified_count ?? 0} of ${data.swing.total_candidates ?? 0} candidates qualified`;
    } else if (filter === "LONGTERM" && data.lt) {
      buyPicks = data.lt.top_challengers || [];
      watchPicks = data.lt.watchlist || [];
      qualifiedNote = `${data.lt.total_scanned ?? 0} stocks scanned`;
    } else if (filter === "PENNY" && data.penny) {
      buyPicks = data.penny.picks || [];
      qualifiedNote = `${data.penny.qualified_count ?? 0} of ${data.penny.total_evaluated ?? 0} evaluated`;
    }
  }

  const totalShown = buyPicks.length + sellPicks.length + watchPicks.length;

  return (
    <View style={styles.container}>
      <Header onRefresh={onRefresh} isRefreshing={isRefreshing} />

      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={isRefreshing} onRefresh={onRefresh} tintColor={theme.colors.accent} />
        }
      >
        {error && (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>⚠ {error}</Text>
          </View>
        )}

        <View style={styles.filterRow}>
          {FILTERS.map((f) => (
            <TouchableOpacity
              key={f.key}
              style={[styles.filterBtn, filter === f.key && styles.filterBtnActive]}
              onPress={() => setFilter(f.key)}
            >
              <Text style={[styles.filterBtnText, filter === f.key && styles.filterBtnTextActive]}>
                {f.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {qualifiedNote ? <Text style={styles.qualifiedNote}>{qualifiedNote}</Text> : null}

        {totalShown === 0 && !error ? (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyText}>
              No {FILTERS.find((f) => f.key === filter)?.label.split(" ")[1].toLowerCase()} picks qualify right now.
            </Text>
          </View>
        ) : (
          <>
            {sellPicks.length > 0 && (
              <>
                <Text style={styles.sectionLabel}>SELL / SHORT</Text>
                {sellPicks.map((p, i) => (
                  <StockCard key={`sell-${p.symbol}-${i}`} pick={p} />
                ))}
              </>
            )}
            {buyPicks.length > 0 && (
              <>
                <Text style={styles.sectionLabel}>
                  {filter === "LONGTERM" ? "TOP CHALLENGERS" : "BUY / LONG"}
                </Text>
                {buyPicks.map((p, i) => (
                  <StockCard key={`buy-${p.symbol}-${i}`} pick={p} />
                ))}
              </>
            )}
            {watchPicks.length > 0 && (
              <>
                <Text style={styles.sectionLabel}>WATCHLIST</Text>
                {watchPicks.map((p, i) => (
                  <StockCard key={`watch-${p.symbol}-${i}`} pick={p} />
                ))}
              </>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.bg },
  scrollContent: { padding: theme.spacing.lg, paddingBottom: 40 },
  errorBox: {
    backgroundColor: theme.colors.redBg,
    borderColor: theme.colors.redBorder,
    borderWidth: 1,
    padding: theme.spacing.md,
    borderRadius: theme.radius.md,
    marginBottom: theme.spacing.md,
  },
  errorText: { color: theme.colors.red, fontSize: 12 },
  filterRow: { flexDirection: "row", gap: 6, marginBottom: theme.spacing.md, flexWrap: "wrap" },
  filterBtn: {
    flexGrow: 1,
    backgroundColor: theme.colors.surface,
    paddingVertical: 9,
    borderRadius: theme.radius.md,
    alignItems: "center",
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  filterBtnActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  filterBtnText: { fontSize: 10, fontWeight: "800", color: theme.colors.textDim, letterSpacing: 0.3 },
  filterBtnTextActive: { color: "#fff" },
  qualifiedNote: {
    fontSize: 10,
    color: theme.colors.textDim,
    marginBottom: theme.spacing.md,
    fontWeight: "600",
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: "800",
    color: theme.colors.textMuted,
    letterSpacing: 0.8,
    marginBottom: theme.spacing.sm,
    marginTop: theme.spacing.sm,
  },
  emptyCard: { padding: 40, alignItems: "center" },
  emptyText: { color: theme.colors.textDim, fontSize: 13, textAlign: "center" },
  card: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.lg,
    marginBottom: theme.spacing.md,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  cardTopRight: { alignItems: "flex-end" },
  symbol: { fontSize: 15, fontWeight: "800", color: theme.colors.text },
  name: { fontSize: 11, color: theme.colors.textMuted, marginTop: 2, maxWidth: 200 },
  ltp: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  chg: { fontSize: 11, fontWeight: "800", marginTop: 2 },
  badgeRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: theme.spacing.sm },
  scoreBadge: {
    backgroundColor: "rgba(99, 102, 241, 0.15)",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
    borderColor: theme.colors.primaryGlow,
  },
  scoreText: { fontSize: 10, fontWeight: "800", color: theme.colors.accent },
  levelsGrid: {
    flexDirection: "row",
    gap: 8,
    backgroundColor: theme.colors.surfaceLight,
    padding: 10,
    borderRadius: theme.radius.md,
    marginTop: theme.spacing.sm,
  },
  lvlBox: { flex: 1, alignItems: "center" },
  lvlLabel: { fontSize: 8, fontWeight: "800", color: theme.colors.textDim, marginBottom: 3 },
  lvlVal: { fontSize: 12, fontWeight: "800", color: theme.colors.text },
  reason: {
    fontSize: 11,
    color: theme.colors.accent,
    marginTop: theme.spacing.sm,
    lineHeight: 16,
  },
});
