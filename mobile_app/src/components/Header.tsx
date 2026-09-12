import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Modal,
  TextInput,
  Alert,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { theme } from "../theme";
import { getApiBaseUrl, setApiBaseUrl, getApiKey, setApiKey } from "../config";
import { updateIndmoneyToken } from "../api";

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
  const [tokenInput, setTokenInput] = useState("");
  const [tokenSaving, setTokenSaving] = useState(false);

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

  const handleSaveToken = async () => {
    if (!tokenInput.trim()) {
      Alert.alert("Empty token", "Paste your fresh INDmoney access token first.");
      return;
    }
    // The token endpoint is gated the same way as every other /api/* route --
    // apply whatever's in the key field now, even if "Connect & Save" wasn't tapped.
    setApiKey(keyInput.trim());
    setTokenSaving(true);
    try {
      const res = await updateIndmoneyToken(tokenInput.trim());
      if (res.success) {
        Alert.alert("Token updated", "Live now — no restart needed.");
        setTokenInput("");
        if (onRefresh) onRefresh();
      } else {
        Alert.alert("Not saved", res.error || "INDmoney rejected the token.");
      }
    } catch (e: any) {
      Alert.alert("Failed to reach backend", e.message || "Check your server URL and key above.");
    } finally {
      setTokenSaving(false);
    }
  };

  const isTokenActive = tokenStatus?.has_token && !tokenStatus?.is_expired;
  const minsRemaining = tokenStatus?.expires_in_min;
  const isFallback = tokenStatus?.fallback_active || !isTokenActive;

  const dotColor = isTokenActive ? theme.colors.green : theme.colors.accent;
  const statusLabel = tokenStatus?.data_source
    ? tokenStatus.data_source
    : isTokenActive
    ? `INDmoney Live (${minsRemaining ? Math.round(minsRemaining) : "?"}m)`
    : "Live Cloud Direct";

  return (
    <>
      <View style={styles.headerContainer}>
        <View style={styles.leftCol}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 7 }}>
            <View style={styles.fpBadge}>
              <Text style={styles.fpBadgeText}>FP</Text>
            </View>
            <Text style={styles.logoTitle}>FINPLUS RADAR</Text>
          </View>
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
          <View style={[styles.modalCard, { maxHeight: "85%" }]}>
            <ScrollView showsVerticalScrollIndicator={false}>
              <Text style={styles.modalTitle}>Server Connection</Text>
              <Text style={styles.modalSub}>
                This app talks to the cloud backend only — there is no local
                network / PC-tethered mode. Only change this if your Render
                service URL changes.
              </Text>

              <TextInput
                style={styles.input}
                value={urlInput}
                onChangeText={setUrlInput}
                placeholder="https://your-service.onrender.com"
                placeholderTextColor={theme.colors.textDim}
                autoCapitalize="none"
                autoCorrect={false}
              />

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

              <View style={styles.divider} />

              <Text style={styles.modalTitle}>INDmoney Access Token</Text>
              <Text style={styles.modalSub}>
                INDmoney tokens expire every 24h and have no auto-refresh —
                generate a fresh one on INDmoney's access-tokens page, then
                paste it here to push it straight to the live backend. Tested
                before saving; takes effect immediately, no redeploy.
              </Text>
              <TextInput
                style={[styles.input, styles.tokenInput]}
                value={tokenInput}
                onChangeText={setTokenInput}
                placeholder="Paste the new INDmoney access token"
                placeholderTextColor={theme.colors.textDim}
                autoCapitalize="none"
                autoCorrect={false}
                multiline
              />
              <TouchableOpacity
                style={[styles.saveBtn, styles.tokenSaveBtn, tokenSaving && { opacity: 0.6 }]}
                onPress={handleSaveToken}
                disabled={tokenSaving}
              >
                {tokenSaving ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <Text style={styles.saveBtnText}>Test & Save Token</Text>
                )}
              </TouchableOpacity>
            </ScrollView>
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
  fpBadge: {
    backgroundColor: "#0f172a",
    borderWidth: 1.5,
    borderColor: "#6366f1",
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  fpBadgeText: {
    color: "#10b981",
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 0.5,
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
  divider: {
    height: 1,
    backgroundColor: theme.colors.surfaceBorder,
    marginVertical: theme.spacing.xl,
  },
  tokenInput: {
    minHeight: 70,
    textAlignVertical: "top",
    fontFamily: "monospace",
    fontSize: 12,
  },
  tokenSaveBtn: {
    alignItems: "center",
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
