import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
  TouchableOpacity,
  Alert,
} from 'react-native';
import apiClient from '../api/apiClient';

interface Stock {
  symbol: string;
  status?: string;
  badge?: string;
  trend?: string;
  ltp?: number;
  lt_quality_score?: number;
  lt_entry_score?: number;
}

const WatchlistScreen = () => {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [stats, setStats] = useState({
    total: 0,
    buy_now: 0,
    wait: 0,
  });

  const fetchWatchlist = useCallback(async (isRefresh = false) => {
    try {
      if (isRefresh) setRefreshing(true);
      else setLoading(true);

      const data = await apiClient.getWatchlist();
      if (data.status === 'success') {
        setStocks(data.watchlist || []);
        setStats({
          total: data.total || 0,
          buy_now: data.buy_now || 0,
          wait: data.wait || 0,
        });
      }
    } catch (error) {
      Alert.alert('Error', 'Failed to fetch watchlist. Check connection.');
      console.error('Watchlist fetch error:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchWatchlist();
    const interval = setInterval(() => fetchWatchlist(), 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, [fetchWatchlist]);

  const getStatusColor = (status: string) => {
    if (status?.includes('BUY')) return '#16c784';
    if (status?.includes('WAIT')) return '#0066cc';
    if (status?.includes('DOWNTREND')) return '#ff4444';
    return '#888';
  };

  const renderStock = ({ item }: { item: Stock }) => (
    <TouchableOpacity style={styles.stockCard}>
      <View style={styles.stockHeader}>
        <Text style={styles.symbol}>{item.symbol}</Text>
        <Text
          style={[
            styles.badge,
            { color: getStatusColor(item.badge) },
          ]}
        >
          {item.badge || item.status || '—'}
        </Text>
      </View>

      <View style={styles.stockDetails}>
        <View style={styles.detailColumn}>
          <Text style={styles.label}>Trend</Text>
          <Text style={styles.value}>{item.trend || '—'}</Text>
        </View>
        <View style={styles.detailColumn}>
          <Text style={styles.label}>Quality</Text>
          <Text style={styles.value}>
            {typeof item.lt_quality_score === 'number'
              ? item.lt_quality_score.toFixed(0)
              : '—'}
          </Text>
        </View>
        <View style={styles.detailColumn}>
          <Text style={styles.label}>Entry</Text>
          <Text style={styles.value}>
            {typeof item.lt_entry_score === 'number'
              ? item.lt_entry_score.toFixed(0)
              : '—'}
          </Text>
        </View>
        <View style={styles.detailColumn}>
          <Text style={styles.label}>LTP</Text>
          <Text style={styles.value}>
            {typeof item.ltp === 'number' ? `₹${item.ltp.toFixed(2)}` : '—'}
          </Text>
        </View>
      </View>
    </TouchableOpacity>
  );

  if (loading) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color="#16c784" />
        <Text style={styles.loadingText}>Loading Watchlist...</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Stats Header */}
      <View style={styles.statsContainer}>
        <View style={styles.statCard}>
          <Text style={styles.statValue}>{stats.buy_now}</Text>
          <Text style={styles.statLabel}>🟢 BUY NOW</Text>
        </View>
        <View style={styles.statCard}>
          <Text style={styles.statValue}>{stats.wait}</Text>
          <Text style={styles.statLabel}>🔵 WAIT</Text>
        </View>
        <View style={styles.statCard}>
          <Text style={styles.statValue}>{stats.total}</Text>
          <Text style={styles.statLabel}>📊 Total</Text>
        </View>
      </View>

      {/* Watchlist */}
      <FlatList
        data={stocks}
        renderItem={renderStock}
        keyExtractor={(item) => item.symbol}
        contentContainerStyle={styles.listContainer}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => fetchWatchlist(true)}
            tintColor="#16c784"
          />
        }
        ListEmptyComponent={
          <Text style={styles.emptyText}>No watchlist items yet</Text>
        }
      />

      {/* Refresh Button */}
      <TouchableOpacity
        style={styles.fab}
        onPress={() => fetchWatchlist(true)}
        disabled={refreshing}
      >
        <Text style={styles.fabText}>{refreshing ? '...' : '🔄'}</Text>
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f0f1e',
  },
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0f0f1e',
  },
  loadingText: {
    color: '#888',
    marginTop: 12,
    fontSize: 14,
  },
  statsContainer: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    paddingVertical: 12,
    gap: 8,
    backgroundColor: '#1a1a2e',
    borderBottomColor: '#2a2a3e',
    borderBottomWidth: 1,
  },
  statCard: {
    flex: 1,
    backgroundColor: '#0f0f1e',
    borderRadius: 8,
    paddingVertical: 8,
    alignItems: 'center',
    borderColor: '#16c784',
    borderWidth: 1,
  },
  statValue: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#16c784',
  },
  statLabel: {
    fontSize: 11,
    color: '#888',
    marginTop: 2,
  },
  listContainer: {
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  stockCard: {
    backgroundColor: '#1a1a2e',
    borderRadius: 10,
    padding: 12,
    marginBottom: 10,
    borderLeftColor: '#16c784',
    borderLeftWidth: 3,
  },
  stockHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  symbol: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#fff',
  },
  badge: {
    fontSize: 12,
    fontWeight: '600',
    backgroundColor: '#2a2a3e',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  stockDetails: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  detailColumn: {
    flex: 1,
  },
  label: {
    fontSize: 10,
    color: '#888',
    marginBottom: 2,
  },
  value: {
    fontSize: 13,
    color: '#fff',
    fontWeight: '500',
  },
  emptyText: {
    color: '#666',
    textAlign: 'center',
    marginTop: 40,
    fontSize: 14,
  },
  fab: {
    position: 'absolute',
    bottom: 20,
    right: 20,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: '#16c784',
    justifyContent: 'center',
    alignItems: 'center',
    elevation: 5,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 3.84,
  },
  fabText: {
    fontSize: 24,
  },
});

export default WatchlistScreen;
