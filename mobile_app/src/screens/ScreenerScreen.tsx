import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  TouchableOpacity,
  TextInput,
} from "react-native";
import { theme } from "../theme";
import { fetchScreenerAll, ScreenerAllResponse, ScreenerItem } from "../api";
import { SignalBadge } from "../components/SignalBadge";

export const ScreenerScreen: React.FC = () => {
  const [screenerData, setScreenerData] = useState<ScreenerAllResponse | null>(null);
  const [cohort, setCohort] = useState<"swing" | "lt" | "penny" | "momentum">("swing");
  const [search, setSearch] = useState("");
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setError(null);
      const res = await fetchScreenerAll();
      setScreenerData(res);
    } catch (e: any) {
      setError(e.message || "Failed to load screener data");
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const onRefresh = async () => {
    setIsRefreshing(true);
    await loadData();
    setIsRefreshing(false);
  };

  const getPicks = (): ScreenerItem[] => {
    if (!screenerData) return [];
    if (cohort === "swing") return screenerData.swing?.picks || [];
    if (cohort === "lt") return screenerData.lt?.picks || [];
    if (cohort === "penny") return screenerData.penny?.picks || [];
    if (cohort === "momentum") {
      return (
        screenerData.momentum?.picks ||
        screenerData.momentum?.top_gainers ||
        []
      );
    }
    return [];
  };

  const allPicks = getPicks();
  const filtered = allPicks.filter(
    (p) =>
      p.symbol.toLowerCase().includes(search.toLowerCase()) ||
      (p.name && p.name.toLowerCase().includes(search.toLowerCase())) ||
      (p.sector && p.sector.toLowerCase().includes(search.toLowerCase()))
  );

  const getDvmBadgeColor = (score?: number) => {
    if (score === undefined || score === null) return theme.colors.surfaceBorder;
    if (score >= 65) return theme.colors.green;
    if (score >= 45) return theme.colors.purple;
    return theme.colors.yellow;
  };

  return (
    <View style={styles.container}>
      {/* Search Input */}
      <View style={styles.searchBar}>
        <TextInput
          style={styles.searchInput}
          placeholder="Search by symbol, company, or sector..."
          placeholderTextColor={theme.colors.textDim}
          value={search}
          onChangeText={setSearch}
          autoCapitalize="characters"
        />
        {search ? (
          <TouchableOpacity onPress={() => setSearch("")} style={styles.clearBtn}>
            <Text style={styles.clearBtnText}>✕</Text>
          </TouchableOpacity>
        ) : null}
      </View>

      {/* Cohort Tabs */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.cohortBar}
      >
        <TouchableOpacity
          style={[styles.cohortChip, cohort === "swing" && styles.cohortChipActive]}
          onPress={() => setCohort("swing")}
        >
          <Text
            style={[
              styles.cohortChipText,
              cohort === "swing" && styles.cohortChipTextActive,
            ]}
          >
            ⚡ Swing Picks ({screenerData?.swing?.picks?.length || 0})
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.cohortChip, cohort === "lt" && styles.cohortChipActive]}
          onPress={() => setCohort("lt")}
        >
          <Text
            style={[
              styles.cohortChipText,
              cohort === "lt" && styles.cohortChipTextActive,
            ]}
          >
            💎 Long Term ({screenerData?.lt?.picks?.length || 0})
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.cohortChip, cohort === "momentum" && styles.cohortChipActive]}
          onPress={() => setCohort("momentum")}
        >
          <Text
            style={[
              styles.cohortChipText,
              cohort === "momentum" && styles.cohortChipTextActive,
            ]}
          >
            🚀 Momentum ({screenerData?.momentum?.picks?.length || 0})
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.cohortChip, cohort === "penny" && styles.cohortChipActive]}
          onPress={() => setCohort("penny")}
        >
          <Text
            style={[
              styles.cohortChipText,
              cohort === "penny" && styles.cohortChipTextActive,
            ]}
          >
            🪙 Penny ({screenerData?.penny?.picks?.length || 0})
          </Text>
        </TouchableOpacity>
      </ScrollView>

      {/* Stock Cards List */}
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

        {filtered.length === 0 ? (
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyTitle}>No candidates found</Text>
            <Text style={styles.emptySub}>
              {allPicks.length === 0
                ? "Background screener engine is currently computing..."
                : "Try adjusting your search filter."}
            </Text>
          </View>
        ) : (
          filtered.map((item) => {
            const isExpanded = expandedSymbol === item.symbol;
            const dvmColor = getDvmBadgeColor(item.durability_score);

            return (
              <TouchableOpacity
                key={item.symbol}
                style={styles.card}
                activeOpacity={0.8}
                onPress={() =>
                  setExpandedSymbol(isExpanded ? null : item.symbol)
                }
              >
                <View style={styles.cardHeader}>
                  <View style={styles.symbolInfo}>
                    <Text style={styles.symbolText}>{item.symbol}</Text>
                    {item.name ? (
                      <Text style={styles.companyName} numberOfLines={1}>
                        {item.name}
                      </Text>
                    ) : null}
                  </View>

                  <View style={styles.priceCol}>
                    <Text style={styles.ltpText}>
                      ₹{item.ltp ? item.ltp.toFixed(2) : "—"}
                    </Text>
                    <Text
                      style={[
                        styles.changeText,
                        {
                          color:
                            (item.change_pct || 0) >= 0
                              ? theme.colors.green
                              : theme.colors.red,
                        },
                      ]}
                    >
                      {(item.change_pct || 0) >= 0 ? "+" : ""}
                      {item.change_pct ? item.change_pct.toFixed(2) : "0.00"}%
                    </Text>
                  </View>
                </View>

                {/* Badges & Metrics Row */}
                <View style={styles.metricsRow}>
                  {item.durability_score !== undefined && (
                    <View
                      style={[
                        styles.dvmBadge,
                        { borderColor: dvmColor, backgroundColor: "rgba(0,0,0,0.2)" },
                      ]}
                    >
                      <Text style={[styles.dvmText, { color: dvmColor }]}>
                        DVM {Math.round(item.durability_score)}
                      </Text>
                    </View>
                  )}

                  {item.signal && (
                    <SignalBadge signal={item.signal} setup={item.setup} size="sm" />
                  )}

                  {item.pe !== undefined && (
                    <Text style={styles.metricItem}>
                      P/E: <Text style={styles.metricVal}>{item.pe.toFixed(1)}</Text>
                    </Text>
                  )}

                  {item.roce !== undefined && (
                    <Text style={styles.metricItem}>
                      ROCE: <Text style={styles.metricVal}>{item.roce.toFixed(1)}%</Text>
                    </Text>
                  )}
                </View>

                {/* Expandable Details */}
                {isExpanded && (
                  <View style={styles.expandedDetails}>
                    {item.trigger_reason && (
                      <Text style={styles.reasonText}>
                        🎯 Trigger: {item.trigger_reason}
                      </Text>
                    )}
                    {item.sector && (
                      <Text style={styles.expandedMeta}>Sector: {item.sector}</Text>
                    )}
                    {item.market_cap && (
                      <Text style={styles.expandedMeta}>
                        Market Cap: ₹{(item.market_cap / 100).toFixed(0)} Cr
                      </Text>
                    )}
                    {item.source && (
                      <Text style={styles.expandedMeta}>
                        Engine Source: {item.source}
                      </Text>
                    )}
                  </View>
                )}
              </TouchableOpacity>
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
  searchBar: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: theme.colors.surface,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.surfaceBorder,
  },
  searchInput: {
    flex: 1,
    height: 38,
    backgroundColor: theme.colors.surfaceLight,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.md,
    color: theme.colors.text,
    fontSize: 13,
  },
  clearBtn: {
    padding: 8,
  },
  clearBtnText: {
    color: theme.colors.textMuted,
    fontSize: 14,
  },
  cohortBar: {
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
    gap: 8,
    backgroundColor: theme.colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.surfaceBorder,
  },
  cohortChip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.surfaceLight,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  cohortChipActive: {
    backgroundColor: theme.colors.primaryGlow,
    borderColor: theme.colors.primary,
  },
  cohortChipText: {
    fontSize: 12,
    fontWeight: "700",
    color: theme.colors.textMuted,
  },
  cohortChipTextActive: {
    color: theme.colors.accent,
  },
  scrollContent: {
    padding: theme.spacing.md,
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
  emptyContainer: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 40,
  },
  emptyTitle: {
    fontSize: 15,
    fontWeight: "700",
    color: theme.colors.textMuted,
  },
  emptySub: {
    fontSize: 12,
    color: theme.colors.textDim,
    marginTop: 4,
    textAlign: "center",
  },
  card: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.md,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  symbolInfo: {
    flex: 1,
    marginRight: 10,
  },
  symbolText: {
    fontSize: 15,
    fontWeight: "800",
    color: theme.colors.text,
  },
  companyName: {
    fontSize: 11,
    color: theme.colors.textMuted,
    marginTop: 2,
  },
  priceCol: {
    alignItems: "flex-end",
  },
  ltpText: {
    fontSize: 15,
    fontWeight: "800",
    color: theme.colors.text,
  },
  changeText: {
    fontSize: 11,
    fontWeight: "700",
    marginTop: 1,
  },
  metricsRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 8,
  },
  dvmBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
  },
  dvmText: {
    fontSize: 10,
    fontWeight: "800",
  },
  metricItem: {
    fontSize: 11,
    color: theme.colors.textDim,
  },
  metricVal: {
    fontWeight: "700",
    color: theme.colors.textMuted,
  },
  expandedDetails: {
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: theme.colors.surfaceBorder,
  },
  reasonText: {
    fontSize: 12,
    color: theme.colors.accent,
    marginBottom: 4,
  },
  expandedMeta: {
    fontSize: 11,
    color: theme.colors.textDim,
    marginTop: 2,
  },
});
