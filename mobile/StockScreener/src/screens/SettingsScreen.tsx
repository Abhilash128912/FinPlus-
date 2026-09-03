import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, Alert, ScrollView } from 'react-native';
import apiClient from '../api/apiClient';

const SettingsScreen = () => {
  const [localhostIP, setLocalhostIP] = useState('192.168.1.100');
  const [renderURL, setRenderURL] = useState('https://stock-screener-api.onrender.com');
  const [useRender, setUseRender] = useState(false);
  const [status, setStatus] = useState('Not connected');

  const testConnection = async () => {
    try {
      const data = await apiClient.getStatus();
      if (data.status === 'success') {
        setStatus(`✓ Connected to ${data.server_time}`);
        Alert.alert('Success', 'Connection successful!');
      }
    } catch (error) {
      setStatus('✗ Connection failed');
      Alert.alert('Error', 'Cannot connect to server');
    }
  };

  const switchToLocalhost = () => {
    const url = `http://${localhostIP}:5050`;
    apiClient.switchServer(false, renderURL, url);
    setUseRender(false);
    Alert.alert('Switched', `Using localhost: ${url}`);
  };

  const switchToRender = () => {
    apiClient.switchServer(true, renderURL, `http://${localhostIP}:5050`);
    setUseRender(true);
    Alert.alert('Switched', `Using Render: ${renderURL}`);
  };

  return (
    <ScrollView style={styles.container}>
      <Text style={styles.title}>Connection Settings</Text>

      {/* Current Status */}
      <View style={styles.statusBox}>
        <Text style={styles.statusLabel}>Current Status</Text>
        <Text style={styles.statusText}>{status}</Text>
        <TouchableOpacity style={styles.testBtn} onPress={testConnection}>
          <Text style={styles.testBtnText}>Test Connection</Text>
        </TouchableOpacity>
      </View>

      {/* Localhost Settings */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>🏠 Localhost (Development)</Text>
        <Text style={styles.hint}>
          Enter your laptop's IP address. Find it with: ipconfig (Windows) or ifconfig (Mac/Linux)
        </Text>
        <TextInput
          style={styles.input}
          placeholder="192.168.1.100"
          placeholderTextColor="#666"
          value={localhostIP}
          onChangeText={setLocalhostIP}
        />
        <Text style={styles.urlPreview}>http://{localhostIP}:5050</Text>
        <TouchableOpacity
          style={[styles.btn, useRender ? styles.btnInactive : styles.btnActive]}
          onPress={switchToLocalhost}
        >
          <Text style={styles.btnText}>Use Localhost</Text>
        </TouchableOpacity>
      </View>

      {/* Render Settings */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>☁️ Render Cloud (Production)</Text>
        <Text style={styles.hint}>
          After deploying to Render, use this URL for remote access
        </Text>
        <TextInput
          style={styles.input}
          placeholder="https://stock-screener-api.onrender.com"
          placeholderTextColor="#666"
          value={renderURL}
          onChangeText={setRenderURL}
        />
        <TouchableOpacity
          style={[styles.btn, !useRender ? styles.btnInactive : styles.btnActive]}
          onPress={switchToRender}
        >
          <Text style={styles.btnText}>Use Render</Text>
        </TouchableOpacity>
      </View>

      {/* App Info */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>ℹ️ App Information</Text>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>Version</Text>
          <Text style={styles.infoValue}>1.0.0</Text>
        </View>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>API Version</Text>
          <Text style={styles.infoValue}>1.0.0</Text>
        </View>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>Data Refresh</Text>
          <Text style={styles.infoValue}>Every 30 seconds</Text>
        </View>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>Market Hours</Text>
          <Text style={styles.infoValue}>09:15 - 15:30 IST</Text>
        </View>
      </View>

      {/* Help */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>📱 Dual System Setup</Text>
        <Text style={styles.helpText}>
          <Text style={styles.bold}>Development:</Text> Use Localhost to test on your laptop's network{'\n\n'}
          <Text style={styles.bold}>Production:</Text> Use Render cloud for live mobile access anywhere{'\n\n'}
          <Text style={styles.bold}>Sync:</Text> Both systems fetch from the same backend - all changes sync automatically
        </Text>
      </View>

      <View style={styles.bottomPadding} />
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f0f1e',
    padding: 16,
  },
  title: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 20,
  },
  statusBox: {
    backgroundColor: '#1a1a2e',
    padding: 16,
    borderRadius: 10,
    borderColor: '#16c784',
    borderWidth: 1,
    marginBottom: 20,
  },
  statusLabel: {
    color: '#888',
    fontSize: 12,
  },
  statusText: {
    color: '#16c784',
    fontSize: 14,
    fontWeight: 'bold',
    marginVertical: 8,
  },
  testBtn: {
    backgroundColor: '#16c784',
    padding: 10,
    borderRadius: 6,
    alignItems: 'center',
  },
  testBtnText: {
    color: '#000',
    fontWeight: 'bold',
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#16c784',
    marginBottom: 8,
  },
  hint: {
    color: '#888',
    fontSize: 12,
    marginBottom: 8,
  },
  input: {
    backgroundColor: '#2a2a3e',
    color: '#fff',
    padding: 10,
    borderRadius: 6,
    marginBottom: 8,
    borderColor: '#16c784',
    borderWidth: 1,
  },
  urlPreview: {
    color: '#666',
    fontSize: 11,
    marginBottom: 8,
    fontStyle: 'italic',
  },
  btn: {
    padding: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  btnActive: {
    backgroundColor: '#16c784',
  },
  btnInactive: {
    backgroundColor: '#333',
  },
  btnText: {
    fontWeight: 'bold',
    color: '#000',
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderBottomColor: '#2a2a3e',
    borderBottomWidth: 1,
  },
  infoLabel: {
    color: '#888',
    fontSize: 12,
  },
  infoValue: {
    color: '#fff',
    fontWeight: '600',
  },
  helpText: {
    color: '#aaa',
    fontSize: 12,
    lineHeight: 18,
  },
  bold: {
    fontWeight: 'bold',
    color: '#16c784',
  },
  bottomPadding: {
    height: 40,
  },
});

export default SettingsScreen;
