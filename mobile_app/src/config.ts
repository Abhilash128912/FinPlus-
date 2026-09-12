/**
 * Global Configuration for the Mobile Trading & Screener Client.
 *
 * Defaults to the developer's local Wi-Fi IP (192.168.1.36:5850).
 * When running over Tailscale VPN, set this to your PC's 100.x.y.z IP.
 * When running over Cloudflare Tunnel, set this to your https://... tunnel URL.
 */

let _apiBaseUrl = "https://finplus-g0b5.onrender.com";
let _apiKey = "";

export const getApiBaseUrl = (): string => _apiBaseUrl;

export const setApiBaseUrl = (url: string) => {
  let cleaned = url.trim();
  if (cleaned.endsWith("/")) {
    cleaned = cleaned.slice(0, -1);
  }
  _apiBaseUrl = cleaned;
};

export const getApiKey = (): string => _apiKey;

export const setApiKey = (key: string) => {
  _apiKey = key.trim();
};
