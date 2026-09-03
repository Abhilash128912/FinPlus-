import React, { useEffect, useState } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { ActivityIndicator, View, Text, StyleSheet } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';

// Import screens (create these files next)
import WatchlistScreen from './screens/WatchlistScreen';
import ScreenerScreen from './screens/ScreenerScreen';
import HoldingsScreen from './screens/HoldingsScreen';
import SettingsScreen from './screens/SettingsScreen';

// Import API
import apiClient from './api/apiClient';

const Tab = createBottomTabNavigator();

const App = () => {
  const [appReady, setAppReady] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState('Connecting...');

  useEffect(() => {
    checkConnection();
    const interval = setInterval(checkConnection, 30000); // Check every 30s
    return () => clearInterval(interval);
  }, []);

  const checkConnection = async () => {
    try {
      const status = await apiClient.getStatus();
      if (status.status === 'success') {
        setConnectionStatus('Connected ✓');
        setAppReady(true);
      }
    } catch (error) {
      setConnectionStatus('Disconnected ✗');
      console.warn('Connection check failed:', error);
    }
  };

  if (!appReady) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#00a86b" />
        <Text style={styles.loadingText}>Stock Screener</Text>
        <Text style={styles.statusText}>{connectionStatus}</Text>
        <Text style={styles.hintText}>
          Make sure your laptop or Render server is running
        </Text>
      </View>
    );
  }

  return (
    <NavigationContainer>
      <Tab.Navigator
        screenOptions={({ route }) => ({
          headerStyle: {
            backgroundColor: '#1a1a2e',
            borderBottomColor: '#16c784',
            borderBottomWidth: 1,
          },
          headerTintColor: '#fff',
          headerTitleStyle: {
            fontWeight: 'bold',
            fontSize: 18,
          },
          tabBarStyle: {
            backgroundColor: '#1a1a2e',
            borderTopColor: '#16c784',
            borderTopWidth: 1,
          },
          tabBarActiveTintColor: '#16c784',
          tabBarInactiveTintColor: '#666',
          tabBarIcon: ({ focused, color, size }) => {
            let iconName = 'home';
            if (route.name === 'Watchlist') iconName = 'shield';
            else if (route.name === 'Screener') iconName = 'search';
            else if (route.name === 'Holdings') iconName = 'briefcase';
            else if (route.name === 'Settings') iconName = 'settings';

            return (
              <Icon
                name={focused ? iconName : `${iconName}-outline`}
                size={size}
                color={color}
              />
            );
          },
        })}
      >
        <Tab.Screen
          name="Watchlist"
          component={WatchlistScreen}
          options={{
            title: '🛡️ LT Watchlist',
            tabBarLabel: 'Watchlist',
          }}
        />
        <Tab.Screen
          name="Screener"
          component={ScreenerScreen}
          options={{
            title: '🔍 Full Screener',
            tabBarLabel: 'Screener',
          }}
        />
        <Tab.Screen
          name="Holdings"
          component={HoldingsScreen}
          options={{
            title: '💼 Holdings',
            tabBarLabel: 'Holdings',
          }}
        />
        <Tab.Screen
          name="Settings"
          component={SettingsScreen}
          options={{
            title: '⚙️ Settings',
            tabBarLabel: 'Settings',
          }}
        />
      </Tab.Navigator>
    </NavigationContainer>
  );
};

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0f0f1e',
  },
  loadingText: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#fff',
    marginTop: 20,
  },
  statusText: {
    fontSize: 14,
    color: '#16c784',
    marginTop: 10,
  },
  hintText: {
    fontSize: 12,
    color: '#888',
    marginTop: 20,
    paddingHorizontal: 20,
    textAlign: 'center',
  },
});

export default App;
