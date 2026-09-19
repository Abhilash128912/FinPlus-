/**
 * Global Configuration for the Mobile Trading & Screener Client.
 *
 * Defaults to the developer's local Wi-Fi IP (192.168.1.36:5850).
 * When running over Tailscale VPN, set this to your PC's 100.x.y.z IP.
 * When running over Cloudflare Tunnel, set this to your https://... tunnel URL.
 *
 * Persisted to AsyncStorage so the server URL and X-Finplus-Key survive an
 * app restart -- previously these were plain in-memory variables that reset
 * to blank on every launch, which silently broke every authenticated
 * request once RADAR's backend started requiring the key.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

const STORAGE_KEY_URL = "finplus_api_base_url";
const STORAGE_KEY_APIKEY = "finplus_api_key";

// 2026-09-19: this was pointing at "finplus-g0b5.onrender.com", which is a
// completely different app (the Stock Screener) -- confirmed by curling it
// and getting that app's HTML back, not RADAR's /api/* routes. RADAR's real
// Render service is "FinPlus--1" (https://finplus-1.onrender.com).
let _apiBaseUrl = "https://finplus-1.onrender.com";
let _apiKey = "";
let _initialized = false;

export const getApiBaseUrl = (): string => _apiBaseUrl;

export const setApiBaseUrl = (url: string) => {
  let cleaned = url.trim();
  if (cleaned.endsWith("/")) {
    cleaned = cleaned.slice(0, -1);
  }
  _apiBaseUrl = cleaned;
  AsyncStorage.setItem(STORAGE_KEY_URL, cleaned).catch(() => {});
};

export const getApiKey = (): string => _apiKey;

export const setApiKey = (key: string) => {
  _apiKey = key.trim();
  AsyncStorage.setItem(STORAGE_KEY_APIKEY, _apiKey).catch(() => {});
};

/** Loads any previously saved URL/key into memory. Must be awaited before
 * the first API call so a saved key isn't missed on cold start. Safe to
 * call more than once -- only the first call does real work. */
export const initConfig = async (): Promise<void> => {
  if (_initialized) return;
  _initialized = true;
  try {
    const [savedUrl, savedKey] = await Promise.all([
      AsyncStorage.getItem(STORAGE_KEY_URL),
      AsyncStorage.getItem(STORAGE_KEY_APIKEY),
    ]);
    if (savedUrl) _apiBaseUrl = savedUrl;
    if (savedKey) _apiKey = savedKey;
  } catch (_) {
    // No persisted config yet, or storage unavailable -- keep defaults.
  }
};
