/**
 * Global configuration for the mobile client. Cloud-only by design -- this
 * app talks to the Render deployment of app.py, never a local/LAN address
 * (see Header.tsx's Settings modal). Persisted to SecureStore so the FinPlus
 * key and (if ever changed) the backend URL survive an app restart instead
 * of resetting to blank every time, the way a plain in-memory variable would.
 */
import * as SecureStore from "expo-secure-store";

const DEFAULT_API_BASE_URL = "https://finplus-1.onrender.com";
const URL_STORAGE_KEY = "finplus_api_base_url";
const KEY_STORAGE_KEY = "finplus_api_key";

let _apiBaseUrl = DEFAULT_API_BASE_URL;
let _apiKey = "";

export const getApiBaseUrl = (): string => _apiBaseUrl;

export const setApiBaseUrl = (url: string) => {
  let cleaned = url.trim();
  if (cleaned.endsWith("/")) {
    cleaned = cleaned.slice(0, -1);
  }
  _apiBaseUrl = cleaned;
  SecureStore.setItemAsync(URL_STORAGE_KEY, cleaned).catch(() => {});
};

export const getApiKey = (): string => _apiKey;

export const setApiKey = (key: string) => {
  _apiKey = key.trim();
  SecureStore.setItemAsync(KEY_STORAGE_KEY, _apiKey).catch(() => {});
};

// Call once at app startup (before the first screen fetches anything) to
// restore whatever was saved on a previous run. Failures are non-fatal --
// the app just falls back to the compiled-in default and an empty key.
export const loadPersistedConfig = async (): Promise<void> => {
  try {
    const [storedUrl, storedKey] = await Promise.all([
      SecureStore.getItemAsync(URL_STORAGE_KEY),
      SecureStore.getItemAsync(KEY_STORAGE_KEY),
    ]);
    if (storedUrl) _apiBaseUrl = storedUrl;
    if (storedKey) _apiKey = storedKey;
  } catch {
    // SecureStore unavailable (e.g. first run edge case) -- keep defaults.
  }
};
