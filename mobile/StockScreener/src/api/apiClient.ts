import axios, { AxiosInstance } from 'axios';

interface ApiConfig {
  localhost?: string;  // e.g., http://192.168.x.x:5050
  renderUrl?: string;  // e.g., https://stock-screener-api.onrender.com
  useRender?: boolean;
}

class ApiClient {
  private client: AxiosInstance;
  private baseURL: string;

  constructor(config: ApiConfig = {}) {
    // Default to Render in production, localhost in development
    const isProduction = !__DEV__;
    const baseURL = isProduction
      ? config.renderUrl || 'https://stock-screener-api.onrender.com'
      : config.localhost || 'http://192.168.1.100:5050'; // Change IP to your laptop's IP

    this.baseURL = baseURL;
    this.client = axios.create({
      baseURL,
      timeout: 15000,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    });

    // Add interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        console.error('API Error:', {
          url: error.config?.url,
          status: error.response?.status,
          message: error.message,
        });
        return Promise.reject(error);
      }
    );
  }

  // Screener data
  async getScreenerData() {
    return this.client.post('/api/mobile/screener').then(r => r.data);
  }

  // LT Watchlist
  async getWatchlist() {
    return this.client.post('/api/mobile/watchlist').then(r => r.data);
  }

  // Holdings
  async getHoldings() {
    return this.client.post('/api/mobile/holdings').then(r => r.data);
  }

  // App status & sync
  async getStatus() {
    return this.client.post('/api/mobile/status').then(r => r.data);
  }

  // Search stocks
  async searchStocks(query: string) {
    return this.client.post(`/api/mobile/search?q=${encodeURIComponent(query)}`).then(r => r.data);
  }

  // Get stock detail
  async getStockDetail(symbol: string) {
    return this.client.post(`/api/mobile/stock?symbol=${encodeURIComponent(symbol)}`).then(r => r.data);
  }

  // Switch between localhost and Render
  switchServer(useRender: boolean, renderUrl?: string, localhostUrl?: string) {
    const url = useRender ? (renderUrl || this.baseURL) : localhostUrl;
    this.baseURL = url;
    this.client.defaults.baseURL = url;
    console.log(`Switched to: ${url}`);
  }

  getBaseURL() {
    return this.baseURL;
  }
}

export default new ApiClient({
  localhost: 'http://192.168.1.100:5050', // Change this to your laptop IP
  renderUrl: 'https://stock-screener-api.onrender.com',
  useRender: false, // Start with localhost for development
});
