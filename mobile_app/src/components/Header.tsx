import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Modal,
  TextInput,
  Alert,
} from "react-native";
import { theme } from "../theme";
import { getApiBaseUrl, setApiBaseUrl, getApiKey, setApiKey } from "../config";

interface HeaderProps {
  tokenStatus?: {
    has_token: boolean;
    is_expired: boolean;
    expires_in_min?: number;
    totp_configured?: boolean;
    current_totp?: string;
    data_source?: string;
    fallback_active?: boolean;
  };
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  tokenStatus,
  onRefresh,
  isRefreshing,
}) => {
  const [modalVisible, setModalVisible] = useState(false);
  const [urlInput, setUrlInput] = useState(getApiBaseUrl());
  const [keyInput, setKeyInput] = useState(getApiKey());

  const handleSaveConfig = () => {
    if (!urlInput.trim()) {
      Alert.alert("Invalid URL", "Please enter a valid server URL.");
      return;
    }
    setApiBaseUrl(urlInput.trim());
    setApiKey(keyInput.trim());
    setModalVisible(false);
    if (onRefresh) onRefresh();
  };

  const isTokenActive = tokenStatus?.has_token && !tokenStatus?.is_expired;
  const minsRemaining = tokenStatus?.expires_in_min;
  const isFallback = tokenStatus?.fallback_active || !isTokenActive;

  const dotColor = isTokenActive ? theme.colors.green : theme.colors.yellow;
  const statusLabel = isTokenActive
    ? `INDmoney Live (${minsRemaining ? Math.round(minsRemaining) : "?"}m)`
    : "Yahoo Finance (Fallback Mode)";

  return (
    <>
      <View style={styles.headerContainer}>
        <View style={styles.leftCol}>
          <Text style={styles.logoTitle}>INDMONEY TRADER</Text>
          <View style={styles.statusRow}>
            <View
              style={[
                styles.statusDot,
                { backgroundColor: dotColor },
              ]}
            />
            <Text style={styles.statusText}>{statusLabel}</Text>
            {tokenStatus?.totp_configured && (
              <View style={styles.totpBadge}>
                <Text style={styles.totpBadgeText}>TOTP AUTO</Text>
              </View>
            )}
          </View>
        </View>

        <View style={styles.rightRow}>
          <TouchableOpacity
            style={styles.iconBtn}
            onPress={onRefresh}
            disabled={isRefreshing}
          >
            <Text style={styles.iconBtnText}>{isRefreshing ? "⏳" : "🔄"}</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.iconBtn, styles.settingsBtn]}
            onPress={() => setModalVisible(true)}
          >
            <Text style={styles.iconBtnText}>⚙️</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Connection & Host Settings Modal */}
      <Modal visible={modalVisible} transparent animationType="slide">
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Server Connection</Text>
            <Text style={styles.modalSub}>
              Enter your PC's IP, Tailscale IP (100.x.y.z), or Cloudflare Tunnel URL.
            </Text>

            <TextInput
              style={styles.input}
              value={urlInput}
              onChangeText={setUrlInput}
              placeholder="http://192.168.1.36:5850"
              placeholderTextColor={theme.colors.textDim}
              autoCapitalize="none"
              autoCorrect={false}
            />

            <View style={styles.quickRows}>
              <TouchableOpacity
                style={styles.quickChip}
                onPress={() => setUrlInput("https://finplus-g0b5.onrender.com")}
              >
                <Text style={styles.quickChipText}>Render Cloud</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.quickChip}
                onPress={() => setUrlInput("http://192.168.1.36:5850")}
              >
                <Text style={styles.quickChipText}>Local Wi-Fi</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.quickChip}
                onPress={() => setUrlInput("http://localhost:5850")}
              >
                <Text style={styles.quickChipText}>Localhost</Text>
              </TouchableOpacity>
            </View>

            <Text style={[styles.modalSub, { marginBottom: 6, fontWeight: "700", color: theme.colors.text }]}>
              FinPlus Secret Key (X-Finplus-Key)
            </Text>
            <TextInput
              style={styles.input}
              value={keyInput}
              onChangeText={setKeyInput}
              placeholder="Paste X-Finplus-Key here"
              placeholderTextColor={theme.colors.textDim}
              autoCapitalize="none"
              autoCorrect={false}
            />

            <View style={styles.modalButtons}>
              <TouchableOpacity
                style={styles.cancelBtn}
                onPress={() => setModalVisible(false)}
              >
                <Text style={styles.cancelBtnText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.saveBtn}
                onPress={handleSaveConfig}
              >
                <Text style={styles.saveBtnText}>Connect & Save</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
};

const styles = StyleSheet.create({
  headerContainer: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    backgroundColor: theme.colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.surfaceBorder,
  },
  leftCol: {
    flexDirection: "column",
  },
  logoTitle: {
    fontSize: 16,
    fontWeight: "800",
    color: theme.colors.text,
    letterSpacing: 0.8,
  },
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 3,
  },
  statusDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    marginRight: 6,
  },
  statusText: {
    fontSize: 11,
    color: theme.colors.textMuted,
    fontWeight: "500",
  },
  totpBadge: {
    marginLeft: 6,
    backgroundColor: theme.colors.primaryGlow,
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 4,
    borderWidth: 0.5,
    borderColor: theme.colors.primary,
  },
  totpBadgeText: {
    fontSize: 9,
    fontWeight: "700",
    color: theme.colors.accent,
  },
  rightRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  iconBtn: {
    width: 36,
    height: 36,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.surfaceLight,
    justifyContent: "center",
    alignItems: "center",
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  settingsBtn: {
    backgroundColor: "rgba(99, 102, 241, 0.12)",
    borderColor: theme.colors.primary,
  },
  iconBtnText: {
    fontSize: 16,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.7)",
    justifyContent: "center",
    alignItems: "center",
    padding: theme.spacing.xl,
  },
  modalCard: {
    width: "100%",
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.xl,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: "700",
    color: theme.colors.text,
    marginBottom: 6,
  },
  modalSub: {
    fontSize: 12,
    color: theme.colors.textMuted,
    marginBottom: theme.spacing.lg,
    lineHeight: 18,
  },
  input: {
    backgroundColor: theme.colors.surfaceLight,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 10,
    color: theme.colors.text,
    fontSize: 14,
    marginBottom: theme.spacing.md,
  },
  quickRows: {
    flexDirection: "row",
    gap: 8,
    marginBottom: theme.spacing.xl,
  },
  quickChip: {
    backgroundColor: theme.colors.surfaceLight,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
    borderColor: theme.colors.surfaceBorder,
  },
  quickChipText: {
    fontSize: 11,
    color: theme.colors.accent,
    fontWeight: "600",
  },
  modalButtons: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: 12,
  },
  cancelBtn: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: theme.radius.md,
  },
  cancelBtnText: {
    color: theme.colors.textMuted,
    fontSize: 13,
    fontWeight: "600",
  },
  saveBtn: {
    backgroundColor: theme.colors.primary,
    paddingVertical: 10,
    paddingHorizontal: 18,
    borderRadius: theme.radius.md,
  },
  saveBtnText: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "700",
  },
});
