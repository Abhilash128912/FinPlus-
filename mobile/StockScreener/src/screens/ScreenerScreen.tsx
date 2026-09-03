import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, FlatList, TextInput, TouchableOpacity, Alert } from 'react-native';
import apiClient from '../api/apiClient';

const ScreenerScreen = () => {
  const [stocks, setStocks] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchScreener = async () => {
    try {
      setLoading(true);
      const data = await apiClient.getScreenerData();
      if (data.status === 'success') {
        setStocks(data.stocks || []);
      }
    } catch (error) {
      Alert.alert('Error', 'Failed to fetch screener data');
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      fetchScreener();
      return;
    }
    try {
      setLoading(true);
      const data = await apiClient.searchStocks(searchQuery);
      if (data.status === 'success') {
        setStocks(data.results || []);
      }
    } catch (error) {
      Alert.alert('Error', 'Search failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchScreener();
  }, []);

  return (
    <View style={styles.container}>
      <View style={styles.searchContainer}>
        <TextInput
          style={styles.searchInput}
          placeholder="Search stocks..."
          placeholderTextColor="#666"
          value={searchQuery}
          onChangeText={setSearchQuery}
          onSubmitEditing={handleSearch}
        />
        <TouchableOpacity style={styles.searchBtn} onPress={handleSearch}>
          <Text style={styles.searchBtnText}>🔍</Text>
        </TouchableOpacity>
      </View>

      <FlatList
        data={stocks}
        renderItem={({ item }) => (
          <View style={styles.stockCard}>
            <Text style={styles.symbol}>{item.symbol}</Text>
            <Text style={styles.detail}>Score: {item.total_score || '—'}</Text>
            <Text style={styles.detail}>Price: ₹{item.ltp || '—'}</Text>
          </View>
        )}
        keyExtractor={(item) => item.symbol}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={<Text style={styles.emptyText}>No stocks found</Text>}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f0f1e',
    padding: 12,
  },
  searchContainer: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 16,
  },
  searchInput: {
    flex: 1,
    backgroundColor: '#1a1a2e',
    color: '#fff',
    padding: 10,
    borderRadius: 8,
    borderColor: '#16c784',
    borderWidth: 1,
  },
  searchBtn: {
    backgroundColor: '#16c784',
    padding: 10,
    borderRadius: 8,
    justifyContent: 'center',
  },
  searchBtnText: {
    fontSize: 18,
  },
  listContent: {
    paddingBottom: 20,
  },
  stockCard: {
    backgroundColor: '#1a1a2e',
    padding: 12,
    borderRadius: 8,
    marginBottom: 10,
    borderLeftColor: '#16c784',
    borderLeftWidth: 2,
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
});

export default ScreenerScreen;
