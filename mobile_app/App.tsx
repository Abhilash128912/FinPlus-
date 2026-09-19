import React, { useEffect, useState } from "react";
import { StatusBar } from "expo-status-bar";
import { StyleSheet, Text, View, ActivityIndicator } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { NavigationContainer, DefaultTheme } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";

import { theme } from "./src/theme";
import { initConfig } from "./src/config";
import { TrendScreen } from "./src/screens/TrendScreen";
import { IntradayScreen } from "./src/screens/IntradayScreen";
import { CommoditiesScreen } from "./src/screens/CommoditiesScreen";
import { AlertsScreen } from "./src/screens/AlertsScreen";

const Tab = createBottomTabNavigator();

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
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Must finish before any screen's first fetch, or a saved key from a
    // previous session gets missed and every request looks unauthenticated.
    initConfig().finally(() => setReady(true));
  }, []);

  if (!ready) {
    return (
      <SafeAreaProvider>
        <SafeAreaView style={[styles.container, styles.loadingContainer]}>
          <StatusBar style="light" />
          <ActivityIndicator color={theme.colors.accent} />
        </SafeAreaView>
      </SafeAreaProvider>
    );
  }

  return (
    <SafeAreaProvider>
      <SafeAreaView style={styles.container} edges={["top", "left", "right", "bottom"]}>
        <StatusBar style="light" />
        <NavigationContainer theme={navTheme}>
          <Tab.Navigator
            screenOptions={{
              headerShown: false,
              tabBarStyle: styles.tabBar,
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
                  <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>
                    📊
                  </Text>
                ),
              }}
            />
            <Tab.Screen
              name="Intraday"
              component={IntradayScreen}
              options={{
                tabBarLabel: "Intraday Calls",
                tabBarIcon: ({ focused }) => (
                  <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>
                    🎯
                  </Text>
                ),
              }}
            />
            <Tab.Screen
              name="Commodities"
              component={CommoditiesScreen}
              options={{
                tabBarLabel: "Commodities",
                tabBarIcon: ({ focused }) => (
                  <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>
                    🛢️
                  </Text>
                ),
              }}
            />
            <Tab.Screen
              name="Alerts"
              component={AlertsScreen}
              options={{
                tabBarLabel: "Signal Journal",
                tabBarIcon: ({ focused }) => (
                  <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>
                    🧾
                  </Text>
                ),
              }}
            />
          </Tab.Navigator>
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
  loadingContainer: {
    justifyContent: "center",
    alignItems: "center",
  },
  tabBar: {
    backgroundColor: theme.colors.surface,
    borderTopWidth: 1,
    borderTopColor: theme.colors.surfaceBorder,
    height: 60,
    paddingBottom: 8,
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
