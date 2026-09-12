import React from "react";
import { StatusBar } from "expo-status-bar";
import { StyleSheet, View, Text } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { NavigationContainer, DefaultTheme } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";

import { theme } from "./src/theme";
import { MarketsScreen } from "./src/screens/MarketsScreen";
import { CommoditiesScreen } from "./src/screens/CommoditiesScreen";
import { ScreenerScreen } from "./src/screens/ScreenerScreen";
import { OptionsScreen } from "./src/screens/OptionsScreen";
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
              name="Markets"
              component={MarketsScreen}
              options={{
                tabBarLabel: "Markets",
                tabBarIcon: ({ focused }) => (
                  <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>
                    📈
                  </Text>
                ),
              }}
            />
            <Tab.Screen
              name="CrudeMCX"
              component={CommoditiesScreen}
              options={{
                tabBarLabel: "Crude/MCX",
                tabBarIcon: ({ focused }) => (
                  <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>
                    🛢️
                  </Text>
                ),
              }}
            />
            <Tab.Screen
              name="Screener"
              component={ScreenerScreen}
              options={{
                tabBarLabel: "Screener",
                tabBarIcon: ({ focused }) => (
                  <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>
                    🔍
                  </Text>
                ),
              }}
            />
            <Tab.Screen
              name="Options"
              component={OptionsScreen}
              options={{
                tabBarLabel: "Options",
                tabBarIcon: ({ focused }) => (
                  <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>
                    ⚡
                  </Text>
                ),
              }}
            />
            <Tab.Screen
              name="Alerts"
              component={AlertsScreen}
              options={{
                tabBarLabel: "Alerts",
                tabBarIcon: ({ focused }) => (
                  <Text style={[styles.tabIcon, focused && styles.tabIconActive]}>
                    🔔
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
    height: 58,
    paddingBottom: 6,
    paddingTop: 6,
  },
  tabLabel: {
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.3,
  },
  tabIcon: {
    fontSize: 18,
    opacity: 0.7,
  },
  tabIconActive: {
    opacity: 1,
    transform: [{ scale: 1.1 }],
  },
});
