import React from "react";
import { StatusBar } from "expo-status-bar";
import { StyleSheet, Text } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { NavigationContainer, DefaultTheme } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";

import { theme } from "./src/theme";
import { TrendScreen } from "./src/screens/TrendScreen";
import { IntradayScreen } from "./src/screens/IntradayScreen";

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
  return (
    <SafeAreaProvider>
      <SafeAreaView style={styles.container} edges={["top", "left", "right"]}>
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
