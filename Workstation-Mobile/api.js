import AsyncStorage from '@react-native-async-storage/async-storage';

const DEFAULT_BASE_URL = 'http://localhost:8000';
let activeBaseUrl = DEFAULT_BASE_URL;

// Load stored URL on startup
export const initApiUrl = async () => {
  try {
    const savedUrl = await AsyncStorage.getItem('@backend_api_url');
    if (savedUrl) {
      activeBaseUrl = savedUrl.trim();
    }
  } catch (e) {
    console.error('Failed to load API URL from storage', e);
  }
  return activeBaseUrl;
};

export const getApiUrl = () => activeBaseUrl;

export const setApiUrl = async (url) => {
  try {
    const cleanUrl = url.trim().replace(/\/$/, ''); // strip trailing slash
    activeBaseUrl = cleanUrl;
    await AsyncStorage.setItem('@backend_api_url', cleanUrl);
  } catch (e) {
    console.error('Failed to save API URL to storage', e);
  }
  return activeBaseUrl;
};

// Generic fetch wrapper with timeout
const apiFetch = async (endpoint, options = {}) => {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), 20000); // 20 second timeout

  try {
    const response = await fetch(`${activeBaseUrl}${endpoint}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'Bypass-Tunnel-Reminder': 'true',
        ...options.headers,
      },
      signal: controller.signal,
    });
    clearTimeout(id);
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `HTTP Error ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    clearTimeout(id);
    if (error.name === 'AbortError') {
      throw new Error('Request timeout. Please check your network connection and server IP.');
    }
    throw error;
  }
};

// API calls
export const getSystemStatus = () => apiFetch('/api/status');
export const connectSystem = (accessToken) => 
  apiFetch('/api/connect', {
    method: 'POST',
    body: JSON.stringify({ access_token: accessToken }),
  });
export const disconnectSystem = () => apiFetch('/api/disconnect', { method: 'POST' });

export const getWatchlist = (params = {}) => {
  // Build query string manually since URLSearchParams is fully supported in RN
  const queryParts = [];
  Object.keys(params).forEach(key => {
    if (params[key] !== undefined && params[key] !== null) {
      queryParts.push(`${encodeURIComponent(key)}=${encodeURIComponent(params[key])}`);
    }
  });
  const queryString = queryParts.join('&');
  return apiFetch(`/api/watchlist?${queryString}`);
};

export const getIndices = () => apiFetch('/api/indices');

export const getStockDetails = (symbol, pivotType = 'None') => 
  apiFetch(`/api/stock/${symbol}?sr_pivot_type=${pivotType}`);

export const getMarketRegime = () => apiFetch('/api/market-regime');

export const logPaperTrade = (tradeData) => 
  apiFetch('/api/paper-trade', {
    method: 'POST',
    body: JSON.stringify(tradeData),
  });

export const getAlphaPicks = () => apiFetch('/api/alpha-picks');

export const unlockAlphaPicks = () => apiFetch('/api/alpha-picks/unlock', { method: 'POST' });

