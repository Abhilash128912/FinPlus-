import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { theme } from "../theme";

interface SignalBadgeProps {
  signal?: string;
  setup?: string;
  size?: "sm" | "md";
}

export const SignalBadge: React.FC<SignalBadgeProps> = ({
  signal = "NONE",
  setup,
  size = "md",
}) => {
  const sig = signal.toUpperCase();
  const isBuy = sig.includes("BUY");
  const isSell = sig.includes("SELL");

  const bgColor = isBuy
    ? theme.colors.greenBg
    : isSell
    ? theme.colors.redBg
    : theme.colors.surfaceLight;

  const borderColor = isBuy
    ? theme.colors.greenBorder
    : isSell
    ? theme.colors.redBorder
    : theme.colors.surfaceBorder;

  const textColor = isBuy
    ? theme.colors.green
    : isSell
    ? theme.colors.red
    : theme.colors.textMuted;

  return (
    <View
      style={[
        styles.badge,
        { backgroundColor: bgColor, borderColor: borderColor },
        size === "sm" && styles.badgeSm,
      ]}
    >
      <Text
        style={[
          styles.badgeText,
          { color: textColor },
          size === "sm" && styles.badgeTextSm,
        ]}
      >
        {sig}
      </Text>
      {setup && size !== "sm" ? (
        <Text style={styles.setupText}>· {setup}</Text>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  badge: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
    gap: 4,
  },
  badgeSm: {
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
  badgeTextSm: {
    fontSize: 10,
  },
  setupText: {
    fontSize: 10,
    color: theme.colors.textDim,
  },
});
