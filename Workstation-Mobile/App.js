import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TouchableOpacity,
  ScrollView,
  FlatList,
  TextInput,
  Modal,
  ActivityIndicator,
  SafeAreaView,
  StatusBar,
  Dimensions,
  Alert,
  RefreshControl,
} from 'react-native';
import { WebView } from 'react-native-webview';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  initApiUrl,
  getApiUrl,
  setApiUrl,
  getSystemStatus,
  connectSystem,
  disconnectSystem,
  getWatchlist,
  getIndices,
  getStockDetails,
  getMarketRegime,
  logPaperTrade,
  getAlphaPicks,
  unlockAlphaPicks,
} from './api';
import {
  Eye,
  TrendingUp,
  Settings,
  Activity,
  RefreshCw,
  Search,
  PlusCircle,
  X,
  Database,
  Sliders,
  DollarSign,
  AlertTriangle,
  Award,
  TrendingDown,
  CheckCircle,
  Play,
  Square,
  BookOpen,
} from 'lucide-react-native';

const { width } = Dimensions.get('window');

// TradingView widget HTML generator
const getTradingViewHtml = (symbol) => `
  <!DOCTYPE html>
  <html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
      body, html { margin: 0; padding: 0; width: 100%; height: 100%; background-color: #0c0f1d; overflow: hidden; }
    </style>
  </head>
  <body>
    <div class="tradingview-widget-container" style="width: 100%; height: 100%;">
      <div id="tradingview_chart" style="width: 100%; height: 100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({
        "width": "100%",
        "height": "100%",
        "symbol": "NSE:${symbol}",
        "interval": "D",
        "timezone": "Asia/Kolkata",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "toolbar_bg": "#0c0f1d",
        "enable_publishing": false,
        "hide_top_toolbar": true,
        "hide_legend": false,
        "save_image": false,
        "allow_symbol_change": false,
        "container_id": "tradingview_chart"
      });
      </script>
    </div>
  </body>
  </html>
`;

export default function App() {
  // Navigation
  const [activeTab, setActiveTab] = useState('watchlist'); // 'watchlist', 'regime', 'trade', 'settings'

  // Server state
  const [apiUrl, setApiUrlState] = useState('https://finplus.onrender.com');
  const [systemStatus, setSystemStatus] = useState(null);
  const [indices, setIndices] = useState(null);
  const [watchlist, setWatchlist] = useState([]);
  const [regimeData, setRegimeData] = useState(null);
  const [alphaPicks, setAlphaPicks] = useState(null);
  const [alphaPicksLoading, setAlphaPicksLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [filterSignal, setFilterSignal] = useState('ALL'); // 'ALL', 'LONG', 'SHORT'
  const [filterBreakout, setFilterBreakout] = useState(0); // 0, 3, 5, 8
  const [showFiltersPanel, setShowFiltersPanel] = useState(false);

  // Detail Modal
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [selectedStockSymbol, setSelectedStockSymbol] = useState('');
  const [selectedStock, setSelectedStock] = useState(null);
  const [detailPivotType, setDetailPivotType] = useState('None'); // 'None', 'Traditional', 'Camarilla'
  const [detailModalLoading, setDetailModalLoading] = useState(false);

  // Paper Trade Form
  const [paperTradeForm, setPaperTradeForm] = useState({
    symbol: '',
    segment: 'Equity - Delivery',
    action: 'BUY',
    quantity: '10',
    entry_price: '',
    exit_price: '',
    notes: '',
  });
  const [paperTradeResult, setPaperTradeResult] = useState(null);
  const [tradeActionLoading, setTradeActionLoading] = useState(false);

  // Settings inputs
  const [tokenInput, setTokenInput] = useState('');

  // Initial load
  useEffect(() => {
    const startup = async () => {
      const url = await initApiUrl();
      setApiUrlState(url);
      
      let savedToken = null;
      // Load saved token if any
      try {
        savedToken = await AsyncStorage.getItem('@indmoney_access_token');
        if (savedToken) {
          setTokenInput(savedToken);
        }
      } catch (err) {
        console.error('Failed to load token from storage', err);
      }
      
      // Fetch status first to check if we need to auto-connect
      try {
        const statusData = await getSystemStatus().catch(() => null);
        if (statusData) {
          setSystemStatus(statusData);
          if (!statusData.token_accepted && savedToken) {
            console.log('Backend has no token, auto-connecting with saved token...');
            const res = await connectSystem(savedToken).catch(() => null);
            if (res) {
              console.log('Auto-connected successfully:', res.message);
            }
          }
        }
      } catch (e) {
        console.error('Failed to auto-connect token on startup:', e);
      }
      
      await fetchAllData();
    };
    startup();
  }, []);

  // Poll for live watchlist updates every 6 seconds when watchlist tab is active
  useEffect(() => {
    let interval = null;
    if (activeTab === 'watchlist') {
      interval = setInterval(() => {
        fetchWatchlistAndStatusSilently();
      }, 6000);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [activeTab, apiUrl]);

  // Fetch updated technical parameters when pivot type selection is updated
  useEffect(() => {
    if (showDetailModal && selectedStockSymbol) {
      const fetchUpdatedPivots = async () => {
        try {
          const data = await getStockDetails(selectedStockSymbol, detailPivotType);
          setSelectedStock(data);
        } catch (err) {
          console.error('Failed to load updated pivots', err);
        }
      };
      fetchUpdatedPivots();
    }
  }, [detailPivotType, showDetailModal, selectedStockSymbol]);

  // Fetch all endpoints
  const fetchAllData = async () => {
    setLoading(true);
    try {
      const [statusData, indicesData, wlData, rData, picksData] = await Promise.all([
        getSystemStatus().catch(() => null),
        getIndices().catch(() => null),
        getWatchlist({ sr_pivot_type: detailPivotType }).catch(() => []),
        getMarketRegime().catch(() => null),
        getAlphaPicks().catch(() => null)
      ]);

      setSystemStatus(statusData);
      setIndices(indicesData);
      setWatchlist(wlData);
      setRegimeData(rData);
      setAlphaPicks(picksData);
    } catch (e) {
      console.error('Error loading API data:', e);
    } finally {
      setLoading(false);
    }
  };

  // Silent update for live price streaming
  const fetchWatchlistAndStatusSilently = async () => {
    try {
      const [statusData, indicesData, wlData, rData, picksData] = await Promise.all([
        getSystemStatus().catch(() => null),
        getIndices().catch(() => null),
        getWatchlist({ sr_pivot_type: detailPivotType }).catch(() => []),
        getMarketRegime().catch(() => null),
        getAlphaPicks().catch(() => null)
      ]);

      if (statusData) setSystemStatus(statusData);
      if (indicesData) setIndices(indicesData);
      if (wlData) setWatchlist(wlData);
      if (rData) setRegimeData(rData);
      if (picksData) setAlphaPicks(picksData);
    } catch (e) {
      console.warn('Silent update failed:', e.message);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchAllData();
    setRefreshing(false);
  };

  // Save base URL change
  const handleSaveApiUrl = async () => {
    setLoading(true);
    try {
      const saved = await setApiUrl(apiUrl);
      Alert.alert('Success', `API Backend URL updated to: ${saved}`);
      await fetchAllData();
    } catch (e) {
      Alert.alert('Connection Error', `Failed to contact API server at: ${apiUrl}. Reason: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Sync token to launch feed
  const handleConnectToken = async () => {
    if (!tokenInput.trim()) {
      Alert.alert('Input Error', 'Please enter a valid INDmoney access token.');
      return;
    }
    setLoading(true);
    try {
      const res = await connectSystem(tokenInput);
      Alert.alert('Sync Started', res.message);
      
      // Save token in AsyncStorage so it persists
      await AsyncStorage.setItem('@indmoney_access_token', tokenInput.trim());
      
      await fetchAllData();
    } catch (e) {
      Alert.alert('Sync Error', e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    setLoading(true);
    try {
      const res = await disconnectSystem();
      Alert.alert('Disconnected', res.message);
      await fetchAllData();
    } catch (e) {
      Alert.alert('Disconnect Error', e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenDetails = async (symbol) => {
    const cleanSym = symbol.replace('.NS', '');
    setSelectedStockSymbol(cleanSym);
    setDetailModalLoading(true);
    setShowDetailModal(true);

    try {
      const data = await getStockDetails(cleanSym, detailPivotType);
      setSelectedStock(data);
    } catch (error) {
      Alert.alert('Details Error', 'Failed to load stock details: ' + error.message);
      setShowDetailModal(false);
    } finally {
      setDetailModalLoading(false);
    }
  };

  const handleRecalculatePicks = async () => {
    setAlphaPicksLoading(true);
    try {
      await unlockAlphaPicks();
      const freshPicks = await getAlphaPicks();
      setAlphaPicks(freshPicks);
      Alert.alert('Recalculated', 'Picks have been successfully unlocked and fresh opportunities selected.');
    } catch (e) {
      Alert.alert('Unlock Error', e.message);
    } finally {
      setAlphaPicksLoading(false);
    }
  };

  // Pre-fill paper trade form from watchlist detail sheet
  const handleQuickTrade = (symbol) => {
    const ltpVal = selectedStock?.live_quote?.close || selectedStock?.historical_metrics?.day_open || 0;
    const ltpStr = ltpVal > 0 ? String(ltpVal.toFixed(2)) : '';
    const wlItem = (watchlist || []).find(item => item && item.Stock && item.Stock.replace('.NS', '') === symbol);
    const isLong = wlItem && wlItem.Signal ? wlItem.Signal.includes('LONG') : true;
    
    // Suggest 3% profit target for LONG, -3% for SHORT
    const exitVal = ltpVal > 0 ? (isLong ? ltpVal * 1.03 : ltpVal * 0.97) : 0;
    const exitStr = exitVal > 0 ? String(exitVal.toFixed(2)) : '';

    setPaperTradeForm({
      symbol: symbol,
      segment: 'Equity - Delivery',
      action: isLong ? 'BUY' : 'SELL',
      quantity: '10',
      entry_price: ltpStr,
      exit_price: exitStr,
      notes: `Quick log from Watchlist scanner details. Trend expected: ${isLong ? 'Bullish' : 'Bearish'}.`,
    });
    setPaperTradeResult(null);
    setShowDetailModal(false);
    setActiveTab('trade');
  };

  // Submit Paper Trade Log
  const handleLogPaperTradeSubmit = async () => {
    const { symbol, segment, action, quantity, entry_price, exit_price } = paperTradeForm;
    if (!symbol.trim() || !quantity || !entry_price || !exit_price) {
      Alert.alert('Validation Error', 'Please complete all required fields.');
      return;
    }

    setTradeActionLoading(true);
    try {
      const res = await logPaperTrade({
        symbol: symbol.toUpperCase().trim(),
        segment,
        action,
        quantity: parseFloat(quantity),
        entry_price: parseFloat(entry_price),
        exit_price: parseFloat(exit_price),
        notes: paperTradeForm.notes,
        source_screener: 'Mobile Workstation',
      });
      setPaperTradeResult(res);
    } catch (e) {
      Alert.alert('Logging Error', e.message);
    } finally {
      setTradeActionLoading(false);
    }
  };

  // Helper colors
  const getScoreBgColor = (score) => {
    if (score >= 8) return styles.bgGreenGlow;
    if (score >= 5) return styles.bgYellowGlow;
    return styles.bgSlate;
  };

  const getScoreTextColor = (score) => {
    if (score >= 8) return '#10b981';
    if (score >= 5) return '#eab308';
    return '#94a3b8';
  };

  // Watchlist List Header components
  const renderWatchlistHeader = () => {
    // Indices Ticker
    const nifty = indices?.NIFTY_50 || {};
    const bank = indices?.BANK_NIFTY || {};
    const niftyPrice = nifty.ltp || nifty.last_price || nifty.close || 0;
    const niftyChg = nifty.day_change_percentage || nifty.change_percentage || 0;
    const bankPrice = bank.ltp || bank.last_price || bank.close || 0;
    const bankChg = bank.day_change_percentage || bank.change_percentage || 0;

    // WS Connection State
    const ws = systemStatus?.websocket || {};
    const hist = systemStatus?.historical_data || {};
    const isWsConnected = ws.connected;

    // Market Breadth Trend Banner variables
    const broad = regimeData?.broad_market || {};
    const advances = broad.advances || 0;
    const declines = broad.declines || 0;
    const uptrend = broad.uptrend_count || 0;
    const downtrend = broad.downtrend_count || 0;
    const neutral = broad.neutral_count || 0;

    return (
      <View style={styles.headerBlock}>
        {/* Indices Ticker */}
        <View style={styles.indicesRow}>
          <View style={[styles.indexCard, niftyChg >= 0 ? styles.borderGreen : styles.borderRed]}>
            <Text style={styles.indexLabel}>NIFTY 50</Text>
            <Text style={styles.indexValue}>{niftyPrice ? Number(niftyPrice).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'}</Text>
            <Text style={[styles.indexChange, niftyChg >= 0 ? styles.textGreen : styles.textRed]}>
              {niftyChg >= 0 ? '▲ +' : '▼ '}{Number(niftyChg).toFixed(2)}%
            </Text>
          </View>
          <View style={[styles.indexCard, bankChg >= 0 ? styles.borderGreen : styles.borderRed]}>
            <Text style={styles.indexLabel}>BANK NIFTY</Text>
            <Text style={styles.indexValue}>{bankPrice ? Number(bankPrice).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'}</Text>
            <Text style={[styles.indexChange, bankChg >= 0 ? styles.textGreen : styles.textRed]}>
              {bankChg >= 0 ? '▲ +' : '▼ '}{Number(bankChg).toFixed(2)}%
            </Text>
          </View>
        </View>

        {/* Connection Status Pill Banner */}
        <View style={styles.statusPills}>
          <View style={styles.pill}>
            <View style={[styles.glowIndicator, { backgroundColor: isWsConnected ? '#10b981' : '#f43f5e' }]} />
            <Text style={styles.pillText}>Feed: {ws.status || 'Disconnected'}</Text>
          </View>
          <View style={styles.pill}>
            <View style={[styles.glowIndicator, { backgroundColor: hist.status === 'Loaded' ? '#10b981' : '#eab308' }]} />
            <Text style={styles.pillText}>History: {hist.status || 'Idle'}</Text>
          </View>
          {systemStatus && !systemStatus.token_accepted && (
            <View style={[styles.pill, styles.pillWarning]}>
              <AlertTriangle size={12} color="#eab308" />
              <Text style={[styles.pillText, { color: '#eab308', marginLeft: 4 }]}>Token Needed</Text>
            </View>
          )}
        </View>

        {/* Market Breadth Trend Banner */}
        {regimeData && regimeData.broad_market && (
          <View style={styles.trendBanner}>
            <View style={styles.trendRow}>
              <Text style={styles.trendLabel}>MARKET BREADTH</Text>
              <Text style={styles.trendRatioText}>
                Adv/Dec Ratio: {declines > 0 ? (advances / declines).toFixed(2) : advances}
              </Text>
            </View>
            <View style={styles.breadthBarContainer}>
              <View style={[styles.breadthSegment, { flex: Math.max(1, uptrend), backgroundColor: '#10b981' }]} />
              <View style={[styles.breadthSegment, { flex: Math.max(1, downtrend), backgroundColor: '#f43f5e' }]} />
              <View style={[styles.breadthSegment, { flex: Math.max(1, neutral), backgroundColor: '#475569' }]} />
            </View>
            <View style={styles.trendCountsRow}>
              <Text style={styles.trendCountGreen}>▲ {uptrend} Positive</Text>
              <Text style={styles.trendCountRed}>▼ {downtrend} Negative</Text>
              <Text style={styles.trendCountNeutral}>⬦ {neutral} Neutral</Text>
            </View>
          </View>
        )}

        {/* Alpha Picks Header & Action */}
        <View style={styles.alphaPicksHeaderRow}>
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Award size={18} color="#eab308" />
            <Text style={styles.alphaPicksTitle}>ALPHA PICKS OF THE DAY</Text>
          </View>
          {alphaPicks && alphaPicks.locked && (
            <TouchableOpacity 
              style={styles.recalcBtn} 
              onPress={handleRecalculatePicks}
              disabled={alphaPicksLoading}
            >
              {alphaPicksLoading ? (
                <ActivityIndicator size="small" color="#eab308" />
              ) : (
                <Text style={styles.recalcBtnText}>🔄 RECALCULATE</Text>
              )}
            </TouchableOpacity>
          )}
        </View>

        {/* Carousel ScrollView */}
        {alphaPicksLoading ? (
          <View style={styles.picksLoader}>
            <ActivityIndicator size="small" color="#06b6d4" />
            <Text style={styles.picksLoaderText}>Scanning active breakouts...</Text>
          </View>
        ) : alphaPicks ? (
          <ScrollView 
            horizontal 
            showsHorizontalScrollIndicator={false}
            snapToInterval={width - 48 + 12} // snap to card width + margin
            decelerationRate="fast"
            contentContainerStyle={styles.picksCarousel}
          >
            {/* Card 1: Intraday Pick */}
            {alphaPicks.intraday ? (
              <View style={[styles.pickCard, styles.borderGold]}>
                <View style={styles.pickCardHeader}>
                  <Text style={styles.pickCardSub}>⚡ INTRADAY BREAKOUT</Text>
                  <Text style={styles.pickTime}>{alphaPicks.intraday.Suggested_At}</Text>
                </View>
                <View style={styles.pickSymbolRow}>
                  <Text style={styles.pickSymbol}>{alphaPicks.intraday.Stock}</Text>
                  <View style={[styles.signalBadge, alphaPicks.intraday.Signal === 'LONG' ? styles.badgeGreen : styles.badgeRed]}>
                    <Text style={[styles.signalBadgeText, alphaPicks.intraday.Signal === 'LONG' ? styles.textGreen : styles.textRed]}>
                      {alphaPicks.intraday.Signal}
                    </Text>
                  </View>
                </View>
                <View style={styles.pickDetailRow}>
                  <View>
                    <Text style={styles.pickLabel}>LTP</Text>
                    <Text style={styles.pickValue}>₹{Number(alphaPicks.intraday.LTP || 0).toFixed(2)}</Text>
                    <Text style={[styles.pickChange, alphaPicks.intraday["Change %"] >= 0 ? styles.textGreen : styles.textRed]}>
                      {alphaPicks.intraday["Change %"] >= 0 ? '+' : ''}{alphaPicks.intraday["Change %"]}%
                    </Text>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={styles.pickLabel}>Score / Conf</Text>
                    <Text style={styles.pickValueText}>{alphaPicks.intraday.Score}</Text>
                    <Text style={styles.pickSubText}>Conf: {alphaPicks.intraday.Confidence}% ({alphaPicks.intraday.Quality})</Text>
                  </View>
                </View>
                <View style={styles.levelsRow}>
                  <Text style={styles.levelText}>Entry: <Text style={styles.levelVal}>₹{Number(alphaPicks.intraday.Entry_Price || 0).toFixed(2)}</Text></Text>
                  <Text style={styles.levelText}>Tgt: <Text style={[styles.levelVal, styles.textGreen]}>₹{Number(alphaPicks.intraday.Target || 0).toFixed(2)}</Text></Text>
                  <Text style={styles.levelText}>SL: <Text style={[styles.levelVal, styles.textRed]}>₹{Number(alphaPicks.intraday.Stop_Loss || 0).toFixed(2)}</Text></Text>
                </View>
              </View>
            ) : (
              <View style={[styles.pickCard, styles.pickCardEmpty]}>
                <Text style={styles.emptyCardTitle}>⚡ INTRADAY BREAKOUT</Text>
                <Text style={styles.emptyCardText}>No active intraday breakouts detected above thresholds.</Text>
              </View>
            )}

            {/* Card 2: Stock Option Pick */}
            {alphaPicks.option ? (
              <View style={[styles.pickCard, styles.borderCyan]}>
                <View style={styles.pickCardHeader}>
                  <Text style={styles.pickCardSub}>🎯 STOCK OPTION CALL</Text>
                  <Text style={styles.pickTime}>{alphaPicks.option.Suggested_At}</Text>
                </View>
                <View style={styles.pickSymbolRow}>
                  <Text style={styles.pickSymbol}>{alphaPicks.option.Contract}</Text>
                  <View style={[styles.signalBadge, styles.badgeGreen]}>
                    <Text style={[styles.signalBadgeText, styles.textGreen]}>BUY</Text>
                  </View>
                </View>
                <View style={styles.pickDetailRow}>
                  <View>
                    <Text style={styles.pickLabel}>Spot LTP</Text>
                    <Text style={styles.pickValue}>₹{Number(alphaPicks.option.LTP || 0).toFixed(2)}</Text>
                    <Text style={[styles.pickChange, alphaPicks.option["Change %"] >= 0 ? styles.textGreen : styles.textRed]}>
                      {alphaPicks.option["Change %"] >= 0 ? '+' : ''}{alphaPicks.option["Change %"]}%
                    </Text>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={styles.pickLabel}>Lot Size / Lots</Text>
                    <Text style={styles.pickValueText}>{alphaPicks.option.Lot_Size || 0} Qty</Text>
                    <Text style={styles.pickSubText}>{alphaPicks.option.Lots || 0} Lot(s)</Text>
                  </View>
                </View>
                <View style={styles.levelsRow}>
                  <Text style={styles.levelText}>Premium: <Text style={styles.levelVal}>₹{Number(alphaPicks.option.Entry_Price || 0).toFixed(1)}</Text></Text>
                  <Text style={styles.levelText}>Tgt: <Text style={[styles.levelVal, styles.textGreen]}>₹{Number(alphaPicks.option.Target || 0).toFixed(1)}</Text></Text>
                  <Text style={styles.levelText}>SL: <Text style={[styles.levelVal, styles.textRed]}>₹{Number(alphaPicks.option.Stop_Loss || 0).toFixed(1)}</Text></Text>
                </View>
              </View>
            ) : (
              <View style={[styles.pickCard, styles.pickCardEmpty]}>
                <Text style={styles.emptyCardTitle}>🎯 STOCK OPTION CALL</Text>
                <Text style={styles.emptyCardText}>No liquid stock option opportunities confirmed.</Text>
              </View>
            )}

            {/* Card 3: Nifty Option Pick */}
            {alphaPicks.nifty_option && alphaPicks.nifty_option.Signal !== 'NEUTRAL / NO TRADE' ? (
              <View style={[styles.pickCard, styles.borderPurple]}>
                <View style={styles.pickCardHeader}>
                  <Text style={styles.pickCardSub}>📊 NIFTY INDEX CALL</Text>
                  <Text style={styles.pickTime}>{alphaPicks.nifty_option.Suggested_At}</Text>
                </View>
                <View style={styles.pickSymbolRow}>
                  <Text style={[styles.pickSymbol, { fontSize: 13 }]}>{alphaPicks.nifty_option.Contract}</Text>
                  <View style={[styles.signalBadge, alphaPicks.nifty_option.Signal.includes('CALL') ? styles.badgeGreen : styles.badgeRed]}>
                    <Text style={[styles.signalBadgeText, alphaPicks.nifty_option.Signal.includes('CALL') ? styles.textGreen : styles.textRed]}>
                      {alphaPicks.nifty_option.Signal.includes('CALL') ? 'CALL' : 'PUT'}
                    </Text>
                  </View>
                </View>
                <View style={styles.pickDetailRow}>
                  <View>
                    <Text style={styles.pickLabel}>Nifty Spot</Text>
                    <Text style={styles.pickValue}>{Number(alphaPicks.nifty_option.Nifty_LTP || 0).toFixed(2)}</Text>
                    <Text style={styles.pickSubText}>PCR: {alphaPicks.nifty_option.PCR}</Text>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={styles.pickLabel}>Support / Resistance</Text>
                    <Text style={styles.pickSubText}>Sup: {Number(alphaPicks.nifty_option.Support || 0).toFixed(0)}</Text>
                    <Text style={styles.pickSubText}>Res: {Number(alphaPicks.nifty_option.Resistance || 0).toFixed(0)}</Text>
                  </View>
                </View>
                <View style={styles.levelsRow}>
                  <Text style={styles.levelText}>Entry: <Text style={styles.levelVal}>₹{Number(alphaPicks.nifty_option.Entry_Price || 0).toFixed(1)}</Text></Text>
                  <Text style={styles.levelText}>Tgt: <Text style={[styles.levelVal, styles.textGreen]}>₹{Number(alphaPicks.nifty_option.Target || 0).toFixed(1)}</Text></Text>
                  <Text style={styles.levelText}>SL: <Text style={[styles.levelVal, styles.textRed]}>₹{Number(alphaPicks.nifty_option.Stop_Loss || 0).toFixed(1)}</Text></Text>
                </View>
              </View>
            ) : (
              <View style={[styles.pickCard, styles.pickCardEmpty]}>
                <Text style={styles.emptyCardTitle}>📊 NIFTY INDEX CALL</Text>
                <Text style={styles.emptyCardText}>Nifty RSI is Neutral. No active index calls suggested.</Text>
              </View>
            )}

            {/* Card 4: Swing Pick */}
            {alphaPicks.swing ? (
              <View style={[styles.pickCard, styles.borderGold]}>
                <View style={styles.pickCardHeader}>
                  <Text style={styles.pickCardSub}>⭐ SWING ALPHA PICK</Text>
                  <Text style={styles.pickTime}>{alphaPicks.swing.Suggested_At}</Text>
                </View>
                <View style={styles.pickSymbolRow}>
                  <View>
                    <Text style={styles.pickSymbol}>{alphaPicks.swing.Stock}</Text>
                    <Text style={styles.pickCompany} numberOfLines={1}>{alphaPicks.swing.Company}</Text>
                  </View>
                  <View style={[styles.signalBadge, styles.badgeGreen]}>
                    <Text style={[styles.signalBadgeText, styles.textGreen]}>SWING</Text>
                  </View>
                </View>
                <View style={styles.pickDetailRow}>
                  <View>
                    <Text style={styles.pickLabel}>LTP</Text>
                    <Text style={styles.pickValue}>₹{Number(alphaPicks.swing.LTP || 0).toFixed(2)}</Text>
                    <Text style={[styles.pickChange, alphaPicks.swing["Change %"] >= 0 ? styles.textGreen : styles.textRed]}>
                      {alphaPicks.swing["Change %"] >= 0 ? '+' : ''}{alphaPicks.swing["Change %"]}%
                    </Text>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={styles.pickLabel}>Quant Score</Text>
                    <Text style={styles.pickValueText}>{alphaPicks.swing.Total}/100</Text>
                    <Text style={styles.pickSubText}>Funda:{alphaPicks.swing.Funda} | Mntm:{alphaPicks.swing.Mntm}</Text>
                  </View>
                </View>
                <View style={styles.levelsRow}>
                  <Text style={styles.levelText}>Entry: <Text style={styles.levelVal}>₹{Number(alphaPicks.swing.Entry_Price || 0).toFixed(2)}</Text></Text>
                  <Text style={styles.levelText}>Tgt: <Text style={[styles.levelVal, styles.textGreen]}>₹{Number(alphaPicks.swing.Target || 0).toFixed(2)}</Text></Text>
                  <Text style={styles.levelText}>SL: <Text style={[styles.levelVal, styles.textRed]}>₹{Number(alphaPicks.swing.Stop_Loss || 0).toFixed(2)}</Text></Text>
                </View>
              </View>
            ) : (
              <View style={[styles.pickCard, styles.pickCardEmpty]}>
                <Text style={styles.emptyCardTitle}>⭐ SWING ALPHA PICK</Text>
                <Text style={styles.emptyCardText}>No Swing picks active in nifty500_scanner database.</Text>
              </View>
            )}
          </ScrollView>
        ) : (
          <View style={styles.picksCarouselPlaceholder}>
            <Text style={styles.placeholderText}>
              Sync token and start WebSocket feed to fetch Alpha Picks of the Day.
            </Text>
          </View>
        )}

        {/* Search and Filters Toggle */}
        <View style={styles.searchContainer}>
          <View style={styles.searchBar}>
            <Search size={16} color="#94a3b8" />
            <TextInput
              style={styles.searchInput}
              placeholder="Search ticker, segment or sector..."
              placeholderTextColor="#64748b"
              value={searchQuery}
              onChangeText={setSearchQuery}
            />
            {searchQuery.length > 0 && (
              <TouchableOpacity onPress={() => setSearchQuery('')}>
                <X size={16} color="#94a3b8" />
              </TouchableOpacity>
            )}
          </View>
          <TouchableOpacity
            style={[styles.filtersToggleBtn, showFiltersPanel && styles.filtersToggleBtnActive]}
            onPress={() => setShowFiltersPanel(!showFiltersPanel)}
          >
            <Sliders size={18} color={showFiltersPanel ? '#06b6d4' : '#f8fafc'} />
          </TouchableOpacity>
        </View>

        {/* Advanced Filters Panel */}
        {showFiltersPanel && (
          <View style={styles.filtersPanel}>
            <Text style={styles.panelTitle}>Signal Filter</Text>
            <View style={styles.filterRow}>
              {['ALL', 'LONG', 'SHORT'].map((sig) => (
                <TouchableOpacity
                  key={sig}
                  style={[styles.filterPill, filterSignal === sig && styles.filterPillActive]}
                  onPress={() => setFilterSignal(sig)}
                >
                  <Text style={[styles.filterPillText, filterSignal === sig && styles.filterPillTextActive]}>
                    {sig}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <Text style={styles.panelTitle}>Min Breakout Score: {filterBreakout}+</Text>
            <View style={styles.filterRow}>
              {[0, 3, 5, 8].map((score) => (
                <TouchableOpacity
                  key={score}
                  style={[styles.filterPill, filterBreakout === score && styles.filterPillActive]}
                  onPress={() => setFilterBreakout(score)}
                >
                  <Text style={[styles.filterPillText, filterBreakout === score && styles.filterPillTextActive]}>
                    {score === 0 ? 'All Scores' : `${score}+`}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        )}
      </View>
    );
  };

  // Watchlist item renderer
  const renderWatchlistItem = ({ item }) => {
    if (!item || !item.Stock) return null;
    const isLong = item.Signal ? item.Signal.includes('LONG') : true;
    const changePct = Number(item["Change %"] || 0);
    const isTopPick = (item.Score || 0) >= 8 || item.Score === item.Total_Checks;

    return (
      <TouchableOpacity
        style={[styles.signalCard, isTopPick && styles.topPickCard]}
        onPress={() => handleOpenDetails(item.Stock)}
        activeOpacity={0.7}
      >
        <View style={styles.cardHeader}>
          <View>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Text style={styles.cardSymbol}>{item.Stock.replace('.NS', '')}</Text>
              {isTopPick && (
                <View style={styles.topPickBadge}>
                  <Text style={styles.topPickBadgeText}>TOP PICK</Text>
                </View>
              )}
            </View>
            <Text style={styles.cardSector}>{item.Sector || 'Other'}</Text>
          </View>
          <View style={[styles.signalBadge, isLong ? styles.badgeGreen : styles.badgeRed]}>
            <Text style={[styles.signalBadgeText, isLong ? styles.textGreen : styles.textRed]}>
              {item.Signal}
            </Text>
          </View>
        </View>

        <View style={styles.cardBody}>
          <View style={styles.metricColumn}>
            <Text style={styles.metricLabel}>LTP</Text>
            <Text style={styles.metricValue}>₹{Number(item.LTP || 0).toFixed(2)}</Text>
            <Text style={[styles.metricSubValue, changePct >= 0 ? styles.textGreen : styles.textRed]}>
              {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
            </Text>
          </View>

          <View style={styles.metricColumn}>
            <Text style={styles.metricLabel}>R-Vol</Text>
            <Text style={styles.metricValue}>{Number(item.RVOL || 0).toFixed(1)}x</Text>
            <Text style={styles.metricSubValue}>Breakout: {item.Score}/{item.Total_Checks || 8}</Text>
          </View>

          <View style={styles.metricColumnRight}>
            <Text style={styles.metricLabel}>Opportunity</Text>
            <View style={[styles.scoreBadge, getScoreBgColor(item.Confidence)]}>
              <Text style={[styles.scoreBadgeText, { color: getScoreTextColor(item.Confidence) }]}>
                {item.Confidence}
              </Text>
            </View>
            <Text style={styles.metricSubValue}>{item.Quality} (Win: {item.Win_Rate}%)</Text>
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  // Filters logic
  const filteredWatchlist = (watchlist || []).filter((item) => {
    if (!item || !item.Stock) return false;
    const symbolMatch =
      item.Stock.toUpperCase().includes(searchQuery.toUpperCase()) ||
      (item.Sector && item.Sector.toUpperCase().includes(searchQuery.toUpperCase()));
    const signalMatch = filterSignal === 'ALL' || (item.Signal && item.Signal.includes(filterSignal));
    const breakoutMatch = (item.Score || 0) >= filterBreakout;
    return symbolMatch && signalMatch && breakoutMatch;
  });

  // Watchlist Tab
  const renderWatchlistTab = () => {
    if (loading && watchlist.length === 0) {
      return (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#06b6d4" />
          <Text style={styles.loadingText}>Fetching live workstation scanner signals...</Text>
        </View>
      );
    }

    return (
      <FlatList
        data={filteredWatchlist}
        renderItem={renderWatchlistItem}
        keyExtractor={(item) => item.Stock}
        contentContainerStyle={styles.listContent}
        ListHeaderComponent={renderWatchlistHeader}
        refreshing={refreshing}
        onRefresh={handleRefresh}
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Award size={48} color="#475569" />
            <Text style={styles.emptyText}>No matching trading opportunities found.</Text>
            <Text style={styles.emptySubText}>
              Adjust your scanner thresholds in filters or check server connectivity.
            </Text>
          </View>
        }
      />
    );
  };

  // Market Regime Tab
  const renderRegimeTab = () => {
    if (loading && !regimeData) {
      return (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#06b6d4" />
          <Text style={styles.loadingText}>Computing market regime indices...</Text>
        </View>
      );
    }

    const broad = regimeData?.broad_market || {};
    const regime = regimeData?.regime || {};
    const edge = regimeData?.edge_index || 0;
    const moneyFlow = regimeData?.money_flow || [];

    // Advance Decline Ratio
    const advances = broad.advances || 0;
    const declines = broad.declines || 0;
    const adTotal = advances + declines;
    const adRatio = adTotal > 0 ? (advances / adTotal) * 100 : 50;

    // Edge Index gauge labeling
    let edgeLabel = 'Neutral';
    let edgeColor = '#eab308';
    if (edge >= 0.8) {
      edgeLabel = 'Extreme Greed';
      edgeColor = '#10b981';
    } else if (edge >= 0.6) {
      edgeLabel = 'Greed';
      edgeColor = '#059669';
    } else if (edge <= 0.2) {
      edgeLabel = 'Extreme Fear';
      edgeColor = '#f43f5e';
    } else if (edge <= 0.4) {
      edgeLabel = 'Fear';
      edgeColor = '#b91c1c';
    }

    return (
      <ScrollView
        style={styles.tabScroll}
        contentContainerStyle={styles.scrollContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor="#06b6d4" colors={["#06b6d4"]} />}
      >
        {/* Regime Overview card */}
        <View style={styles.regimeCard}>
          <Text style={styles.regimeCardTitle}>Market Regime State</Text>
          <View style={styles.regimeRow}>
            <View style={styles.regimeItem}>
              <Text style={styles.regimeLabel}>Broad Trend</Text>
              <Text style={[styles.regimeValue, broad.trend === 'UPTREND' ? styles.textGreen : styles.textRed]}>
                {broad.trend || 'UNKNOWN'}
              </Text>
            </View>
            <View style={styles.regimeItem}>
              <Text style={styles.regimeLabel}>Regime Classification</Text>
              <Text style={[styles.regimeValue, { color: '#06b6d4' }]}>
                {regime.regime || 'Sideways / Load'}
              </Text>
            </View>
          </View>

          {/* Advance / Decline Bar */}
          <Text style={styles.progressBarLabel}>
            Advances: {advances} | Declines: {declines} (Ratio: {declines > 0 ? (advances / declines).toFixed(2) : advances.toString()})
          </Text>
          <View style={styles.progressBarBg}>
            <View style={[styles.progressBarFill, { width: `${adRatio}%`, backgroundColor: '#10b981' }]} />
          </View>
        </View>

        {/* Edge Index dial bar */}
        <View style={styles.regimeCard}>
          <Text style={styles.regimeCardTitle}>Edge Index (Greed & Fear)</Text>
          <View style={styles.gaugeHeader}>
            <Text style={[styles.gaugeValue, { color: edgeColor }]}>{(edge * 100).toFixed(0)}%</Text>
            <Text style={[styles.gaugeLabel, { color: edgeColor }]}>{edgeLabel}</Text>
          </View>
          <View style={styles.progressBarBg}>
            <View style={[styles.progressBarFill, { width: `${edge * 100}%`, backgroundColor: edgeColor }]} />
          </View>
          <Text style={styles.regimeDesc}>
            Calculated from raw RSI rankings, momentum indicators, and advance-decline volume ratios across our 50-stock watchlist universe.
          </Text>
        </View>

        {/* Sector Strength & Money Flow list */}
        <View style={styles.regimeCard}>
          <Text style={styles.regimeCardTitle}>Sector Money Flow Heatmap</Text>
          {moneyFlow.length === 0 ? (
            <Text style={styles.noDataText}>No sector money flow statistics computed.</Text>
          ) : (
            moneyFlow.map((sec, idx) => {
              const val = Number(sec.MoneyFlow || 0);
              const change = Number(sec.DayChange || 0);
              return (
                <View key={sec.Sector || idx} style={styles.sectorRow}>
                  <View style={{ flex: 2 }}>
                    <Text style={styles.sectorName}>{sec.Sector}</Text>
                    <Text style={styles.sectorCount}>{sec.StocksCount} Stocks</Text>
                  </View>
                  <View style={{ flex: 1, alignItems: 'flex-end' }}>
                    <Text style={styles.sectorVal}>₹{val.toFixed(1)} Cr</Text>
                    <Text style={[styles.sectorChange, change >= 0 ? styles.textGreen : styles.textRed]}>
                      {change >= 0 ? '+' : ''}{change.toFixed(2)}%
                    </Text>
                  </View>
                </View>
              );
            })
          )}
        </View>
      </ScrollView>
    );
  };

  // Paper Trading Tab
  const renderTradeTab = () => {
    // If trade saved successfully, show receipt card
    if (paperTradeResult) {
      const isPnLPositive = paperTradeResult.metrics?.net_pnl >= 0;
      return (
        <ScrollView style={styles.tabScroll} contentContainerStyle={styles.scrollContent}>
          <View style={styles.tradeReceiptCard}>
            <View style={styles.receiptHeader}>
              <CheckCircle size={48} color="#10b981" />
              <Text style={styles.receiptTitle}>Trade Logged successfully!</Text>
              <Text style={styles.receiptTradeId}>ID: #{paperTradeResult.trade_id}</Text>
            </View>

            <View style={styles.receiptDivider} />

            <View style={styles.receiptDetails}>
              <View style={styles.receiptRow}>
                <Text style={styles.receiptLabel}>Ticker / Action</Text>
                <Text style={styles.receiptVal}>
                  {paperTradeForm.symbol.toUpperCase()} - {paperTradeForm.action}
                </Text>
              </View>
              <View style={styles.receiptRow}>
                <Text style={styles.receiptLabel}>Segment</Text>
                <Text style={styles.receiptVal}>{paperTradeForm.segment}</Text>
              </View>
              <View style={styles.receiptRow}>
                <Text style={styles.receiptLabel}>Quantity</Text>
                <Text style={styles.receiptVal}>{paperTradeForm.quantity}</Text>
              </View>
              <View style={styles.receiptRow}>
                <Text style={styles.receiptLabel}>Prices (Entry / Exit)</Text>
                <Text style={styles.receiptVal}>
                  ₹{Number(paperTradeForm.entry_price).toFixed(2)} / ₹{Number(paperTradeForm.exit_price).toFixed(2)}
                </Text>
              </View>
              <View style={styles.receiptRow}>
                <Text style={styles.receiptLabel}>Taxes & Charges</Text>
                <Text style={[styles.receiptVal, { color: '#f43f5e' }]}>
                  -₹{Number(paperTradeResult.metrics?.total_charges || 0).toFixed(2)}
                </Text>
              </View>

              <View style={styles.receiptDivider} />

              <View style={styles.receiptRow}>
                <Text style={[styles.receiptLabel, { fontSize: 18, fontWeight: 'bold' }]}>Net P&L</Text>
                <Text
                  style={[
                    styles.receiptVal,
                    { fontSize: 20, fontWeight: 'bold' },
                    isPnLPositive ? styles.textGreen : styles.textRed,
                  ]}
                >
                  {isPnLPositive ? '+' : ''}₹{Number(paperTradeResult.metrics?.net_pnl || 0).toFixed(2)}
                </Text>
              </View>
            </View>

            <TouchableOpacity
              style={styles.resetTradeBtn}
              onPress={() => {
                setPaperTradeResult(null);
                setPaperTradeForm({
                  symbol: '',
                  segment: 'Equity - Delivery',
                  action: 'BUY',
                  quantity: '10',
                  entry_price: '',
                  exit_price: '',
                  notes: '',
                });
              }}
            >
              <Text style={styles.resetTradeBtnText}>LOG ANOTHER TRADE</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      );
    }

    return (
      <ScrollView style={styles.tabScroll} contentContainerStyle={styles.scrollContent}>
        <View style={styles.tradeFormCard}>
          <Text style={styles.formTitle}>Paper Trading Log console</Text>

          {/* Symbol */}
          <Text style={styles.inputLabel}>Stock Symbol (e.g. RELIANCE)</Text>
          <TextInput
            style={styles.formInput}
            value={paperTradeForm.symbol}
            onChangeText={(txt) => setPaperTradeForm({ ...paperTradeForm, symbol: txt })}
            placeholder="Enter Stock Symbol"
            placeholderTextColor="#64748b"
            autoCapitalize="characters"
          />

          {/* Action toggle buttons */}
          <Text style={styles.inputLabel}>Transaction Action</Text>
          <View style={styles.actionToggleRow}>
            {['BUY', 'SELL'].map((act) => (
              <TouchableOpacity
                key={act}
                style={[
                  styles.actionBtn,
                  paperTradeForm.action === act && (act === 'BUY' ? styles.actionBtnBuy : styles.actionBtnSell),
                ]}
                onPress={() => setPaperTradeForm({ ...paperTradeForm, action: act })}
              >
                <Text
                  style={[
                    styles.actionBtnText,
                    paperTradeForm.action === act && styles.actionBtnTextActive,
                  ]}
                >
                  {act}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Segment selection */}
          <Text style={styles.inputLabel}>Market Segment (zero brokerage for Equity-Delivery)</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.segmentScroll}>
            {[
              'Equity - Delivery',
              'Equity - Intraday',
              'Futures',
              'Options',
            ].map((seg) => (
              <TouchableOpacity
                key={seg}
                style={[
                  styles.segmentPill,
                  paperTradeForm.segment === seg && styles.segmentPillActive,
                ]}
                onPress={() => setPaperTradeForm({ ...paperTradeForm, segment: seg })}
              >
                <Text
                  style={[
                    styles.segmentPillText,
                    paperTradeForm.segment === seg && styles.segmentPillTextActive,
                  ]}
                >
                  {seg}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          {/* Numerical inputs row */}
          <View style={styles.formGridRow}>
            <View style={{ flex: 1, marginRight: 8 }}>
              <Text style={styles.inputLabel}>Quantity</Text>
              <TextInput
                style={styles.formInput}
                keyboardType="numeric"
                value={paperTradeForm.quantity}
                onChangeText={(txt) => setPaperTradeForm({ ...paperTradeForm, quantity: txt })}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.inputLabel}>Entry Price (₹)</Text>
              <TextInput
                style={styles.formInput}
                keyboardType="numeric"
                value={paperTradeForm.entry_price}
                onChangeText={(txt) => setPaperTradeForm({ ...paperTradeForm, entry_price: txt })}
                placeholder="0.00"
                placeholderTextColor="#64748b"
              />
            </View>
          </View>

          <Text style={styles.inputLabel}>Exit Price Target (₹)</Text>
          <TextInput
            style={styles.formInput}
            keyboardType="numeric"
            value={paperTradeForm.exit_price}
            onChangeText={(txt) => setPaperTradeForm({ ...paperTradeForm, exit_price: txt })}
            placeholder="0.00"
            placeholderTextColor="#64748b"
          />

          {/* Notes */}
          <Text style={styles.inputLabel}>Log Notes / Strategy Context</Text>
          <TextInput
            style={[styles.formInput, { height: 64, textAlignVertical: 'top' }]}
            multiline
            numberOfLines={3}
            value={paperTradeForm.notes}
            onChangeText={(txt) => setPaperTradeForm({ ...paperTradeForm, notes: txt })}
            placeholder="Breakout strategy name, chart patterns observed, target justifications..."
            placeholderTextColor="#64748b"
          />

          {/* Submit button */}
          <TouchableOpacity
            style={styles.submitLogBtn}
            onPress={handleLogPaperTradeSubmit}
            disabled={tradeActionLoading}
          >
            {tradeActionLoading ? (
              <ActivityIndicator size="small" color="#f8fafc" />
            ) : (
              <Text style={styles.submitLogBtnText}>LOG TRANSACTION</Text>
            )}
          </TouchableOpacity>
        </View>
      </ScrollView>
    );
  };

  // Settings Tab
  const renderSettingsTab = () => {
    return (
      <ScrollView style={styles.tabScroll} contentContainerStyle={styles.scrollContent}>
        {/* API connection details */}
        <View style={styles.settingsCard}>
          <View style={styles.cardHeaderInline}>
            <Sliders size={20} color="#06b6d4" />
            <Text style={styles.settingsTitle}>Server Configuration</Text>
          </View>
          <Text style={styles.settingsLabel}>FastAPI Backend URL Address</Text>
          <TextInput
            style={styles.settingsInput}
            value={apiUrl}
            onChangeText={setApiUrlState}
            placeholder="http://192.168.1.XX:8000"
            placeholderTextColor="#64748b"
            autoCapitalize="none"
            autoCorrect={false}
          />
          <TouchableOpacity style={styles.settingsSaveBtn} onPress={handleSaveApiUrl}>
            <Text style={styles.settingsSaveBtnText}>SAVE & RECONNECT</Text>
          </TouchableOpacity>
        </View>

        {/* INDmoney Token Details */}
        <View style={styles.settingsCard}>
          <View style={styles.cardHeaderInline}>
            <Database size={20} color="#06b6d4" />
            <Text style={styles.settingsTitle}>INDmoney Sync Credentials</Text>
          </View>
          <Text style={styles.settingsLabel}>Session Access Token Key</Text>
          <TextInput
            style={[styles.settingsInput, { height: 80, textAlignVertical: 'top' }]}
            multiline
            numberOfLines={4}
            value={tokenInput}
            onChangeText={setTokenInput}
            placeholder="Paste raw 'access_token' value extracted from indmoney.com cookies..."
            placeholderTextColor="#64748b"
            secureTextEntry={false}
          />

          <View style={styles.actionBtnRow}>
            <TouchableOpacity style={styles.connectBtn} onPress={handleConnectToken}>
              <Play size={14} color="#f8fafc" style={{ marginRight: 6 }} />
              <Text style={styles.connectBtnText}>SYNC TOKEN & START</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.disconnectBtn} onPress={handleDisconnect}>
              <Square size={14} color="#f8fafc" style={{ marginRight: 6 }} />
              <Text style={styles.disconnectBtnText}>STOP FEED</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Bookmarklet Instructions */}
        <View style={styles.settingsCard}>
          <View style={styles.cardHeaderInline}>
            <BookOpen size={20} color="#eab308" />
            <Text style={styles.settingsTitle}>Mobile Token extraction guide</Text>
          </View>
          <Text style={styles.helperText}>
            Logging in to INDmoney requires copying credentials. To do this effortlessly from your mobile browser:
          </Text>
          <View style={styles.stepContainer}>
            <Text style={styles.stepNum}>1</Text>
            <Text style={styles.stepDesc}>Create a browser bookmark on your mobile named "INDmoney Sync".</Text>
          </View>
          <View style={styles.stepContainer}>
            <Text style={styles.stepNum}>2</Text>
            <Text style={styles.stepDesc}>Edit bookmark URL and paste bookmarklet utility JS code from the Finance folder.</Text>
          </View>
          <View style={styles.stepContainer}>
            <Text style={styles.stepNum}>3</Text>
            <Text style={styles.stepDesc}>Open indmoney.com in mobile browser, log in, then tap the Bookmark from your address bar.</Text>
          </View>
          <View style={styles.stepContainer}>
            <Text style={styles.stepNum}>4</Text>
            <Text style={styles.stepDesc}>The bookmarklet extracts cookies and automatically logs you in here in one click!</Text>
          </View>
        </View>
      </ScrollView>
    );
  };

  // Stock Detail sheet modal
  const renderDetailModal = () => {
    if (!selectedStockSymbol) return null;

    const hist = selectedStock?.historical_metrics || {};
    const live = selectedStock?.live_quote || {};
    const pivots = selectedStock?.pivots || { resistances: [0, 0, 0], supports: [0, 0, 0] };

    // Get watchlist signal entry
    const signalItem = watchlist.find((item) => item.Stock.replace('.NS', '') === selectedStockSymbol) || {};
    const hasSignal = Object.keys(signalItem).length > 0;

    return (
      <Modal
        visible={showDetailModal}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setShowDetailModal(false)}
      >
        <SafeAreaView style={styles.modalContainer}>
          {/* Header */}
          <View style={styles.modalHeader}>
            <View>
              <Text style={styles.modalTitle}>{selectedStockSymbol}</Text>
              <Text style={styles.modalSubtitle}>{signalItem.Sector || 'Stock Tech Stats'}</Text>
            </View>
            <TouchableOpacity style={styles.closeBtn} onPress={() => setShowDetailModal(false)}>
              <X size={24} color="#f8fafc" />
            </TouchableOpacity>
          </View>

          {detailModalLoading ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color="#06b6d4" />
              <Text style={styles.loadingText}>Loading technical snapshot...</Text>
            </View>
          ) : (
            <ScrollView contentContainerStyle={styles.modalScrollContent}>
              {/* TradingView Chart Container */}
              <View style={styles.chartContainer}>
                <WebView
                  key={selectedStockSymbol}
                  originWhitelist={['*']}
                  source={{ uri: `https://in.tradingview.com/chart/?symbol=NSE:${selectedStockSymbol}` }}
                  style={styles.webView}
                  scrollEnabled={true}
                  domStorageEnabled={true}
                  javaScriptEnabled={true}
                  cacheEnabled={false}
                  incognito={true}
                  cacheMode="LOAD_NO_CACHE"
                  allowsInlineMediaPlayback={true}
                />
              </View>

              {/* Price Panel */}
              <View style={styles.statsCard}>
                <View style={styles.regimeRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.statLabel}>LTP Price</Text>
                    <Text style={styles.statPrice}>₹{(live.close || hist.last_close || hist.prev_day_close || 0).toFixed(2)}</Text>
                  </View>
                  <View style={{ flex: 1, alignItems: 'flex-end' }}>
                    <Text style={styles.statLabel}>RVOL (Rel Vol)</Text>
                    <Text style={styles.statValue}>{Number(hist.rvol || 0).toFixed(2)}x</Text>
                  </View>
                </View>
              </View>

              {/* Pivot Selector Pills */}
              <View style={styles.pivotsCard}>
                <Text style={styles.cardSecTitle}>Pivot Support & Resistances</Text>
                <View style={styles.pivotToggles}>
                  {['None', 'Traditional', 'Camarilla'].map((p) => (
                    <TouchableOpacity
                      key={p}
                      style={[styles.pivotTabBtn, detailPivotType === p && styles.pivotTabBtnActive]}
                      onPress={() => setDetailPivotType(p)}
                    >
                      <Text style={[styles.pivotTabBtnText, detailPivotType === p && styles.pivotTabBtnTextActive]}>
                        {p}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>

                {detailPivotType !== 'None' ? (
                  <View style={styles.levelsTable}>
                    <View style={styles.levelRow}>
                      <Text style={[styles.levelLabel, styles.textRed]}>Resistance 3 (R3)</Text>
                      <Text style={styles.levelValue}>₹{(pivots.resistances?.[2] || 0).toFixed(2)}</Text>
                    </View>
                    <View style={styles.levelRow}>
                      <Text style={[styles.levelLabel, styles.textRed]}>Resistance 1 (R1)</Text>
                      <Text style={styles.levelValue}>₹{(pivots.resistances?.[0] || 0).toFixed(2)}</Text>
                    </View>
                    <View style={styles.levelRow}>
                      <Text style={styles.levelLabel}>EMA20 Trendline</Text>
                      <Text style={styles.levelValue}>₹{(hist.ema20 || 0).toFixed(2)}</Text>
                    </View>
                    <View style={styles.levelRow}>
                      <Text style={[styles.levelLabel, styles.textGreen]}>Support 1 (S1)</Text>
                      <Text style={styles.levelValue}>₹{(pivots.supports?.[0] || 0).toFixed(2)}</Text>
                    </View>
                    <View style={styles.levelRow}>
                      <Text style={[styles.levelLabel, styles.textGreen]}>Support 3 (S3)</Text>
                      <Text style={styles.levelValue}>₹{(pivots.supports?.[2] || 0).toFixed(2)}</Text>
                    </View>
                  </View>
                ) : (
                  <Text style={styles.noDataText}>Select pivot type to render support & resistance lines.</Text>
                )}
              </View>

              {/* News Sentiment */}
              <View style={styles.statsCard}>
                <Text style={styles.cardSecTitle}>News Sentiment Analyzer</Text>
                {hasSignal ? (
                  <View>
                    <View style={styles.sentimentBadgeRow}>
                      <View
                        style={[
                          styles.sentimentBadge,
                          signalItem.News_Sentiment === 'POSITIVE'
                            ? styles.badgeGreen
                            : signalItem.News_Sentiment === 'DANGER'
                            ? styles.badgeRed
                            : styles.badgeSlate,
                        ]}
                      >
                        <Text
                          style={[
                            styles.sentimentBadgeText,
                            signalItem.News_Sentiment === 'POSITIVE'
                              ? styles.textGreen
                              : signalItem.News_Sentiment === 'DANGER'
                              ? styles.textRed
                              : styles.textSlate,
                          ]}
                        >
                          {signalItem.News_Sentiment} (Score: {signalItem.News_Score})
                        </Text>
                      </View>
                      <Text style={styles.sentimentCounts}>{signalItem.News_Counts}</Text>
                    </View>
                    <Text style={styles.latestHeadline}>"{signalItem.News_Latest || 'No headlines index cached.'}"</Text>
                  </View>
                ) : (
                  <Text style={styles.noDataText}>Sentiment metrics only load for active signal breakouts.</Text>
                )}
              </View>

              {/* Opportunity Analysis details */}
              {hasSignal && (
                <View style={styles.statsCard}>
                  <Text style={styles.cardSecTitle}>Opportunity Metrics</Text>
                  <View style={styles.regimeRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.statLabel}>Win Rate</Text>
                      <Text style={styles.statValDetail}>{signalItem.Win_Rate}%</Text>
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.statLabel}>Expectancy</Text>
                      <Text style={styles.statValDetail}>{signalItem.Expectancy} R</Text>
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.statLabel}>Expected Move</Text>
                      <Text style={[styles.statValDetail, styles.textGreen]}>+{signalItem.Expected_Move}%</Text>
                    </View>
                  </View>
                </View>
              )}

              {/* Action Buttons */}
              <TouchableOpacity style={styles.modalLogBtn} onPress={() => handleQuickTrade(selectedStockSymbol)}>
                <PlusCircle size={18} color="#f8fafc" style={{ marginRight: 8 }} />
                <Text style={styles.modalLogBtnText}>QUICK PAPER TRADE LOG</Text>
              </TouchableOpacity>
            </ScrollView>
          )}
        </SafeAreaView>
      </Modal>
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor="#080b16" />

      {/* Main Header bar */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>FINPLUS WORKSTATION</Text>
        <TouchableOpacity style={styles.refreshBtn} onPress={handleRefresh} disabled={loading}>
          {loading ? (
            <ActivityIndicator size="small" color="#06b6d4" />
          ) : (
            <RefreshCw size={18} color="#06b6d4" />
          )}
        </TouchableOpacity>
      </View>

      {/* Main tab display router */}
      <View style={styles.tabContent}>
        {activeTab === 'watchlist' && renderWatchlistTab()}
        {activeTab === 'regime' && renderRegimeTab()}
        {activeTab === 'trade' && renderTradeTab()}
        {activeTab === 'settings' && renderSettingsTab()}
      </View>

      {/* Stock detail Modal */}
      {renderDetailModal()}

      {/* Bottom custom Tab Navigation bar */}
      <View style={styles.tabBar}>
        <TouchableOpacity
          style={[styles.tabItem, activeTab === 'watchlist' && styles.tabItemActive]}
          onPress={() => setActiveTab('watchlist')}
        >
          <Eye size={20} color={activeTab === 'watchlist' ? '#06b6d4' : '#64748b'} />
          <Text style={[styles.tabLabel, activeTab === 'watchlist' && styles.tabLabelActive]}>Watchlist</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tabItem, activeTab === 'regime' && styles.tabItemActive]}
          onPress={() => setActiveTab('regime')}
        >
          <TrendingUp size={20} color={activeTab === 'regime' ? '#06b6d4' : '#64748b'} />
          <Text style={[styles.tabLabel, activeTab === 'regime' && styles.tabLabelActive]}>Regime</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tabItem, activeTab === 'trade' && styles.tabItemActive]}
          onPress={() => setActiveTab('trade')}
        >
          <DollarSign size={20} color={activeTab === 'trade' ? '#06b6d4' : '#64748b'} />
          <Text style={[styles.tabLabel, activeTab === 'trade' && styles.tabLabelActive]}>Log Trade</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tabItem, activeTab === 'settings' && styles.tabItemActive]}
          onPress={() => setActiveTab('settings')}
        >
          <Settings size={20} color={activeTab === 'settings' ? '#06b6d4' : '#64748b'} />
          <Text style={[styles.tabLabel, activeTab === 'settings' && styles.tabLabelActive]}>Settings</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  // Global & containers
  container: {
    flex: 1,
    backgroundColor: '#080b16',
  },
  header: {
    height: 56,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    backgroundColor: '#0c0f1d',
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  headerTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#06b6d4',
    letterSpacing: 1,
  },
  refreshBtn: {
    padding: 6,
  },
  tabContent: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#080b16',
    padding: 24,
  },
  loadingText: {
    marginTop: 12,
    color: '#94a3b8',
    fontSize: 14,
    textAlign: 'center',
  },
  tabScroll: {
    flex: 1,
    backgroundColor: '#080b16',
  },
  scrollContent: {
    padding: 16,
    paddingBottom: 32,
  },
  listContent: {
    paddingBottom: 32,
  },

  // Watchlist Header elements
  headerBlock: {
    padding: 16,
    backgroundColor: '#0c0f1d',
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  indicesRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  indexCard: {
    flex: 1,
    backgroundColor: '#12172a',
    padding: 10,
    borderRadius: 8,
    marginHorizontal: 4,
    borderWidth: 1,
  },
  borderGreen: {
    borderColor: '#10b98133',
  },
  borderRed: {
    borderColor: '#f43f5e33',
  },
  indexLabel: {
    fontSize: 10,
    fontWeight: '600',
    color: '#94a3b8',
    marginBottom: 2,
  },
  indexValue: {
    fontSize: 15,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  indexChange: {
    fontSize: 11,
    fontWeight: '600',
    marginTop: 2,
  },
  textGreen: {
    color: '#10b981',
  },
  textRed: {
    color: '#f43f5e',
  },
  statusPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginBottom: 12,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1e293b',
    paddingVertical: 4,
    paddingHorizontal: 8,
    borderRadius: 12,
    marginRight: 6,
    marginBottom: 6,
  },
  pillWarning: {
    backgroundColor: '#eab3081a',
  },
  glowIndicator: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginRight: 6,
  },
  pillText: {
    fontSize: 10,
    color: '#94a3b8',
    fontWeight: '500',
  },
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  searchBar: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#12172a',
    borderRadius: 8,
    paddingHorizontal: 12,
    height: 40,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  searchInput: {
    flex: 1,
    marginLeft: 8,
    color: '#f8fafc',
    fontSize: 14,
    height: '100%',
  },
  filtersToggleBtn: {
    width: 40,
    height: 40,
    backgroundColor: '#12172a',
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: 8,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  filtersToggleBtnActive: {
    borderColor: '#06b6d4',
    backgroundColor: '#06b6d41a',
  },

  // Filters Panel
  filtersPanel: {
    backgroundColor: '#12172a',
    borderRadius: 8,
    padding: 12,
    marginTop: 8,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  panelTitle: {
    fontSize: 11,
    fontWeight: 'bold',
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 8,
    marginTop: 4,
  },
  filterRow: {
    flexDirection: 'row',
    marginBottom: 10,
  },
  filterPill: {
    backgroundColor: '#1e293b',
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 16,
    marginRight: 8,
  },
  filterPillActive: {
    backgroundColor: '#06b6d4',
  },
  filterPillText: {
    color: '#94a3b8',
    fontSize: 12,
    fontWeight: '500',
  },
  filterPillTextActive: {
    color: '#f8fafc',
    fontWeight: 'bold',
  },

  // Watchlist List Signal Card
  signalCard: {
    backgroundColor: '#12172a',
    borderRadius: 10,
    padding: 14,
    marginHorizontal: 16,
    marginTop: 12,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
    paddingBottom: 8,
    marginBottom: 10,
  },
  cardSymbol: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  cardSector: {
    fontSize: 11,
    color: '#64748b',
    marginTop: 2,
  },
  signalBadge: {
    paddingVertical: 3,
    paddingHorizontal: 8,
    borderRadius: 4,
  },
  badgeGreen: {
    backgroundColor: '#10b9811a',
  },
  badgeRed: {
    backgroundColor: '#f43f5e1a',
  },
  badgeSlate: {
    backgroundColor: '#4755691a',
  },
  signalBadgeText: {
    fontSize: 10,
    fontWeight: 'bold',
  },
  cardBody: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  metricColumn: {
    flex: 1,
  },
  metricColumnRight: {
    flex: 1.2,
    alignItems: 'flex-end',
  },
  metricLabel: {
    fontSize: 9,
    color: '#64748b',
    textTransform: 'uppercase',
    marginBottom: 2,
  },
  metricValue: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  metricSubValue: {
    fontSize: 10,
    color: '#94a3b8',
    marginTop: 2,
  },
  scoreBadge: {
    paddingVertical: 2,
    paddingHorizontal: 8,
    borderRadius: 4,
    marginTop: 1,
  },
  bgGreenGlow: {
    backgroundColor: '#10b9811a',
    borderWidth: 1,
    borderColor: '#10b98133',
  },
  bgYellowGlow: {
    backgroundColor: '#eab3081a',
    borderWidth: 1,
    borderColor: '#eab30833',
  },
  bgSlate: {
    backgroundColor: '#3341551a',
    borderWidth: 1,
    borderColor: '#33415533',
  },
  scoreBadgeText: {
    fontSize: 12,
    fontWeight: 'bold',
  },

  // Empty list UI
  emptyContainer: {
    padding: 32,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 48,
  },
  emptyText: {
    color: '#f8fafc',
    fontSize: 15,
    fontWeight: 'bold',
    marginTop: 12,
    textAlign: 'center',
  },
  emptySubText: {
    color: '#64748b',
    fontSize: 13,
    textAlign: 'center',
    marginTop: 6,
  },

  // Market Regime tab cards
  regimeCard: {
    backgroundColor: '#12172a',
    borderRadius: 10,
    padding: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  regimeCardTitle: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#f8fafc',
    marginBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
    paddingBottom: 6,
  },
  regimeRow: {
    flexDirection: 'row',
    marginBottom: 12,
  },
  regimeItem: {
    flex: 1,
  },
  regimeLabel: {
    fontSize: 11,
    color: '#64748b',
    marginBottom: 4,
  },
  regimeValue: {
    fontSize: 18,
    fontWeight: 'bold',
  },
  progressBarLabel: {
    fontSize: 11,
    color: '#94a3b8',
    marginBottom: 6,
  },
  progressBarBg: {
    height: 8,
    backgroundColor: '#1e293b',
    borderRadius: 4,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    borderRadius: 4,
  },
  gaugeHeader: {
    flexDirection: 'row',
    alignItems: 'baseline',
    marginBottom: 8,
  },
  gaugeValue: {
    fontSize: 32,
    fontWeight: 'bold',
    marginRight: 8,
  },
  gaugeLabel: {
    fontSize: 16,
    fontWeight: '600',
  },
  regimeDesc: {
    fontSize: 11,
    color: '#64748b',
    marginTop: 10,
    lineHeight: 16,
  },
  sectorRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  sectorName: {
    fontSize: 13,
    fontWeight: '600',
    color: '#f8fafc',
  },
  sectorCount: {
    fontSize: 10,
    color: '#64748b',
    marginTop: 2,
  },
  sectorVal: {
    fontSize: 13,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  sectorChange: {
    fontSize: 11,
    fontWeight: '600',
    marginTop: 2,
  },
  noDataText: {
    color: '#64748b',
    fontSize: 12,
    textAlign: 'center',
    paddingVertical: 12,
  },

  // Paper Trading Tab
  tradeFormCard: {
    backgroundColor: '#12172a',
    borderRadius: 10,
    padding: 16,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  formTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#06b6d4',
    marginBottom: 16,
  },
  inputLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: '#94a3b8',
    marginBottom: 6,
    marginTop: 10,
  },
  formInput: {
    backgroundColor: '#080b16',
    borderWidth: 1,
    borderColor: '#1e293b',
    borderRadius: 6,
    height: 40,
    paddingHorizontal: 12,
    color: '#f8fafc',
    fontSize: 14,
  },
  actionToggleRow: {
    flexDirection: 'row',
    height: 40,
    backgroundColor: '#080b16',
    borderRadius: 6,
    padding: 3,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  actionBtn: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: 4,
  },
  actionBtnBuy: {
    backgroundColor: '#10b981',
  },
  actionBtnSell: {
    backgroundColor: '#f43f5e',
  },
  actionBtnText: {
    color: '#64748b',
    fontSize: 13,
    fontWeight: 'bold',
  },
  actionBtnTextActive: {
    color: '#f8fafc',
  },
  segmentScroll: {
    flexDirection: 'row',
    marginTop: 2,
    marginBottom: 4,
  },
  segmentPill: {
    backgroundColor: '#080b16',
    borderWidth: 1,
    borderColor: '#1e293b',
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: 18,
    marginRight: 8,
    height: 36,
    justifyContent: 'center',
  },
  segmentPillActive: {
    borderColor: '#06b6d4',
    backgroundColor: '#06b6d41a',
  },
  segmentPillText: {
    color: '#64748b',
    fontSize: 12,
    fontWeight: '600',
  },
  segmentPillTextActive: {
    color: '#06b6d4',
  },
  formGridRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  submitLogBtn: {
    backgroundColor: '#06b6d4',
    borderRadius: 6,
    height: 44,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 20,
    shadowColor: '#06b6d4',
    shadowOpacity: 0.3,
    shadowRadius: 5,
    shadowOffset: { width: 0, height: 2 },
  },
  submitLogBtnText: {
    color: '#f8fafc',
    fontSize: 14,
    fontWeight: 'bold',
    letterSpacing: 0.5,
  },

  // Trade Receipt screen
  tradeReceiptCard: {
    backgroundColor: '#12172a',
    borderRadius: 10,
    padding: 24,
    borderWidth: 1,
    borderColor: '#1e293b',
    alignItems: 'center',
  },
  receiptHeader: {
    alignItems: 'center',
    marginBottom: 16,
  },
  receiptTitle: {
    color: '#f8fafc',
    fontSize: 16,
    fontWeight: 'bold',
    marginTop: 12,
    textAlign: 'center',
  },
  receiptTradeId: {
    fontSize: 11,
    color: '#64748b',
    marginTop: 4,
  },
  receiptDivider: {
    width: '100%',
    height: 1,
    backgroundColor: '#1e293b',
    marginVertical: 14,
  },
  receiptDetails: {
    width: '100%',
  },
  receiptRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginVertical: 6,
  },
  receiptLabel: {
    fontSize: 13,
    color: '#94a3b8',
  },
  receiptVal: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  resetTradeBtn: {
    backgroundColor: '#1e293b',
    borderRadius: 6,
    height: 40,
    justifyContent: 'center',
    alignItems: 'center',
    width: '100%',
    marginTop: 24,
  },
  resetTradeBtnText: {
    color: '#f8fafc',
    fontSize: 12,
    fontWeight: 'bold',
    letterSpacing: 0.5,
  },

  // Settings
  settingsCard: {
    backgroundColor: '#12172a',
    borderRadius: 10,
    padding: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  cardHeaderInline: {
    flexDirection: 'row',
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
    paddingBottom: 8,
    marginBottom: 12,
  },
  settingsTitle: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#f8fafc',
    marginLeft: 8,
  },
  settingsLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: '#94a3b8',
    marginBottom: 6,
  },
  settingsInput: {
    backgroundColor: '#080b16',
    borderWidth: 1,
    borderColor: '#1e293b',
    borderRadius: 6,
    height: 40,
    paddingHorizontal: 12,
    color: '#f8fafc',
    fontSize: 14,
    marginBottom: 10,
  },
  settingsSaveBtn: {
    backgroundColor: '#1e293b',
    borderRadius: 6,
    height: 36,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#334155',
  },
  settingsSaveBtnText: {
    color: '#06b6d4',
    fontSize: 12,
    fontWeight: 'bold',
  },
  actionBtnRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 4,
  },
  connectBtn: {
    flex: 1.2,
    backgroundColor: '#10b981',
    borderRadius: 6,
    height: 38,
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  connectBtnText: {
    color: '#f8fafc',
    fontSize: 11,
    fontWeight: 'bold',
  },
  disconnectBtn: {
    flex: 0.8,
    backgroundColor: '#f43f5e',
    borderRadius: 6,
    height: 38,
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
  },
  disconnectBtnText: {
    color: '#f8fafc',
    fontSize: 11,
    fontWeight: 'bold',
  },
  helperText: {
    fontSize: 12,
    color: '#94a3b8',
    lineHeight: 18,
    marginBottom: 12,
  },
  stepContainer: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginVertical: 4,
  },
  stepNum: {
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: '#eab30833',
    color: '#eab308',
    textAlign: 'center',
    fontSize: 10,
    fontWeight: 'bold',
    lineHeight: 18,
    marginRight: 8,
    marginTop: 2,
  },
  stepDesc: {
    flex: 1,
    fontSize: 12,
    color: '#f8fafc',
    lineHeight: 18,
  },

  // Modal Detail styles
  modalContainer: {
    flex: 1,
    backgroundColor: '#080b16',
  },
  modalHeader: {
    height: 56,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    backgroundColor: '#0c0f1d',
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  modalSubtitle: {
    fontSize: 11,
    color: '#64748b',
    marginTop: 1,
  },
  closeBtn: {
    padding: 6,
  },
  modalScrollContent: {
    padding: 16,
    paddingBottom: 32,
  },
  chartContainer: {
    height: 230,
    backgroundColor: '#0c0f1d',
    borderRadius: 8,
    overflow: 'hidden',
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  webView: {
    flex: 1,
    backgroundColor: '#0c0f1d',
  },
  statsCard: {
    backgroundColor: '#12172a',
    borderRadius: 10,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  statLabel: {
    fontSize: 10,
    color: '#64748b',
    textTransform: 'uppercase',
    marginBottom: 4,
  },
  statPrice: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  statValue: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  statValDetail: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#f8fafc',
    marginTop: 2,
  },
  cardSecTitle: {
    fontSize: 13,
    fontWeight: 'bold',
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 12,
  },
  pivotsCard: {
    backgroundColor: '#12172a',
    borderRadius: 10,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  pivotToggles: {
    flexDirection: 'row',
    backgroundColor: '#080b16',
    padding: 3,
    borderRadius: 6,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  pivotTabBtn: {
    flex: 1,
    height: 28,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: 4,
  },
  pivotTabBtnActive: {
    backgroundColor: '#06b6d4',
  },
  pivotTabBtnText: {
    color: '#64748b',
    fontSize: 11,
    fontWeight: 'bold',
  },
  pivotTabBtnTextActive: {
    color: '#f8fafc',
  },
  levelsTable: {
    backgroundColor: '#080b16',
    borderRadius: 6,
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: '#1e293b',
  },
  levelRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: '#12172a',
  },
  levelLabel: {
    fontSize: 12,
    color: '#94a3b8',
  },
  levelValue: {
    fontSize: 12,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  sentimentBadgeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  sentimentBadge: {
    paddingVertical: 3,
    paddingHorizontal: 8,
    borderRadius: 4,
  },
  sentimentBadgeText: {
    fontSize: 11,
    fontWeight: 'bold',
  },
  sentimentCounts: {
    fontSize: 11,
    color: '#64748b',
  },
  textSlate: {
    color: '#94a3b8',
  },
  latestHeadline: {
    fontSize: 12,
    color: '#f8fafc',
    fontStyle: 'italic',
    lineHeight: 18,
  },
  modalLogBtn: {
    backgroundColor: '#06b6d4',
    height: 44,
    borderRadius: 8,
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 8,
  },
  modalLogBtnText: {
    color: '#f8fafc',
    fontSize: 13,
    fontWeight: 'bold',
    letterSpacing: 0.5,
  },

  // Bottom Custom Navigation bar
  tabBar: {
    height: 72,
    flexDirection: 'row',
    backgroundColor: '#0c0f1d',
    borderTopWidth: 1,
    borderTopColor: '#1e293b',
    paddingBottom: 14,
  },
  tabItem: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  tabItemActive: {
    borderTopWidth: 2,
    borderTopColor: '#06b6d4',
  },
  tabLabel: {
    fontSize: 10,
    color: '#64748b',
    marginTop: 4,
    fontWeight: '500',
  },
  tabLabelActive: {
    color: '#06b6d4',
    fontWeight: 'bold',
  },
  topPickCard: {
    borderColor: '#eab30855',
    borderWidth: 1.5,
    backgroundColor: '#1e1a0a',
  },
  topPickBadge: {
    backgroundColor: '#eab3081a',
    borderColor: '#eab30844',
    borderWidth: 1,
    paddingVertical: 2,
    paddingHorizontal: 6,
    borderRadius: 4,
    marginLeft: 8,
    alignSelf: 'center',
  },
  topPickBadgeText: {
    color: '#eab308',
    fontSize: 8,
    fontWeight: 'bold',
    letterSpacing: 0.5,
  },

  // Market Breadth Trend Banner
  trendBanner: {
    backgroundColor: '#12172a',
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#1e293b',
    marginBottom: 12,
  },
  trendRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  trendLabel: {
    fontSize: 9,
    fontWeight: 'bold',
    color: '#94a3b8',
    letterSpacing: 0.5,
  },
  trendRatioText: {
    fontSize: 9,
    fontWeight: 'bold',
    color: '#64748b',
  },
  breadthBarContainer: {
    height: 6,
    flexDirection: 'row',
    borderRadius: 3,
    overflow: 'hidden',
    marginBottom: 6,
  },
  breadthSegment: {
    height: '100%',
  },
  trendCountsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  trendCountGreen: {
    fontSize: 10,
    fontWeight: '600',
    color: '#10b981',
  },
  trendCountRed: {
    fontSize: 10,
    fontWeight: '600',
    color: '#f43f5e',
  },
  trendCountNeutral: {
    fontSize: 10,
    fontWeight: '600',
    color: '#94a3b8',
  },

  // Alpha Picks Header & Carousel
  alphaPicksHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
    marginTop: 4,
  },
  alphaPicksTitle: {
    fontSize: 11,
    fontWeight: 'bold',
    color: '#eab308',
    letterSpacing: 0.5,
    marginLeft: 6,
  },
  recalcBtn: {
    backgroundColor: '#eab3081a',
    borderColor: '#eab30833',
    borderWidth: 1,
    paddingVertical: 3,
    paddingHorizontal: 8,
    borderRadius: 12,
  },
  recalcBtnText: {
    fontSize: 9,
    fontWeight: 'bold',
    color: '#eab308',
  },
  picksLoader: {
    height: 140,
    backgroundColor: '#0c0f1d',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#1e293b',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  picksLoaderText: {
    color: '#64748b',
    fontSize: 11,
    marginTop: 8,
  },
  picksCarousel: {
    paddingLeft: 4,
    paddingRight: 16,
    marginBottom: 16,
  },
  picksCarouselPlaceholder: {
    height: 100,
    backgroundColor: '#0c0f1d',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#1e293b',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  placeholderText: {
    color: '#64748b',
    fontSize: 11,
    textAlign: 'center',
  },
  pickCard: {
    width: width - 48,
    backgroundColor: '#12172a',
    borderRadius: 10,
    padding: 12,
    marginRight: 12,
    borderWidth: 1.5,
  },
  pickCardEmpty: {
    width: width - 48,
    backgroundColor: '#0c0f1d',
    borderRadius: 10,
    padding: 12,
    marginRight: 12,
    borderWidth: 1,
    borderColor: '#1e293b',
    justifyContent: 'center',
    alignItems: 'center',
    height: 130,
  },
  emptyCardTitle: {
    fontSize: 11,
    fontWeight: 'bold',
    color: '#64748b',
    marginBottom: 8,
  },
  emptyCardText: {
    color: '#475569',
    fontSize: 11,
    textAlign: 'center',
  },
  borderGold: {
    borderColor: '#eab30888',
    backgroundColor: '#16130b',
  },
  borderCyan: {
    borderColor: '#06b6d488',
    backgroundColor: '#07151e',
  },
  borderPurple: {
    borderColor: '#a855f788',
    backgroundColor: '#120d1c',
  },
  pickCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
    paddingBottom: 6,
    marginBottom: 8,
  },
  pickCardSub: {
    fontSize: 9,
    fontWeight: 'bold',
    color: '#94a3b8',
    letterSpacing: 0.5,
  },
  pickTime: {
    fontSize: 9,
    color: '#64748b',
  },
  pickSymbolRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  pickSymbol: {
    fontSize: 15,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  pickCompany: {
    fontSize: 10,
    color: '#64748b',
    marginTop: 1,
  },
  pickDetailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  pickLabel: {
    fontSize: 8,
    color: '#64748b',
    textTransform: 'uppercase',
    marginBottom: 2,
  },
  pickValue: {
    fontSize: 13,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  pickValueText: {
    fontSize: 12,
    fontWeight: 'bold',
    color: '#f8fafc',
  },
  pickSubText: {
    fontSize: 9,
    color: '#64748b',
  },
  pickChange: {
    fontSize: 10,
    fontWeight: '600',
    marginTop: 1,
  },
  levelsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: '#080b1655',
    padding: 6,
    borderRadius: 6,
  },
  levelText: {
    fontSize: 10,
    color: '#94a3b8',
  },
  levelVal: {
    fontWeight: 'bold',
  },
});
