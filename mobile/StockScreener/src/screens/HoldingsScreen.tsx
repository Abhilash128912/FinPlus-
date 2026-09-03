import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, RefreshControl, FlatList, TouchableOpacity, Alert } from 'react-native';
import apiClient from '../api/apiClient';

const HoldingsScreen = () => {
  const [holdings, setHoldings] = useState<any>({});
  const [stats, setStats] = useState({ total_value: 0, pnl: 0, pnl_pct: 0 });
  const [refreshing, setRefreshing] = useState(false);

  const fetchHoldings = async (isRefresh = false) => {
    try {
      setRefreshing(true);
      const data = await apiClient.getHoldings();
      if (data.status === 'success') {
        setHoldings(data.holdings || {});
        setStats({
          total_value: data.total_value || 0,
          pnl: data.pnl || 0,
          pnl_pct: data.pnl_pct || 0,
        });
      }
    } catch (error) {
      Alert.alert('Error', 'Failed to fetch holdings');
      console.error('Holdings fetch error:', error);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchHoldings();
    const interval = setInterval(fetchHoldings, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <View style={styles.container}>
      <View style={styles.statsContainer}>
        <View style={styles.statBox}>
          <Text style={styles.statLabel}>Portfolio Value</Text>
          <Text style={styles.statValue}>₹{stats.total_value.toFixed(2)}</Text>
        </View>
        <View style={styles.statBox}>
          <Text style={styles.statLabel}>P&L</Text>
          <Text style={[styles.statValue, { color: stats.pnl >= 0 ? '#16c784' : '#ff4444' }]}>
            {stats.pnl >= 0 ? '+' : ''}₹{stats.pnl.toFixed(2)} ({stats.pnl_pct.toFixed(2)}%)
          </Text>
        </View>
      </View>

      <Text style={styles.title}>Holdings: {Object.keys(holdings).length}</Text>

      <View style={styles.listContainer}>
        {Object.entries(holdings).map(([symbol, holding]: [string, any]) => (
          <View key={symbol} style={styles.holdingCard}>
            <Text style={styles.symbol}>{symbol}</Text>
            <Text style={styles.detail}>{holding.qty} shares @ ₹{holding.avg_price}</Text>
            <Text style={styles.detail}>Bought: {holding.buy_date}</Text>
          </View>
        ))}
        {Object.keys(holdings).length === 0 && (
          <Text style={styles.emptyText}>No active holdings</Text>
        )}
      </View>

      <TouchableOpacity style={styles.refreshBtn} onPress={() => fetchHoldings(true)}>
        <Text style={styles.refreshBtnText}>🔄 Refresh</Text>
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f0f1e',
    padding: 12,
  },
  statsContainer: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 20,
  },
  statBox: {
    flex: 1,
    backgroundColor: '#1a1a2e',
    padding: 12,
    borderRadius: 10,
    borderColor: '#16c784',
    borderWidth: 1,
  },
  statLabel: {
    color: '#888',
    fontSize: 12,
    marginBottom: 4,
  },
  statValue: {
    color: '#16c784',
    fontSize: 16,
    fontWeight: 'bold',
  },
  title: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 12,
  },
  listContainer: {
    flex: 1,
  },
  holdingCard: {
    backgroundColor: '#1a1a2e',
    padding: 12,
    borderRadius: 8,
    marginBottom: 8,
    borderLeftColor: '#16c784',
    borderLeftWidth: 3,
  },
  symbol: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
  },
  detail: {
    color: '#888',
    fontSize: 12,
    marginTop: 4,
  },
  emptyText: {
    color: '#666',
    textAlign: 'center',
    marginTop: 40,
  },
  refreshBtn: {
    backgroundColor: '#16c784',
    padding: 12,
    borderRadius: 8,
    alignItems: 'center',
    marginTop: 12,
  },
  refreshBtnText: {
    color: '#000',
    fontWeight: 'bold',
  },
});

export default HoldingsScreen;
