import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  TouchableOpacity,
  ActivityIndicator,
} from "react-native";
import { theme } from "../theme";
import { fetchOptionExpiries, fetchOptionChain } from "../api";

export const OptionsScreen: React.FC = () => {
  const [underlying, setUnderlying] = useState<"NIFTY" | "BANKNIFTY">("NIFTY");
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<string>("");
  const [chainData, setChainData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadExpiries = async () => {
    try {
      const res = await fetchOptionExpiries(underlying);
      if (res.expiries && res.expiries.length > 0) {
        setExpiries(res.expiries);
        setSelectedExpiry(res.expiries[0]);
      }
    } catch (e: any) {
      setError(e.message || "Failed to fetch expiries");
    }
  };

  const loadChain = async (exp?: string) => {
    const targetExp = exp || selectedExpiry;
    if (!targetExp) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetchOptionChain(underlying, targetExp);
      setChainData(res.data || res);
    } catch (e: any) {
      setError(e.message || "Failed to load option chain");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadExpiries();
  }, [underlying]);

  useEffect(() => {
    if (selectedExpiry) {
      loadChain(selectedExpiry);
    }
  }, [selectedExpiry, underlying]);

  const onRefresh = async () => {
    setIsRefreshing(true);
    await loadChain();
    setIsRefreshing(false);
  };

  const pcr = chainData?.pcr || chainData?.put_call_ratio;
  const maxPain = chainData?.max_pain;
  const spotPrice = chainData?.spot_price || chainData?.underlying_price;
  const strikes: any[] = chainData?.strikes || chainData?.contracts || [];

  return (
    <View style={styles.container}>
      {/* Underlying Selector */}
      <View style={styles.topBar}>
        <TouchableOpacity
          style={[styles.topTab, underlying === "NIFTY" && styles.topTabActive]}
          onPress={() => setUnderlying("NIFTY")}
        >
          <Text
            style={[
              styles.topTabText,
              underlying === "NIFTY" && styles.topTabTextActive,
            ]}
          >
            NIFTY 50
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.topTab, underlying === "BANKNIFTY" && styles.topTabActive]}
          onPress={() => setUnderlying("BANKNIFTY")}
        >
          <Text
            style={[
              styles.topTabText,
              underlying === "BANKNIFTY" && styles.topTabTextActive,
            ]}
          >
            BANK NIFTY
          </Text>
        </TouchableOpacity>
      </View>

      {/* Expiries Carousel */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.expiryBar}
      >
        {expiries.map((exp) => (
          <TouchableOpacity
            key={exp}
            style={[
              styles.expiryChip,
              selectedExpiry === exp && styles.expiryChipActive,
            ]}
            onPress={() => setSelectedExpiry(exp)}
          >
            <Text
              style={[
                styles.expiryText,
                selectedExpiry === exp && styles.expiryTextActive,
              ]}
            >
              {exp}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

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

        {/* Derivatives Summary Stats */}
        <View style={styles.summaryCard}>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryLabel}>SPOT PRICE</Text>
            <Text style={styles.summaryVal}>
              ₹{spotPrice ? spotPrice.toLocaleString("en-IN") : "—"}
            </Text>
          </View>

          <View style={styles.summaryDivider} />

          <View style={styles.summaryItem}>
            <Text style={styles.summaryLabel}>PCR</Text>
            <Text
              style={[
                styles.summaryVal,
                { color: pcr >= 1 ? theme.colors.green : theme.colors.red },
              ]}
            >
              {pcr ? pcr.toFixed(2) : "—"}
            </Text>
          </View>

          <View style={styles.summaryDivider} />

          <View style={styles.summaryItem}>
            <Text style={styles.summaryLabel}>MAX PAIN</Text>
            <Text style={[styles.summaryVal, { color: theme.colors.yellow }]}>
              {maxPain ? `₹${maxPain}` : "—"}
            </Text>
          </View>
        </View>

        {loading ? (
          <View style={styles.loadingBox}>
            <ActivityIndicator size="small" color={theme.colors.accent} />
            <Text style={styles.loadingText}>Loading strike chain...</Text>
          </View>
        ) : (
          <View style={styles.tableCard}>
            <Text style={styles.tableHeader}>STRIKE LADDER (CALL vs PUT)</Text>
            <View style={styles.tableHeadRow}>
              <Text style={[styles.headCol, styles.callHead]}>CALL LTP</Text>
              <Text style={[styles.headCol, styles.strikeHead]}>STRIKE</Text>
              <Text style={[styles.headCol, styles.putHead]}>PUT LTP</Text>
            </View>

            {strikes.slice(0, 15).map((row: any, i: number) => {
              const strike = row.strike || row.strike_price;
              const callLtp = row.call?.ltp || row.ce_ltp;
              const putLtp = row.put?.ltp || row.pe_ltp;
              const isAtm = spotPrice && Math.abs(strike - spotPrice) < 50;

              return (
                <View
                  key={i}
                  style={[styles.tableRow, isAtm && styles.atmTableRow]}
                >
                  <Text style={[styles.bodyCol, styles.callText]}>
                    ₹{callLtp ? callLtp.toFixed(1) : "—"}
                  </Text>
                  <View style={[styles.strikePill, isAtm && styles.atmPill]}>
                    <Text
                      style={[
                        styles.strikeText,
                        isAtm && styles.atmStrikeText,
                      ]}
                    >
                      {strike}
                    </Text>
                  </View>
                  <Text style={[styles.bodyCol, styles.putText]}>
                    ₹{putLtp ? putLtp.toFixed(1) : "—"}
                  </Text>
                </View>
              );
            })}
          </View>
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
  topBar: {
    flexDirection: "row",
    backgroundColor: theme.colors.surface,
    padding: theme.spacing.sm,
    gap: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.surfaceBorder,
  },
  topTab: {
    flex: 1,
    paddingVertical: 9,
    alignItems: "center",
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.surfaceLight,
  },
  topTabActive: {
    backgroundColor: theme.colors.primary,
  },
  topTabText: {
    fontSize: 12,
    fontWeight: "700",
    color: theme.colors.textMuted,
  },
  topTabTextActive: {
    color: "#fff",
  },
  expiryBar: {
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
    backgroundColor: theme.colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.surfaceBorder,
    gap: 8,
  },
  expiryChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: theme.radius.sm,
    backgroundColor: theme.colors.surfaceLight,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  expiryChipActive: {
    backgroundColor: theme.colors.primaryGlow,
    borderColor: theme.colors.primary,
  },
  expiryText: {
    fontSize: 11,
    fontWeight: "700",
    color: theme.colors.textMuted,
  },
  expiryTextActive: {
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
  summaryCard: {
    flexDirection: "row",
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.md,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
    marginBottom: theme.spacing.md,
    justifyContent: "space-between",
  },
  summaryItem: {
    flex: 1,
    alignItems: "center",
  },
  summaryLabel: {
    fontSize: 9,
    fontWeight: "800",
    color: theme.colors.textDim,
    marginBottom: 4,
  },
  summaryVal: {
    fontSize: 15,
    fontWeight: "800",
    color: theme.colors.text,
  },
  summaryDivider: {
    width: 1,
    backgroundColor: theme.colors.surfaceBorder,
  },
  loadingBox: {
    padding: 30,
    alignItems: "center",
    gap: 8,
  },
  loadingText: {
    fontSize: 12,
    color: theme.colors.textDim,
  },
  tableCard: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.md,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  tableHeader: {
    fontSize: 11,
    fontWeight: "800",
    color: theme.colors.textMuted,
    letterSpacing: 0.8,
    marginBottom: 10,
  },
  tableHeadRow: {
    flexDirection: "row",
    paddingBottom: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.surfaceBorder,
  },
  headCol: {
    flex: 1,
    fontSize: 10,
    fontWeight: "800",
  },
  callHead: {
    color: theme.colors.green,
    textAlign: "left",
  },
  strikeHead: {
    color: theme.colors.textMuted,
    textAlign: "center",
  },
  putHead: {
    color: theme.colors.red,
    textAlign: "right",
  },
  tableRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 9,
    borderBottomWidth: 1,
    borderBottomColor: "rgba(255,255,255,0.03)",
  },
  atmTableRow: {
    backgroundColor: "rgba(99, 102, 241, 0.08)",
  },
  bodyCol: {
    flex: 1,
    fontSize: 12,
    fontWeight: "700",
  },
  callText: {
    color: theme.colors.green,
    textAlign: "left",
  },
  putText: {
    color: theme.colors.red,
    textAlign: "right",
  },
  strikePill: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: theme.radius.sm,
    backgroundColor: theme.colors.surfaceLight,
  },
  atmPill: {
    backgroundColor: theme.colors.primary,
  },
  strikeText: {
    fontSize: 12,
    fontWeight: "800",
    color: theme.colors.text,
    textAlign: "center",
  },
  atmStrikeText: {
    color: "#fff",
  },
});
