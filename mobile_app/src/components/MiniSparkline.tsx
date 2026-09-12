import React from "react";
import { View, StyleSheet } from "react-native";
import { theme } from "../theme";

interface MiniSparklineProps {
  data: number[];
  color?: string;
  height?: number;
  width?: number;
}

export const MiniSparkline: React.FC<MiniSparklineProps> = ({
  data = [],
  color = theme.colors.accent,
  height = 24,
  width = 70,
}) => {
  if (!data || data.length < 2) {
    return <View style={[styles.placeholder, { width, height }]} />;
  }

  // Downsample to at most 18 points for clean micro-bar visual
  const sampleCount = Math.min(data.length, 16);
  const step = Math.max(1, Math.floor(data.length / sampleCount));
  const points: number[] = [];
  for (let i = 0; i < data.length; i += step) {
    points.push(data[i]);
    if (points.length >= sampleCount) break;
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;

  const isUp = points[points.length - 1] >= points[0];
  const barColor = color || (isUp ? theme.colors.green : theme.colors.red);

  return (
    <View style={[styles.container, { width, height }]}>
      {points.map((val, idx) => {
        const norm = (val - min) / range;
        const barH = Math.max(3, Math.round(norm * (height - 4)));
        return (
          <View
            key={idx}
            style={[
              styles.bar,
              {
                height: barH,
                backgroundColor: barColor,
                opacity: 0.35 + (idx / points.length) * 0.65,
              },
            ]}
          />
        );
      })}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    gap: 1.5,
  },
  placeholder: {
    backgroundColor: "transparent",
  },
  bar: {
    flex: 1,
    borderRadius: 1,
  },
});
