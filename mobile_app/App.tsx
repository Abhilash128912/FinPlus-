import React from "react";
import { StatusBar } from "expo-status-bar";
import { StyleSheet, Text } from "react-native";
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { NavigationContainer, DefaultTheme } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";

import { theme } from "./src/theme";
import { TrendScreen } from "./src/screens/TrendScreen";
import { IntradayScreen } from "./src/screens/IntradayScreen";
import { ScreenerScreen } from "./src/screens/ScreenerScreen";

const Tab = createBottomTabNavigator();

const Tabs: React.FC = () => {
  // On Android, insets.bottom can be 0 or small, which causes the tab bar to collide
  // with the phone's 3-button navigation bar or gesture pill. Enforce a safe minimum.
  const insets = useSafeAreaInsets();
  const bottomInset = Math.max(insets.bottom, 20);

  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarStyle: [
          styles.tabBar,
          {
            height: 60 + bottomInset,
            paddingBottom: bottomInset + 4,
            paddingTop: 8,
          },
        ],
        tabBarActiveTintColor: theme.colors.accent,
        tabBarInactiveTintColor: theme.colors.textDim,
        tabBarLabelStyle: styles.tabLabel,
      }}
    >
      <Tab.Screen
        name="Trend"
        component={TrendScreen}
        options={{
          tabBarLabel: "Trend Analyser",
          tabBarIcon: ({ focused }) => (
            <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>📊</Text>
          ),
        }}
      />
      <Tab.Screen
        name="Stocks"
        component={ScreenerScreen}
        options={{
          tabBarLabel: "Stocks",
          tabBarIcon: ({ focused }) => (
            <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>💹</Text>
          ),
        }}
      />
      <Tab.Screen
        name="Intraday"
        component={IntradayScreen}
        options={{
          tabBarLabel: "Intraday Calls",
          tabBarIcon: ({ focused }) => (
            <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>🎯</Text>
          ),
        }}
      />
    </Tab.Navigator>
  );
};

const navTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    background: theme.colors.bg,
    card: theme.colors.surface,
    text: theme.colors.text,
    border: theme.colors.surfaceBorder,
  },
};

export default function App() {
  return (
    <SafeAreaProvider>
      {/* Bottom edge is intentionally NOT excluded here: the tab bar itself
          pads for insets.bottom (see Tabs above), and letting SafeAreaView
          also reserve it would double the gap under the tab bar. */}
      <SafeAreaView style={styles.container} edges={["top", "left", "right"]}>
        <StatusBar style="light" />
        <NavigationContainer theme={navTheme}>
          <Tabs />
        </NavigationContainer>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.surface,
  },
  tabBar: {
    backgroundColor: theme.colors.surface,
    borderTopWidth: 1,
    borderTopColor: theme.colors.surfaceBorder,
    paddingTop: 6,
  },
  tabLabel: {
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 0.4,
  },
  tabIcon: {
    fontSize: 20,
    opacity: 0.7,
  },
  tabIconActive: {
    opacity: 1,
    transform: [{ scale: 1.15 }],
  },
});
