import React, { useState, useEffect } from 'react';
import { 
  loadJournalEngine, 
  saveJournalEngine, 
  calculateZerodhaCharges, 
  createTradeUUID,
  getTradeKey,
  mergeJournalTrades,
  exportMasterJsonBackup, 
  importMasterJsonBackup, 
  exportJournalCSV,
  importJournalCSV
} from './journal/journal_engine';
import { 
  TrendingUp, 
  TrendingDown, 
  PlusCircle, 
  Download, 
  Upload, 
  CheckCircle2, 
  AlertCircle, 
  Trash2, 
  Edit3, 
  X, 
  ShieldAlert, 
  DollarSign,
  Activity,
  FileText,
  Calendar,
  Filter,
  Clock,
  Layers,
  Search,
  Eye,
  RefreshCw,
  Save,
  Wifi,
  WifiOff,
  Copy,
  Check,
  Settings
} from 'lucide-react';


export default function App() {
  // Master Trade State
  const [trades, setTrades] = useState(() => loadJournalEngine());
  const [activeTab, setActiveTab] = useState('home'); // 'home' | 'trades' | 'capital' | 'screener' | 'sip' | 'mtf' | 'overview'

  // Screener States
  const [screenerData, setScreenerData] = useState([]);
  const [screenerLoading, setScreenerLoading] = useState(false);
  const [screenerSearchQuery, setScreenerSearchQuery] = useState('');
  const [screenerFilter, setScreenerFilter] = useState('all'); // 'all' | 'qualified'
  const [screenerSortCol, setScreenerSortCol] = useState('total_score');
  const [screenerSortAsc, setScreenerSortAsc] = useState(false);
  const [localScanActive, setLocalScanActive] = useState(false);
  const [selectedScreenerStock, setSelectedScreenerStock] = useState(null);
  const [serverUrl, setServerUrl] = useState(() => {
    return localStorage.getItem('finplus_server_url') || '';
  });
  const [serverStatus, setServerStatus] = useState('offline');
  const [serverUrlInput, setServerUrlInput] = useState(() => {
    return localStorage.getItem('finplus_server_url') || '';
  });

  // PnL View Mode: 'overall' | 'daily'
  const [pnlViewMode, setPnlViewMode] = useState('overall');
  const getTodayDateStr = () => {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };
  const [selectedDailyDate, setSelectedDailyDate] = useState(() => getTodayDateStr());

  // Capital Management & Risk Settings (Persisted in localStorage)
  const [openingCapitalInput, setOpeningCapitalInput] = useState(() => {
    return localStorage.getItem('finplus_opening_capital') || '3933.52';
  });
  const [brokerAdjustmentInput, setBrokerAdjustmentInput] = useState(() => {
    return localStorage.getItem('finplus_broker_adjustment') || '0';
  });
  const [depositsInput, setDepositsInput] = useState(() => {
    return localStorage.getItem('finplus_deposits') || '0';
  });
  const [withdrawalsInput, setWithdrawalsInput] = useState(() => {
    return localStorage.getItem('finplus_withdrawals') || '0';
  });

  // 1000-Day Challenge Daily Rollover Risk Settings (Single Risk Rule: ₹250/day)
  const [dailyRiskLimitInput, setDailyRiskLimitInput] = useState(() => {
    return localStorage.getItem('finplus_daily_risk_limit') || '250';
  });
  const [challengeStartDateInput, setChallengeStartDateInput] = useState(() => {
    const val = localStorage.getItem('finplus_challenge_start_date');
    return val && val !== '2026-07-24' ? val : '2026-07-23';
  });
  const [totalChallengeDaysInput, setTotalChallengeDaysInput] = useState(() => {
    return localStorage.getItem('finplus_total_challenge_days') || '1000';
  });

  // Segment Capital Allocation & Monthly Risk SL State (4 Active Trading Segments - Total 100%)
  const [allocIntraday, setAllocIntraday] = useState(() => localStorage.getItem('finplus_alloc_intraday') || '50');
  const [allocNatgas, setAllocNatgas] = useState(() => localStorage.getItem('finplus_alloc_natgas') || '25');
  const [allocNifty, setAllocNifty] = useState(() => localStorage.getItem('finplus_alloc_nifty') || '15');
  const [allocCrude, setAllocCrude] = useState(() => localStorage.getItem('finplus_alloc_crude') || '10');

  const [monthlySlIntraday, setMonthlySlIntraday] = useState(() => localStorage.getItem('finplus_msl_intraday') || '5');
  const [monthlySlNatgas, setMonthlySlNatgas] = useState(() => localStorage.getItem('finplus_msl_natgas') || '10');
  const [monthlySlNifty, setMonthlySlNifty] = useState(() => localStorage.getItem('finplus_msl_nifty') || '15');
  const [monthlySlCrude, setMonthlySlCrude] = useState(() => localStorage.getItem('finplus_msl_crude') || '10');
  
  const currentYearMonthStr = new Date().toISOString().slice(0, 7);
  const [selectedRiskMonth, setSelectedRiskMonth] = useState(currentYearMonthStr);
  const RENDER_BACKEND_URL = 'https://finplus.onrender.com';
  const isNativeMobileApp = Boolean(window.Capacitor?.isNativePlatform?.()) || window.location.protocol === 'capacitor:';
  const API_BASE_URL = serverUrl 
    || (isNativeMobileApp ? RENDER_BACKEND_URL : (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' ? 'http://127.0.0.1:8000' : RENDER_BACKEND_URL));
  const [liveLtps, setLiveLtps] = useState({
    "ASHOKLEY": 175.05, "ASHOKLEY.NS": 175.05,
    "BEL": 400.60, "BEL.NS": 400.60,
    "BORANA": 325.00, "BORANA.NS": 325.00,
    "EMMVEE": 314.15, "EMMVEE.NS": 314.15,
    "FEDERALBNK": 355.75, "FEDERALBNK.NS": 355.75,
    "ITC": 276.90, "ITC.NS": 276.90,
    "NMDC": 85.08, "NMDC.NS": 85.08,
    "PANAMAPET": 507.25, "PANAMAPET.NS": 507.25,
    "TATAPOWER": 374.85, "TATAPOWER.NS": 374.85,
    "TATASTEEL": 183.95, "TATASTEEL.NS": 183.95,
    "UYFINCORP": 18.98, "UYFINCORP.NS": 18.98,
    "GOLDBEES": 74.20, "GOLDBEES.NS": 74.20,
    "NIFTYBEES": 286.50, "NIFTYBEES.NS": 286.50
  });
  const [toast, setToast] = useState(null);

  // Dynamic 5% Pullback SIP & MTF State
  const [pullbackData, setPullbackData] = useState(() => {
    const defaultData = {
      "capital_settings": { "start_date": "2026-07-03", "initial_capital": 3477.97, "daily_rate": 200.0 },
      "ASHOKLEY.NS": { "name": "Ashok Leyland Limited", "category": "Core", "transactions": [{ "date": "2026-07-13", "price": 160.53, "shares": 2 }], "local_peak": 176.25, "date_added": "2026-07-03", "initial_reference_price": 175.05 },
      "BEL.NS": { "name": "Bharat Electronics Limited", "category": "Core", "transactions": [{ "date": "2026-07-29", "price": 403.52, "shares": 3 }], "local_peak": 405.85, "date_added": "2026-07-03", "initial_reference_price": 400.60 },
      "BORANA.NS": { "name": "BORANA", "category": "Core", "transactions": [{ "date": "2026-08-06", "price": 342.0, "shares": 1 }], "local_peak": 353.95, "date_added": "2026-08-06", "initial_reference_price": 325.00 },
      "EMMVEE.NS": { "name": "Emmvee Photovoltaic Power Limited", "category": "Growth", "in_watchlist": false, "transactions": [{ "date": "2026-08-03", "price": 330.98, "shares": 2 }, { "date": "2026-08-12", "price": 314.10, "shares": -2, "type": "SELL" }], "local_peak": 330.98, "date_added": "2026-07-03", "initial_reference_price": 314.10 },
      "FEDERALBNK.NS": { "name": "The Federal Bank Limited", "category": "Core", "transactions": [{ "date": "2026-08-03", "price": 359.10, "shares": 1 }, { "date": "2026-08-11", "price": 353.10, "shares": 1 }], "local_peak": 359.10, "date_added": "2026-07-03", "initial_reference_price": 355.75 },
      "ITC.NS": { "name": "ITC Limited", "category": "Core", "transactions": [{ "date": "2026-07-14", "price": 275.45, "shares": 1 }], "local_peak": 286.25, "date_added": "2026-07-03", "initial_reference_price": 276.90 },
      "NMDC.NS": { "name": "NMDC Limited", "category": "Core", "transactions": [{ "date": "2026-08-03", "price": 84.80, "shares": 1 }, { "date": "2026-08-11", "price": 85.29, "shares": 5 }], "local_peak": 85.49, "date_added": "2026-07-03", "initial_reference_price": 85.08 },
      "PANAMAPET.NS": { "name": "Panama Petrochem Limited", "category": "Growth", "in_watchlist": false, "transactions": [{ "date": "2026-08-11", "price": 544.95, "shares": 3 }, { "date": "2026-08-12", "price": 567.65, "shares": -3, "type": "SELL" }], "local_peak": 598.70, "date_added": "2026-08-11", "initial_reference_price": 506.15 },
      "TATAPOWER.NS": { "name": "Tata Power Company Limited", "category": "Core", "transactions": [{ "date": "2026-07-10", "price": 382.25, "shares": 1 }], "local_peak": 382.25, "date_added": "2026-07-03", "initial_reference_price": 374.85 },
      "TATASTEEL.NS": { "name": "Tata Steel Limited", "category": "Growth", "transactions": [{ "date": "2026-07-27", "price": 182.82, "shares": 1 }], "local_peak": 191.53, "date_added": "2026-07-05", "initial_reference_price": 183.95 },
      "UYFINCORP.NS": { "name": "UYFINCORP", "category": "Core", "transactions": [{ "date": "2026-08-06", "price": 19.33, "shares": 12 }], "local_peak": 22.34, "date_added": "2026-08-06", "initial_reference_price": 18.98 },
      "NIFTYBEES.NS": { "name": "Nippon India Nifty 50 BeES ETF", "category": "Park", "transactions": [{ "date": "2026-08-12", "price": 277.21, "shares": 1 }], "local_peak": 286.50, "date_added": "2026-08-11", "initial_reference_price": 277.21 },
      "GOLDBEES.NS": { "name": "Nippon India Gold BeES ETF", "category": "Park", "transactions": [{ "date": "2026-08-12", "price": 126.19, "shares": 2 }], "local_peak": 126.18, "date_added": "2026-08-11", "initial_reference_price": 126.19 },
      "mtf_trading": []
    };

    const saved = localStorage.getItem('finplus_pullback_portfolio');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        
        // Sanitize MTF trades to strip out stale hardcoded unlogged demo trades (LODHA, INDUSTOWER, NAUKRI)
        if (parsed.mtf_trading) {
          const mtfList = Array.isArray(parsed.mtf_trading)
            ? parsed.mtf_trading
            : (parsed.mtf_trading.trades || []);
          const cleanMtf = mtfList.filter(t => t.ticker !== 'LODHA.NS' && t.ticker !== 'INDUSTOWER.NS' && t.ticker !== 'NAUKRI.NS');
          parsed.mtf_trading = cleanMtf;
        }

        return { ...defaultData, ...parsed };
      } catch (e) {}
    }
    return defaultData;
  });

  // Pullback Forms State
  const [newSipTicker, setNewSipTicker] = useState('');
  const [newSipName, setNewSipName] = useState('');
  const [newSipCategory, setNewSipCategory] = useState('Core');
  const [newSipShares, setNewSipShares] = useState('1');
  const [newSipBuyPrice, setNewSipBuyPrice] = useState('');
  const [newSipTxDate, setNewSipTxDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [nifty500List, setNifty500List] = useState([]);
  const [showNiftyDropdown, setShowNiftyDropdown] = useState(false);

  // Load bundled NSE stock list (2413 stocks with company names) for autocomplete
  useEffect(() => {
    const loadNseStocks = async () => {
      try {
        const res = await fetch('/nse_stocks.json');
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data) && data.length > 0) {
            setNifty500List(data);
          }
        }
      } catch (e) {
        console.warn('Could not load bundled NSE stock list', e);
      }
    };
    loadNseStocks();
  }, []);

  // Combined master stock list from bundled NSE stocks JSON + API fallback
  // Master ETF & Index Fund List for Park category
  const POPULAR_ETFS = React.useMemo(() => [
    { symbol: "GOLDBEES", name: "Nippon India ETF Gold BeES", isEtf: true, aliases: ["gold", "goldb", "goldbees", "gold bees", "gold etf", "nippon gold", "gold be"] },
    { symbol: "NIFTYBEES", name: "Nippon India ETF Nifty 50 BeES", isEtf: true, aliases: ["nifty", "niftyb", "niftybees", "nifty bees", "nifty 50", "nifty etf", "nippon nifty"] },
    { symbol: "BANKBEES", name: "Nippon India ETF Nifty Bank BeES", isEtf: true, aliases: ["bank", "bankbees", "bank bees", "bank etf", "nifty bank", "banknifty etf"] },
    { symbol: "LIQUIDBEES", name: "Nippon India ETF Liquid BeES", isEtf: true, aliases: ["liquid", "liquidbees", "liquid bees", "liquid etf", "cash", "park cash"] },
    { symbol: "SILVERBEES", name: "Nippon India ETF Silver BeES", isEtf: true, aliases: ["silver", "silverbees", "silver bees", "silver etf", "nippon silver"] },
    { symbol: "ITBEES", name: "Nippon India ETF Nifty IT", isEtf: true, aliases: ["it", "itbees", "it bees", "it etf", "tech etf", "nifty it"] },
    { symbol: "JUNIORBEES", name: "Nippon India ETF Nifty Next 50", isEtf: true, aliases: ["junior", "juniorbees", "junior bees", "next 50", "nifty next 50"] },
    { symbol: "CPSEETF", name: "CPSE ETF", isEtf: true, aliases: ["cpse", "cpse etf", "psu etf", "cpseetf"] },
    { symbol: "MON100", name: "Motilal Oswal Nasdaq 100 ETF", isEtf: true, aliases: ["nasdaq", "mon100", "nasdaq 100", "us tech", "motilal nasdaq"] },
    { symbol: "AUTOBEES", name: "Nippon India ETF Nifty Auto", isEtf: true, aliases: ["auto", "autobees", "auto bees", "auto etf"] },
    { symbol: "PHARMABEES", name: "Nippon India ETF Nifty Pharma", isEtf: true, aliases: ["pharma", "pharmabees", "pharma bees", "pharma etf"] },
    { symbol: "HDFCGOLD", name: "HDFC Gold ETF", isEtf: true, aliases: ["hdfc gold", "hdfc gold etf"] },
    { symbol: "GOLDIETF", name: "ICICI Prudential Gold ETF", isEtf: true, aliases: ["icici gold", "goldietf", "icici prudential gold"] },
    { symbol: "SETFNIF50", name: "SBI Nifty 50 ETF", isEtf: true, aliases: ["sbi nifty", "sbi nifty 50", "setfnif50"] }
  ], []);

  // Combined master stock list from bundled NSE stocks JSON + ETFs
  const combinedStockList = React.useMemo(() => {
    const etfMapped = POPULAR_ETFS.map(e => ({
      symbol: e.symbol,
      name: e.name,
      isEtf: true,
      aliases: [
        e.symbol.toLowerCase(),
        e.name.toLowerCase(),
        ...(e.aliases || []).map(a => a.toLowerCase())
      ]
    }));

    if (nifty500List && nifty500List.length > 0) {
      const stockMapped = nifty500List.map(s => ({
        symbol: s.s || s.symbol || '',
        name: s.n || s.name || s.s || s.symbol || '',
        isEtf: false,
        aliases: [
          (s.s || s.symbol || '').toLowerCase(),
          (s.n || s.name || '').toLowerCase()
        ]
      }));
      return [...etfMapped, ...stockMapped];
    }
    return etfMapped;
  }, [nifty500List, POPULAR_ETFS]);

  // Ranked suggestions with alias & prefix matching (shared for SIP + MTF)
  const filteredNiftySuggestions = React.useMemo(() => {
    const query = newSipTicker.toLowerCase().replace('.ns', '').trim();
    if (!query || query.length < 2) return [];
    const scored = combinedStockList.map(s => {
      const sym = (s.symbol || '').toLowerCase();
      const name = (s.name || '').toLowerCase();
      const aliases = s.aliases || [];
      let score = 0;
      if (sym === query || aliases.includes(query)) score = 100;
      else if (sym.startsWith(query)) score = 90;
      else if (aliases.some(a => a.startsWith(query))) score = 85;
      else if (name.startsWith(query)) score = 75;
      else if (sym.includes(query)) score = 60;
      else if (aliases.some(a => a.includes(query))) score = 55;
      else if (name.includes(query)) score = 40;
      return { stock: s, score };
    }).filter(item => item.score > 0);
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, 8).map(item => item.stock);
  }, [newSipTicker, combinedStockList]);

  // Live auto-fill company name & default buy price when suggestion matches current input
  useEffect(() => {
    if (!newSipTicker.trim()) {
      setNewSipName('');
      setNewSipBuyPrice('');
      return;
    }
    if (filteredNiftySuggestions.length > 0) {
      const topMatch = filteredNiftySuggestions[0];
      setNewSipName(topMatch.name || topMatch.symbol);
      const cleanSym = topMatch.symbol.toUpperCase().replace('.NS', '');
      const ltp = liveLtps[cleanSym] || liveLtps[`${cleanSym}.NS`];
      if (ltp && !newSipBuyPrice) {
        setNewSipBuyPrice(String(ltp));
      }
      // Auto-switch category to Park if it's an ETF
      if (topMatch.isEtf || cleanSym.endsWith('BEES') || cleanSym.endsWith('ETF') || topMatch.name.toLowerCase().includes('etf')) {
        setNewSipCategory('Park');
      }
    }
  }, [newSipTicker, filteredNiftySuggestions, liveLtps]);

  const [txTicker, setTxTicker] = useState('TATAPOWER.NS');
  const [txType, setTxType] = useState('BUY');
  const [txDate, setTxDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [txPrice, setTxPrice] = useState('');
  const [txShares, setTxShares] = useState('1');

  // SIP Form Mode ('BUY' or 'SELL') & SIP View Mode ('holdings' or 'sold')
  const [sipFormMode, setSipFormMode] = useState('BUY'); // 'BUY' | 'SELL'
  const [sipViewMode, setSipViewMode] = useState('holdings'); // 'holdings' | 'sold'

  // SIP Sell Form State (in main SIP panel)
  const [sipSellSelectedTicker, setSipSellSelectedTicker] = useState('');
  const [sipSellFormShares, setSipSellFormShares] = useState('1');
  const [sipSellFormPrice, setSipSellFormPrice] = useState('');
  const [sipSellFormDate, setSipSellFormDate] = useState(() => new Date().toISOString().split('T')[0]);

  // SIP Sell Modal State (quick action from table)
  const [sipSellModalStock, setSipSellModalStock] = useState(null);
  const [sipSellModalShares, setSipSellModalShares] = useState('1');
  const [sipSellModalPrice, setSipSellModalPrice] = useState('');
  const [sipSellModalDate, setSipSellModalDate] = useState(() => new Date().toISOString().split('T')[0]);

  // SIP Edit Stock & Transactions Modal State
  const [sipEditModalStock, setSipEditModalStock] = useState(null);
  const [editSipName, setEditSipName] = useState('');
  const [editSipCategory, setEditSipCategory] = useState('Core');
  const [editSipPeak, setEditSipPeak] = useState('');
  const [editSipTxs, setEditSipTxs] = useState([]);

  const [mtfTicker, setMtfTicker] = useState('');
  const [mtfBuyPrice, setMtfBuyPrice] = useState('');
  const [mtfShares, setMtfShares] = useState('10');
  const [mtfBrokerFundedPct, setMtfBrokerFundedPct] = useState('68.0');
  const [mtfBuyDate, setMtfBuyDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [mtfViewMode, setMtfViewMode] = useState('overall'); // 'overall', 'active', 'closed'
  const [showMtfDropdown, setShowMtfDropdown] = useState(false);

  // MTF ticker autocomplete suggestions (must be AFTER mtfTicker state declaration)
  const filteredMtfSuggestions = React.useMemo(() => {
    const query = mtfTicker.toLowerCase().replace('.ns', '').trim();
    if (!query || query.length < 2) return [];
    const scored = combinedStockList.map(s => {
      const sym = (s.symbol || '').toLowerCase();
      const name = (s.name || '').toLowerCase();
      const aliases = s.aliases || [];
      let score = 0;
      if (sym === query || aliases.includes(query)) score = 100;
      else if (sym.startsWith(query)) score = 80;
      else if (aliases.some(a => a.startsWith(query))) score = 75;
      else if (name.startsWith(query)) score = 70;
      else if (sym.includes(query)) score = 50;
      else if (name.includes(query)) score = 40;
      else if (aliases.some(a => a.includes(query))) score = 35;
      return { stock: s, score };
    }).filter(item => item.score > 0);
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, 8).map(item => item.stock);
  }, [mtfTicker, combinedStockList]);

  // Auto-fill MTF buy price from live LTP when a suggestion is selected
  useEffect(() => {
    if (!mtfTicker.trim()) return;
    if (filteredMtfSuggestions.length > 0) {
      const top = filteredMtfSuggestions[0];
      if (top.symbol.toLowerCase() === mtfTicker.toLowerCase().replace('.ns', '')) {
        const ltp = liveLtps[top.symbol] || liveLtps[`${top.symbol}.NS`];
        if (ltp && !mtfBuyPrice) setMtfBuyPrice(String(ltp));
      }
    }
  }, [mtfTicker, filteredMtfSuggestions, liveLtps]);


  const [isSyncing, setIsSyncing] = useState(false);
  const [detectedIps, setDetectedIps] = useState([]);
  const [lastSyncedTime, setLastSyncedTime] = useState(() => localStorage.getItem('finplus_last_synced_time') || '');

  // Full Unified Bidirectional Sync with Server (Trades + Pullback Stocks + Capital & Risk Settings)
  const handleSyncAll = async (targetUrl = null, silent = false) => {
    setIsSyncing(true);
    const activeCandidates = targetUrl 
      ? [targetUrl] 
      : Array.from(new Set([
          serverUrl, 
          API_BASE_URL, 
          (typeof window !== 'undefined' && window.location.hostname && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1' ? `${window.location.protocol}//${window.location.hostname}:8000` : null),
          'http://127.0.0.1:8000', 
          'http://localhost:8000', 
          RENDER_BACKEND_URL
        ].filter(Boolean)));
    
    let syncSuccess = false;
    let syncMsg = '';

    for (const endpoint of activeCandidates) {
      try {
        const cleanEndpoint = endpoint.trim().replace(/\/$/, '');
        // 1. Fetch current server dataset
        const res = await fetch(`${cleanEndpoint}/api/sync/all`, { method: 'GET' });
        if (res.ok) {
          const sData = await res.json();
          if (sData && sData.status === 'success') {
            // A. Merge Trades
            let mergedTrades = trades;
            if (Array.isArray(sData.trades)) {
              mergedTrades = mergeJournalTrades(trades, sData.trades);
              setTrades(mergedTrades);
              saveJournalEngine(mergedTrades);
            }

            // B. Merge Pullback Data & MTF
            let mergedPullback = pullbackData;
            if (sData.pullback && typeof sData.pullback === 'object') {
              const currentSaved = localStorage.getItem('finplus_pullback_portfolio');
              let localP = pullbackData;
              if (currentSaved) {
                try { localP = JSON.parse(currentSaved); } catch(e) {}
              }
              mergedPullback = { ...localP, ...sData.pullback };
              
              // Merge MTF array safely
              const backendMtf = Array.isArray(sData.pullback.mtf_trading) ? sData.pullback.mtf_trading : (sData.pullback.mtf_trading?.trades || []);
              const localMtf = Array.isArray(localP.mtf_trading) ? localP.mtf_trading : (localP.mtf_trading?.trades || []);
              const mtfMap = new Map();
              backendMtf.forEach(t => {
                if (t) {
                  const key = t.id !== undefined && t.id !== null ? `id_${t.id}` : `${t.ticker}_${t.buy_date}_${t.shares}`;
                  mtfMap.set(key, t);
                }
              });
              localMtf.forEach(t => {
                if (t) {
                  const key = t.id !== undefined && t.id !== null ? `id_${t.id}` : `${t.ticker}_${t.buy_date}_${t.shares}`;
                  const existing = mtfMap.get(key);
                  if (!existing) mtfMap.set(key, t);
                  else mtfMap.set(key, { ...existing, ...t });
                }
              });
              mergedPullback.mtf_trading = Array.from(mtfMap.values()).filter(t => t && t.ticker !== 'LODHA.NS' && t.ticker !== 'INDUSTOWER.NS' && t.ticker !== 'NAUKRI.NS');
              setPullbackData(mergedPullback);
              localStorage.setItem('finplus_pullback_portfolio', JSON.stringify(mergedPullback));
            }

            // C. Merge Settings
            if (sData.settings && typeof sData.settings === 'object' && Object.keys(sData.settings).length > 0) {
              const st = sData.settings;
              if (st.finplus_opening_capital) { setOpeningCapitalInput(st.finplus_opening_capital); localStorage.setItem('finplus_opening_capital', st.finplus_opening_capital); }
              if (st.finplus_broker_adjustment !== undefined) { setBrokerAdjustmentInput(st.finplus_broker_adjustment); localStorage.setItem('finplus_broker_adjustment', st.finplus_broker_adjustment); }
              if (st.finplus_deposits !== undefined) { setDepositsInput(st.finplus_deposits); localStorage.setItem('finplus_deposits', st.finplus_deposits); }
              if (st.finplus_withdrawals !== undefined) { setWithdrawalsInput(st.finplus_withdrawals); localStorage.setItem('finplus_withdrawals', st.finplus_withdrawals); }
              if (st.finplus_daily_risk_limit !== undefined) { setDailyRiskLimitInput(st.finplus_daily_risk_limit); localStorage.setItem('finplus_daily_risk_limit', st.finplus_daily_risk_limit); }
              if (st.finplus_challenge_start_date) { setChallengeStartDateInput(st.finplus_challenge_start_date); localStorage.setItem('finplus_challenge_start_date', st.finplus_challenge_start_date); }
              if (st.finplus_total_challenge_days) { setTotalChallengeDaysInput(st.finplus_total_challenge_days); localStorage.setItem('finplus_total_challenge_days', st.finplus_total_challenge_days); }
              if (st.finplus_alloc_intraday) { setAllocIntraday(st.finplus_alloc_intraday); localStorage.setItem('finplus_alloc_intraday', st.finplus_alloc_intraday); }
              if (st.finplus_alloc_natgas) { setAllocNatgas(st.finplus_alloc_natgas); localStorage.setItem('finplus_alloc_natgas', st.finplus_alloc_natgas); }
              if (st.finplus_alloc_nifty) { setAllocNifty(st.finplus_alloc_nifty); localStorage.setItem('finplus_alloc_nifty', st.finplus_alloc_nifty); }
              if (st.finplus_alloc_crude) { setAllocCrude(st.finplus_alloc_crude); localStorage.setItem('finplus_alloc_crude', st.finplus_alloc_crude); }
              if (st.finplus_msl_intraday) { setMonthlySlIntraday(st.finplus_msl_intraday); localStorage.setItem('finplus_msl_intraday', st.finplus_msl_intraday); }
              if (st.finplus_msl_natgas) { setMonthlySlNatgas(st.finplus_msl_natgas); localStorage.setItem('finplus_msl_natgas', st.finplus_msl_natgas); }
              if (st.finplus_msl_nifty) { setMonthlySlNifty(st.finplus_msl_nifty); localStorage.setItem('finplus_msl_nifty', st.finplus_msl_nifty); }
              if (st.finplus_msl_crude) { setMonthlySlCrude(st.finplus_msl_crude); localStorage.setItem('finplus_msl_crude', st.finplus_msl_crude); }
            }

            // 2. Push unified union back to server
            const currentSettings = {
              finplus_opening_capital: localStorage.getItem('finplus_opening_capital') || openingCapitalInput,
              finplus_broker_adjustment: localStorage.getItem('finplus_broker_adjustment') || brokerAdjustmentInput,
              finplus_deposits: localStorage.getItem('finplus_deposits') || depositsInput,
              finplus_withdrawals: localStorage.getItem('finplus_withdrawals') || withdrawalsInput,
              finplus_daily_risk_limit: localStorage.getItem('finplus_daily_risk_limit') || dailyRiskLimitInput,
              finplus_challenge_start_date: localStorage.getItem('finplus_challenge_start_date') || challengeStartDateInput,
              finplus_total_challenge_days: localStorage.getItem('finplus_total_challenge_days') || totalChallengeDaysInput,
              finplus_alloc_intraday: localStorage.getItem('finplus_alloc_intraday') || allocIntraday,
              finplus_alloc_natgas: localStorage.getItem('finplus_alloc_natgas') || allocNatgas,
              finplus_alloc_nifty: localStorage.getItem('finplus_alloc_nifty') || allocNifty,
              finplus_alloc_crude: localStorage.getItem('finplus_alloc_crude') || allocCrude,
              finplus_msl_intraday: localStorage.getItem('finplus_msl_intraday') || monthlySlIntraday,
              finplus_msl_natgas: localStorage.getItem('finplus_msl_natgas') || monthlySlNatgas,
              finplus_msl_nifty: localStorage.getItem('finplus_msl_nifty') || monthlySlNifty,
              finplus_msl_crude: localStorage.getItem('finplus_msl_crude') || monthlySlCrude
            };

            await fetch(`${cleanEndpoint}/api/sync/all`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                trades: mergedTrades,
                pullback: mergedPullback,
                settings: currentSettings
              })
            });

            const timeStr = new Date().toLocaleTimeString();
            setLastSyncedTime(timeStr);
            localStorage.setItem('finplus_last_synced_time', timeStr);
            setServerStatus('online');
            syncSuccess = true;
            const stockCount = Object.keys(mergedPullback).filter(k => k.includes('.NS')).length;
            syncMsg = `Synced: ${mergedTrades.length} trades, ${stockCount} stocks & settings updated!`;
            break;
          }
        }
      } catch (e) {}
    }

    setIsSyncing(false);
    if (!silent) {
      if (syncSuccess) {
        showToast(syncMsg, 'success');
      } else {
        showToast('Could not connect to sync server. Check IP & Wi-Fi connection.', 'error');
      }
    }
    return syncSuccess;
  };

  // Initial sync on mount
  useEffect(() => {
    handleSyncAll(null, true);
  }, [API_BASE_URL, serverUrl]);

  // Server Health Status Check Effect
  useEffect(() => {
    const checkServerStatus = async () => {
      const candidates = Array.from(new Set([
        serverUrl, 
        API_BASE_URL, 
        (typeof window !== 'undefined' && window.location.hostname && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1' ? `${window.location.protocol}//${window.location.hostname}:8000` : null),
        'http://127.0.0.1:8000', 
        'http://localhost:8000', 
        RENDER_BACKEND_URL
      ].filter(Boolean)));

      for (const endpoint of candidates) {
        try {
          const res = await fetch(`${endpoint}/health`, { method: 'GET' });
          if (res.ok) {
            const data = await res.json();
            setServerStatus('online');
            if (data.local_ips && Array.isArray(data.local_ips)) {
              setDetectedIps(data.local_ips);
            }
            return;
          }
        } catch (e) {}
      }
      setServerStatus('offline');
    };

    checkServerStatus();
    const interval = setInterval(checkServerStatus, 12000);
    return () => clearInterval(interval);
  }, [API_BASE_URL, serverUrl]);

  const handleSaveServerUrl = async () => {
    const trimmed = serverUrlInput.trim().replace(/\/$/, '');
    localStorage.setItem('finplus_server_url', trimmed);
    setServerUrl(trimmed);
    showToast('Connecting and synchronizing with server...');
    await handleSyncAll(trimmed, false);
  };

  const addStockToSipWatchlist = async (ticker, name, currentPrice) => {
    let cleanSymbol = ticker.toUpperCase().replace('.NS', '');
    const formatted = `${cleanSymbol}.NS`;
    const existingStock = pullbackData[formatted] || pullbackData[cleanSymbol];
    if (existingStock) {
      showToast(`${formatted} is already in your Watchlist!`, 'info');
      return;
    }
    const refPrice = currentPrice > 0 ? currentPrice : 0;
    const txDateStr = new Date().toISOString().split('T')[0];
    const updated = {
      ...pullbackData,
      [formatted]: {
        name: name || cleanSymbol,
        category: 'Core',
        transactions: [],
        local_peak: refPrice,
        date_added: txDateStr,
        initial_reference_price: refPrice
      }
    };
    savePullbackState(updated);
    if (refPrice > 0) {
      setLiveLtps(prev => ({ ...prev, [formatted]: refPrice, [cleanSymbol]: refPrice }));
    }
    showToast(`Added ${formatted} to Watchlist (Pending Initial Buy)!`);
  };


  // Periodically fetch live yfinance LTPs for all monitored stocks in Pullback SIP & MTF
  useEffect(() => {
    const fetchYfinanceLivePrices = async () => {
      const sipTickers = Object.keys(pullbackData).filter(k => k !== 'capital_settings' && k !== 'option_trading' && k !== 'mtf_trading');
      let mtfList = [];
      if (Array.isArray(pullbackData.mtf_trading)) {
        mtfList = pullbackData.mtf_trading;
      } else if (pullbackData.mtf_trading && Array.isArray(pullbackData.mtf_trading.trades)) {
        mtfList = pullbackData.mtf_trading.trades;
      }
      const mtfTickers = mtfList.map(m => m.ticker).filter(Boolean);
      const tickers = Array.from(new Set([...sipTickers, ...mtfTickers]));
      if (tickers.length === 0) return;

      const queryStr = tickers.join(',');
      let fetchedPrices = {};

      const apiEndpoints = Array.from(new Set([API_BASE_URL, RENDER_BACKEND_URL, 'http://127.0.0.1:8000'].filter(Boolean)));
      for (const endpoint of apiEndpoints) {
        try {
          const res = await fetch(`${endpoint}/api/investment/yfinance-prices?tickers=${encodeURIComponent(queryStr)}`);
          if (res.ok) {
            const data = await res.json();
            if (data && data.prices) {
              Object.entries(data.prices).forEach(([sym, info]) => {
                if (info && info.ltp) {
                  const clean = sym.replace('.NS', '').trim();
                  fetchedPrices[sym] = info.ltp;
                  fetchedPrices[clean] = info.ltp;
                  fetchedPrices[clean.toUpperCase()] = info.ltp;
                }
              });
              if (Object.keys(fetchedPrices).length > 0) break;
            }
          }
        } catch (e) {}
      }

      // Tier 3: Direct Yahoo Finance API fallback for any un-priced ticker
      for (const sym of tickers) {
        const clean = sym.replace('.NS', '').trim();
        if (!fetchedPrices[sym]) {
          try {
            const yRes = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}`);
            if (yRes.ok) {
              const yData = await yRes.json();
              const price = yData?.chart?.result?.[0]?.meta?.regularMarketPrice;
              if (price) {
                fetchedPrices[sym] = price;
                fetchedPrices[clean] = price;
              }
            }
          } catch (e) {}
        }
      }

      if (Object.keys(fetchedPrices).length > 0) {
        setLiveLtps(prev => ({ ...prev, ...fetchedPrices }));
      }
    };

    fetchYfinanceLivePrices();
    const interval = setInterval(fetchYfinanceLivePrices, 10000);
    return () => clearInterval(interval);
  }, [pullbackData]);

  // Persist pullbackData to localStorage and backend (multi-endpoint sync)
  const savePullbackState = async (updatedData) => {
    setPullbackData(updatedData);
    localStorage.setItem('finplus_pullback_portfolio', JSON.stringify(updatedData));
    const endpoints = Array.from(new Set([API_BASE_URL, RENDER_BACKEND_URL, 'http://127.0.0.1:8000'].filter(Boolean)));
    for (const endpoint of endpoints) {
      try {
        await fetch(`${endpoint}/api/investment/pullback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updatedData)
        });
      } catch (e) {}
    }
  };

  // Pullback & MTF Top-Level Scope Calculations
  const sipCapSettings = pullbackData.capital_settings || { start_date: '2026-07-03', initial_capital: 330.51, daily_rate: 200.0 };
  const sipStartDt = new Date(sipCapSettings.start_date || '2026-07-03');
  const todayDt = new Date();
  sipStartDt.setHours(0, 0, 0, 0);
  todayDt.setHours(0, 0, 0, 0);
  const sipDaysPassed = Math.max(0, Math.floor((todayDt.getTime() - sipStartDt.getTime()) / (1000 * 60 * 60 * 24)));
  const totalSipAccumulatedCap = (Number(sipCapSettings.initial_capital) || 0) + (sipDaysPassed * (Number(sipCapSettings.daily_rate) || 200));

  const stockTickersList = Object.keys(pullbackData).filter(k => k !== 'capital_settings' && k !== 'option_trading' && k !== 'mtf_trading');

  let totalSipDeployedCost = 0;
  let totalSipCurrentVal = 0;
  let totalSipRealizedProfit = 0;
  let totalSipBuyTxCount = 0;
  let totalSipSellTxCount = 0;

  const pullbackStockSummary = stockTickersList.map(ticker => {
    const details = pullbackData[ticker] || {};
    const txs = details.transactions || [];
    let netShares = 0;
    let netCost = 0;
    let realizedProfit = 0;

    txs.forEach(t => {
      const sh = Number(t.shares) || 0;
      const pr = Number(t.price) || 0;
      if (sh > 0) {
        netShares += sh;
        netCost += sh * pr;
        totalSipBuyTxCount++;
      } else if (sh < 0) {
        totalSipSellTxCount++;
        const sellShares = Math.abs(sh);
        const avgBuy = netShares > 0 ? netCost / netShares : pr;
        realizedProfit += (pr - avgBuy) * sellShares;
        netShares = Math.max(0, netShares - sellShares);
        netCost = netShares * avgBuy;
      }
    });

    totalSipDeployedCost += netCost;
    totalSipRealizedProfit += realizedProfit;

    const cleanSym = ticker.replace('.NS', '').trim();
    const category = details.category || 'Core';
    const isPark = category === 'Park';
    const ltp = liveLtps[cleanSym] || liveLtps[ticker] || details.initial_reference_price || (txs.length > 0 ? txs[txs.length - 1].price : 0);
    const peak = details.local_peak || ltp;
    const targetBuyPrice = isPark ? 0 : peak * 0.95; // 5% Pullback Target Price Level (disabled for Park)
    const currentVal = netShares * ltp;
    totalSipCurrentVal += currentVal;

    const unrealizedPnl = currentVal - netCost;
    const pnlPct = netCost > 0 ? (unrealizedPnl / netCost) * 100 : 0;
    const pullbackPct = (peak > 0 && !isPark) ? ((peak - ltp) / peak) * 100 : 0;

    // Chronological Last Buy Transaction Date & Cool-down Math
    const buyTxs = txs.filter(t => Number(t.shares) > 0).sort((a, b) => new Date(a.date) - new Date(b.date));
    const lastBuyTx = buyTxs.length > 0 ? buyTxs[buyTxs.length - 1] : null;
    
    let daysSinceLastBuyStr = 'Never';
    let daysSinceLastBuyNum = 9999;
    let daysNeverBought = 0;  // days since added, for stocks never bought
    let cooldownUntilStr = '';
    let isCoolingDown = false;

    if (lastBuyTx && lastBuyTx.date) {
      const lastBuyDt = new Date(lastBuyTx.date);
      lastBuyDt.setHours(0,0,0,0);
      daysSinceLastBuyNum = Math.max(0, Math.floor((todayDt.getTime() - lastBuyDt.getTime()) / (1000 * 60 * 60 * 24)));
      daysSinceLastBuyStr = `${daysSinceLastBuyNum} days`;
      
      const allowedDt = new Date(lastBuyDt.getTime() + (7 * 24 * 60 * 60 * 1000));
      cooldownUntilStr = allowedDt.toISOString().split('T')[0];
      if (daysSinceLastBuyNum < 7) {
        isCoolingDown = true;
      }
    } else {
      const dateAdded = new Date(details.date_added || '2026-07-03');
      dateAdded.setHours(0,0,0,0);
      daysNeverBought = Math.max(0, Math.floor((todayDt.getTime() - dateAdded.getTime()) / (1000 * 60 * 60 * 24)));
      daysSinceLastBuyStr = `Never (${daysNeverBought}d added)`;
    }

    let systemStatus = '🟢 Active';
    let signalClass = 'active';

    if (isPark) {
      systemStatus = '🅿️ Parked ETF / Reserve';
      signalClass = 'park';
    } else if (netShares === 0) {
      if (ltp <= targetBuyPrice || pullbackPct >= 5.0) {
        systemStatus = '🟢 BUY TRIGGERED';
        signalClass = 'buy';
      } else if (daysNeverBought >= 25) {
        systemStatus = '🟢 BUY TRIGGERED (25d Waiting Period)';
        signalClass = 'buy';
      } else {
        systemStatus = `🟣 Pending Initial Buy (${daysNeverBought}/25d)`;
        signalClass = 'pending';
      }
    } else if (isCoolingDown) {
      systemStatus = `⏳ COOLDOWN (Until ${cooldownUntilStr})`;
      signalClass = 'cooldown';
    } else if (ltp <= targetBuyPrice || pullbackPct >= 5.0) {
      systemStatus = '🟢 BUY TRIGGERED';
      signalClass = 'buy';
    } else if (daysSinceLastBuyNum >= 25 && daysSinceLastBuyNum < 9000) {
      systemStatus = '⏱️ TIME-OUT BUY';
      signalClass = 'timeout';
    }

    return {
      ticker,
      cleanSym,
      name: details.name || ticker,
      category: details.category || 'Core',
      netShares,
      avgCost: netShares > 0 ? netCost / netShares : 0,
      netCost,
      ltp,
      peak,
      targetBuyPrice,
      currentVal,
      unrealizedPnl,
      pnlPct,
      pullbackPct,
      daysSinceLastBuyStr,
      daysSinceLastBuyNum,
      isCoolingDown,
      cooldownUntilStr,
      systemStatus,
      signalClass,
      lastTxDateStr: lastBuyTx ? lastBuyTx.date : (details.date_added || '2026-07-03')
    };
  });

  // Zerodha Equity Delivery Statutory Charges Engine (Zero Brokerage, 0.1% STT, 0.015% Stamp Duty, 0.00297% NSE Txn, 18% GST)
  let totalSipDeliveryTaxes = 0;
  let totalSipStt = 0;
  let totalSipStampDuty = 0;
  let totalSipExchangeTxn = 0;
  let totalSipGst = 0;
  let totalSipDpCharges = 0;

  stockTickersList.forEach(ticker => {
    const details = pullbackData[ticker] || {};
    const txs = details.transactions || [];
    txs.forEach(t => {
      const sh = Number(t.shares) || 0;
      const pr = Number(t.price) || 0;
      const amt = Math.abs(sh) * pr;
      if (sh > 0) {
        const stt = amt * 0.001; // 0.1% STT on Buy
        const stamp = amt * 0.00015; // 0.015% Stamp Duty on Buy
        const txn = amt * 0.0000297; // 0.00297% NSE Exchange Txn
        const sebi = amt * 0.000001; // SEBI turnover fee
        const gst = (txn + sebi) * 0.18; // 18% GST
        const total = stt + stamp + txn + sebi + gst;

        totalSipDeliveryTaxes += total;
        totalSipStt += stt;
        totalSipStampDuty += stamp;
        totalSipExchangeTxn += txn;
        totalSipGst += gst;
      } else if (sh < 0) {
        const stt = amt * 0.001; // 0.1% STT on Sell
        const txn = amt * 0.0000297;
        const sebi = amt * 0.000001;
        const gst = (txn + sebi) * 0.18;
        const dp = 15.34; // ₹13 + 18% GST DP Charge
        const total = stt + txn + sebi + gst + dp;

        totalSipDeliveryTaxes += total;
        totalSipStt += stt;
        totalSipExchangeTxn += txn;
        totalSipGst += gst;
        totalSipDpCharges += dp;
      }
    });
  });

  const totalSipUnrealizedPnl = totalSipCurrentVal - totalSipDeployedCost;
  const totalSipNetPnl = totalSipUnrealizedPnl - totalSipDeliveryTaxes;
  const totalSipNetPnlPct = totalSipDeployedCost > 0 ? (totalSipNetPnl / totalSipDeployedCost) * 100 : 0;

  // Detailed list of all historical SIP Sell transactions
  const sipSoldTradesList = [];
  let totalSipSellTaxes = 0;

  stockTickersList.forEach(ticker => {
    const details = pullbackData[ticker] || {};
    const txs = details.transactions || [];
    let runningShares = 0;
    let runningCost = 0;

    txs.forEach((t, idx) => {
      const sh = Number(t.shares) || 0;
      const pr = Number(t.price) || 0;
      if (sh > 0) {
        runningShares += sh;
        runningCost += sh * pr;
      } else if (sh < 0) {
        const sellShares = Math.abs(sh);
        const avgBuy = runningShares > 0 ? runningCost / runningShares : pr;
        const grossProfit = (pr - avgBuy) * sellShares;
        const profitPct = avgBuy > 0 ? ((pr - avgBuy) / avgBuy) * 100 : 0;

        const amt = sellShares * pr;
        const stt = amt * 0.001;
        const txn = amt * 0.0000297;
        const sebi = amt * 0.000001;
        const gst = (txn + sebi) * 0.18;
        const dp = 15.34; // ₹13 + 18% GST Zerodha DP charge
        const sellTaxes = stt + txn + sebi + gst + dp;
        const netProfit = grossProfit - sellTaxes;

        totalSipSellTaxes += sellTaxes;

        sipSoldTradesList.push({
          id: `${ticker}-${idx}-${t.date}`,
          ticker,
          cleanSym: ticker.replace('.NS', '').trim(),
          name: details.name || ticker,
          category: details.category || 'Core',
          sellDate: t.date,
          sharesSold: sellShares,
          avgBuyPrice: avgBuy,
          sellPrice: pr,
          sellValue: amt,
          grossPnl: grossProfit,
          grossPnlPct: profitPct,
          taxes: sellTaxes,
          netPnl: netProfit,
          txIndex: idx
        });

        runningShares = Math.max(0, runningShares - sellShares);
        runningCost = runningShares * avgBuy;
      }
    });
  });

  // Sort sold trades by date descending (most recent first)
  sipSoldTradesList.sort((a, b) => new Date(b.sellDate) - new Date(a.sellDate));

  const totalSipRealizedNetProfit = totalSipRealizedProfit - totalSipSellTaxes;
  const totalSipCombinedNetPnl = (totalSipUnrealizedPnl + totalSipRealizedProfit) - totalSipDeliveryTaxes;

  const availableSipCash = Math.max(0, totalSipAccumulatedCap - totalSipDeployedCost + (totalSipRealizedProfit * 0.5));
  const mutualFundSweepProfit = totalSipRealizedProfit * 0.5;

  const mtfTradeList = Array.isArray(pullbackData.mtf_trading)
    ? pullbackData.mtf_trading
    : (pullbackData.mtf_trading ? (pullbackData.mtf_trading.trades || []) : []);

  let activeMtfDeployedMargin = 0;
  let activeMtfBrokerFunding = 0;
  let activeMtfCurrentVal = 0;
  let activeMtfCarryingCharges = 0;
  let activeMtfInterest14 = 0;
  let activeMtfGrossPnl = 0;
  let activeMtfNetPnl = 0;

  let overallMtfDeployedMargin = 0;
  let overallMtfBrokerFunding = 0;
  let overallMtfCurrentVal = 0;
  let overallMtfGrossPnl = 0;
  let overallMtfInterest14 = 0;
  let overallMtfBrokerage = 0;
  let overallMtfPledge = 0;
  let overallMtfGovt = 0;
  let overallMtfCarryingCharges = 0;
  let overallMtfNetPnl = 0;

  let closedMtfGrossPnl = 0;
  let closedMtfInterest14 = 0;
  let closedMtfBrokerage = 0;
  let closedMtfPledge = 0;
  let closedMtfGovt = 0;
  let closedMtfCarryingCharges = 0;
  let closedMtfNetPnl = 0;

  const mtfSummaryList = mtfTradeList.map(t => {
    const cleanSym = t.ticker.replace('.NS', '').trim();
    const ltp = liveLtps[cleanSym] || liveLtps[t.ticker] || t.buy_price;
    const totalBuyVal = t.shares * t.buy_price;
    
    // Broker Funding % (Default 68.0%, User margin = 32.0%)
    const brokerFundedPct = t.broker_funding_pct !== undefined ? Number(t.broker_funding_pct) : 68.0;
    const userFundedPct = 100.0 - brokerFundedPct;
    const funding = t.broker_funding || (totalBuyVal * (brokerFundedPct / 100.0));
    const marginPaid = t.margin_paid || t.margin_used || (totalBuyVal - funding);

    // Holding Period & 14% Interest Math
    const buyDtStr = t.buy_date || '2026-08-03';
    const buyDt = new Date(buyDtStr);
    buyDt.setHours(0,0,0,0);
    const endDtStr = (t.status === 'Closed' && t.sell_date) ? t.sell_date : new Date().toISOString().split('T')[0];
    const endDt = new Date(endDtStr);
    endDt.setHours(0,0,0,0);
    
    const diffTime = Math.max(0, endDt.getTime() - buyDt.getTime());
    const holdingDays = Math.max(1, Math.floor(diffTime / (1000 * 60 * 60 * 24)));

    // 14% p.a. Interest Accrual
    const interestCost14 = funding * (0.14) * (holdingDays / 365.0);
    const interestCost999 = funding * (0.0999) * (holdingDays / 365.0);

    // Dynamic INDmoney / Zerodha Percentage-Based Tariff Charges
    const sellOrLtpPrice = t.status === 'Closed' ? (t.sell_price || ltp) : ltp;
    const currentVal = t.shares * sellOrLtpPrice;

    // 1. Brokerage: 0.05% per order, max ₹20 per side
    const buyBrokerage = Math.min(20, totalBuyVal * 0.0005);
    const sellBrokerage = Math.min(20, currentVal * 0.0005);
    const brokerage = buyBrokerage + sellBrokerage;

    // 2. Pledge / Unpledge Charges: ₹23.60 flat (₹20 + 18% GST)
    const pledgeCharges = 23.60;

    // 3. Percentage-Based Govt & Statutory Charges
    const sttCost = (totalBuyVal * 0.001) + (currentVal * 0.001); // 0.1% buy + 0.1% sell
    const stampDutyCost = totalBuyVal * 0.00015; // 0.015% buy
    const exchangeTxnFee = (totalBuyVal + currentVal) * 0.0000297; // 0.00297% NSE
    const sebiFee = (totalBuyVal + currentVal) * 0.000001; // ₹10/crore
    const gstCost = (brokerage + exchangeTxnFee) * 0.18; // 18% GST on brokerage + txn fee
    const govtOtherCharges = sttCost + stampDutyCost + exchangeTxnFee + sebiFee + gstCost;

    const totalCarryingCost = interestCost14 + brokerage + pledgeCharges + govtOtherCharges;

    // P&L Calculations
    const grossPnl = currentVal - totalBuyVal;
    const netPnl = grossPnl - totalCarryingCost;
    const netReturnPct = marginPaid > 0 ? (netPnl / marginPaid) * 100 : 0;

    // Overall Accumulation (Deployed capital/value only applies to Active positions)
    if (t.status === 'Active') {
      overallMtfDeployedMargin += marginPaid;
      overallMtfBrokerFunding += funding;
      overallMtfCurrentVal += currentVal;
    }
    overallMtfGrossPnl += grossPnl;
    overallMtfInterest14 += interestCost14;
    overallMtfBrokerage += brokerage;
    overallMtfPledge += pledgeCharges;
    overallMtfGovt += govtOtherCharges;
    overallMtfCarryingCharges += totalCarryingCost;
    overallMtfNetPnl += netPnl;

    if (t.status === 'Active') {
      activeMtfDeployedMargin += marginPaid;
      activeMtfBrokerFunding += funding;
      activeMtfCurrentVal += currentVal;
      activeMtfCarryingCharges += totalCarryingCost;
      activeMtfInterest14 += interestCost14;
      activeMtfGrossPnl += grossPnl;
      activeMtfNetPnl += netPnl;
    } else if (t.status === 'Closed') {
      closedMtfGrossPnl += grossPnl;
      closedMtfInterest14 += interestCost14;
      closedMtfBrokerage += brokerage;
      closedMtfPledge += pledgeCharges;
      closedMtfGovt += govtOtherCharges;
      closedMtfCarryingCharges += totalCarryingCost;
      closedMtfNetPnl += netPnl;
    }

    // 5% Fixed Trailing Stop Loss Calculation (Includes all charges plus accumulated 14% interest)
    // IMPORTANT: SL Level is 100% ratcheted to PEAK. It NEVER decreases when LTP drops!
    const storedPeak = t.peak_price || t.buy_price;
    const peakLtp = Math.max(t.buy_price, storedPeak, ltp);
    
    // Gross 5% Trailing SL level (5% drop from peak stock price)
    const grossSlPrice = peakLtp * 0.95;
    
    // Evaluate tariff charges at the fixed SL price level so SL level does NOT drift with falling LTP
    const slVal = t.shares * grossSlPrice;
    const slBuyBrokerage = Math.min(20, totalBuyVal * 0.0005);
    const slSellBrokerage = Math.min(20, slVal * 0.0005);
    const slBrokerage = slBuyBrokerage + slSellBrokerage;
    const slPledge = 23.60;
    const slStt = (totalBuyVal * 0.001) + (slVal * 0.001);
    const slStamp = totalBuyVal * 0.00015;
    const slExchange = (totalBuyVal + slVal) * 0.0000297;
    const slSebi = (totalBuyVal + slVal) * 0.000001;
    const slGst = (slBrokerage + slExchange) * 0.18;
    const slGovt = slStt + slStamp + slExchange + slSebi + slGst;
    
    const fixedCarryingCostAtSL = interestCost14 + slBrokerage + slPledge + slGovt;
    const carryingCostPerShare = t.shares > 0 ? (fixedCarryingCostAtSL / t.shares) : 0;
    
    // Net 5% Trailing SL level (Rigidly locked to peak; adjusts upward with daily accrued interest)
    const netSlPrice = grossSlPrice + carryingCostPerShare;
    
    const tslBuffer = ltp - netSlPrice;
    const tslBufferPct = ltp > 0 ? ((ltp - netSlPrice) / ltp) * 100 : 0;

    let tslStatusTag = '🟢 SL SAFE';
    let tslStatusBg = 'rgba(52, 211, 153, 0.15)';
    let tslStatusColor = '#34d399';
    let tslStatusBorder = 'rgba(52, 211, 153, 0.3)';

    if (t.status === 'Closed') {
      tslStatusTag = '🏁 CLOSED';
      tslStatusBg = 'rgba(255,255,255,0.06)';
      tslStatusColor = '#a5b4fc';
      tslStatusBorder = 'rgba(255,255,255,0.1)';
    } else if (ltp <= netSlPrice) {
      tslStatusTag = '🔴 5% TRAILING SL HIT (SELL SIGNAL)';
      tslStatusBg = 'rgba(239, 68, 68, 0.25)';
      tslStatusColor = '#f87171';
      tslStatusBorder = 'rgba(239, 68, 68, 0.5)';
    } else if (ltp <= netSlPrice * 1.015) {
      tslStatusTag = '⚠️ NEAR TRAILING SL (Caution)';
      tslStatusBg = 'rgba(245, 158, 11, 0.25)';
      tslStatusColor = '#fbbf24';
      tslStatusBorder = 'rgba(245, 158, 11, 0.5)';
    }

    return {
      ...t,
      cleanSym,
      ltp,
      totalBuyVal,
      marginPaid,
      funding,
      userFundedPct,
      brokerFundedPct,
      buyDtStr,
      endDtStr,
      holdingDays,
      interestCost14,
      interestCost999,
      brokerage,
      pledgeCharges,
      sttCost,
      stampDutyCost,
      exchangeTxnFee,
      sebiFee,
      gstCost,
      govtOtherCharges,
      totalCarryingCost,
      sellOrLtpPrice,
      currentVal,
      grossPnl,
      netPnl,
      netReturnPct,
      peakLtp,
      carryingCostPerShare,
      grossSlPrice,
      netSlPrice,
      tslBuffer,
      tslBufferPct,
      tslStatusTag,
      tslStatusBg,
      tslStatusColor,
      tslStatusBorder
    };
  });

  // Handlers for 5% Pullback SIP & MTF Margin Trading
  const handleAddStockToWatchlist = async (e) => {
    e.preventDefault();
    if (!newSipTicker.trim()) return;
    let inputSym = newSipTicker.trim().toUpperCase();
    const inputClean = inputSym.replace('.NS', '').trim().toLowerCase();

    const matchedStock = combinedStockList.find(s => {
      const sym = (s.symbol || '').toUpperCase();
      const name = (s.name || '').toUpperCase();
      const cleanSym = sym.replace('.NS', '');
      const aliases = (s.aliases || []).map(a => a.toUpperCase());
      return cleanSym === inputSym || sym === inputSym || name === inputSym || aliases.includes(inputSym) || aliases.includes(inputClean.toUpperCase());
    });

    let cleanSymbol = matchedStock ? matchedStock.symbol.toUpperCase().replace('.NS', '') : inputSym.replace(/\s+/g, '').replace('.NS', '');
    const formatted = `${cleanSymbol}.NS`;

    const sharesNum = Number(newSipShares) || 0;
    const priceNum = Number(newSipBuyPrice) || 0;
    const txDateStr = newSipTxDate || new Date().toISOString().split('T')[0];

    const existingStock = pullbackData[formatted] || pullbackData[cleanSymbol] || pullbackData[inputSym];

    if (existingStock) {
      // IF STOCK ALREADY EXISTS IN PORTFOLIO/WATCHLIST (e.g. ITC.NS)
      if (sharesNum > 0 && priceNum > 0) {
        const updatedTxs = [
          ...(existingStock.transactions || []),
          { date: txDateStr, price: priceNum, shares: sharesNum }
        ];

        let totalSh = 0;
        let totalCost = 0;
        updatedTxs.forEach(t => {
          const s = Number(t.shares) || 0;
          const p = Number(t.price) || 0;
          if (s > 0) { totalSh += s; totalCost += s * p; }
          else if (s < 0) { totalSh = Math.max(0, totalSh + s); }
        });
        const newAvg = totalSh > 0 ? totalCost / totalSh : priceNum;

        const updated = {
          ...pullbackData,
          [formatted]: {
            ...existingStock,
            transactions: updatedTxs
          }
        };

        savePullbackState(updated);
        showToast(`Logged purchase of ${sharesNum} share(s) of ${formatted} @ ₹${priceNum.toFixed(2)}! Total position: ${totalSh} share(s) @ avg ₹${newAvg.toFixed(2)}.`);
        setNewSipTicker('');
        setNewSipName('');
        setNewSipShares('1');
        setNewSipBuyPrice('');
        setShowNiftyDropdown(false);
        return;
      } else {
        showToast(`${formatted} is already in your Watchlist. Enter Shares (>0) & Buy Price (₹) to record an additional purchase.`, 'info');
        setShowNiftyDropdown(false);
        return;
      }
    }

    let liveFetchedPrice = 0;
    const apiEndpoints = [API_BASE_URL, 'https://finplus.onrender.com', 'http://127.0.0.1:8000'];
    for (const endpoint of apiEndpoints) {
      try {
        const res = await fetch(`${endpoint}/api/investment/yfinance-prices?tickers=${encodeURIComponent(formatted)}`);
        if (res.ok) {
          const data = await res.json();
          const pObj = data.prices?.[formatted] || data.prices?.[cleanSymbol] || data.prices?.[inputSym];
          if (pObj && pObj.ltp) {
            liveFetchedPrice = pObj.ltp;
            break;
          }
        }
      } catch (e) {}
    }

    const finalName = (matchedStock ? matchedStock.name : newSipName.trim()) || cleanSymbol;
    const initialTxs = (sharesNum > 0 && priceNum > 0)
      ? [{ date: txDateStr, price: priceNum, shares: sharesNum }]
      : [];

    const refPrice = liveFetchedPrice > 0 ? liveFetchedPrice : (priceNum > 0 ? priceNum : 0);

    const updated = {
      ...pullbackData,
      [formatted]: {
        name: finalName,
        category: newSipCategory,
        transactions: initialTxs,
        local_peak: refPrice,
        date_added: txDateStr,
        initial_reference_price: refPrice
      }
    };

    savePullbackState(updated);
    if (refPrice > 0) {
      setLiveLtps(prev => ({ ...prev, [formatted]: refPrice, [cleanSymbol]: refPrice }));
    }

    if (sharesNum > 0 && priceNum > 0) {
      showToast(`Added ${formatted} (${finalName}) to portfolio with ${sharesNum} share(s) @ ₹${priceNum.toFixed(2)}!`);
    } else {
      showToast(`Added ${formatted} (${finalName}) to Watchlist (Pending Initial Buy)!`);
    }

    setNewSipTicker('');
    setNewSipName('');
    setNewSipShares('1');
    setNewSipBuyPrice('');
    setShowNiftyDropdown(false);
  };

  const handleDeleteStockFromWatchlist = (ticker) => {
    const cleanSym = ticker.replace('.NS', '').trim();
    const stockObj = pullbackData[ticker] || {};
    const hasTransactions = Array.isArray(stockObj.transactions) && stockObj.transactions.length > 0;

    if (!window.confirm(`Are you sure you want to remove ${cleanSym} from your Active Watchlist?${hasTransactions ? ' (All historical buy & sell records will remain safely preserved in Sold History).' : ''}`)) return;

    const updated = { ...pullbackData };
    if (hasTransactions) {
      // Keep transaction history intact, but mark as hidden from active watchlist
      updated[ticker] = {
        ...stockObj,
        in_watchlist: false
      };
      showToast(`Removed ${cleanSym} from Active Watchlist (past trade history preserved in Sold History)!`);
    } else {
      delete updated[ticker];
      showToast(`Removed ${cleanSym} from 5% SIP Watchlist!`);
    }

    savePullbackState(updated);
  };

  const handleRecordSipSellSubmit = (e) => {
    e.preventDefault();
    if (!sipSellSelectedTicker) {
      showToast("Please select a stock holding to sell.", "error");
      return;
    }
    const holding = pullbackStockSummary.find(s => s.ticker === sipSellSelectedTicker);
    if (!holding || holding.netShares <= 0) {
      showToast("No shares available to sell for this stock.", "error");
      return;
    }
    const sharesNum = parseInt(sipSellFormShares) || 0;
    const priceNum = parseFloat(sipSellFormPrice) || 0;
    const txDateStr = sipSellFormDate || new Date().toISOString().split('T')[0];

    if (sharesNum <= 0) {
      showToast("Please enter a valid share quantity (> 0).", "error");
      return;
    }
    if (sharesNum > holding.netShares) {
      showToast(`Cannot sell ${sharesNum} shares. You currently hold ${holding.netShares} shares.`, "error");
      return;
    }
    if (priceNum <= 0) {
      showToast("Please enter a valid sell execution price (₹).", "error");
      return;
    }

    const stockObj = pullbackData[sipSellSelectedTicker] || { name: sipSellSelectedTicker, category: 'Core', transactions: [] };
    const existingTxs = stockObj.transactions || [];
    const newTx = { date: txDateStr, price: priceNum, shares: -Math.abs(sharesNum), type: 'SELL' };

    const updated = {
      ...pullbackData,
      [sipSellSelectedTicker]: {
        ...stockObj,
        transactions: [...existingTxs, newTx]
      }
    };

    savePullbackState(updated);
    const avgCost = holding.avgCost || priceNum;
    const realizedProfit = (priceNum - avgCost) * sharesNum;
    showToast(`Recorded SALE of ${sharesNum} share(s) of ${holding.cleanSym} @ ₹${priceNum.toFixed(2)} (Realized: ${realizedProfit >= 0 ? '+' : ''}₹${realizedProfit.toFixed(2)})!`);
    
    setSipSellFormShares('1');
    setSipSellFormPrice('');
  };

  const handleConfirmSellModal = (e) => {
    e.preventDefault();
    if (!sipSellModalStock) return;
    const ticker = sipSellModalStock.ticker;
    const holding = pullbackStockSummary.find(s => s.ticker === ticker);
    const availableShares = holding ? holding.netShares : (sipSellModalStock.netShares || 0);

    const sharesNum = parseInt(sipSellModalShares) || 0;
    const priceNum = parseFloat(sipSellModalPrice) || 0;
    const txDateStr = sipSellModalDate || new Date().toISOString().split('T')[0];

    if (sharesNum <= 0) {
      showToast("Please enter a valid share quantity (> 0).", "error");
      return;
    }
    if (sharesNum > availableShares) {
      showToast(`Cannot sell ${sharesNum} shares. You currently hold ${availableShares} shares.`, "error");
      return;
    }
    if (priceNum <= 0) {
      showToast("Please enter a valid sell execution price (₹).", "error");
      return;
    }

    const stockObj = pullbackData[ticker] || { name: ticker, category: 'Core', transactions: [] };
    const existingTxs = stockObj.transactions || [];
    const newTx = { date: txDateStr, price: priceNum, shares: -Math.abs(sharesNum), type: 'SELL' };

    const updated = {
      ...pullbackData,
      [ticker]: {
        ...stockObj,
        transactions: [...existingTxs, newTx]
      }
    };

    savePullbackState(updated);
    const avgCost = sipSellModalStock.avgCost || (holding ? holding.avgCost : priceNum);
    const realizedProfit = (priceNum - avgCost) * sharesNum;
    showToast(`Recorded SALE of ${sharesNum} share(s) of ${sipSellModalStock.cleanSym} @ ₹${priceNum.toFixed(2)} (Realized: ${realizedProfit >= 0 ? '+' : ''}₹${realizedProfit.toFixed(2)})!`);

    setSipSellModalStock(null);
  };

  const handleDeleteSipTx = (ticker, txIndex) => {
    const stockObj = pullbackData[ticker];
    if (!stockObj || !stockObj.transactions) return;
    const tx = stockObj.transactions[txIndex];
    const txLabel = tx ? `${tx.shares > 0 ? 'Buy' : 'Sell'} of ${Math.abs(tx.shares)} share(s) @ ₹${tx.price} on ${tx.date}` : 'transaction';
    if (!window.confirm(`Are you sure you want to delete this ${txLabel} for ${ticker.replace('.NS', '')}?`)) return;

    const updatedTxs = stockObj.transactions.filter((_, idx) => idx !== txIndex);
    const updated = {
      ...pullbackData,
      [ticker]: {
        ...stockObj,
        transactions: updatedTxs
      }
    };

    savePullbackState(updated);
    showToast(`Deleted transaction for ${ticker.replace('.NS', '')}!`);
  };

  const handleOpenSipEditModal = (stock) => {
    const ticker = stock.ticker;
    const details = pullbackData[ticker] || {};
    const txs = Array.isArray(details.transactions) ? details.transactions : [];
    
    setSipEditModalStock(stock);
    setEditSipName(details.name || stock.name || stock.cleanSym);
    setEditSipCategory(details.category || stock.category || 'Core');
    setEditSipPeak(details.local_peak ? String(details.local_peak) : (stock.peak ? String(stock.peak) : ''));
    setEditSipTxs(txs.map((t, idx) => ({
      id: idx,
      date: t.date || new Date().toISOString().split('T')[0],
      shares: Math.abs(Number(t.shares) || 1),
      price: Number(t.price) || 0,
      type: (Number(t.shares) < 0 || t.type === 'SELL') ? 'SELL' : 'BUY'
    })));
  };

  const handleSaveSipEdit = (e) => {
    if (e) e.preventDefault();
    if (!sipEditModalStock) return;
    const ticker = sipEditModalStock.ticker;
    const existing = pullbackData[ticker] || {};

    const formattedTxs = editSipTxs
      .filter(t => Math.abs(Number(t.shares)) > 0 && Number(t.price) > 0)
      .map(t => {
        const sharesNum = Math.abs(Number(t.shares));
        const isSell = t.type === 'SELL';
        return {
          date: t.date || new Date().toISOString().split('T')[0],
          price: parseFloat(t.price),
          shares: isSell ? -sharesNum : sharesNum,
          ...(isSell ? { type: 'SELL' } : {})
        };
      });

    const peakNum = editSipPeak ? parseFloat(editSipPeak) : (existing.local_peak || 0);

    const updated = {
      ...pullbackData,
      [ticker]: {
        ...existing,
        name: editSipName.trim() || ticker,
        category: editSipCategory,
        local_peak: peakNum,
        transactions: formattedTxs
      }
    };

    savePullbackState(updated);
    setSipEditModalStock(null);
    showToast(`Updated ${sipEditModalStock.cleanSym} successfully!`);
  };

  const handleRecordMtfTx = (e) => {
    e.preventDefault();
    if (!mtfTicker || !mtfBuyPrice || parseFloat(mtfBuyPrice) <= 0) return;
    const pr = parseFloat(mtfBuyPrice);
    const sh = parseInt(mtfShares) || 1;
    const totalVal = pr * sh;
    
    // Broker Funding % (default 68.0%, user margin = 32.0%)
    const brokerFundedPct = Math.min(100, Math.max(0, parseFloat(mtfBrokerFundedPct) || 68.0));
    const userMarginPct = 100.0 - brokerFundedPct;
    
    const funding = totalVal * (brokerFundedPct / 100.0);
    const marginPaid = totalVal - funding;

    const currentMtfList = Array.isArray(pullbackData.mtf_trading)
      ? pullbackData.mtf_trading
      : (pullbackData.mtf_trading ? (pullbackData.mtf_trading.trades || []) : []);

    const newId = currentMtfList.length > 0 ? Math.max(...currentMtfList.map(t => t.id || 0)) + 1 : 0;
    const formattedTicker = mtfTicker.trim().toUpperCase().endsWith('.NS') ? mtfTicker.trim().toUpperCase() : `${mtfTicker.trim().toUpperCase()}.NS`;

    const newMtfTrade = {
      id: newId,
      ticker: formattedTicker,
      buy_date: mtfBuyDate || new Date().toISOString().split('T')[0],
      buy_price: pr,
      shares: sh,
      broker_funding_pct: brokerFundedPct,
      margin_ratio: userMarginPct / 100.0,
      margin_paid: marginPaid,
      broker_funding: funding,
      status: 'Active'
    };

    const updated = {
      ...pullbackData,
      mtf_trading: Array.isArray(pullbackData.mtf_trading) ? [newMtfTrade, ...currentMtfList] : {
        ...pullbackData.mtf_trading,
        trades: [newMtfTrade, ...currentMtfList]
      }
    };
    savePullbackState(updated);
    showToast(`Logged MTF Position for ${formattedTicker} (${sh} shares @ ₹${pr}, ${brokerFundedPct}% Broker Funded)!`);
    setMtfTicker('');
    setMtfBuyPrice('');
  };

  const handleCloseMtfTx = (tradeId) => {
    const exitPriceStr = prompt("Enter Exit Price for MTF Trade (₹):");
    if (!exitPriceStr || parseFloat(exitPriceStr) <= 0) return;
    const exitPr = parseFloat(exitPriceStr);

    const currentMtfList = Array.isArray(pullbackData.mtf_trading)
      ? pullbackData.mtf_trading
      : (pullbackData.mtf_trading ? (pullbackData.mtf_trading.trades || []) : []);

    const updatedMtfList = currentMtfList.map(t => {
      if (t.id === tradeId) {
        return {
          ...t,
          status: 'Closed',
          sell_date: new Date().toISOString().split('T')[0],
          sell_price: exitPr
        };
      }
      return t;
    });

    const updated = {
      ...pullbackData,
      mtf_trading: Array.isArray(pullbackData.mtf_trading) ? updatedMtfList : {
        ...pullbackData.mtf_trading,
        trades: updatedMtfList
      }
    };
    savePullbackState(updated);
    showToast(`Closed MTF position @ ₹${exitPr}!`);
  };

  const handleDeleteMtfTx = (tradeId) => {
    if (!window.confirm("Are you sure you want to remove this MTF position?")) return;

    const currentMtfList = Array.isArray(pullbackData.mtf_trading)
      ? pullbackData.mtf_trading
      : (pullbackData.mtf_trading ? (pullbackData.mtf_trading.trades || []) : []);

    const updatedMtfList = currentMtfList.filter(t => t.id !== tradeId);

    const updated = {
      ...pullbackData,
      mtf_trading: Array.isArray(pullbackData.mtf_trading) ? updatedMtfList : {
        ...pullbackData.mtf_trading,
        trades: updatedMtfList
      }
    };
    savePullbackState(updated);
    showToast("Removed MTF position!");
  };

  // Form State for Adding New Trade
  const [symbol, setSymbol] = useState('');
  const [entryPrice, setEntryPrice] = useState('');
  const [quantity, setQuantity] = useState('100');
  const [stopLoss, setStopLoss] = useState('');
  const [targetPrice, setTargetPrice] = useState('');
  const [instrumentType, setInstrumentType] = useState('Intraday');
  const [customSlPct, setCustomSlPct] = useState('0.8');

  const SEGMENT_SL_CONFIG = {
    'Intraday': { slPct: 0.8, presets: [0.5, 0.8, 1.0], range: '0.5% – 1.0%', riskRule: 'Max 1% capital risk', label: 'Intraday Equities' },
    'Intraday Short': { slPct: 0.8, presets: [0.5, 0.8, 1.0], range: '0.5% – 1.0%', riskRule: 'Max 1% capital risk', label: 'Intraday Equities' },
    'Stock Options': { slPct: 15.0, presets: [10.0, 15.0, 20.0], range: '10.0% – 20.0%', riskRule: 'Max 2%–3% of option buying pool', label: 'Stock Options (F&O)' },
    'Delivery': { slPct: 6.0, presets: [5.0, 6.0, 7.0], range: '5.0% – 7.0%', riskRule: 'Max 2% capital risk', label: 'Delivery / Swing Trading' },
    'Crude Oil Options': { slPct: 1.0, presets: [0.8, 1.0, 1.2], range: '0.8% – 1.2%', riskRule: 'Fixed capital risk (₹3,000–₹5,000)', label: 'Crude Oil Main' },
    'Crude Oil Mini': { slPct: 1.0, presets: [0.8, 1.0, 1.2], range: '0.8% – 1.2%', riskRule: 'Fixed capital risk (₹300–₹500)', label: 'Crude Oil Mini' },
    'Natural Gas Options': { slPct: 2.0, presets: [1.5, 2.0, 2.5], range: '1.5% – 2.5%', riskRule: 'Fixed capital risk (extreme volatility)', label: 'Natural Gas Main' },
    'Natural Gas Mini': { slPct: 2.0, presets: [1.5, 2.0, 2.5], range: '1.5% – 2.5%', riskRule: 'Fixed capital risk (extreme volatility)', label: 'Natural Gas Mini' },
    'Nifty Options': { slPct: 17.5, presets: [15.0, 17.5, 20.0], range: '15.0% – 20.0%', riskRule: 'Max 2%–3% of option buying pool', label: 'Nifty Options (Buyers)' }
  };

  const getSegmentConfig = (type) => {
    if (!type) return SEGMENT_SL_CONFIG['Intraday'];
    const key = type.trim();
    if (SEGMENT_SL_CONFIG[key]) return SEGMENT_SL_CONFIG[key];
    const lower = key.toLowerCase();
    if (lower.includes('stock option') || lower.includes('stock options')) return SEGMENT_SL_CONFIG['Stock Options'];
    if (lower.includes('delivery') || lower.includes('swing') || lower.includes('equity')) return SEGMENT_SL_CONFIG['Delivery'];
    if (lower.includes('crude') && lower.includes('mini')) return SEGMENT_SL_CONFIG['Crude Oil Mini'];
    if (lower.includes('crude')) return SEGMENT_SL_CONFIG['Crude Oil Options'];
    if (lower.includes('natural') && lower.includes('mini')) return SEGMENT_SL_CONFIG['Natural Gas Mini'];
    if (lower.includes('natural') || lower.includes('natgas')) return SEGMENT_SL_CONFIG['Natural Gas Options'];
    if (lower.includes('nifty') || lower.includes('option')) return SEGMENT_SL_CONFIG['Nifty Options'];
    return SEGMENT_SL_CONFIG['Intraday'];
  };

  // Auto-calculate SL & Target dynamically based on segment guide rules
  // Rounds to nearest 0.05 increment (exchange-compliant step size)
  const roundToStep = (val, stepDown) => {
    const steps = Math.round(val / 0.05);
    const floorVal = (Math.floor(val / 0.05) * 0.05);
    const ceilVal  = (Math.ceil(val  / 0.05) * 0.05);
    const result = stepDown ? floorVal : ceilVal;
    return parseFloat(result.toFixed(2));
  };

  const calculateAutoSLAndTarget = (priceVal, typeVal, slPctVal) => {
    const price = parseFloat(priceVal);
    const config = getSegmentConfig(typeVal);
    const useSlPct = parseFloat(slPctVal) || (config ? config.slPct : 1.0);

    if (isNaN(price) || price <= 0) return { sl: '', target: '', config, slPctUsed: useSlPct };

    const isShort = typeVal === 'Intraday Short';
    const rawSl = isShort ? price * (1 + (useSlPct / 100)) : price * (1 - (useSlPct / 100));
    const rawTgt = isShort ? price * (1 - (2 * useSlPct / 100)) : price * (1 + (2 * useSlPct / 100));

    const slPrice  = isShort ? roundToStep(rawSl, false) : roundToStep(rawSl, true);
    const tgtPrice = isShort ? roundToStep(rawTgt, true) : roundToStep(rawTgt, false);

    return {
      sl: slPrice.toFixed(2),
      target: tgtPrice.toFixed(2),
      config,
      slPctUsed: useSlPct
    };
  };

  const getLotIntelligenceInfo = (symbolStr, typeStr) => {
    const sym = (symbolStr || '').toUpperCase().trim();
    const type = (typeStr || '').trim();

    if (type === 'Stock Options' || (type.includes('Stock') && type.includes('Option'))) {
      return { lotSize: 500, label: 'Stock Option Lot (e.g. 500 qty)', defaultQty: '500' };
    }
    if (type === 'Crude Oil Mini' || sym.includes('CRUDEOILM') || (sym.includes('CRUDE') && sym.includes('MINI'))) {
      return { lotSize: 10, label: '1 Lot = 10 qty (Crude Mini)', defaultQty: '10' };
    }
    if (type === 'Crude Oil Options' || sym.includes('CRUDEOIL') || sym.includes('CRUDE')) {
      return { lotSize: 100, label: '1 Lot = 100 qty (Crude Main)', defaultQty: '100' };
    }
    if (type === 'Natural Gas Mini' || sym.includes('NATGASMINI') || (sym.includes('NATURAL') && sym.includes('MINI'))) {
      return { lotSize: 250, label: '1 Lot = 250 qty (NatGas Mini)', defaultQty: '250' };
    }
    if (type === 'Natural Gas Options' || sym.includes('NATURALGAS') || sym.includes('NATGAS')) {
      return { lotSize: 1250, label: '1 Lot = 1250 qty (NatGas Main)', defaultQty: '1250' };
    }
    if (type === 'Nifty Options' || sym.includes('NIFTY')) {
      return { lotSize: 65, label: '1 Lot = 65 qty (Nifty)', defaultQty: '65' };
    }
    return { lotSize: 1, label: '1 Share (Equity)', defaultQty: '100' };
  };

  const handleSlPctChange = (newPctStr) => {
    setCustomSlPct(newPctStr.toString());
    if (entryPrice) {
      const { sl, target } = calculateAutoSLAndTarget(entryPrice, instrumentType, newPctStr);
      setStopLoss(sl);
      setTargetPrice(target);
    }
  };

  const detectSegmentFromSymbol = (symbolStr) => {
    const s = (symbolStr || '').toUpperCase().trim();
    if (!s) return 'Intraday';

    if (s.includes('CRUDEOILM') || (s.includes('CRUDE') && s.includes('MINI'))) {
      return 'Crude Oil Mini';
    }
    if (s.includes('CRUDEOIL') || s.includes('CRUDE')) {
      return 'Crude Oil Options';
    }
    if (s.includes('NATGASMINI') || (s.includes('NATURAL') && s.includes('MINI')) || (s.includes('NAT') && s.includes('MINI'))) {
      return 'Natural Gas Mini';
    }
    if (s.includes('NATURALGAS') || s.includes('NATGAS') || s.includes('NAT')) {
      return 'Natural Gas Options';
    }
    if (s.includes('NIFTY') || s.includes('BANKNIFTY') || s.includes('FINNIFTY')) {
      return 'Nifty Options';
    }
    if (/\b(CE|PE)\b/.test(s) || s.endsWith('CE') || s.endsWith('PE')) {
      return 'Stock Options';
    }
    return 'Intraday';
  };

  const handleSymbolChange = (e) => {
    const val = e.target.value;
    setSymbol(val);
    const newType = detectSegmentFromSymbol(val);
    setInstrumentType(newType);

    const cfg = getSegmentConfig(newType);
    setCustomSlPct(cfg.slPct.toString());

    const lotInfo = getLotIntelligenceInfo(val, newType);
    setQuantity(lotInfo.defaultQty);

    if (entryPrice) {
      const { sl, target } = calculateAutoSLAndTarget(entryPrice, newType, cfg.slPct);
      setStopLoss(sl);
      setTargetPrice(target);
    }
  };

  const handleEntryPriceChange = (e) => {
    const val = e.target.value;
    setEntryPrice(val);
    const { sl, target } = calculateAutoSLAndTarget(val, instrumentType, customSlPct);
    setStopLoss(sl);
    setTargetPrice(target);
  };

  const handleInstrumentTypeChange = (e) => {
    const newType = e.target.value;
    setInstrumentType(newType);
    const cfg = getSegmentConfig(newType);
    const defaultPct = cfg.slPct.toString();
    setCustomSlPct(defaultPct);
    const lotInfo = getLotIntelligenceInfo(symbol, newType);
    setQuantity(lotInfo.defaultQty);
    if (entryPrice) {
      const { sl, target } = calculateAutoSLAndTarget(entryPrice, newType, defaultPct);
      setStopLoss(sl);
      setTargetPrice(target);
    }
  };

  // Exit Price Modal State
  const [editingTrade, setEditingTrade] = useState(null);
  const [exitPriceInput, setExitPriceInput] = useState('');

  // Full Edit Trade Transaction Modal State
  const [fullEditTrade, setFullEditTrade] = useState(null);
  const [editSymbol, setEditSymbol] = useState('');
  const [editType, setEditType] = useState('Intraday');
  const [editEntryPrice, setEditEntryPrice] = useState('');
  const [editQuantity, setEditQuantity] = useState('');
  const [editStopLoss, setEditStopLoss] = useState('');
  const [editTargetPrice, setEditTargetPrice] = useState('');
  const [editExitPrice, setEditExitPrice] = useState('');
  const [editStatus, setEditStatus] = useState('ACTIVE');

  // Selected trade for viewing detailed contract note charges
  const [selectedChargeTrade, setSelectedChargeTrade] = useState(null);

  // Toast Helper
  const showToast = (message, type = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  // Sync trades to local storage on any state change
  useEffect(() => {
    saveJournalEngine(trades);
  }, [trades]);

  // Sync capital management, segment allocations & monthly SL risk settings to localStorage and backend
  useEffect(() => {
    localStorage.setItem('finplus_opening_capital', openingCapitalInput);
    localStorage.setItem('finplus_broker_adjustment', brokerAdjustmentInput);
    localStorage.setItem('finplus_deposits', depositsInput);
    localStorage.setItem('finplus_withdrawals', withdrawalsInput);
    localStorage.setItem('finplus_daily_risk_limit', dailyRiskLimitInput);
    localStorage.setItem('finplus_challenge_start_date', challengeStartDateInput);
    localStorage.setItem('finplus_total_challenge_days', totalChallengeDaysInput);

    localStorage.setItem('finplus_alloc_intraday', allocIntraday);
    localStorage.setItem('finplus_alloc_natgas', allocNatgas);
    localStorage.setItem('finplus_alloc_nifty', allocNifty);
    localStorage.setItem('finplus_alloc_crude', allocCrude);

    localStorage.setItem('finplus_msl_intraday', monthlySlIntraday);
    localStorage.setItem('finplus_msl_natgas', monthlySlNatgas);
    localStorage.setItem('finplus_msl_nifty', monthlySlNifty);
    localStorage.setItem('finplus_msl_crude', monthlySlCrude);

    const timer = setTimeout(() => {
      const payload = {
        finplus_opening_capital: openingCapitalInput,
        finplus_broker_adjustment: brokerAdjustmentInput,
        finplus_deposits: depositsInput,
        finplus_withdrawals: withdrawalsInput,
        finplus_daily_risk_limit: dailyRiskLimitInput,
        finplus_challenge_start_date: challengeStartDateInput,
        finplus_total_challenge_days: totalChallengeDaysInput,
        finplus_alloc_intraday: allocIntraday,
        finplus_alloc_natgas: allocNatgas,
        finplus_alloc_nifty: allocNifty,
        finplus_alloc_crude: allocCrude,
        finplus_msl_intraday: monthlySlIntraday,
        finplus_msl_natgas: monthlySlNatgas,
        finplus_msl_nifty: monthlySlNifty,
        finplus_msl_crude: monthlySlCrude
      };
      const candidateServers = Array.from(new Set([
        serverUrl,
        API_BASE_URL,
        (typeof window !== 'undefined' && window.location.hostname && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1' ? `${window.location.protocol}//${window.location.hostname}:8000` : null),
        'http://127.0.0.1:8000',
        'http://localhost:8000',
        RENDER_BACKEND_URL
      ].filter(Boolean)));

      for (const s of candidateServers) {
        fetch(`${s}/api/settings`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }).catch(() => {});
      }
    }, 1500);

    return () => clearTimeout(timer);
  }, [
    openingCapitalInput, brokerAdjustmentInput, depositsInput, withdrawalsInput,
    dailyRiskLimitInput, challengeStartDateInput, totalChallengeDaysInput,
    allocIntraday, allocNatgas, allocNifty, allocCrude,
    monthlySlIntraday, monthlySlNatgas, monthlySlNifty, monthlySlCrude,
    API_BASE_URL, serverUrl
  ]);

  // Master Live Price Polling Engine (Every 4 seconds via Independent YFinance Backend)
  useEffect(() => {
    const pollMasterLivePrices = async () => {
      try {
        const safeList = Array.isArray(trades) ? trades.filter(Boolean) : [];
        const activePositions = safeList.filter(t => t && t.status === 'ACTIVE');
        const activeSymbols = activePositions.map(t => (t.symbol || '').trim()).filter(Boolean);

        const pullbackTickers = Object.keys(pullbackData).filter(k => k !== 'capital_settings' && k !== 'option_trading' && k !== 'mtf_trading');
        
        let mtfItems = [];
        if (Array.isArray(pullbackData.mtf_trading)) {
          mtfItems = pullbackData.mtf_trading;
        } else if (pullbackData.mtf_trading && Array.isArray(pullbackData.mtf_trading.trades)) {
          mtfItems = pullbackData.mtf_trading.trades;
        }
        const mtfTickers = mtfItems.map(m => m.ticker).filter(Boolean);

        const allSymbols = Array.from(new Set([...activeSymbols, ...pullbackTickers, ...mtfTickers]));
        if (allSymbols.length === 0) return;

        const queryStr = allSymbols.join(',');

        let fetchedMap = {};
        let backendUpdatedPeaks = false;

        const endpointsToTry = Array.from(new Set([API_BASE_URL, RENDER_BACKEND_URL, 'http://127.0.0.1:8000'].filter(Boolean)));
        for (const endpoint of endpointsToTry) {
          try {
            const res = await fetch(`${endpoint}/api/investment/yfinance-prices?tickers=${encodeURIComponent(queryStr)}`);
            if (res.ok) {
              const data = await res.json();
              if (data && data.prices) {
                Object.entries(data.prices).forEach(([sym, info]) => {
                  if (info) {
                    const ltpVal = typeof info === 'number' ? info : info.ltp;
                    if (ltpVal) {
                      fetchedMap[sym] = ltpVal;
                      const clean = sym.replace('.NS', '').trim();
                      fetchedMap[clean] = ltpVal;
                      fetchedMap[clean.toUpperCase()] = ltpVal;
                    }
                  }
                });
                backendUpdatedPeaks = !!data.updated_peaks;
                if (Object.keys(fetchedMap).length > 0) break;
              }
            }
          } catch (err) {
            try {
              const res = await fetch(`${endpoint}/api/ltp?symbols=${encodeURIComponent(queryStr)}`);
              if (res.ok) {
                const data = await res.json();
                if (data && data.ltps) {
                  Object.entries(data.ltps).forEach(([sym, ltpVal]) => {
                    fetchedMap[sym] = ltpVal;
                    const clean = sym.replace('.NS', '').trim();
                    fetchedMap[clean] = ltpVal;
                    fetchedMap[clean.toUpperCase()] = ltpVal;
                  });
                  if (Object.keys(fetchedMap).length > 0) break;
                }
              }
            } catch (e) {}
          }
        }

        // Direct Yahoo Finance API browser fallback if any symbol unpriced
        for (const sym of allSymbols) {
          const clean = sym.replace('.NS', '').trim();
          if (!fetchedMap[sym] && !fetchedMap[clean]) {
            try {
              const formatted = sym.includes('.NS') || sym.includes('=') || sym.includes('^') ? sym : `${clean}.NS`;
              const yRes = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(formatted)}?interval=1d&range=1d`);
              if (yRes.ok) {
                const yData = await yRes.json();
                const price = yData?.chart?.result?.[0]?.meta?.regularMarketPrice;
                if (price && price > 0) {
                  fetchedMap[sym] = price;
                  fetchedMap[clean] = price;
                  fetchedMap[clean.toUpperCase()] = price;
                }
              }
            } catch (e) {}
          }
        }

        if (Object.keys(fetchedMap).length > 0) {
          setLiveLtps(prev => ({ ...prev, ...fetchedMap }));
        }

        if (backendUpdatedPeaks) {
          try {
            const freshRes = await fetch(`${API_BASE_URL}/api/investment/pullback`);
            if (freshRes.ok) {
              const freshData = await freshRes.json();
              if (freshData && Object.keys(freshData).length > 0) {
                setPullbackData(freshData);
              }
            }
          } catch (e) {}
        }
      } catch (e) {}
    };

    pollMasterLivePrices();
    const interval = setInterval(pollMasterLivePrices, 4000);
    return () => clearInterval(interval);
  }, [trades, pullbackData]);

  // Restore trades from local backend disk on mount
  useEffect(() => {
    const fetchBackendTrades = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/trades/journal`);
        if (res.ok) {
          const data = await res.json();
          const diskTrades = Array.isArray(data.trades) ? data.trades : (Array.isArray(data) ? data : []);
          if (diskTrades.length > 0) {
            setTrades(prev => mergeJournalTrades(prev, diskTrades));
          }
        }
      } catch (e) {}
    };
    fetchBackendTrades();
  }, []);

    // Handle Add New Trade
  const handleAddTrade = (e) => {
    e.preventDefault();
    if (!symbol.trim() || !entryPrice || parseFloat(entryPrice) <= 0) {
      showToast("Please provide a valid symbol and entry price.", "error");
      return;
    }

    const newTrade = {
      uuid: createTradeUUID(),
      symbol: symbol.trim().toUpperCase(),
      entry_price: parseFloat(entryPrice),
      quantity: parseInt(quantity) || 1,
      stop_loss: stopLoss ? parseFloat(stopLoss) : null,
      target_price: targetPrice ? parseFloat(targetPrice) : null,
      instrument_type: instrumentType,
      exit_price: null,
      status: 'ACTIVE',
      created_at: new Date().toISOString()
    };

    const updated = [newTrade, ...trades];
    setTrades(updated);
    showToast(`Added trade for ${newTrade.symbol} @ ₹${newTrade.entry_price}`);

    // Reset Form
    setSymbol('');
    setEntryPrice('');
    setStopLoss('');
    setTargetPrice('');
  };

  // Handle Exit Trade
  const handleExitTrade = (e) => {
    e.preventDefault();
    if (!editingTrade || !exitPriceInput || parseFloat(exitPriceInput) <= 0) {
      showToast("Please enter a valid exit price.", "error");
      return;
    }

    const exitVal = parseFloat(exitPriceInput);
    const updated = trades.map(t => {
      if ((t.uuid && t.uuid === editingTrade.uuid) || (t.id && t.id === editingTrade.id)) {
        return {
          ...t,
          exit_price: exitVal,
          status: 'CLOSED',
          updated_at: new Date().toISOString()
        };
      }
      return t;
    });

    setTrades(updated);
    showToast(`Closed ${editingTrade.symbol} at ₹${exitVal}`);
    setEditingTrade(null);
    setExitPriceInput('');
  };

  // Handle Delete Trade
  const handleDeleteTrade = (tradeToDelete) => {
    if (!window.confirm(`Delete position log for ${tradeToDelete.symbol}?`)) return;
    const updated = trades.filter(t => {
      if (tradeToDelete.uuid) return t.uuid !== tradeToDelete.uuid;
      if (tradeToDelete.id) return t.id !== tradeToDelete.id;
      return true;
    });
    setTrades(updated);
    showToast("Trade log deleted.", "info");
  };

  // Open Full Edit Trade Modal
  const handleOpenEditModal = (trade) => {
    setFullEditTrade(trade);
    setEditSymbol(trade.symbol || '');
    setEditType(trade.instrument_type || 'Intraday');
    setEditEntryPrice(trade.entry_price || '');
    setEditQuantity(trade.quantity || '');
    setEditStopLoss(trade.stop_loss || '');
    setEditTargetPrice(trade.target_price || '');
    setEditExitPrice(trade.exit_price || '');
    setEditStatus(trade.status || 'ACTIVE');
  };

  // Save Full Edit Trade
  const handleSaveFullTradeEdit = (e) => {
    e.preventDefault();
    if (!fullEditTrade) return;
    if (!editSymbol.trim() || !editEntryPrice || parseFloat(editEntryPrice) <= 0) {
      showToast("Please enter a valid symbol and entry price.", "error");
      return;
    }

    const updated = trades.map(t => {
      if ((t.uuid && t.uuid === fullEditTrade.uuid) || (t.id && t.id === fullEditTrade.id)) {
        const exitVal = editExitPrice ? parseFloat(editExitPrice) : null;
        const newStatus = exitVal && exitVal > 0 ? 'CLOSED' : editStatus;
        return {
          ...t,
          symbol: editSymbol.trim().toUpperCase(),
          instrument_type: editType,
          entry_price: parseFloat(editEntryPrice),
          quantity: parseInt(editQuantity) || 1,
          stop_loss: editStopLoss ? parseFloat(editStopLoss) : null,
          target_price: editTargetPrice ? parseFloat(editTargetPrice) : null,
          exit_price: exitVal,
          status: newStatus,
          updated_at: new Date().toISOString()
        };
      }
      return t;
    });

    setTrades(updated);
    showToast(`Updated trade transaction log for ${editSymbol.toUpperCase()}!`);
    setFullEditTrade(null);
  };

  // Master JSON Export & Restore
  const handleExportJson = () => {
    if (trades.length === 0) {
      showToast("No trade logs available to export.", "error");
      return;
    }
    exportMasterJsonBackup(trades);
    showToast("Master trade journal exported as JSON backup!");
  };

  const handleImportJsonFile = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const res = importMasterJsonBackup(evt.target.result, trades);
      if (res.success) {
        setTrades(res.trades);
        if (res.settings) {
          if (res.settings.openingCapital) setOpeningCapitalInput(res.settings.openingCapital);
          if (res.settings.brokerAdjustment) setBrokerAdjustmentInput(res.settings.brokerAdjustment);
          if (res.settings.deposits) setDepositsInput(res.settings.deposits);
          if (res.settings.withdrawals) setWithdrawalsInput(res.settings.withdrawals);
          if (res.settings.dailyRiskLimit) setDailyRiskLimitInput(res.settings.dailyRiskLimit);
          if (res.settings.challengeStartDate) setChallengeStartDateInput(res.settings.challengeStartDate);
          if (res.settings.totalChallengeDays) setTotalChallengeDaysInput(res.settings.totalChallengeDays);
        }
        showToast(`Imported ${res.count} trades & capital settings successfully!`);
      } else {
        showToast(res.error || "Failed to import JSON file.", "error");
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleImportCsvFile = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const res = importJournalCSV(evt.target.result, trades);
      if (res.success) {
        setTrades(res.trades);
        showToast(`Imported ${res.count} trade records from CSV successfully!`);
      } else {
        showToast(res.error || "Failed to import CSV file.", "error");
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  // Metrics Calculations
  const safeTrades = Array.isArray(trades) ? trades.filter(Boolean) : [];
  const closedTrades = safeTrades.filter(t => t && t.status === 'CLOSED' && Number(t.exit_price) > 0);
  const activeTrades = safeTrades.filter(t => t && t.status === 'ACTIVE');

  let totalRealizedNetPnl = 0;
  let totalGrossPnl = 0;
  let totalZerodhaCharges = 0;
  let winningTradesCount = 0;

  closedTrades.forEach(t => {
    const chg = calculateZerodhaCharges(t);
    totalRealizedNetPnl += chg.net_pnl;
    totalGrossPnl += chg.gross_pnl;
    totalZerodhaCharges += chg.total;
    if (chg.net_pnl > 0) winningTradesCount++;
  });

  // Cumulative totals (Journal closed trades + MTF closed trades)
  const closedMtfTrades = mtfSummaryList.filter(t => t.status === 'Closed');
  const cumulativeRealizedNetPnl = totalRealizedNetPnl + closedMtfNetPnl;
  const cumulativeGrossPnl = totalGrossPnl + closedMtfGrossPnl;
  const cumulativeCharges = totalZerodhaCharges + closedMtfCarryingCharges;
  const cumulativeClosedTradesCount = closedTrades.length + closedMtfTrades.length;
  const cumulativeWinningTradesCount = winningTradesCount + closedMtfTrades.filter(t => t.netPnl > 0).length;
  const cumulativeWinRatePct = cumulativeClosedTradesCount > 0 
    ? ((cumulativeWinningTradesCount / cumulativeClosedTradesCount) * 100).toFixed(1)
    : '0';

  const winRatePct = closedTrades.length > 0 ? ((winningTradesCount / closedTrades.length) * 100).toFixed(1) : '0';

  // Helper to extract YYYY-MM-DD from trade created_at, entry_date, date, or updated_at
  const getTradeDateStr = (t) => {
    if (!t) return getTodayDateStr();
    const raw = t.created_at || t.entry_date || t.date || t.entry_scan_time || t.timestamp || t.updated_at;
    if (!raw) return getTodayDateStr();
    return String(raw).split('T')[0];
  };

  // Group Closed Trades by Date for Daily Breakdown
  const dailyPnlBreakdownMap = {};
  closedTrades.forEach(t => {
    const chg = calculateZerodhaCharges(t);
    const dateKey = getTradeDateStr(t);
    if (!dailyPnlBreakdownMap[dateKey]) {
      dailyPnlBreakdownMap[dateKey] = {
        date: dateKey,
        tradesCount: 0,
        winsCount: 0,
        grossPnl: 0,
        totalCharges: 0,
        netPnl: 0
      };
    }
    dailyPnlBreakdownMap[dateKey].tradesCount += 1;
    if (chg.net_pnl > 0) dailyPnlBreakdownMap[dateKey].winsCount += 1;
    dailyPnlBreakdownMap[dateKey].grossPnl += chg.gross_pnl;
    dailyPnlBreakdownMap[dateKey].totalCharges += chg.total;
    dailyPnlBreakdownMap[dateKey].netPnl += chg.net_pnl;
  });

  const dailyPnlSummaryList = Object.values(dailyPnlBreakdownMap).sort((a, b) => b.date.localeCompare(a.date));

  // Selected Date Metrics Calculation
  const dailyClosedTrades = closedTrades.filter(t => getTradeDateStr(t) === selectedDailyDate);
  let selectedDailyNetPnl = 0;
  let selectedDailyGrossPnl = 0;
  let selectedDailyCharges = 0;
  let selectedDailyWinsCount = 0;

  dailyClosedTrades.forEach(t => {
    const chg = calculateZerodhaCharges(t);
    selectedDailyNetPnl += chg.net_pnl;
    selectedDailyGrossPnl += chg.gross_pnl;
    selectedDailyCharges += chg.total;
    if (chg.net_pnl > 0) selectedDailyWinsCount += 1;
  });

  const selectedDailyWinRatePct = dailyClosedTrades.length > 0
    ? ((selectedDailyWinsCount / dailyClosedTrades.length) * 100).toFixed(1)
    : '0';

  let totalUnrealizedPnl = 0;
  activeTrades.forEach(t => {
    const sym = (t.symbol || '').trim();
    const ltp = liveLtps[sym] ?? liveLtps[sym.toUpperCase()] ?? liveLtps[t.symbol] ?? t.entry_price;
    const isShort = t.instrument_type === 'Intraday Short';
    const diff = isShort ? (t.entry_price - ltp) : (ltp - t.entry_price);
    totalUnrealizedPnl += diff * t.quantity;
  });

  // Capital Management Auto Calculations
  const openingCapitalNum = parseFloat(openingCapitalInput) || 0;
  const brokerAdjNum = parseFloat(brokerAdjustmentInput) || 0;
  const depositsNum = parseFloat(depositsInput) || 0;
  const withdrawalsNum = parseFloat(withdrawalsInput) || 0;

  const totalTradeNetPnl = totalRealizedNetPnl + totalUnrealizedPnl;
  const closingCapitalNum = openingCapitalNum + totalTradeNetPnl + brokerAdjNum + depositsNum - withdrawalsNum;

  // Current Month Segment Allocation & Monthly Risk SL Tracker
  // Available Closed Months List for Risk SL Audit
  const availableClosedMonths = Array.from(new Set(
    (Array.isArray(closedTrades) ? closedTrades : [])
      .map(t => getTradeDateStr(t).slice(0, 7))
      .filter(m => m && m.length === 7)
  )).sort((a, b) => b.localeCompare(a));

  if (!availableClosedMonths.includes(currentYearMonthStr)) {
    availableClosedMonths.unshift(currentYearMonthStr);
  }

  // Selected Month Closed Trades
  const selectedMonthClosedTrades = (Array.isArray(closedTrades) ? closedTrades : []).filter(t => {
    if (!t) return false;
    const mStr = getTradeDateStr(t).slice(0, 7);
    return mStr === (selectedRiskMonth || currentYearMonthStr);
  });

  const getSegmentSelectedMonthPnl = (segKey) => {
    const lower = segKey.toLowerCase();
    return selectedMonthClosedTrades.filter(t => {
      const type = (t.instrument_type || '').toLowerCase();
      if (lower.includes('intraday')) return type.includes('intraday');
      if (lower.includes('natural') || lower.includes('natgas')) return type.includes('natural') || type.includes('natgas');
      if (lower.includes('nifty')) return type.includes('nifty');
      if (lower.includes('crude')) return type.includes('crude');
      return false;
    }).reduce((acc, t) => {
      const chg = calculateZerodhaCharges(t);
      return acc + (chg.net_pnl || 0);
    }, 0);
  };

  // Empirical Performance Stats across Lifetime Trades per Segment
  const getSegmentEmpiricalStats = (segKey) => {
    const lower = segKey.toLowerCase();
    const segTrades = (Array.isArray(closedTrades) ? closedTrades : []).filter(t => {
      const type = (t.instrument_type || '').toLowerCase();
      if (lower.includes('intraday')) return type.includes('intraday');
      if (lower.includes('natural') || lower.includes('natgas')) return type.includes('natural') || type.includes('natgas');
      if (lower.includes('nifty')) return type.includes('nifty');
      if (lower.includes('crude')) return type.includes('crude');
      return false;
    });

    const totalCount = segTrades.length;
    let winCount = 0;
    let lossCount = 0;
    let grossWins = 0;
    let grossLosses = 0;

    segTrades.forEach(t => {
      const chg = calculateZerodhaCharges(t);
      const netPnl = chg.net_pnl;
      if (netPnl > 0) {
        winCount += 1;
        grossWins += netPnl;
      } else if (netPnl < 0) {
        lossCount += 1;
        grossLosses += Math.abs(netPnl);
      }
    });

    const winRate = totalCount > 0 ? ((winCount / totalCount) * 100).toFixed(1) : '0.0';
    const profitFactor = grossLosses > 0 ? (grossWins / grossLosses).toFixed(2) : (grossWins > 0 ? '∞' : '0.00');
    const avgWin = winCount > 0 ? grossWins / winCount : 0;
    const avgLoss = lossCount > 0 ? grossLosses / lossCount : 0;
    const riskRewardRatio = avgLoss > 0 ? (avgWin / avgLoss).toFixed(2) : (avgWin > 0 ? '1:2+' : '0.00');

    return {
      totalCount,
      winCount,
      lossCount,
      winRate,
      profitFactor,
      riskRewardRatio
    };
  };

  const segmentAllocList = [
    {
      name: 'Intraday (Equities/Indices)',
      rank: '#1 Most Profitable',
      color: '#34d399',
      rationale: 'Core Income Engine: Maximizes exposure where your win-rate is highest.',
      allocState: allocIntraday,
      setAllocState: setAllocIntraday,
      mslState: monthlySlIntraday,
      setMslState: setMonthlySlIntraday,
      currentPnl: getSegmentSelectedMonthPnl('intraday'),
      stats: getSegmentEmpiricalStats('intraday')
    },
    {
      name: 'Natural Gas',
      rank: '#2 Moderately Profitable',
      color: '#38bdf8',
      rationale: 'Growth Driver: High volatility requires strict position sizing.',
      allocState: allocNatgas,
      setAllocState: setAllocNatgas,
      mslState: monthlySlNatgas,
      setMslState: setMonthlySlNatgas,
      currentPnl: getSegmentSelectedMonthPnl('natural'),
      stats: getSegmentEmpiricalStats('natural')
    },
    {
      name: 'Nifty Options',
      rank: '#3 Moderately Risky',
      color: '#c084fc',
      rationale: 'Asymmetric Risk: Capped risk (if buying) or high margin (if selling).',
      allocState: allocNifty,
      setAllocState: setAllocNifty,
      mslState: monthlySlNifty,
      setMslState: setMonthlySlNifty,
      currentPnl: getSegmentSelectedMonthPnl('nifty'),
      stats: getSegmentEmpiricalStats('nifty')
    },
    {
      name: 'Crude Oil',
      rank: '#4 Most Risky',
      color: '#fb923c',
      rationale: 'Protection Mode: Low exposure limits damage from global gaps.',
      allocState: allocCrude,
      setAllocState: setAllocCrude,
      mslState: monthlySlCrude,
      setMslState: setMonthlySlCrude,
      currentPnl: getSegmentSelectedMonthPnl('crude'),
      stats: getSegmentEmpiricalStats('crude')
    }
  ];

  const currentCapitalBase = (closingCapitalNum > 0 ? closingCapitalNum : (openingCapitalNum > 0 ? openingCapitalNum : 0));
  const totalMonthlyRiskBudget = segmentAllocList.reduce((acc, s) => {
    const allocPct = Number(s.allocState) || 0;
    const mslPct = Number(s.mslState) || 0;
    return acc + (currentCapitalBase * (allocPct / 100) * (mslPct / 100));
  }, 0);

  const currentMonthTotalPnl = segmentAllocList.reduce((acc, s) => acc + s.currentPnl, 0);

  const breachedSegmentsCount = segmentAllocList.filter(s => {
    const allocPct = Number(s.allocState) || 0;
    const mslPct = Number(s.mslState) || 0;
    const maxLoss = currentCapitalBase * (allocPct / 100) * (mslPct / 100);
    const lossUsed = s.currentPnl < 0 ? Math.abs(s.currentPnl) : 0;
    return maxLoss > 0 && lossUsed >= maxLoss;
  }).length;

  // Single Daily Rollover Risk Limit (Base Limit ₹250/day)
  const dailyRiskLimit = parseFloat(dailyRiskLimitInput) || 250;
  const totalChallengeDays = parseInt(totalChallengeDaysInput) || 1000;

  // Day Counter Calculation
  const startDateObj = new Date(challengeStartDateInput || new Date().toISOString().split('T')[0]);
  const todayObj = new Date();
  startDateObj.setHours(0, 0, 0, 0);
  todayObj.setHours(0, 0, 0, 0);
  
  const diffTime = Math.max(0, todayObj.getTime() - startDateObj.getTime());
  const currentDayCount = Math.min(totalChallengeDays, Math.floor(diffTime / (1000 * 60 * 60 * 24)) + 1);
  const challengeProgressPct = Math.min(100, ((currentDayCount / totalChallengeDays) * 100)).toFixed(1);

  // Daily Loss Carryover Engine
  const todayStr = getTodayDateStr();
  const tradesByDate = {};

  closedTrades.forEach(t => {
    const chg = calculateZerodhaCharges(t);
    const tradeDate = getTradeDateStr(t);
    tradesByDate[tradeDate] = (tradesByDate[tradeDate] || 0) + chg.net_pnl;
  });

  const sortedPastDates = Object.keys(tradesByDate).filter(d => d < todayStr).sort();

  // Cumulative Carried Loss Engine:
  // Total CUMULATIVE allowance = days elapsed × ₹250 daily limit.
  // This means after 15 days, the total risk budget is 15 × ₹250 = ₹3,750.
  // Losses (Journal + closed MTF) are netted against this cumulative budget.
  const totalPastNetPnl = sortedPastDates.reduce((acc, d) => acc + (tradesByDate[d] || 0), 0);
  // Also include closed MTF positions net P&L in the carried loss engine
  const totalPastNetPnlWithMtf = totalPastNetPnl + closedMtfNetPnl;

  // Cumulative budget earned so far (all days elapsed including today)
  const totalCumulativeBudget = currentDayCount * dailyRiskLimit;
  // Past budget (all challenge days elapsed prior to today)
  const pastChallengeDaysCount = Math.max(0, currentDayCount - 1);
  const totalPastAllowance = pastChallengeDaysCount * dailyRiskLimit;
  // Carried loss = how much total net loss (journal + mtf) exceeds the past cumulative daily budget
  const cumulativeCarriedLoss = Math.max(0, -(totalPastNetPnlWithMtf) - totalPastAllowance);

  // Today's total realized PnL (closed trades only — unrealized excluded to avoid cross-day distortion)
  const todayTotalPnl = tradesByDate[todayStr] || 0;
  const todayCurrentLoss = todayTotalPnl < 0 ? Math.abs(todayTotalPnl) : 0;
  
  // Today's Starting Risk Budget = what's left of cumulative budget after subtracting all past losses
  // Correct formula: (currentDayCount × dailyRiskLimit) - total losses so far (excl. today's intraday)
  const totalLossesSoFar = Math.max(0, -(totalPastNetPnlWithMtf));
  const todayStartingRisk = Math.max(0, totalCumulativeBudget - totalLossesSoFar);

  // Today's Available Risk Allowance Remaining
  const availableRiskLimitToday = Math.max(0, todayStartingRisk - todayCurrentLoss);

  // Excess loss today over today's available starting risk
  const todayExcessLoss = Math.max(0, todayCurrentLoss - todayStartingRisk);
  
  // Total Carried Loss to Tomorrow (cumulative past carried loss plus any excess loss incurred today)
  const totalCarriedLossTomorrow = cumulativeCarriedLoss + todayExcessLoss;

  // Tomorrow's Available Risk Allowance
  const nextDayAvailableRisk = Math.max(0, dailyRiskLimit - totalCarriedLossTomorrow);

  const isRiskWarningActive = cumulativeCarriedLoss > 0 || todayCurrentLoss >= dailyRiskLimit;

  // Average Daily Net P&L Calculation (Net P&L divided by elapsed Days)
  const averageDailyNetPnl = currentDayCount > 0 ? (totalRealizedNetPnl / currentDayCount) : 0;

  // Expectancy Per Trade (Edge per Trade)
  const expectancyPerTrade = closedTrades.length > 0 ? (totalRealizedNetPnl / closedTrades.length) : 0;

  // Disciplined Trading Days Streak (Consecutive days without exceeding daily risk limit)
  const allTradingDates = Object.keys(tradesByDate).sort().reverse();
  let disciplineStreakDays = 0;
  for (const dStr of allTradingDates) {
    const netPnl = tradesByDate[dStr] || 0;
    if (netPnl >= -dailyRiskLimit) {
      disciplineStreakDays += 1;
    } else {
      break;
    }
  }

  // Risk Stack Binding Constraint Evaluation
  let bindingConstraintLabel = "🟢 ACTIVE: Within All Risk Limits";
  let bindingConstraintLevel = "none";

  if (availableRiskLimitToday <= 0) {
    bindingConstraintLabel = `⚡ BINDING: Daily Risk Limit (₹0.00 Remaining)`;
    bindingConstraintLevel = "daily";
  } else if (breachedSegmentsCount > 0) {
    bindingConstraintLabel = `⚡ BINDING: Monthly Segment SL Limit Reached (${breachedSegmentsCount} Segments)`;
    bindingConstraintLevel = "segment";
  } else if (cumulativeCarriedLoss > 0) {
    bindingConstraintLabel = `⚠️ BINDING: Carried Loss Active (₹${cumulativeCarriedLoss.toFixed(2)} Deducted)`;
    bindingConstraintLevel = "carried";
  }

  return (
    <div className="app-main-wrapper">
      
      {/* Toast Notification */}
      {toast && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          background: toast.type === 'error' ? '#ef4444' : '#10b981',
          color: 'white',
          padding: '12px 20px',
          borderRadius: '8px',
          boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
          zIndex: 10000,
          fontWeight: 700,
          display: 'flex',
          alignItems: 'center',
          gap: '10px'
        }}>
          {toast.type === 'error' ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
          {toast.message}
        </div>
      )}

      {/* Main Top Header - Styled Finplus Header */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <h1 style={{ fontSize: '28px', fontWeight: 900, color: '#ffffff', letterSpacing: '-0.5px' }}>
            Finplus PnL Journal
          </h1>
          <div style={{ color: '#a5b4fc', fontSize: '13px', marginTop: '4px', fontWeight: 500 }}>
            1000-Day Discipline Protocol • Daily Rollover Risk Limit: ₹{dailyRiskLimit} / Day
          </div>
        </div>

        {/* Action Controls - Action Control Buttons */}
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          <button 
            onClick={() => setActiveTab('settings')}
            title="Open Cloud Synchronization & App Settings"
            style={{
              background: activeTab === 'settings' ? 'rgba(236, 72, 153, 0.25)' : 'rgba(99, 102, 241, 0.15)',
              border: `1px solid ${activeTab === 'settings' ? '#ec4899' : 'rgba(99, 102, 241, 0.35)'}`,
              color: activeTab === 'settings' ? '#f472b6' : '#a5b4fc',
              padding: '10px 18px',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 700,
              fontSize: '13px'
            }}
          >
            <Settings size={16} />
            Settings
          </button>

          <button 
            onClick={() => handleSyncAll(null, false)}
            disabled={isSyncing}
            title={serverStatus === 'online' ? `Server Online${lastSyncedTime ? ' • Last synced: ' + lastSyncedTime : ''} (Click to Sync Now)` : 'Server Offline • Click to Reconnect / Sync'}
            style={{
              background: serverStatus === 'online' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
              border: `1px solid ${serverStatus === 'online' ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)'}`,
              color: serverStatus === 'online' ? '#34d399' : '#f87171',
              padding: '10px 18px',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 700,
              fontSize: '13px'
            }}
          >
            <RefreshCw size={16} className={isSyncing ? 'spin-icon' : ''} />
            {isSyncing ? 'Syncing...' : (serverStatus === 'online' ? '🟢 Synced' : '🔴 Sync: Offline')}
          </button>

          <button 
            onClick={handleExportJson}
            title="Export JSON master backup"
            style={{
              background: 'rgba(16, 185, 129, 0.15)',
              border: '1px solid rgba(16, 185, 129, 0.35)',
              color: '#34d399',
              padding: '10px 18px',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 700,
              fontSize: '13px'
            }}
          >
            <Download size={16} />
            Export Journal (.json)
          </button>

          <label 
            title="Restore JSON master backup"
            style={{
              background: 'rgba(99, 102, 241, 0.15)',
              border: '1px solid rgba(99, 102, 241, 0.35)',
              color: '#a5b4fc',
              padding: '10px 18px',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 700,
              fontSize: '13px'
            }}
          >
            <Upload size={16} />
            Restore Journal (.json)
            <input type="file" accept=".json" onChange={handleImportJsonFile} style={{ display: 'none' }} />
          </label>

          <label 
            title="Import CSV/Excel trade records"
            style={{
              background: 'rgba(6, 182, 212, 0.15)',
              border: '1px solid rgba(6, 182, 212, 0.35)',
              color: '#67e8f9',
              padding: '10px 18px',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 700,
              fontSize: '13px'
            }}
          >
            <Upload size={16} />
            Import CSV (.csv)
            <input type="file" accept=".csv" onChange={handleImportCsvFile} style={{ display: 'none' }} />
          </label>

          <button 
            onClick={() => exportJournalCSV(trades)}
            title="Export CSV spreadsheet"
            style={{
              background: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid rgba(255, 255, 255, 0.12)',
              color: '#cbd5e1',
              padding: '10px 18px',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 600,
              fontSize: '13px'
            }}
          >
            <FileText size={16} />
            Export CSV
          </button>
        </div>
      </header>

      {activeTab === 'home' && (<>
      {/* TOP STATUS CARDS ROW (3 Wide Cards Top Summary Cards Row) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '16px' }}>
        
        {/* Card 1: 📅 1000-DAY CHALLENGE & DISCIPLINE STREAK */}
        <div className="glass-panel" style={{ padding: '22px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              📅 1000-DAY CHALLENGE
            </div>
            <span style={{ 
              fontSize: '11px', 
              fontWeight: 800, 
              background: disciplineStreakDays > 0 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)', 
              color: disciplineStreakDays > 0 ? '#34d399' : '#f87171',
              padding: '3px 8px',
              borderRadius: '6px'
            }}>
              🔥 {disciplineStreakDays}-Day Discipline Streak
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ height: '8px', width: '8px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 10px #10b981' }}></span>
            <span style={{ fontSize: '24px', fontWeight: 900, color: '#10b981' }}>
              Day {currentDayCount} <span style={{ fontSize: '14px', color: '#a5b4fc', fontWeight: 600 }}>/ {totalChallengeDays}</span>
            </span>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.06)', borderRadius: '4px', height: '6px', width: '100%', marginTop: '12px', overflow: 'hidden' }}>
            <div style={{ background: '#a855f7', height: '100%', width: `${challengeProgressPct}%`, transition: 'width 0.4s ease' }} />
          </div>
          <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '6px', display: 'flex', justifyContent: 'space-between' }}>
            <span>{challengeProgressPct}% Completed</span>
            <span>Started: {challengeStartDateInput}</span>
          </div>
        </div>

        {/* Card 2: 🛡️ Daily Risk Protocol & Binding Constraint */}
        <div className="glass-panel" style={{ padding: '22px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              🛡️ TODAY'S RISK BUDGET & ROLLOVER
            </div>
            <span style={{ 
              fontSize: '10px', 
              fontWeight: 800, 
              background: bindingConstraintLevel === 'daily' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(16, 185, 129, 0.15)', 
              color: bindingConstraintLevel === 'daily' ? '#f87171' : '#34d399',
              padding: '2px 6px',
              borderRadius: '4px'
            }}>
              {bindingConstraintLevel === 'daily' ? '⚡ LIMIT BREACHED' : '🟢 RISK ALLOWED'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ height: '8px', width: '8px', borderRadius: '50%', background: availableRiskLimitToday > 0 ? '#10b981' : '#f87171', boxShadow: `0 0 10px ${availableRiskLimitToday > 0 ? '#10b981' : '#f87171'}` }}></span>
            <span style={{ fontSize: '24px', fontWeight: 900, color: availableRiskLimitToday > 0 ? '#ffffff' : '#f87171' }}>
              ₹{availableRiskLimitToday.toFixed(2)} <span style={{ fontSize: '13px', color: '#a5b4fc', fontWeight: 600 }}>/ ₹{dailyRiskLimit}</span>
            </span>
          </div>
          <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '14px' }}>
            {todayExcessLoss > 0 ? (
              <>Excess Carried Loss: <strong style={{ color: '#f87171' }}>₹{totalCarriedLossTomorrow.toFixed(2)}</strong> | Tomorrow Available: <strong style={{ color: '#67e8f9' }}>₹{nextDayAvailableRisk.toFixed(2)}</strong></>
            ) : (
              <>Base Budget: ₹{dailyRiskLimit} | Carried Loss: ₹{cumulativeCarriedLoss.toFixed(2)}</>
            )}
          </div>
        </div>

        {/* Card 3: 📊 EXPECTANCY & EDGE PER TRADE */}
        <div className="glass-panel" style={{ padding: '22px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              📊 EXPECTANCY & EDGE PER TRADE
            </div>
            <span style={{
              fontSize: '11px',
              fontWeight: 800,
              background: expectancyPerTrade >= 0 ? 'rgba(52, 211, 153, 0.15)' : 'rgba(248, 113, 113, 0.15)',
              color: expectancyPerTrade >= 0 ? '#34d399' : '#f87171',
              padding: '2px 8px',
              borderRadius: '6px'
            }}>
              Expectancy: {expectancyPerTrade >= 0 ? '+' : ''}₹{expectancyPerTrade.toFixed(2)}/T
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ height: '8px', width: '8px', borderRadius: '50%', background: averageDailyNetPnl >= 0 ? '#10b981' : '#f87171', boxShadow: `0 0 10px ${averageDailyNetPnl >= 0 ? '#10b981' : '#f87171'}` }}></span>
            <span style={{ fontSize: '24px', fontWeight: 900, color: averageDailyNetPnl > 0 ? '#34d399' : (averageDailyNetPnl < 0 ? '#f87171' : '#ffffff') }}>
              {averageDailyNetPnl >= 0 ? '+' : ''}₹{averageDailyNetPnl.toFixed(2)} <span style={{ fontSize: '13px', color: '#a5b4fc', fontWeight: 600 }}>/ day</span>
            </span>
          </div>
          <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '14px', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap' }}>
            <span>Overall Win Rate: <strong>{winRatePct}%</strong> ({winningTradesCount}W / {closedTrades.length}T)</span>
            <span>Edge: <strong>{expectancyPerTrade >= 0 ? '+' : ''}₹{expectancyPerTrade.toFixed(2)} / T</strong></span>
          </div>
        </div>

      </div>

      {/* SECTION HEADER: "Portfolio Performance Findings" */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
            <h2 style={{ fontSize: '20px', fontWeight: 800, color: '#ffffff' }}>
              Portfolio Performance Findings
            </h2>

            {/* PnL View Mode Segmented Toggle: Overall PnL vs Daily PnL */}
            <div style={{ display: 'flex', background: 'rgba(15, 23, 42, 0.7)', border: '1px solid rgba(99, 102, 241, 0.3)', borderRadius: '8px', padding: '3px' }}>
              <button
                type="button"
                onClick={() => setPnlViewMode('overall')}
                style={{
                  background: pnlViewMode === 'overall' ? 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)' : 'transparent',
                  color: pnlViewMode === 'overall' ? '#ffffff' : '#a5b4fc',
                  border: 'none',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  fontWeight: 700,
                  fontSize: '12px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  boxShadow: pnlViewMode === 'overall' ? '0 2px 8px rgba(99, 102, 241, 0.4)' : 'none',
                  transition: 'all 0.2s ease'
                }}
              >
                <Activity size={14} /> Overall P&L
              </button>

              <button
                type="button"
                onClick={() => setPnlViewMode('daily')}
                style={{
                  background: pnlViewMode === 'daily' ? 'linear-gradient(135deg, #0d9488 0%, #14b8a6 100%)' : 'transparent',
                  color: pnlViewMode === 'daily' ? '#ffffff' : '#a5b4fc',
                  border: 'none',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  fontWeight: 700,
                  fontSize: '12px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  boxShadow: pnlViewMode === 'daily' ? '0 2px 8px rgba(20, 184, 166, 0.4)' : 'none',
                  transition: 'all 0.2s ease'
                }}
              >
                <Calendar size={14} /> Daily P&L
              </button>
            </div>
          </div>

          <div style={{ fontSize: '12px', color: '#a5b4fc', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ height: '6px', width: '6px', borderRadius: '50%', background: '#10b981', display: 'inline-block' }}></span>
            LTP Live Auto-Refreshed
          </div>
        </div>

        {/* OVERALL PNL MODE PANELS */}
        {pnlViewMode === 'overall' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: '20px' }}>
            
            {/* Panel 1: Total Portfolio Net Overview & Risk Allowance */}
            <div className="glass-panel" style={{ padding: '24px', gridColumn: '1 / -1', borderLeft: '4px solid #a855f7', background: 'linear-gradient(135deg, rgba(168, 85, 247, 0.08) 0%, rgba(99, 102, 241, 0.04) 100%)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ height: '8px', width: '8px', borderRadius: '50%', background: '#c084fc', boxShadow: '0 0 10px #c084fc' }}></span>
                  <span style={{ fontSize: '14px', fontWeight: 800, color: '#c084fc', textTransform: 'uppercase' }}>
                    ⚡ Total Portfolio Net Overview (Journal + MTF + SIP)
                  </span>
                </div>
                <span style={{ fontSize: '11px', background: 'rgba(168, 85, 247, 0.2)', color: '#e9d5ff', padding: '3px 10px', borderRadius: '6px', fontWeight: 700 }}>
                  Day {currentDayCount} of {totalChallengeDays} Budget Earned: ₹{(currentDayCount * dailyRiskLimit).toLocaleString('en-IN')}
                </span>
              </div>

              {(() => {
                const hasActiveMtf = mtfTradeList.some(t => t.status === 'Active');
                const mtfOverviewNetPnl = hasActiveMtf ? (closedMtfNetPnl + activeMtfNetPnl) : closedMtfNetPnl;
                const overallPortfolioTotalNetPnl = totalRealizedNetPnl + mtfOverviewNetPnl + totalSipUnrealizedPnl;
                const netAfterRiskBudget = overallPortfolioTotalNetPnl + (currentDayCount * dailyRiskLimit);

                return (
                  <>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '14px', marginBottom: '16px' }}>
                      <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '12px 16px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
                        <div style={{ fontSize: '11px', color: '#14b8a6', fontWeight: 700 }}>NET TRADING P&L</div>
                        <div style={{ fontSize: '18px', fontWeight: 900, color: totalRealizedNetPnl >= 0 ? '#34d399' : '#f87171', marginTop: '4px' }}>
                          {totalRealizedNetPnl >= 0 ? '+' : ''}₹{totalRealizedNetPnl.toFixed(2)}
                        </div>
                        <div style={{ fontSize: '10px', color: '#a5b4fc', marginTop: '2px' }}>Journal Closed</div>
                      </div>

                      <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '12px 16px', borderRadius: '10px', border: hasActiveMtf ? '1px solid rgba(52, 211, 153, 0.35)' : '1px solid rgba(255,255,255,0.06)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div style={{ fontSize: '11px', color: '#f59e0b', fontWeight: 700 }}>NET MTF P&L</div>
                          {hasActiveMtf && (
                            <span style={{ fontSize: '9px', color: '#34d399', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '3px', background: 'rgba(52, 211, 153, 0.15)', padding: '1px 5px', borderRadius: '4px' }}>
                              <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#34d399', boxShadow: '0 0 6px #34d399' }}></span>
                              LIVE
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '18px', fontWeight: 900, color: mtfOverviewNetPnl >= 0 ? '#34d399' : '#f87171', marginTop: '4px' }}>
                          {mtfOverviewNetPnl >= 0 ? '+' : ''}₹{mtfOverviewNetPnl.toFixed(2)}
                        </div>
                        <div style={{ fontSize: '10px', color: '#a5b4fc', marginTop: '2px' }}>
                          {hasActiveMtf 
                            ? `Closed (${closedMtfNetPnl >= 0 ? '+' : ''}₹${closedMtfNetPnl.toFixed(2)}) + Active (${activeMtfNetPnl >= 0 ? '+' : ''}₹${activeMtfNetPnl.toFixed(2)})` 
                            : 'Closed MTF Leverage'}
                        </div>
                      </div>

                      <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '12px 16px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
                        <div style={{ fontSize: '11px', color: '#00b4d8', fontWeight: 700 }}>SIP RUNNING P&L</div>
                        <div style={{ fontSize: '18px', fontWeight: 900, color: totalSipUnrealizedPnl >= 0 ? '#34d399' : '#f87171', marginTop: '4px' }}>
                          {totalSipUnrealizedPnl >= 0 ? '+' : ''}₹{totalSipUnrealizedPnl.toFixed(2)}
                        </div>
                        <div style={{ fontSize: '10px', color: '#a5b4fc', marginTop: '2px' }}>SIP Holdings Unrealized</div>
                      </div>

                      <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '12px 16px', borderRadius: '10px', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
                        <div style={{ fontSize: '11px', color: '#c084fc', fontWeight: 700 }}>TOTAL NET P&L</div>
                        <div style={{ fontSize: '18px', fontWeight: 900, color: overallPortfolioTotalNetPnl >= 0 ? '#34d399' : '#f87171', marginTop: '4px' }}>
                          {overallPortfolioTotalNetPnl >= 0 ? '+' : ''}₹{overallPortfolioTotalNetPnl.toFixed(2)}
                        </div>
                        <div style={{ fontSize: '10px', color: '#a5b4fc', marginTop: '2px' }}>
                          Trading + MTF {hasActiveMtf ? '(Live Active)' : ''} + SIP
                        </div>
                      </div>
                    </div>

                    {/* Net Position After Risk Budget Allowance Banner */}
                    <div style={{ 
                      display: 'flex', 
                      justifyContent: 'space-between', 
                      alignItems: 'center', 
                      flexWrap: 'wrap', 
                      gap: '12px',
                      background: 'rgba(251, 191, 36, 0.08)', 
                      border: '1px solid rgba(251, 191, 36, 0.4)', 
                      borderRadius: '10px', 
                      padding: '14px 18px' 
                    }}>
                      <div>
                        <div style={{ fontSize: '14px', fontWeight: 800, color: '#fbbf24' }}>
                          🛡️ Net After Risk Budget:
                        </div>
                        <div style={{ fontSize: '11px', color: '#cbd5e1', marginTop: '2px' }}>
                          Total Net P&L + Earned Budget Allowance (Day {currentDayCount} × ₹{dailyRiskLimit} = ₹{(currentDayCount * dailyRiskLimit).toLocaleString('en-IN')})
                        </div>
                      </div>
                      <div style={{ fontSize: '22px', fontWeight: 900, color: netAfterRiskBudget >= 0 ? '#34d399' : '#f87171' }}>
                        {netAfterRiskBudget >= 0 ? '+' : ''}₹{netAfterRiskBudget.toFixed(2)}
                      </div>
                    </div>
                  </>
                );
              })()}
            </div>

            {/* Panel 2: Realized Net P&L Summary */}
            <div className="glass-panel" style={{ padding: '24px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                <span style={{ height: '8px', width: '8px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 10px #10b981' }}></span>
                <span style={{ fontSize: '14px', fontWeight: 800, color: '#34d399', textTransform: 'uppercase' }}>
                  ● Cumulative Realized P&L Summary (Journal + MTF)
                </span>
              </div>

              <div className="glass-panel-inner" style={{ padding: '20px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', alignItems: 'center' }}>
                <div>
                  <div style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 600 }}>NET REALIZED P&L</div>
                  <div style={{ fontSize: '22px', fontWeight: 900, color: cumulativeRealizedNetPnl > 0 ? '#34d399' : (cumulativeRealizedNetPnl < 0 ? '#f87171' : '#ffffff'), marginTop: '4px' }}>
                    {cumulativeRealizedNetPnl >= 0 ? '+' : ''}₹{cumulativeRealizedNetPnl.toFixed(2)}
                  </div>
                </div>

                <div style={{ textAlign: 'center', borderLeft: '1px solid rgba(99, 102, 241, 0.2)', borderRight: '1px solid rgba(99, 102, 241, 0.2)' }}>
                  <div style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 600 }}>AVG DAILY P&L</div>
                  <div style={{ fontSize: '22px', fontWeight: 900, color: averageDailyNetPnl > 0 ? '#34d399' : (averageDailyNetPnl < 0 ? '#f87171' : '#ffffff'), marginTop: '4px' }}>
                    {averageDailyNetPnl >= 0 ? '+' : ''}₹{averageDailyNetPnl.toFixed(2)}
                  </div>
                  <div style={{ fontSize: '10px', color: '#a5b4fc', marginTop: '2px' }}>Day {currentDayCount} Avg</div>
                </div>

                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 600 }}>WIN RATE</div>
                  <div style={{ fontSize: '22px', fontWeight: 900, color: '#c084fc', marginTop: '4px' }}>
                    {cumulativeWinRatePct}%
                  </div>
                  <div style={{ fontSize: '10px', color: '#a5b4fc', marginTop: '2px' }}>{cumulativeWinningTradesCount} W / {cumulativeClosedTradesCount} T</div>
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#a5b4fc', marginTop: '12px', padding: '0 4px' }}>
                <span>Gross: ₹{cumulativeGrossPnl.toFixed(2)}</span>
                <span>Taxes & Charges: ₹{cumulativeCharges.toFixed(2)}</span>
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '6px', textAlign: 'center', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '6px' }}>
                {(() => {
                  const hasActiveMtf = mtfTradeList.some(t => t.status === 'Active');
                  const mtfPnlVal = hasActiveMtf ? (closedMtfNetPnl + activeMtfNetPnl) : closedMtfNetPnl;
                  return (
                    <>
                      Journal P&L: <strong style={{ color: totalRealizedNetPnl >= 0 ? '#34d399' : '#f87171' }}>{totalRealizedNetPnl >= 0 ? '+' : ''}₹{totalRealizedNetPnl.toFixed(2)}</strong> | MTF P&L: <strong style={{ color: mtfPnlVal >= 0 ? '#34d399' : '#f87171' }}>{mtfPnlVal >= 0 ? '+' : ''}₹{mtfPnlVal.toFixed(2)}</strong> {hasActiveMtf ? '(Live Active)' : ''}
                    </>
                  );
                })()}
              </div>
            </div>

            {/* Panel 2: Active Open Positions */}
            <div className="glass-panel" style={{ padding: '24px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                <span style={{ height: '8px', width: '8px', borderRadius: '50%', background: '#6366f1', boxShadow: '0 0 10px #6366f1' }}></span>
                <span style={{ fontSize: '14px', fontWeight: 800, color: '#818cf8', textTransform: 'uppercase' }}>
                  ● Active Open Positions
                </span>
              </div>

              <div className="glass-panel-inner" style={{ padding: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 600 }}>UNREALIZED P&L</div>
                  <div style={{ fontSize: '26px', fontWeight: 900, color: totalUnrealizedPnl > 0 ? '#34d399' : (totalUnrealizedPnl < 0 ? '#f87171' : '#ffffff'), marginTop: '4px' }}>
                    {totalUnrealizedPnl >= 0 ? '+' : ''}₹{totalUnrealizedPnl.toFixed(2)}
                  </div>
                </div>

                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 600 }}>POSITIONS HELD</div>
                  <div style={{ fontSize: '26px', fontWeight: 900, color: '#67e8f9', marginTop: '4px' }}>
                    {activeTrades.length}
                  </div>
                  <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '2px' }}>Live Polling Active</div>
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#a5b4fc', marginTop: '12px', padding: '0 4px' }}>
                <span>Live Tick Interval: 4s</span>
                <span>Backend: Independent YFinance Engine</span>
              </div>
            </div>

          </div>
        )}

        {/* DAILY PNL MODE PANELS & DATE SELECTOR */}
        {pnlViewMode === 'daily' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            
            {/* Daily Date Selector Bar */}
            <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                <div style={{ fontSize: '13px', fontWeight: 700, color: '#a5b4fc', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Calendar size={16} style={{ color: '#14b8a6' }} /> Select Trading Date:
                </div>
                <input 
                  type="date"
                  value={selectedDailyDate}
                  onChange={e => setSelectedDailyDate(e.target.value)}
                  style={{
                    background: 'rgba(15, 23, 42, 0.8)',
                    border: '1px solid rgba(20, 184, 166, 0.4)',
                    color: '#ffffff',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    fontSize: '13px',
                    fontWeight: 700,
                    outline: 'none'
                  }}
                />
                <button
                  type="button"
                  onClick={() => setSelectedDailyDate(getTodayDateStr())}
                  style={{
                    background: selectedDailyDate === getTodayDateStr() ? 'rgba(20, 184, 166, 0.25)' : 'rgba(255,255,255,0.06)',
                    border: selectedDailyDate === getTodayDateStr() ? '1px solid #14b8a6' : '1px solid rgba(255,255,255,0.12)',
                    color: selectedDailyDate === getTodayDateStr() ? '#34d399' : '#a5b4fc',
                    padding: '8px 14px',
                    borderRadius: '8px',
                    fontWeight: 700,
                    fontSize: '12px',
                    cursor: 'pointer'
                  }}
                >
                  Today ({getTodayDateStr()})
                </button>
              </div>

              {/* Quick Date Shortcuts from Trading History */}
              {dailyPnlSummaryList.length > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 600 }}>Trading History:</span>
                  {dailyPnlSummaryList.slice(0, 5).map(item => (
                    <button
                      key={item.date}
                      type="button"
                      onClick={() => setSelectedDailyDate(item.date)}
                      style={{
                        background: selectedDailyDate === item.date ? 'rgba(20, 184, 166, 0.3)' : 'rgba(255, 255, 255, 0.05)',
                        border: selectedDailyDate === item.date ? '1px solid #14b8a6' : '1px solid rgba(255, 255, 255, 0.1)',
                        color: item.netPnl > 0 ? '#34d399' : (item.netPnl < 0 ? '#f87171' : '#ffffff'),
                        padding: '4px 10px',
                        borderRadius: '6px',
                        fontSize: '11px',
                        fontWeight: 700,
                        cursor: 'pointer'
                      }}
                    >
                      {item.date}: {item.netPnl >= 0 ? '+' : ''}₹{item.netPnl.toFixed(0)}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Side-by-side Daily Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: '20px' }}>
              
              {/* Daily Card 1: Selected Day Realized P&L */}
              <div className="glass-panel" style={{ padding: '24px', borderLeft: `4px solid ${selectedDailyNetPnl >= 0 ? '#14b8a6' : '#f87171'}` }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ height: '8px', width: '8px', borderRadius: '50%', background: '#14b8a6', boxShadow: '0 0 10px #14b8a6' }}></span>
                    <span style={{ fontSize: '14px', fontWeight: 800, color: '#2dd4bf', textTransform: 'uppercase' }}>
                      ● Daily Realized P&L ({selectedDailyDate})
                    </span>
                  </div>
                  <span style={{ fontSize: '11px', background: 'rgba(20, 184, 166, 0.15)', color: '#2dd4bf', padding: '3px 8px', borderRadius: '4px', fontWeight: 700 }}>
                    {dailyClosedTrades.length} Trade{dailyClosedTrades.length === 1 ? '' : 's'} Logged
                  </span>
                </div>

                <div className="glass-panel-inner" style={{ padding: '20px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 600 }}>NET DAILY P&L</div>
                    <div style={{ fontSize: '22px', fontWeight: 900, color: selectedDailyNetPnl > 0 ? '#34d399' : (selectedDailyNetPnl < 0 ? '#f87171' : '#ffffff'), marginTop: '4px' }}>
                      {selectedDailyNetPnl >= 0 ? '+' : ''}₹{selectedDailyNetPnl.toFixed(2)}
                    </div>
                  </div>

                  <div style={{ textAlign: 'center', borderLeft: '1px solid rgba(99, 102, 241, 0.2)', borderRight: '1px solid rgba(99, 102, 241, 0.2)' }}>
                    <div style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 600 }}>DAILY WIN RATE</div>
                    <div style={{ fontSize: '22px', fontWeight: 900, color: '#c084fc', marginTop: '4px' }}>
                      {selectedDailyWinRatePct}%
                    </div>
                    <div style={{ fontSize: '10px', color: '#a5b4fc', marginTop: '2px' }}>{selectedDailyWinsCount} W / {dailyClosedTrades.length} T</div>
                  </div>

                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 600 }}>DAILY TAXES</div>
                    <div style={{ fontSize: '22px', fontWeight: 900, color: '#f87171', marginTop: '4px' }}>
                      ₹{selectedDailyCharges.toFixed(2)}
                    </div>
                    <div style={{ fontSize: '10px', color: '#a5b4fc', marginTop: '2px' }}>Zerodha Charges</div>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#a5b4fc', marginTop: '12px', padding: '0 4px' }}>
                  <span>Gross P&L: ₹{selectedDailyGrossPnl.toFixed(2)}</span>
                  <span>Date Status: {dailyClosedTrades.length > 0 ? 'Closed Trades Found' : 'No Trades On This Date'}</span>
                </div>
              </div>

              {/* Daily Card 2: Daily P&L History Breakdown Table */}
              <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Calendar size={16} style={{ color: '#a855f7' }} />
                    <span style={{ fontSize: '14px', fontWeight: 800, color: '#c084fc', textTransform: 'uppercase' }}>
                      Daily P&L History Breakdown
                    </span>
                  </div>
                  <span style={{ fontSize: '11px', color: '#a5b4fc' }}>{dailyPnlSummaryList.length} Active Days</span>
                </div>

                <div style={{ maxHeight: '160px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px', paddingRight: '4px' }}>
                  {dailyPnlSummaryList.length === 0 ? (
                    <div style={{ fontSize: '12px', color: '#a5b4fc', textAlign: 'center', padding: '20px 0' }}>
                      No trade dates recorded yet.
                    </div>
                  ) : (
                    dailyPnlSummaryList.map(item => {
                      const isSelected = item.date === selectedDailyDate;
                      return (
                        <div
                          key={item.date}
                          onClick={() => setSelectedDailyDate(item.date)}
                          style={{
                            background: isSelected ? 'rgba(20, 184, 166, 0.15)' : 'rgba(255, 255, 255, 0.04)',
                            border: isSelected ? '1px solid #14b8a6' : '1px solid rgba(255, 255, 255, 0.08)',
                            padding: '10px 14px',
                            borderRadius: '8px',
                            cursor: 'pointer',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            transition: 'all 0.15s ease'
                          }}
                        >
                          <div>
                            <div style={{ fontSize: '13px', fontWeight: 800, color: isSelected ? '#34d399' : '#ffffff' }}>
                              {item.date} {isSelected ? '(Selected)' : ''}
                            </div>
                            <div style={{ fontSize: '11px', color: '#a5b4fc' }}>
                              {item.tradesCount} Trade{item.tradesCount > 1 ? 's' : ''} • Win Rate: {((item.winsCount / item.tradesCount) * 100).toFixed(0)}%
                            </div>
                          </div>

                          <div style={{ textAlign: 'right' }}>
                            <div style={{ fontSize: '14px', fontWeight: 900, color: item.netPnl > 0 ? '#34d399' : (item.netPnl < 0 ? '#f87171' : '#ffffff') }}>
                              {item.netPnl >= 0 ? '+' : ''}₹{item.netPnl.toFixed(2)}
                            </div>
                            <div style={{ fontSize: '10px', color: '#a5b4fc' }}>
                              Gross: ₹{item.grossPnl.toFixed(0)} | Taxes: ₹{item.totalCharges.toFixed(0)}
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

            </div>

          </div>
        )}

      </div>

      {/* Trade Risk Warning Alert Banner */}
      {isRiskWarningActive && (
        <div style={{
          background: 'rgba(245, 158, 11, 0.1)',
          border: '1px solid rgba(245, 158, 11, 0.3)',
          padding: '14px 20px',
          borderRadius: '10px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px'
        }}>
          <ShieldAlert size={20} style={{ color: '#fbbf24', flexShrink: 0 }} />
          <div style={{ fontSize: '13px', color: '#fef3c7' }}>
            <strong>Risk Warning Active (Day {currentDayCount} of {totalChallengeDays}):</strong> {cumulativeCarriedLoss > 0 ? (
              <>Carried loss of <strong>₹{cumulativeCarriedLoss.toFixed(2)}</strong> reduces today's available daily risk to <strong>₹{availableRiskLimitToday.toFixed(2)}</strong>.</>
            ) : (
              <>Daily loss limit (₹{dailyRiskLimit}) breached for today. Exercise strict discipline!</>
            )}
          </div>
        </div>
      )}
      </>)}

      {activeTab === 'trades' && (<>
      {/* Add New Trade Planner Form */}
      <form onSubmit={handleAddTrade} className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '12px' }}>
          <PlusCircle size={18} style={{ color: '#14b8a6' }} />
          <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff' }}>Log New Position</h2>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '14px' }}>
          <div>
            <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>SYMBOL</label>
            <input 
              type="text" 
              placeholder="e.g. CRUDEOILM 6500 CE" 
              value={symbol} 
              onChange={handleSymbolChange} 
              className="input-field" 
              required
            />
          </div>

          <div>
            <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>TYPE</label>
            <select 
              value={instrumentType} 
              onChange={handleInstrumentTypeChange} 
              className="input-field"
            >
              <option value="Intraday">Intraday Buy</option>
              <option value="Intraday Short">Intraday Short</option>
              <option value="Stock Options">Stock Options (NSE F&O)</option>
              <option value="Crude Oil Options">Crude Oil Main (Lot: 100)</option>
              <option value="Crude Oil Mini">Crude Oil Mini (Lot: 10)</option>
              <option value="Natural Gas Options">Natural Gas Main (Lot: 1250)</option>
              <option value="Natural Gas Mini">Natural Gas Mini (Lot: 250)</option>
              <option value="Nifty Options">Nifty Options (Lot: 65)</option>
              <option value="Delivery">Equity Delivery</option>
            </select>
          </div>

          <div>
            <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>ENTRY PRICE (₹)</label>
            <input 
              type="number" 
              step="0.05" 
              placeholder="12.50" 
              value={entryPrice} 
              onChange={handleEntryPriceChange} 
              className="input-field" 
              required
            />
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700 }}>QUANTITY</label>
              <span style={{ fontSize: '10px', color: '#c084fc', fontWeight: 700 }}>
                {getLotIntelligenceInfo(symbol, instrumentType).label}
              </span>
            </div>
            <input 
              type="number" 
              placeholder="100" 
              value={quantity} 
              onChange={e => setQuantity(e.target.value)} 
              className="input-field" 
              required
            />
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px', flexWrap: 'wrap', gap: '4px' }}>
              <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700 }}>STOP LOSS (₹)</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ fontSize: '10px', color: '#38bdf8', fontWeight: 700 }}>SL %:</span>
                {(getSegmentConfig(instrumentType).presets || [0.8, 1.0, 1.2]).map(p => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => handleSlPctChange(p)}
                    style={{
                      background: parseFloat(customSlPct) === p ? 'rgba(56, 189, 248, 0.25)' : 'rgba(255,255,255,0.05)',
                      border: parseFloat(customSlPct) === p ? '1px solid #38bdf8' : '1px solid rgba(255,255,255,0.1)',
                      color: parseFloat(customSlPct) === p ? '#38bdf8' : '#94a3b8',
                      borderRadius: '4px',
                      padding: '1px 5px',
                      fontSize: '10px',
                      fontWeight: 800,
                      cursor: 'pointer'
                    }}
                  >
                    {p}%
                  </button>
                ))}
                <input 
                  type="number"
                  step="0.1"
                  value={customSlPct}
                  onChange={e => handleSlPctChange(e.target.value)}
                  style={{
                    width: '42px',
                    padding: '1px 4px',
                    fontSize: '10px',
                    fontWeight: 800,
                    textAlign: 'center',
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(56, 189, 248, 0.3)',
                    borderRadius: '4px',
                    color: '#38bdf8'
                  }}
                  title="Custom SL %"
                />
              </div>
            </div>
            <input 
              type="number" 
              step="0.05" 
              placeholder="11.00" 
              value={stopLoss} 
              onChange={e => setStopLoss(e.target.value)} 
              className="input-field"
            />
          </div>

          <div>
            <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>TARGET (₹)</label>
            <input 
              type="number" 
              step="0.05" 
              placeholder="15.00" 
              value={targetPrice} 
              onChange={e => setTargetPrice(e.target.value)} 
              className="input-field"
            />
          </div>
        </div>

        {/* Active Segment Monthly SL Breach Alert Banner */}
        {(() => {
          const matchedSeg = segmentAllocList.find(s => {
            const lower = s.name.toLowerCase();
            const type = instrumentType.toLowerCase();
            if (lower.includes('intraday')) return type.includes('intraday');
            if (lower.includes('natural') || lower.includes('natgas')) return type.includes('natural') || type.includes('natgas');
            if (lower.includes('nifty')) return type.includes('nifty');
            if (lower.includes('crude')) return type.includes('crude');
            return false;
          });

          if (matchedSeg) {
            const capitalPool = (closingCapitalNum > 0 ? closingCapitalNum : openingCapitalNum);
            const allocPct = Number(matchedSeg.allocState) || 0;
            const mslPct = Number(matchedSeg.mslState) || 0;
            const maxLoss = capitalPool * (allocPct / 100) * (mslPct / 100);
            const lossUsed = matchedSeg.currentPnl < 0 ? Math.abs(matchedSeg.currentPnl) : 0;
            if (maxLoss > 0 && lossUsed >= maxLoss) {
              return (
                <div style={{
                  background: 'rgba(30, 27, 45, 0.85)',
                  border: '1px solid rgba(251, 146, 60, 0.35)',
                  padding: '12px 16px',
                  borderRadius: '8px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  color: '#fb923c',
                  fontSize: '12px',
                  fontWeight: 700
                }}>
                  <AlertCircle size={18} style={{ color: '#fb923c', flexShrink: 0 }} />
                  <span>
                    ⚠️ <strong>MONTHLY RISK SL BREACHED FOR {matchedSeg.name.toUpperCase()}:</strong> Current month loss (₹{lossUsed.toFixed(0)}) exceeds your monthly risk limit (₹{maxLoss.toFixed(0)}). Exercise caution.
                  </span>
                </div>
              );
            }
          }
          return null;
        })()}

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '4px' }}>
          <button 
            type="submit" 
            style={{
              background: '#14b8a6',
              color: '#ffffff',
              border: 'none',
              padding: '12px 24px',
              borderRadius: '8px',
              fontWeight: 800,
              fontSize: '14px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <PlusCircle size={18} />
            Log Position
          </button>
        </div>
      </form>

      {/* View Mode Badge (kept from old tab bar) */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 600 }}>Mode:</span>
        <span style={{
          background: pnlViewMode === 'daily' ? 'rgba(20, 184, 166, 0.2)' : 'rgba(99, 102, 241, 0.2)',
          border: pnlViewMode === 'daily' ? '1px solid #14b8a6' : '1px solid #6366f1',
          color: pnlViewMode === 'daily' ? '#34d399' : '#818cf8',
          padding: '4px 10px',
          borderRadius: '6px',
          fontSize: '12px',
          fontWeight: 800,
          display: 'flex',
          alignItems: 'center',
          gap: '4px'
        }}>
          {pnlViewMode === 'daily' ? <Calendar size={13} /> : <Activity size={13} />}
          {pnlViewMode === 'daily' ? `Daily P&L (${selectedDailyDate})` : 'Overall P&L'}
        </span>
      </div>

      {/* Active Positions Table */}
      <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#818cf8', marginTop: '8px' }}>Active Open Positions ({activeTrades.length})</h2>
      {true && (
        <div className="glass-panel" style={{ padding: '24px', overflowX: 'auto' }}>
          {activeTrades.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#a5b4fc' }}>
              No open active positions. Log a trade above to start tracking.
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
              <thead>
                <tr style={{ textAlign: 'left', color: '#a5b4fc', borderBottom: '1px solid rgba(99, 102, 241, 0.2)' }}>
                  <th style={{ padding: '12px 8px' }}>Symbol</th>
                  <th style={{ padding: '12px 8px' }}>Type</th>
                  <th style={{ padding: '12px 8px' }}>Entry (₹)</th>
                  <th style={{ padding: '12px 8px' }}>Qty</th>
                  <th style={{ padding: '12px 8px' }}>Live LTP (₹)</th>
                  <th style={{ padding: '12px 8px' }}>Unrealized P&L</th>
                  <th style={{ padding: '12px 8px', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {activeTrades.map((t, idx) => {
                  const sym = (t.symbol || '').trim();
                  const ltp = liveLtps[sym] ?? liveLtps[sym.toUpperCase()] ?? liveLtps[t.symbol] ?? t.entry_price;
                  const isShort = t.instrument_type === 'Intraday Short';
                  const diff = isShort ? (t.entry_price - ltp) : (ltp - t.entry_price);
                  const pnl = diff * t.quantity;

                  return (
                    <tr key={t.uuid || t.id || idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                      <td style={{ padding: '16px 8px', fontWeight: 800, color: '#ffffff' }}>{t.symbol}</td>
                      <td style={{ padding: '16px 8px' }}>
                        <span style={{ background: 'rgba(99, 102, 241, 0.15)', padding: '4px 10px', borderRadius: '6px', fontSize: '12px' }}>{t.instrument_type}</span>
                      </td>
                      <td style={{ padding: '16px 8px', fontWeight: 600 }}>₹{t.entry_price.toFixed(2)}</td>
                      <td style={{ padding: '16px 8px' }}>{t.quantity}</td>
                      <td style={{ padding: '16px 8px', fontWeight: 800, color: '#67e8f9' }}>₹{ltp.toFixed(2)}</td>
                      <td style={{ padding: '16px 8px', fontWeight: 800, color: pnl > 0 ? '#34d399' : (pnl < 0 ? '#f87171' : '#ffffff') }}>
                        {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}
                      </td>
                      <td style={{ padding: '16px 8px', textAlign: 'right' }}>
                        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                          <button 
                            onClick={() => handleOpenEditModal(t)}
                            title="Edit Trade Transaction Details"
                            style={{ background: 'rgba(168, 85, 247, 0.2)', border: '1px solid rgba(168, 85, 247, 0.4)', color: '#c084fc', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}
                          >
                            <Edit3 size={13} /> Edit
                          </button>
                          <button 
                            onClick={() => {
                              setEditingTrade(t);
                              setExitPriceInput(ltp.toFixed(2));
                            }}
                            style={{ background: 'rgba(16, 185, 129, 0.2)', border: '1px solid rgba(16, 185, 129, 0.4)', color: '#34d399', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontWeight: 700, fontSize: '12px' }}
                          >
                            Close Position
                          </button>
                          <button 
                            onClick={() => handleDeleteTrade(t)}
                            style={{ background: 'rgba(239, 68, 68, 0.2)', border: 'none', color: '#f87171', padding: '6px 8px', borderRadius: '6px', cursor: 'pointer' }}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Closed Positions Table */}
      <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#14b8a6' }}>Realized Closed Positions ({pnlViewMode === 'daily' ? dailyClosedTrades.length : closedTrades.length})</h2>
      {true && (
        <div className="glass-panel" style={{ padding: '24px', overflowX: 'auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          
          {/* Table Header Filter Indicator */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px', background: 'rgba(15, 23, 42, 0.4)', padding: '10px 14px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: '13px', color: '#a5b4fc', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Filter size={15} style={{ color: pnlViewMode === 'daily' ? '#14b8a6' : '#6366f1' }} />
              {pnlViewMode === 'daily' ? (
                <>Showing Closed Trades for Date: <strong style={{ color: '#34d399' }}>{selectedDailyDate}</strong> ({dailyClosedTrades.length} trade{dailyClosedTrades.length === 1 ? '' : 's'})</>
              ) : (
                <>Showing All-Time Realized Closed Positions (<strong style={{ color: '#ffffff' }}>{closedTrades.length}</strong> total)</>
              )}
            </div>

            {pnlViewMode === 'daily' ? (
              <button
                type="button"
                onClick={() => setPnlViewMode('overall')}
                style={{
                  background: 'rgba(99, 102, 241, 0.15)',
                  border: '1px solid rgba(99, 102, 241, 0.3)',
                  color: '#818cf8',
                  padding: '6px 12px',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontWeight: 700,
                  cursor: 'pointer'
                }}
              >
                Show All Dates (Overall P&L)
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setPnlViewMode('daily')}
                style={{
                  background: 'rgba(20, 184, 166, 0.15)',
                  border: '1px solid rgba(20, 184, 166, 0.3)',
                  color: '#34d399',
                  padding: '6px 12px',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontWeight: 700,
                  cursor: 'pointer'
                }}
              >
                Filter by Daily P&L Date
              </button>
            )}
          </div>

          {(() => {
            const displayTradesList = pnlViewMode === 'daily' ? dailyClosedTrades : closedTrades;

            if (displayTradesList.length === 0) {
              return (
                <div style={{ textAlign: 'center', padding: '40px 0', color: '#a5b4fc' }}>
                  {pnlViewMode === 'daily' ? (
                    <>No realized closed positions logged on <strong>{selectedDailyDate}</strong>.</>
                  ) : (
                    <>No realized closed positions logged yet.</>
                  )}
                </div>
              );
            }

            return (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: '#a5b4fc', borderBottom: '1px solid rgba(99, 102, 241, 0.2)' }}>
                    <th style={{ padding: '12px 8px' }}>Symbol</th>
                    <th style={{ padding: '12px 8px' }}>Type</th>
                    <th style={{ padding: '12px 8px' }}>Date</th>
                    <th style={{ padding: '12px 8px' }}>Entry (₹)</th>
                    <th style={{ padding: '12px 8px' }}>Qty</th>
                    <th style={{ padding: '12px 8px' }}>Exit Price (₹)</th>
                    <th style={{ padding: '12px 8px' }}>Capital</th>
                    <th style={{ padding: '12px 8px' }}>Net Realized P&L</th>
                    <th style={{ padding: '12px 8px', textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {displayTradesList.map((t, idx) => {
                    const chg = calculateZerodhaCharges(t);
                    const capital = t.entry_price * t.quantity;
                    const tradeDateStr = getTradeDateStr(t);
                    return (
                      <tr key={t.uuid || t.id || idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        <td style={{ padding: '16px 8px', fontWeight: 800, color: '#ffffff' }}>{t.symbol}</td>
                        <td style={{ padding: '16px 8px' }}>
                          <span style={{ background: 'rgba(99, 102, 241, 0.15)', padding: '4px 10px', borderRadius: '6px', fontSize: '12px', color: '#a5b4fc' }}>
                            {t.instrument_type}
                          </span>
                        </td>
                        <td style={{ padding: '16px 8px', fontSize: '12px', color: '#a5b4fc', fontWeight: 600 }}>{tradeDateStr}</td>
                        <td style={{ padding: '16px 8px', fontWeight: 600 }}>₹{t.entry_price.toFixed(2)}</td>
                        <td style={{ padding: '16px 8px' }}>{t.quantity}</td>
                        <td style={{ padding: '16px 8px', fontWeight: 800, color: '#67e8f9' }}>₹{t.exit_price.toFixed(2)}</td>
                        <td style={{ padding: '16px 8px', color: '#a5b4fc' }}>₹{capital.toFixed(2)}</td>
                        <td style={{ padding: '16px 8px' }}>
                          <div style={{ fontSize: '15px', fontWeight: 800, color: chg.net_pnl > 0 ? '#34d399' : (chg.net_pnl < 0 ? '#f87171' : '#ffffff') }}>
                            {chg.net_pnl >= 0 ? '+' : ''}₹{chg.net_pnl.toFixed(2)}
                          </div>
                          <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '2px' }}>
                            Gross: ₹{chg.gross_pnl.toFixed(2)} | Charges: ₹{chg.total.toFixed(2)}
                          </div>
                        </td>
                        <td style={{ padding: '16px 8px', textAlign: 'right' }}>
                          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                            <button 
                              onClick={() => handleOpenEditModal(t)}
                              title="Edit Trade Transaction Details"
                              style={{ background: 'rgba(168, 85, 247, 0.2)', border: '1px solid rgba(168, 85, 247, 0.4)', color: '#c084fc', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}
                            >
                              <Edit3 size={13} /> Edit
                            </button>
                            <button 
                              onClick={() => setSelectedChargeTrade(t)}
                              title="View Zerodha Contract Note Tax Breakdown"
                              style={{ background: 'rgba(6, 182, 212, 0.2)', border: 'none', color: '#67e8f9', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
                            >
                              Charges
                            </button>
                            <button 
                              onClick={() => handleDeleteTrade(t)}
                              style={{ background: 'rgba(239, 68, 68, 0.2)', border: 'none', color: '#f87171', padding: '6px 8px', borderRadius: '6px', cursor: 'pointer' }}
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            );
          })()}
        </div>
      )}
      </>)}

      {/* Capital Management Tab View */}
      {activeTab === 'capital' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Top Capital Executive Cards (All 6 Components Explicitly Visualized) */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
            
            <div className="glass-panel" style={{ padding: '20px', borderLeft: '4px solid #6366f1' }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '8px' }}>1. OPENING CAPITAL</div>
              <div style={{ fontSize: '24px', fontWeight: 900, color: 'white' }}>
                ₹{openingCapitalNum.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>Starting Account Baseline</div>
            </div>

            <div className="glass-panel" style={{ padding: '20px', borderLeft: `4px solid ${totalTradeNetPnl >= 0 ? '#10b981' : '#f87171'}` }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '8px' }}>2. TRADE NET P&L (AUTO)</div>
              <div style={{ fontSize: '24px', fontWeight: 900, color: totalTradeNetPnl > 0 ? '#34d399' : (totalTradeNetPnl < 0 ? '#f87171' : '#ffffff') }}>
                {totalTradeNetPnl >= 0 ? '+' : ''}₹{totalTradeNetPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>Realized Net + Open PnL</div>
            </div>

            <div className="glass-panel" style={{ padding: '20px', borderLeft: '4px solid #fde047' }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '8px' }}>3. BROKER ADJUSTMENT</div>
              <div style={{ fontSize: '24px', fontWeight: 900, color: '#fde047' }}>
                {brokerAdjNum >= 0 ? '+' : ''}₹{brokerAdjNum.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>DP Fees / Manual Adjustments</div>
            </div>

            <div className="glass-panel" style={{ padding: '20px', borderLeft: '4px solid #34d399' }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '8px' }}>4. DEPOSITS (+)</div>
              <div style={{ fontSize: '24px', fontWeight: 900, color: '#34d399' }}>
                +₹{depositsNum.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>Additional Capital Funds</div>
            </div>

            <div className="glass-panel" style={{ padding: '20px', borderLeft: '4px solid #f87171' }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '8px' }}>5. WITHDRAWALS (-)</div>
              <div style={{ fontSize: '24px', fontWeight: 900, color: '#f87171' }}>
                -₹{withdrawalsNum.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>Fund Payouts</div>
            </div>

            <div className="glass-panel" style={{ padding: '20px', background: 'rgba(168, 85, 247, 0.15)', border: '1px solid rgba(168, 85, 247, 0.4)', borderLeft: '4px solid #c084fc' }}>
              <div style={{ color: '#c084fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '8px' }}>6. FINAL CLOSING CAPITAL</div>
              <div style={{ fontSize: '24px', fontWeight: 900, color: 'white' }}>
                ₹{closingCapitalNum.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#c084fc', fontWeight: 700, marginTop: '4px' }}>Auto Formula Calculated</div>
            </div>

          </div>

          {/* Form to Edit Capital Baseline & Fund Flow Inputs */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '12px' }}>
              <DollarSign size={18} style={{ color: '#c084fc' }} />
              <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff' }}>Edit Capital Baseline & Fund Flow Inputs</h2>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  OPENING CAPITAL (₹)
                </label>
                <input 
                  type="number" 
                  step="100"
                  value={openingCapitalInput}
                  onChange={e => setOpeningCapitalInput(e.target.value)}
                  className="input-field"
                  placeholder="3933.52"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>Your starting account balance</div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  BROKER ADJUSTMENT VARIATION (₹)
                </label>
                <input 
                  type="number" 
                  step="0.01"
                  value={brokerAdjustmentInput}
                  onChange={e => setBrokerAdjustmentInput(e.target.value)}
                  className="input-field"
                  placeholder="0.00"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>DP charges, interest, manual variations (Set to 0 if none)</div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  DEPOSITS / ADDITIONAL CAPITAL (₹)
                </label>
                <input 
                  type="number" 
                  step="100"
                  value={depositsInput}
                  onChange={e => setDepositsInput(e.target.value)}
                  className="input-field"
                  placeholder="0"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>New funds added to trading account</div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  WITHDRAWALS (₹)
                </label>
                <input 
                  type="number" 
                  step="100"
                  value={withdrawalsInput}
                  onChange={e => setWithdrawalsInput(e.target.value)}
                  className="input-field"
                  placeholder="0"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>Funds withdrawn from broker account</div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  DAILY ROLLOVER RISK LIMIT (₹)
                </label>
                <input 
                  type="number" 
                  step="10"
                  value={dailyRiskLimitInput}
                  onChange={e => setDailyRiskLimitInput(e.target.value)}
                  className="input-field"
                  placeholder="250"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>Base daily risk limit (₹250/day)</div>
              </div>
            </div>
          </div>

          {/* Quick Link to Cloud Sync & Settings */}
          <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', background: 'rgba(99, 102, 241, 0.1)', border: '1px solid rgba(99, 102, 241, 0.25)', borderRadius: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Settings size={20} style={{ color: '#ec4899' }} />
              <div>
                <div style={{ fontSize: '13px', fontWeight: 800, color: '#ffffff' }}>Mobile App Cloud Synchronization & Server Settings</div>
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '2px' }}>Configure Render Cloud Mode, Local Wi-Fi connection, or sync data.</div>
              </div>
            </div>
            <button 
              onClick={() => setActiveTab('settings')}
              style={{ background: '#6366f1', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontWeight: 700, fontSize: '12px' }}
            >
              Open Settings Tab →
            </button>
          </div>

        </div>
      )}

      {/* Dedicated Application Settings & Cloud Synchronization Tab */}
      {activeTab === 'settings' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Settings Top Banner */}
          <div className="glass-panel" style={{ padding: '20px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', borderLeft: '4px solid #ec4899' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div style={{ background: 'rgba(236, 72, 153, 0.2)', padding: '10px', borderRadius: '10px', color: '#ec4899' }}>
                <Settings size={24} />
              </div>
              <div>
                <h2 style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>Application Settings & Synchronization Hub</h2>
                <div style={{ fontSize: '12px', color: '#a5b4fc', marginTop: '2px' }}>
                  Cloud database sync via Render, Local Wi-Fi pairing, 1000-Day Challenge risk rules, and master backups.
                </div>
              </div>
            </div>
            <button 
              onClick={() => handleSyncAll(null, false)}
              disabled={isSyncing}
              style={{ 
                background: serverStatus === 'online' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)', 
                border: `1px solid ${serverStatus === 'online' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)'}`,
                color: serverStatus === 'online' ? '#34d399' : '#f87171', 
                padding: '8px 16px', 
                borderRadius: '6px', 
                cursor: 'pointer', 
                fontWeight: 700,
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <RefreshCw size={14} className={isSyncing ? 'spin-icon' : ''} />
              {isSyncing ? 'Syncing...' : (serverStatus === 'online' ? '🟢 Cloud Online' : '🔴 Offline')}
            </button>
          </div>

          {/* Server Sync Configuration (For Mobile App Synchronization) */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px', borderLeft: '4px solid #34d399' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '12px', flexWrap: 'wrap', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {serverStatus === 'online' ? <Wifi size={20} style={{ color: '#34d399' }} /> : <WifiOff size={20} style={{ color: '#f87171' }} />}
                <div>
                  <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff' }}>Mobile App Synchronization Hub</h2>
                  <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '2px' }}>
                    Bidirectional real-time sync for Trades, SIP/MTF Portfolios & Capital Settings
                  </div>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {lastSyncedTime && (
                  <span style={{ fontSize: '11px', color: '#a5b4fc' }}>
                    Last synced: <strong style={{ color: '#ffffff' }}>{lastSyncedTime}</strong>
                  </span>
                )}
                <span style={{ 
                  fontSize: '11px', 
                  fontWeight: 800, 
                  background: serverStatus === 'online' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)', 
                  color: serverStatus === 'online' ? '#34d399' : '#f87171',
                  padding: '4px 10px',
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}>
                  <span style={{ height: '6px', width: '6px', borderRadius: '50%', background: serverStatus === 'online' ? '#34d399' : '#f87171' }} />
                  {serverStatus === 'online' ? 'Connected & Online' : 'Offline / Unreachable'}
                </span>
              </div>
            </div>

            {/* Detected Local PC IPs (Helper for Mobile App Setup) */}
            {detectedIps.length > 0 && (
              <div style={{ background: 'rgba(99, 102, 241, 0.1)', border: '1px solid rgba(99, 102, 241, 0.25)', borderRadius: '8px', padding: '14px' }}>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#a5b4fc', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Activity size={14} style={{ color: '#38bdf8' }} />
                  DETECTED PC SERVER IP ADDRESSES (Enter this into your Mobile App):
                </div>
                <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                  {detectedIps.map(ip => {
                    const fullUrl = `http://${ip}:8000`;
                    return (
                      <div key={ip} style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255, 255, 255, 0.1)', padding: '6px 12px', borderRadius: '6px' }}>
                        <code style={{ fontSize: '13px', fontWeight: 700, color: '#34d399' }}>{fullUrl}</code>
                        <button
                          type="button"
                          onClick={() => {
                            navigator.clipboard.writeText(fullUrl);
                            showToast(`Copied ${fullUrl} to clipboard!`);
                          }}
                          style={{ background: 'rgba(99, 102, 241, 0.3)', border: 'none', color: '#ffffff', padding: '4px 8px', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}
                        >
                          <Copy size={12} /> Copy
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setServerUrlInput(fullUrl);
                            handleSaveServerUrl();
                          }}
                          style={{ background: 'rgba(56, 189, 248, 0.2)', border: '1px solid rgba(56, 189, 248, 0.3)', color: '#38bdf8', padding: '4px 8px', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', fontWeight: 700 }}
                        >
                          Use this URL
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Mode Presets: Cloud Mode (Render) vs Local Wi-Fi */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
              <div 
                style={{ 
                  background: (serverUrl === 'https://finplus.onrender.com' || (!serverUrl && isNativeMobileApp)) ? 'rgba(99, 102, 241, 0.2)' : 'rgba(15, 23, 42, 0.5)', 
                  border: `1px solid ${(serverUrl === 'https://finplus.onrender.com' || (!serverUrl && isNativeMobileApp)) ? '#818cf8' : 'rgba(99, 102, 241, 0.2)'}`, 
                  borderRadius: '8px', 
                  padding: '14px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '13px', fontWeight: 800, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    ☁️ Cloud Mode (Render)
                  </span>
                  {(serverUrl === 'https://finplus.onrender.com' || (!serverUrl && isNativeMobileApp)) && (
                    <span style={{ fontSize: '10px', fontWeight: 800, color: '#34d399', background: 'rgba(16, 185, 129, 0.2)', padding: '2px 8px', borderRadius: '10px' }}>
                      ACTIVE
                    </span>
                  )}
                </div>
                <div style={{ fontSize: '11px', color: '#a5b4fc', lineHeight: '1.4' }}>
                  <strong>Ideal for traveling / anywhere:</strong> Syncs via <code>https://finplus.onrender.com</code> over 4G/5G mobile data or any Wi-Fi network worldwide.
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setServerUrlInput('https://finplus.onrender.com');
                    localStorage.setItem('finplus_server_url', 'https://finplus.onrender.com');
                    setServerUrl('https://finplus.onrender.com');
                    showToast('Switched to Cloud Mode (Render)! Connecting...');
                    handleSyncAll('https://finplus.onrender.com', false);
                  }}
                  style={{
                    background: '#6366f1',
                    color: 'white',
                    border: 'none',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontWeight: 700,
                    marginTop: '4px'
                  }}
                >
                  Use Cloud Mode (Render)
                </button>
              </div>

              <div 
                style={{ 
                  background: (serverUrl.includes('192.168.') || serverUrl.includes('10.') || serverUrl.includes('127.0.0.1') || serverUrl.includes('localhost')) ? 'rgba(16, 185, 129, 0.15)' : 'rgba(15, 23, 42, 0.5)', 
                  border: `1px solid ${(serverUrl.includes('192.168.') || serverUrl.includes('10.') || serverUrl.includes('127.0.0.1') || serverUrl.includes('localhost')) ? '#34d399' : 'rgba(99, 102, 241, 0.2)'}`, 
                  borderRadius: '8px', 
                  padding: '14px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '13px', fontWeight: 800, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    🏠 Local Wi-Fi Mode
                  </span>
                  {(serverUrl.includes('192.168.') || serverUrl.includes('10.') || serverUrl.includes('127.0.0.1') || serverUrl.includes('localhost')) && (
                    <span style={{ fontSize: '10px', fontWeight: 800, color: '#34d399', background: 'rgba(16, 185, 129, 0.2)', padding: '2px 8px', borderRadius: '10px' }}>
                      ACTIVE
                    </span>
                  )}
                </div>
                <div style={{ fontSize: '11px', color: '#a5b4fc', lineHeight: '1.4' }}>
                  <strong>Direct LAN connection:</strong> Connects directly to your PC when both devices are on the same home or office Wi-Fi network.
                </div>
                {detectedIps.length > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      const localTarget = `http://${detectedIps[0]}:8000`;
                      setServerUrlInput(localTarget);
                      localStorage.setItem('finplus_server_url', localTarget);
                      setServerUrl(localTarget);
                      showToast(`Switched to Local Wi-Fi Mode (${localTarget})!`);
                      handleSyncAll(localTarget, false);
                    }}
                    style={{
                      background: 'rgba(16, 185, 129, 0.25)',
                      border: '1px solid rgba(16, 185, 129, 0.5)',
                      color: '#34d399',
                      padding: '8px 12px',
                      borderRadius: '6px',
                      cursor: 'pointer',
                      fontSize: '12px',
                      fontWeight: 700,
                      marginTop: '4px'
                    }}
                  >
                    Use Local PC Wi-Fi (http://{detectedIps[0]}:8000)
                  </button>
                )}
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  ACTIVE BACKEND SERVER URL (Cloud or Local)
                </label>
                <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                  <input 
                    type="text" 
                    value={serverUrlInput}
                    onChange={e => setServerUrlInput(e.target.value)}
                    className="input-field"
                    style={{ flex: 1, minWidth: '220px' }}
                    placeholder="e.g. https://finplus.onrender.com or http://10.54.126.26:8000"
                  />
                  <button 
                    onClick={handleSaveServerUrl}
                    style={{ 
                      background: '#6366f1', 
                      color: 'white', 
                      border: 'none', 
                      padding: '10px 18px', 
                      borderRadius: '6px', 
                      cursor: 'pointer', 
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px'
                    }}
                  >
                    <Save size={15} />
                    Save & Connect
                  </button>
                  <button 
                    onClick={() => handleSyncAll(null, false)}
                    disabled={isSyncing}
                    style={{ 
                      background: 'rgba(16, 185, 129, 0.2)', 
                      border: '1px solid rgba(16, 185, 129, 0.4)',
                      color: '#34d399', 
                      padding: '10px 18px', 
                      borderRadius: '6px', 
                      cursor: 'pointer', 
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px'
                    }}
                  >
                    <RefreshCw size={15} className={isSyncing ? 'spin-icon' : ''} />
                    {isSyncing ? 'Syncing...' : 'Sync All Data Now'}
                  </button>
                </div>
                <div style={{ fontSize: '12px', color: '#a5b4fc', marginTop: '10px', lineHeight: '1.6' }}>
                  <strong>How to access your app from mobile while traveling:</strong>
                  <ul style={{ paddingLeft: '20px', marginTop: '4px' }}>
                    <li>Select <strong>Cloud Mode (Render)</strong> above or set URL to <code>https://finplus.onrender.com</code>.</li>
                    <li>The app communicates securely with your cloud backend hosted on Render over 4G/5G mobile internet.</li>
                    <li>All trades, portfolio additions, MTF positions, and capital settings sync automatically without needing to be on the same Wi-Fi.</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>

          {/* 1000-Day Challenge Risk & Baseline Settings Card */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px', borderLeft: '4px solid #6366f1' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '12px' }}>
              <DollarSign size={18} style={{ color: '#c084fc' }} />
              <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff' }}>Edit Capital Baseline & Challenge Risk Parameters</h2>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  OPENING CAPITAL (₹)
                </label>
                <input 
                  type="number" 
                  step="100"
                  value={openingCapitalInput}
                  onChange={e => setOpeningCapitalInput(e.target.value)}
                  className="input-field"
                  placeholder="3933.52"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>Your starting account balance</div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  BROKER ADJUSTMENT VARIATION (₹)
                </label>
                <input 
                  type="number" 
                  step="0.01"
                  value={brokerAdjustmentInput}
                  onChange={e => setBrokerAdjustmentInput(e.target.value)}
                  className="input-field"
                  placeholder="0.00"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>DP charges, interest, manual variations</div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  DEPOSITS / ADDITIONAL CAPITAL (₹)
                </label>
                <input 
                  type="number" 
                  step="100"
                  value={depositsInput}
                  onChange={e => setDepositsInput(e.target.value)}
                  className="input-field"
                  placeholder="0"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>New funds added to trading account</div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  WITHDRAWALS (₹)
                </label>
                <input 
                  type="number" 
                  step="100"
                  value={withdrawalsInput}
                  onChange={e => setWithdrawalsInput(e.target.value)}
                  className="input-field"
                  placeholder="0"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>Funds withdrawn from broker account</div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  DAILY ROLLOVER RISK LIMIT (₹)
                </label>
                <input 
                  type="number" 
                  step="10"
                  value={dailyRiskLimitInput}
                  onChange={e => setDailyRiskLimitInput(e.target.value)}
                  className="input-field"
                  placeholder="250"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>Base daily risk limit (₹250/day)</div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>
                  CHALLENGE START DATE
                </label>
                <input 
                  type="date" 
                  value={challengeStartDateInput}
                  onChange={e => setChallengeStartDateInput(e.target.value)}
                  className="input-field"
                />
                <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>1000-Day Challenge start date</div>
              </div>
            </div>
          </div>

          {/* Backup & Data Transfer Center */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px', borderLeft: '4px solid #14b8a6' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '12px' }}>
              <FileText size={18} style={{ color: '#14b8a6' }} />
              <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff' }}>Data Backup & Master Export / Import</h2>
            </div>
            
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
              <button 
                onClick={handleExportJson}
                style={{
                  background: 'rgba(16, 185, 129, 0.15)',
                  border: '1px solid rgba(16, 185, 129, 0.35)',
                  color: '#34d399',
                  padding: '10px 18px',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  fontWeight: 700,
                  fontSize: '13px'
                }}
              >
                <Download size={16} />
                Export Journal (.json)
              </button>

              <label 
                style={{
                  background: 'rgba(99, 102, 241, 0.15)',
                  border: '1px solid rgba(99, 102, 241, 0.35)',
                  color: '#a5b4fc',
                  padding: '10px 18px',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  fontWeight: 700,
                  fontSize: '13px'
                }}
              >
                <Upload size={16} />
                Restore Journal (.json)
                <input type="file" accept=".json" onChange={handleImportJsonFile} style={{ display: 'none' }} />
              </label>

              <button 
                onClick={() => exportJournalCSV(trades)}
                style={{
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  color: '#cbd5e1',
                  padding: '10px 18px',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  fontWeight: 600,
                  fontSize: '13px'
                }}
              >
                <FileText size={16} />
                Export CSV (.csv)
              </button>
            </div>
          </div>

          {/* Segment-Wise Risk & Stop-Loss Guidelines Table */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px', borderLeft: '4px solid #6366f1' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <ShieldAlert size={20} style={{ color: '#818cf8' }} />
                <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff' }}>Segment-Wise Stop-Loss & Risk Management Matrix</h2>
              </div>
              <span style={{ fontSize: '11px', fontWeight: 700, color: '#818cf8', background: 'rgba(99, 102, 241, 0.15)', padding: '4px 10px', borderRadius: '12px', border: '1px solid rgba(99, 102, 241, 0.3)' }}>
                Recommended Strategy
              </span>
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)', color: '#a5b4fc', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    <th style={{ padding: '12px 16px' }}>Segment / Asset Class</th>
                    <th style={{ padding: '12px 16px' }}>Ideal Stop-Loss (% of Asset Price)</th>
                    <th style={{ padding: '12px 16px' }}>Recommended Risk per Trade</th>
                    <th style={{ padding: '12px 16px' }}>Key Strategy Notes</th>
                  </tr>
                </thead>
                <tbody style={{ color: '#e0e7ff' }}>
                  <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)', background: 'rgba(255, 255, 255, 0.02)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: 700, color: '#38bdf8' }}>Intraday Equities</td>
                    <td style={{ padding: '14px 16px' }}>
                      <span style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '4px 8px', borderRadius: '6px', fontWeight: 700 }}>
                        0.5% to 1.0%
                      </span>
                    </td>
                    <td style={{ padding: '14px 16px', fontWeight: 600 }}>Max 1% of total trading capital</td>
                    <td style={{ padding: '14px 16px', color: '#94a3b8', fontSize: '12px' }}>Tight risk control; close all positions before 3:15 PM</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: 700, color: '#34d399' }}>Delivery / Swing Trading</td>
                    <td style={{ padding: '14px 16px' }}>
                      <span style={{ background: 'rgba(52, 211, 153, 0.15)', color: '#34d399', padding: '4px 8px', borderRadius: '6px', fontWeight: 700 }}>
                        5.0% to 7.0%
                      </span>
                    </td>
                    <td style={{ padding: '14px 16px', fontWeight: 600 }}>Max 2% of total trading capital</td>
                    <td style={{ padding: '14px 16px', color: '#94a3b8', fontSize: '12px' }}>Allows room for market volatility & multi-day trends</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)', background: 'rgba(255, 255, 255, 0.02)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: 700, color: '#fb923c' }}>Crude Oil Futures</td>
                    <td style={{ padding: '14px 16px' }}>
                      <span style={{ background: 'rgba(251, 146, 60, 0.15)', color: '#fb923c', padding: '4px 8px', borderRadius: '6px', fontWeight: 700 }}>
                        0.8% to 1.2%
                      </span>
                    </td>
                    <td style={{ padding: '14px 16px', fontWeight: 600 }}>Fixed capital risk (e.g., ₹3,000–₹5,000)</td>
                    <td style={{ padding: '14px 16px', color: '#94a3b8', fontSize: '12px' }}>MCX high leverage; monitor inventory EIA data</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: 700, color: '#ef4444' }}>Natural Gas Futures</td>
                    <td style={{ padding: '14px 16px' }}>
                      <span style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', padding: '4px 8px', borderRadius: '6px', fontWeight: 700 }}>
                        1.5% to 2.5%
                      </span>
                    </td>
                    <td style={{ padding: '14px 16px', fontWeight: 600 }}>Fixed capital risk (extreme volatility)</td>
                    <td style={{ padding: '14px 16px', color: '#94a3b8', fontSize: '12px' }}>Extreme intraday gaps & spikes; use strict position sizing</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)', background: 'rgba(255, 255, 255, 0.02)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: 700, color: '#a855f7' }}>Stock Options (F&O)</td>
                    <td style={{ padding: '14px 16px' }}>
                      <span style={{ background: 'rgba(168, 85, 247, 0.15)', color: '#c084fc', padding: '4px 8px', borderRadius: '6px', fontWeight: 700 }}>
                        10.0% to 20.0% of premium
                      </span>
                    </td>
                    <td style={{ padding: '14px 16px', fontWeight: 600 }}>Max 2% to 3% of option capital</td>
                    <td style={{ padding: '14px 16px', color: '#94a3b8', fontSize: '12px' }}>Zerodha Kite F&O rate: ₹20/order brokerage, 0.1% STT on sell premium</td>
                  </tr>
                  <tr style={{ background: 'rgba(255, 255, 255, 0.02)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: 700, color: '#c084fc' }}>Nifty Options (Buyers)</td>
                    <td style={{ padding: '14px 16px' }}>
                      <span style={{ background: 'rgba(192, 132, 252, 0.15)', color: '#c084fc', padding: '4px 8px', borderRadius: '6px', fontWeight: 700 }}>
                        15.0% to 20.0% of premium
                      </span>
                    </td>
                    <td style={{ padding: '14px 16px', fontWeight: 600 }}>Max 2% to 3% of option buying pool</td>
                    <td style={{ padding: '14px 16px', color: '#94a3b8', fontSize: '12px' }}>Protect against theta decay; slice risk relative to option capital</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

        </div>
      )}

      {/* Auto Segment Capital Allocation & Monthly Stop-Loss Manager Tab */}
      {activeTab === 'capital' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Executive Overview Header Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
            <div className="glass-panel" style={{ padding: '20px', borderLeft: '4px solid #10b981' }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '8px' }}>
                TOTAL ACCOUNT CAPITAL
              </div>
              <div style={{ fontSize: '24px', fontWeight: 900, color: '#ffffff' }}>
                ₹{((closingCapitalNum > 0 ? closingCapitalNum : openingCapitalNum)).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#34d399', marginTop: '4px', fontWeight: 700 }}>
                100% Capital Pool Baseline
              </div>
            </div>

            <div className="glass-panel" style={{ padding: '20px', borderLeft: '4px solid #6366f1' }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '8px' }}>
                TOTAL MONTHLY RISK BUDGET
              </div>
              <div style={{ fontSize: '24px', fontWeight: 900, color: '#818cf8' }}>
                ₹{totalMonthlyRiskBudget.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>
                Combined Segment Max Stop-Loss Limits
              </div>
            </div>

            <div className="glass-panel" style={{ padding: '20px', borderLeft: `4px solid ${currentMonthTotalPnl >= 0 ? '#10b981' : '#fb7185'}` }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '8px' }}>
                AUDITED MONTH REALIZED P&L
              </div>
              <div style={{ fontSize: '24px', fontWeight: 900, color: currentMonthTotalPnl > 0 ? '#34d399' : (currentMonthTotalPnl < 0 ? '#fb7185' : '#ffffff') }}>
                {currentMonthTotalPnl >= 0 ? '+' : ''}₹{currentMonthTotalPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>
                {selectedMonthClosedTrades.length} Closed Trades Audited
              </div>
            </div>

            <div className="glass-panel" style={{ padding: '20px', borderLeft: `4px solid ${breachedSegmentsCount > 0 ? '#fb7185' : '#34d399'}`, background: breachedSegmentsCount > 0 ? 'rgba(251, 113, 133, 0.05)' : 'rgba(52, 211, 153, 0.05)' }}>
              <div style={{ color: breachedSegmentsCount > 0 ? '#fb7185' : '#34d399', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '8px' }}>
                MONTHLY BREACH PROTECTION
              </div>
              <div style={{ fontSize: '24px', fontWeight: 900, color: breachedSegmentsCount > 0 ? '#fb7185' : '#ffffff' }}>
                {breachedSegmentsCount > 0 ? `${breachedSegmentsCount} LIMIT EXCEEDED` : 'ALL SAFE'}
              </div>
              <div style={{ fontSize: '11px', color: breachedSegmentsCount > 0 ? '#fb7185' : '#34d399', fontWeight: 700, marginTop: '4px' }}>
                {breachedSegmentsCount > 0 ? 'Risk limit reached for segment' : 'All segments within monthly SL limits'}
              </div>
            </div>
          </div>

          {/* UNIFIED RISK STACK VISUALIZER & BINDING CONSTRAINT CARD */}
          <div className="glass-panel" style={{ padding: '24px', background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(30, 41, 59, 0.8) 100%)', border: '1px solid rgba(99, 102, 241, 0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <ShieldAlert size={20} style={{ color: bindingConstraintLevel !== 'none' ? '#fb7185' : '#34d399' }} />
                <span style={{ fontSize: '15px', fontWeight: 800, color: '#ffffff', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  🛡️ Unified Multi-Layer Risk Stack & Active Constraint
                </span>
              </div>

              {/* Binding Constraint Badge */}
              <div style={{
                background: bindingConstraintLevel === 'daily' ? 'rgba(239, 68, 68, 0.2)' : (bindingConstraintLevel === 'segment' ? 'rgba(245, 158, 11, 0.2)' : 'rgba(16, 185, 129, 0.15)'),
                border: `1px solid ${bindingConstraintLevel === 'daily' ? '#ef4444' : (bindingConstraintLevel === 'segment' ? '#f59e0b' : '#10b981')}`,
                color: bindingConstraintLevel === 'daily' ? '#f87171' : (bindingConstraintLevel === 'segment' ? '#fbbf24' : '#34d399'),
                padding: '6px 14px',
                borderRadius: '8px',
                fontSize: '12px',
                fontWeight: 800,
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}>
                {bindingConstraintLabel}
              </div>
            </div>

            {/* Multi-Layer Risk Stack Bar */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#a5b4fc', fontWeight: 700, flexWrap: 'wrap', gap: '8px' }}>
                <span>Layer 1: Today's Available Risk (₹{availableRiskLimitToday.toFixed(2)})</span>
                <span>Layer 2: Monthly Segment Risk Budget (₹{totalMonthlyRiskBudget.toFixed(2)})</span>
                <span>Layer 3: Total Account Capital (₹{((closingCapitalNum > 0 ? closingCapitalNum : openingCapitalNum)).toFixed(2)})</span>
              </div>

              {/* Visual Stack Progress Bar */}
              <div style={{ position: 'relative', width: '100%', height: '24px', background: 'rgba(255,255,255,0.06)', borderRadius: '12px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.1)' }}>
                {/* Outer Layer: Capital Pool Background (100%) */}
                <div style={{ position: 'absolute', top: 0, left: 0, height: '100%', width: '100%', background: 'rgba(99, 102, 241, 0.15)' }} />

                {/* Middle Layer: Monthly Segment Risk Budget Bar */}
                <div style={{ 
                  position: 'absolute', 
                  top: 0, 
                  left: 0, 
                  height: '100%', 
                  width: `${Math.min(100, (totalMonthlyRiskBudget / Math.max(1, (closingCapitalNum > 0 ? closingCapitalNum : openingCapitalNum))) * 100)}%`, 
                  background: 'linear-gradient(90deg, rgba(99, 102, 241, 0.5) 0%, rgba(168, 85, 247, 0.5) 100%)' 
                }} />

                {/* Inner Layer: Today's Available Risk Bar */}
                <div style={{ 
                  position: 'absolute', 
                  top: 0, 
                  left: 0, 
                  height: '100%', 
                  width: `${Math.min(100, (todayStartingRisk / Math.max(1, (closingCapitalNum > 0 ? closingCapitalNum : openingCapitalNum))) * 100)}%`, 
                  background: availableRiskLimitToday > 0 ? 'linear-gradient(90deg, #10b981 0%, #34d399 100%)' : '#ef4444',
                  boxShadow: availableRiskLimitToday > 0 ? '0 0 12px rgba(52, 211, 153, 0.6)' : 'none'
                }} />
              </div>

              {/* Stack Legend & Context */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', marginTop: '4px' }}>
                <div style={{ fontSize: '11px', color: '#a5b4fc', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ height: '10px', width: '10px', borderRadius: '50%', background: availableRiskLimitToday > 0 ? '#10b981' : '#ef4444', display: 'inline-block' }}></span>
                  Today's Budget: <strong>₹{todayStartingRisk.toFixed(2)}</strong> (Used: ₹{todayCurrentLoss.toFixed(2)})
                </div>
                <div style={{ fontSize: '11px', color: '#a5b4fc', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ height: '10px', width: '10px', borderRadius: '50%', background: '#818cf8', display: 'inline-block' }}></span>
                  Monthly Segment Cap: <strong>₹{totalMonthlyRiskBudget.toFixed(2)}</strong>
                </div>
                <div style={{ fontSize: '11px', color: '#a5b4fc', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ height: '10px', width: '10px', borderRadius: '50%', background: '#6366f1', display: 'inline-block' }}></span>
                  Account Capital: <strong>₹{((closingCapitalNum > 0 ? closingCapitalNum : openingCapitalNum)).toFixed(2)}</strong>
                </div>
              </div>
            </div>
          </div>

          {/* Main Segment Monthly Stop-Loss & Capital Allocation Table */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '12px', flexWrap: 'wrap', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <ShieldAlert size={22} style={{ color: '#38bdf8' }} />
                <div>
                  <h2 style={{ fontSize: '18px', fontWeight: 800, color: '#ffffff' }}>Segment Capital Allocation & Monthly Stop-Loss Control</h2>
                  <p style={{ fontSize: '12px', color: '#a5b4fc', margin: 0 }}>
                    Auto-computed capital pool and monthly maximum loss thresholds per segment based on your profitability ranking.
                  </p>
                </div>
              </div>

              {/* Historical Month Selector for Risk SL Audit */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', background: 'rgba(255,255,255,0.03)', padding: '6px 14px', borderRadius: '10px', border: '1px solid rgba(99, 102, 241, 0.2)' }}>
                <Calendar size={16} style={{ color: '#38bdf8' }} />
                <span style={{ fontSize: '12px', fontWeight: 700, color: '#a5b4fc' }}>Audit Month:</span>
                <select 
                  value={selectedRiskMonth} 
                  onChange={e => setSelectedRiskMonth(e.target.value)} 
                  className="input-field"
                  style={{ width: '150px', padding: '4px 10px', fontSize: '12px', fontWeight: 800, color: '#38bdf8' }}
                >
                  {availableClosedMonths.map(mStr => {
                    const [yr, mo] = mStr.split('-');
                    const dObj = new Date(parseInt(yr), parseInt(mo) - 1, 1);
                    const label = dObj.toLocaleString('default', { month: 'short', year: 'numeric' });
                    return <option key={mStr} value={mStr}>{label} {mStr === currentYearMonthStr ? '(Active)' : ''}</option>;
                  })}
                </select>
              </div>
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)', color: '#a5b4fc', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    <th style={{ padding: '12px 14px' }}>Segment / Rank & Empirical Stats</th>
                    <th style={{ padding: '12px 14px' }}>Allocation %</th>
                    <th style={{ padding: '12px 14px' }}>Segment Capital Pool (₹)</th>
                    <th style={{ padding: '12px 14px' }}>Monthly SL %</th>
                    <th style={{ padding: '12px 14px' }}>Monthly Max Loss SL (₹)</th>
                    <th style={{ padding: '12px 14px' }}>Audited Month PnL (₹)</th>
                    <th style={{ padding: '12px 14px' }}>Risk Used & Status</th>
                  </tr>
                </thead>
                <tbody style={{ color: '#e0e7ff' }}>
                  {segmentAllocList.map((seg, idx) => {
                    const capitalPool = (closingCapitalNum > 0 ? closingCapitalNum : openingCapitalNum);
                    const allocPct = Number(seg.allocState) || 0;
                    const segCapital = capitalPool * (allocPct / 100);
                    const mslPct = Number(seg.mslState) || 0;
                    const monthlyMaxLoss = segCapital * (mslPct / 100);
                    const monthPnl = seg.currentPnl;
                    const lossUsed = monthPnl < 0 ? Math.abs(monthPnl) : 0;
                    const usedPct = monthlyMaxLoss > 0 ? (lossUsed / monthlyMaxLoss) * 100 : 0;
                    const isBreached = monthlyMaxLoss > 0 && lossUsed >= monthlyMaxLoss;
                    const isWarning = !isBreached && usedPct >= 50;

                    return (
                      <tr key={idx} style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)', background: isBreached ? 'rgba(251, 113, 133, 0.03)' : (idx % 2 === 0 ? 'rgba(255, 255, 255, 0.02)' : 'transparent') }}>
                        <td style={{ padding: '14px' }}>
                          <div style={{ fontWeight: 800, color: seg.color, fontSize: '14px' }}>{seg.name}</div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px', flexWrap: 'wrap' }}>
                            <span style={{ background: `${seg.color}25`, color: seg.color, padding: '2px 6px', borderRadius: '4px', fontSize: '10px', fontWeight: 800 }}>
                              {seg.rank}
                            </span>
                            <span style={{ fontSize: '11px', color: '#94a3b8' }}>{seg.rationale}</span>
                          </div>

                          {/* Empirical Stats Badges */}
                          <div style={{ display: 'flex', gap: '6px', marginTop: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
                            {seg.stats.totalCount < 3 ? (
                              <span style={{ fontSize: '10px', background: 'rgba(255,255,255,0.06)', color: '#94a3b8', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>
                                📊 Insufficient Data ({seg.stats.totalCount}/3 trades)
                              </span>
                            ) : (
                              <>
                                <span style={{ fontSize: '10px', background: 'rgba(52, 211, 153, 0.15)', color: '#34d399', padding: '2px 6px', borderRadius: '4px', fontWeight: 800 }}>
                                  Win Rate: {seg.stats.winRate}%
                                </span>
                                <span style={{ fontSize: '10px', background: 'rgba(168, 85, 247, 0.15)', color: '#c084fc', padding: '2px 6px', borderRadius: '4px', fontWeight: 800 }}>
                                  PF: {seg.stats.profitFactor}
                                </span>
                                <span style={{ fontSize: '10px', background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '2px 6px', borderRadius: '4px', fontWeight: 800 }}>
                                  R:R: 1:{seg.stats.riskRewardRatio}
                                </span>
                                <span style={{ fontSize: '10px', color: '#94a3b8' }}>
                                  ({seg.stats.totalCount} T)
                                </span>
                              </>
                            )}
                          </div>
                        </td>

                        <td style={{ padding: '14px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input 
                              type="number" 
                              step="0.5" 
                              value={seg.allocState} 
                              onChange={e => seg.setAllocState(e.target.value)} 
                              className="input-field" 
                              style={{ width: '65px', padding: '4px 8px', fontSize: '13px', fontWeight: 800, textAlign: 'center', color: seg.color }}
                            />
                            <span style={{ fontWeight: 800, color: seg.color }}>%</span>
                          </div>
                        </td>

                        <td style={{ padding: '14px', fontWeight: 800, color: '#ffffff', fontSize: '15px' }}>
                          ₹{segCapital.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>

                        <td style={{ padding: '14px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input 
                              type="number" 
                              step="1" 
                              value={seg.mslState} 
                              onChange={e => seg.setMslState(e.target.value)} 
                              className="input-field" 
                              style={{ width: '60px', padding: '4px 8px', fontSize: '13px', fontWeight: 800, textAlign: 'center', color: '#cbd5e1' }}
                            />
                            <span style={{ fontWeight: 800, color: '#a5b4fc' }}>%</span>
                          </div>
                        </td>

                        <td style={{ padding: '14px', fontWeight: 800, color: '#cbd5e1', fontSize: '15px' }}>
                          ₹{monthlyMaxLoss.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>

                        <td style={{ padding: '14px', fontWeight: 800, fontSize: '14px', color: monthPnl > 0 ? '#34d399' : (monthPnl < 0 ? '#fb7185' : '#ffffff') }}>
                          {monthPnl >= 0 ? '+' : ''}₹{monthPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>

                        <td style={{ padding: '14px' }}>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                              <span style={{ fontSize: '11px', fontWeight: 800, color: isBreached ? '#fb7185' : (isWarning ? '#fde047' : '#34d399') }}>
                                {isBreached ? '🛑 Risk Limit Reached' : (isWarning ? '⚠️ HIGH RISK WARNING' : '🟢 SAFE')}
                              </span>
                              <span style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700 }}>
                                {usedPct.toFixed(0)}% Used
                              </span>
                            </div>

                            {/* Risk Usage Progress Bar */}
                            <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden' }}>
                              <div style={{ 
                                width: `${Math.min(100, usedPct)}%`, 
                                height: '100%', 
                                background: isBreached ? '#fb7185' : (isWarning ? '#fde047' : '#34d399'),
                                transition: 'width 0.3s ease'
                              }} />
                            </div>

                            <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '2px' }}>
                              {isBreached ? `Loss exceeds ₹${monthlyMaxLoss.toFixed(0)} limit!` : `Remaining Risk Buffer: ₹${Math.max(0, monthlyMaxLoss - lossUsed).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`}
                            </div>
                          </div>
                        </td>
                      </tr>
                    );
                  })}

                  {/* Summary Row for Unallocated Cash Reserve if total allocation < 100% */}
                  {(() => {
                    const capitalPool = (closingCapitalNum > 0 ? closingCapitalNum : openingCapitalNum);
                    const totalAllocPct = (Number(allocIntraday) || 0) + (Number(allocNatgas) || 0) + (Number(allocNifty) || 0) + (Number(allocCrude) || 0);
                    const unallocatedPct = 100 - totalAllocPct;
                    const unallocatedRupees = capitalPool * (Math.max(0, unallocatedPct) / 100);

                    if (unallocatedPct > 0.01) {
                      return (
                        <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.08)', background: 'rgba(255, 255, 255, 0.02)' }}>
                          <td style={{ padding: '14px' }}>
                            <div style={{ fontWeight: 800, color: '#94a3b8', fontSize: '13px' }}>💵 Unallocated Cash Reserve</div>
                            <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>Unassigned capital pool retained as unhedged cash buffer</div>
                          </td>
                          <td style={{ padding: '14px', fontWeight: 800, color: '#94a3b8', fontSize: '13px' }}>
                            {unallocatedPct.toFixed(1)}%
                          </td>
                          <td style={{ padding: '14px', fontWeight: 800, color: '#94a3b8', fontSize: '14px' }}>
                            ₹{unallocatedRupees.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </td>
                          <td colSpan={4} style={{ padding: '14px', fontSize: '11px', color: '#64748b' }}>
                            {totalAllocPct.toFixed(1)}% Assigned across 4 segments | ₹{unallocatedRupees.toFixed(2)} held as cash reserve
                          </td>
                        </tr>
                      );
                    }
                    if (totalAllocPct > 100) {
                      return (
                        <tr style={{ borderBottom: '1px solid rgba(239, 68, 68, 0.2)', background: 'rgba(239, 68, 68, 0.05)' }}>
                          <td colSpan={7} style={{ padding: '12px 14px', color: '#f87171', fontSize: '12px', fontWeight: 700 }}>
                            ⚠️ Warning: Total segment capital allocation exceeds 100% ({totalAllocPct}% assigned). Please adjust segment percentages to sum to 100%.
                          </td>
                        </tr>
                      );
                    }
                    return null;
                  })()}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      )}

      {/* Dynamic 5% Pullback SIP & Investment System Tab */}
      {activeTab === 'sip' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Top Executive Overview Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
            <div className="glass-panel" style={{ padding: '18px', borderLeft: '4px solid #00b4d8' }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                TOTAL AMOUNT INVESTED
              </div>
              <div style={{ fontSize: '22px', fontWeight: 900, color: '#ffffff' }}>
                ₹{totalSipDeployedCost.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>
                Active open positions cost basis
              </div>
            </div>

            <div className="glass-panel" style={{ padding: '18px', borderLeft: '4px solid #10b981' }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                CURRENT PORTFOLIO VALUE
              </div>
              <div style={{ fontSize: '22px', fontWeight: 900, color: '#34d399' }}>
                ₹{totalSipCurrentVal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#34d399', marginTop: '4px', fontWeight: 700 }}>
                +{pullbackStockSummary.filter(s => s.netShares > 0).length} stock(s) with open positions
              </div>
            </div>

            <div className="glass-panel" style={{ padding: '18px', borderLeft: `4px solid ${totalSipRealizedProfit >= 0 ? '#10b981' : '#fb7185'}` }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                REALIZED P&L (SOLD STOCKS)
              </div>
              <div style={{ fontSize: '22px', fontWeight: 900, color: totalSipRealizedProfit >= 0 ? '#34d399' : '#fb7185' }}>
                {totalSipRealizedProfit >= 0 ? '+' : ''}₹{totalSipRealizedProfit.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>
                {totalSipSellTxCount} sold trade(s) | Net: <span style={{ color: totalSipRealizedNetProfit >= 0 ? '#34d399' : '#fb7185', fontWeight: 800 }}>{totalSipRealizedNetProfit >= 0 ? '+' : ''}₹{totalSipRealizedNetProfit.toFixed(2)}</span>
              </div>
            </div>

            <div className="glass-panel" style={{ padding: '18px', borderLeft: `4px solid ${totalSipUnrealizedPnl >= 0 ? '#10b981' : '#fb7185'}` }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                UNREALIZED PORTFOLIO P&L
              </div>
              <div style={{ fontSize: '22px', fontWeight: 900, color: totalSipUnrealizedPnl >= 0 ? '#34d399' : '#fb7185' }}>
                {totalSipUnrealizedPnl >= 0 ? '+' : ''}₹{totalSipUnrealizedPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: totalSipUnrealizedPnl >= 0 ? '#34d399' : '#fb7185', marginTop: '4px', fontWeight: 700 }}>
                Gross: {totalSipDeployedCost > 0 ? `${totalSipUnrealizedPnl >= 0 ? '+' : ''}${((totalSipUnrealizedPnl / totalSipDeployedCost) * 100).toFixed(2)}%` : '0.00%'}
              </div>
            </div>

            <div className="glass-panel" style={{ padding: '18px', borderLeft: '4px solid #f59e0b' }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                ZERODHA TAXES & CHARGES
              </div>
              <div style={{ fontSize: '22px', fontWeight: 900, color: '#fbbf24' }}>
                ₹{totalSipDeliveryTaxes.toFixed(2)}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>
                STT: ₹{totalSipStt.toFixed(2)} | DP: ₹{totalSipDpCharges.toFixed(2)} | Txn+GST: ₹{(totalSipExchangeTxn + totalSipGst).toFixed(2)}
              </div>
            </div>

            <div className="glass-panel" style={{ padding: '18px', borderLeft: `4px solid ${totalSipCombinedNetPnl >= 0 ? '#10b981' : '#fb7185'}` }}>
              <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                COMBINED NET SIP P&L
              </div>
              <div style={{ fontSize: '22px', fontWeight: 900, color: totalSipCombinedNetPnl >= 0 ? '#34d399' : '#fb7185' }}>
                {totalSipCombinedNetPnl >= 0 ? '+' : ''}₹{totalSipCombinedNetPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px', fontWeight: 700 }}>
                Realized ({totalSipRealizedProfit >= 0 ? '+' : ''}₹{totalSipRealizedProfit.toFixed(1)}) + Unrealized ({totalSipUnrealizedPnl >= 0 ? '+' : ''}₹{totalSipUnrealizedPnl.toFixed(1)}) − Tax
              </div>
            </div>
          </div>

          {/* 5% Pullback Trigger Signals Panel */}
          {pullbackStockSummary.filter(s => (s.netShares > 0 || (pullbackData[s.ticker] && pullbackData[s.ticker].in_watchlist !== false)) && s.category !== 'Park' && (s.pullbackPct >= 5.0 || s.daysSinceLastBuyNum >= 25 || s.signalClass === 'buy' || s.signalClass === 'timeout')).length > 0 && (
            <div className="glass-panel" style={{ padding: '20px', background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                <TrendingUp size={20} style={{ color: '#34d399' }} />
                <h3 style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff', margin: 0 }}>
                  🚨 Active 5% Pullback & Time-Out Buy Signals
                </h3>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
                {pullbackStockSummary.filter(s => (s.netShares > 0 || (pullbackData[s.ticker] && pullbackData[s.ticker].in_watchlist !== false)) && s.category !== 'Park' && (s.pullbackPct >= 5.0 || s.daysSinceLastBuyNum >= 25 || s.signalClass === 'buy' || s.signalClass === 'timeout')).map(s => (
                  <div key={s.ticker} style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255,255,255,0.1)', padding: '12px 16px', borderRadius: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div style={{ fontWeight: 800, color: '#ffffff', fontSize: '14px' }}>{s.cleanSym} ({s.name})</div>
                      <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '2px' }}>
                        Peak: ₹{s.peak.toFixed(2)} | LTP: ₹{s.ltp.toFixed(2)} ({s.pullbackPct.toFixed(1)}% drop) | Target Buy: ₹{s.targetBuyPrice.toFixed(2)}
                      </div>
                    </div>
                    <span style={{ 
                      fontSize: '11px', 
                      fontWeight: 800, 
                      padding: '4px 10px', 
                      borderRadius: '6px', 
                      background: s.signalClass === 'buy' ? 'rgba(52, 211, 153, 0.2)' : (s.signalClass === 'timeout' ? 'rgba(251, 146, 60, 0.2)' : 'rgba(245, 158, 11, 0.2)'),
                      color: s.signalClass === 'buy' ? '#34d399' : (s.signalClass === 'timeout' ? '#fb923c' : '#fde047'),
                      border: `1px solid ${s.signalClass === 'buy' ? '#34d399' : (s.signalClass === 'timeout' ? '#fb923c' : '#fde047')}`
                    }}>
                      {s.systemStatus}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Record SIP Transaction & Watchlist Management Section */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            
            {/* Mode Switcher: Buy / Add Watchlist vs Sell / Exit Stock */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Activity size={18} style={{ color: '#38bdf8' }} />
                <h3 style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff', margin: 0 }}>
                  ⚙️ SIP Transaction Management
                </h3>
              </div>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  type="button"
                  onClick={() => setSipFormMode('BUY')}
                  style={{
                    background: sipFormMode === 'BUY' ? '#10b981' : 'rgba(255,255,255,0.06)',
                    color: '#ffffff',
                    border: `1px solid ${sipFormMode === 'BUY' ? '#34d399' : 'rgba(255,255,255,0.1)'}`,
                    padding: '8px 16px',
                    borderRadius: '8px',
                    fontWeight: 800,
                    fontSize: '12px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    transition: 'all 0.2s ease'
                  }}
                >
                  <PlusCircle size={14} />
                  🛒 Buy / Add Stock
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setSipFormMode('SELL');
                    const firstHeld = pullbackStockSummary.find(s => s.netShares > 0);
                    if (firstHeld && !sipSellSelectedTicker) {
                      setSipSellSelectedTicker(firstHeld.ticker);
                      setSipSellFormPrice(firstHeld.ltp > 0 ? String(firstHeld.ltp) : '');
                      setSipSellFormShares('1');
                    }
                  }}
                  style={{
                    background: sipFormMode === 'SELL' ? '#f59e0b' : 'rgba(255,255,255,0.06)',
                    color: '#ffffff',
                    border: `1px solid ${sipFormMode === 'SELL' ? '#fbbf24' : 'rgba(255,255,255,0.1)'}`,
                    padding: '8px 16px',
                    borderRadius: '8px',
                    fontWeight: 800,
                    fontSize: '12px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    transition: 'all 0.2s ease'
                  }}
                >
                  <DollarSign size={14} />
                  💰 Sell / Record Sold Stock
                </button>
              </div>
            </div>

            {/* FORM A: BUY / ADD WATCHLIST */}
            {sipFormMode === 'BUY' && (
              <form id="sip-watchlist-form" onSubmit={handleAddStockToWatchlist} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div style={{ position: 'relative' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700 }}>
                      SEARCH NIFTY 500 TICKER / COMPANY
                    </label>
                    {filteredNiftySuggestions.length > 0 && newSipTicker.trim() && (
                      <span style={{ fontSize: '10px', color: '#38bdf8', fontWeight: 800, background: 'rgba(56, 189, 248, 0.12)', padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(56, 189, 248, 0.2)' }}>
                        ✨ Match: {filteredNiftySuggestions[0].symbol.toUpperCase().replace('.NS', '')}.NS
                      </span>
                    )}
                  </div>
                  <input 
                    type="text" 
                    placeholder="Type company or ticker (e.g. SBI, Tata Steel, Reliance, INFY)" 
                    value={newSipTicker} 
                    onChange={e => {
                      setNewSipTicker(e.target.value);
                      setShowNiftyDropdown(true);
                    }}
                    onFocus={() => setShowNiftyDropdown(true)}
                    className="input-field" 
                    required 
                  />
                  
                  {/* Autocomplete Dropdown List */}
                  {showNiftyDropdown && filteredNiftySuggestions.length > 0 && (
                    <div style={{
                      position: 'absolute',
                      top: '100%',
                      left: 0,
                      right: 0,
                      zIndex: 9999,
                      background: '#0f172a',
                      border: '1px solid rgba(99, 102, 241, 0.4)',
                      borderRadius: '8px',
                      maxHeight: '220px',
                      overflowY: 'auto',
                      boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                      marginTop: '4px'
                    }}>
                      {filteredNiftySuggestions.map(item => {
                        const cleanSym = item.symbol.toUpperCase().replace('.NS', '');
                        const formattedSym = `${cleanSym}.NS`;
                        const isItemEtf = item.isEtf || cleanSym.endsWith('BEES') || cleanSym.endsWith('ETF') || (item.name && item.name.toLowerCase().includes('etf'));
                        return (
                          <div 
                            key={item.symbol} 
                            onClick={() => {
                              setNewSipTicker(formattedSym);
                              setNewSipName(item.name || item.symbol);
                              if (isItemEtf) {
                                setNewSipCategory('Park');
                              }
                              const ltp = liveLtps[cleanSym] || liveLtps[formattedSym];
                              if (ltp) setNewSipBuyPrice(String(ltp));
                              setShowNiftyDropdown(false);
                            }}
                            style={{
                              padding: '10px 14px',
                              borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
                              cursor: 'pointer',
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center'
                            }}
                            onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(99, 102, 241, 0.2)'}
                            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                          >
                            <div>
                              <div style={{ fontWeight: 800, color: isItemEtf ? '#38bdf8' : '#ffffff', fontSize: '13px' }}>
                                {formattedSym}
                              </div>
                              <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                                {item.name || item.symbol}
                              </div>
                            </div>
                            <span style={{
                              fontSize: '10px',
                              color: isItemEtf ? '#38bdf8' : '#34d399',
                              fontWeight: 800,
                              background: isItemEtf ? 'rgba(56, 189, 248, 0.15)' : 'rgba(52, 211, 153, 0.1)',
                              border: `1px solid ${isItemEtf ? 'rgba(56, 189, 248, 0.3)' : 'rgba(52, 211, 153, 0.2)'}`,
                              padding: '2px 8px',
                              borderRadius: '4px'
                            }}>
                              {isItemEtf ? '🅿️ ETF / Park' : 'Nifty 500'}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                <div>
                  <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>COMPANY NAME (AUTO-FILLED)</label>
                  <input type="text" placeholder="e.g. Infosys Limited" value={newSipName} onChange={e => setNewSipName(e.target.value)} className="input-field" />
                </div>

                {/* Purchase Details: Execution Price, Shares Qty, Buy Date */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px' }}>
                  <div>
                    <label style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 800, display: 'block', marginBottom: '4px' }}>
                      BUY PRICE (₹)
                    </label>
                    <input 
                      id="new-sip-buy-price-input"
                      type="number" 
                      step="0.05" 
                      placeholder="e.g. 275.45" 
                      value={newSipBuyPrice} 
                      onChange={e => setNewSipBuyPrice(e.target.value)} 
                      className="input-field" 
                      style={{ borderColor: 'rgba(56, 189, 248, 0.4)', background: 'rgba(15, 23, 42, 0.8)' }}
                    />
                    <span style={{ fontSize: '10px', color: '#94a3b8', marginTop: '2px', display: 'block' }}>
                      Exact buy execution price
                    </span>
                  </div>

                  <div>
                    <label style={{ fontSize: '11px', color: '#34d399', fontWeight: 800, display: 'block', marginBottom: '4px' }}>
                      SHARES BOUGHT (QTY)
                    </label>
                    <input 
                      type="number" 
                      step="1" 
                      min="0"
                      placeholder="e.g. 1" 
                      value={newSipShares} 
                      onChange={e => setNewSipShares(e.target.value)} 
                      className="input-field" 
                      style={{ borderColor: 'rgba(52, 211, 153, 0.4)', background: 'rgba(15, 23, 42, 0.8)' }}
                    />
                    <span style={{ fontSize: '10px', color: '#94a3b8', marginTop: '2px', display: 'block' }}>
                      0 = Watchlist only
                    </span>
                  </div>

                  <div>
                    <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>BUY DATE</label>
                    <input 
                      type="date" 
                      value={newSipTxDate} 
                      onChange={e => setNewSipTxDate(e.target.value)} 
                      className="input-field" 
                    />
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>CATEGORY</label>
                  <select value={newSipCategory} onChange={e => setNewSipCategory(e.target.value)} className="input-field">
                    <option value="Core">Core (#1 High Edge Baseline)</option>
                    <option value="Growth">Growth (#2 Momentum High Beta)</option>
                    <option value="Park">Park (ETF / Liquid Cash Reserve — No 5% Signal)</option>
                  </select>
                </div>

                <button type="submit" style={{ background: '#10b981', color: '#ffffff', border: 'none', padding: '12px', borderRadius: '8px', fontWeight: 800, cursor: 'pointer', marginTop: '6px', fontSize: '14px' }}>
                  {Number(newSipShares) > 0 ? '➕ Record Stock Purchase' : '📌 Add Stock to Watchlist'}
                </button>
              </form>
            )}

            {/* FORM B: RECORD SALE OF STOCKS */}
            {sipFormMode === 'SELL' && (() => {
              const openHoldings = pullbackStockSummary.filter(s => s.netShares > 0);
              const selectedHolding = openHoldings.find(s => s.ticker === sipSellSelectedTicker) || openHoldings[0];

              if (openHoldings.length === 0) {
                return (
                  <div style={{ textAlign: 'center', padding: '32px 16px', background: 'rgba(15, 23, 42, 0.5)', borderRadius: '8px', border: '1px dashed rgba(255,255,255,0.1)' }}>
                    <AlertCircle size={28} style={{ color: '#f59e0b', margin: '0 auto 8px' }} />
                    <div style={{ fontSize: '14px', fontWeight: 800, color: '#ffffff' }}>No Open Stock Positions to Sell</div>
                    <p style={{ fontSize: '12px', color: '#94a3b8', maxWidth: '400px', margin: '6px auto 14px' }}>
                      You currently have 0 active shares in your portfolio. Add stock purchases first using the "Buy / Add Stock" tab above.
                    </p>
                    <button
                      type="button"
                      onClick={() => setSipFormMode('BUY')}
                      style={{ background: '#10b981', color: '#ffffff', border: 'none', padding: '8px 16px', borderRadius: '6px', fontWeight: 700, cursor: 'pointer', fontSize: '12px' }}
                    >
                      Go to Buy Form
                    </button>
                  </div>
                );
              }

              const sellSharesNum = parseInt(sipSellFormShares) || 0;
              const sellPriceNum = parseFloat(sipSellFormPrice) || (selectedHolding ? selectedHolding.ltp : 0);
              const avgCost = selectedHolding ? selectedHolding.avgCost : 0;
              const sellVal = sellSharesNum * sellPriceNum;
              const costVal = sellSharesNum * avgCost;
              const estGrossProfit = sellVal - costVal;
              const estProfitPct = costVal > 0 ? (estGrossProfit / costVal) * 100 : 0;

              // Zerodha Sell Charges estimation
              const stt = sellVal * 0.001;
              const txn = sellVal * 0.0000297;
              const gst = txn * 0.18;
              const dp = 15.34;
              const estSellCharges = stt + txn + gst + dp;
              const estNetProfit = estGrossProfit - estSellCharges;

              return (
                <form onSubmit={handleRecordSipSellSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                  <div>
                    <label style={{ fontSize: '11px', color: '#f59e0b', fontWeight: 800, display: 'block', marginBottom: '6px' }}>
                      SELECT STOCK POSITION TO SELL
                    </label>
                    <select
                      value={sipSellSelectedTicker || (selectedHolding ? selectedHolding.ticker : '')}
                      onChange={e => {
                        const tick = e.target.value;
                        setSipSellSelectedTicker(tick);
                        const match = openHoldings.find(s => s.ticker === tick);
                        if (match) {
                          setSipSellFormPrice(match.ltp > 0 ? String(match.ltp) : '');
                          setSipSellFormShares('1');
                        }
                      }}
                      className="input-field"
                      style={{ borderColor: 'rgba(245, 158, 11, 0.4)', background: 'rgba(15, 23, 42, 0.9)' }}
                      required
                    >
                      {openHoldings.map(h => (
                        <option key={h.ticker} value={h.ticker}>
                          {h.cleanSym} — {h.name} ({h.netShares} share{h.netShares > 1 ? 's' : ''} held @ avg ₹{h.avgCost.toFixed(2)} | LTP: ₹{h.ltp.toFixed(2)})
                        </option>
                      ))}
                    </select>
                  </div>

                  {selectedHolding && (
                    <div style={{ background: 'rgba(15, 23, 42, 0.7)', border: '1px solid rgba(245, 158, 11, 0.25)', padding: '12px 16px', borderRadius: '8px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '10px' }}>
                      <div>
                        <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>AVAILABLE SHARES</div>
                        <div style={{ fontSize: '16px', fontWeight: 900, color: '#34d399' }}>{selectedHolding.netShares} sh</div>
                      </div>
                      <div>
                        <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>AVG BUY COST</div>
                        <div style={{ fontSize: '16px', fontWeight: 900, color: '#ffffff' }}>₹{selectedHolding.avgCost.toFixed(2)}</div>
                      </div>
                      <div>
                        <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>CURRENT MARKET LTP</div>
                        <div style={{ fontSize: '16px', fontWeight: 900, color: '#38bdf8' }}>₹{selectedHolding.ltp.toFixed(2)}</div>
                      </div>
                      <div>
                        <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>CATEGORY</div>
                        <div style={{ fontSize: '14px', fontWeight: 800, color: selectedHolding.category === 'Core' ? '#34d399' : '#c084fc' }}>{selectedHolding.category}</div>
                      </div>
                    </div>
                  )}

                  {/* Sell Inputs */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <label style={{ fontSize: '11px', color: '#f59e0b', fontWeight: 800 }}>
                          SHARES TO SELL
                        </label>
                        {selectedHolding && (
                          <div style={{ display: 'flex', gap: '4px' }}>
                            <button
                              type="button"
                              onClick={() => setSipSellFormShares('1')}
                              style={{ fontSize: '9px', background: 'rgba(255,255,255,0.08)', border: 'none', color: '#38bdf8', padding: '1px 5px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700 }}
                            >
                              1
                            </button>
                            {selectedHolding.netShares > 1 && (
                              <button
                                type="button"
                                onClick={() => setSipSellFormShares(String(Math.max(1, Math.floor(selectedHolding.netShares / 2))))}
                                style={{ fontSize: '9px', background: 'rgba(255,255,255,0.08)', border: 'none', color: '#fbbf24', padding: '1px 5px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700 }}
                              >
                                50%
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => setSipSellFormShares(String(selectedHolding.netShares))}
                              style={{ fontSize: '9px', background: 'rgba(255,255,255,0.08)', border: 'none', color: '#34d399', padding: '1px 5px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700 }}
                            >
                              All ({selectedHolding.netShares})
                            </button>
                          </div>
                        )}
                      </div>
                      <input
                        type="number"
                        step="1"
                        min="1"
                        max={selectedHolding ? selectedHolding.netShares : 1}
                        value={sipSellFormShares}
                        onChange={e => setSipSellFormShares(e.target.value)}
                        className="input-field"
                        style={{ borderColor: 'rgba(245, 158, 11, 0.4)', background: 'rgba(15, 23, 42, 0.8)' }}
                        required
                      />
                    </div>

                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <label style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 800 }}>
                          SELL EXECUTION PRICE (₹)
                        </label>
                        {selectedHolding && selectedHolding.ltp > 0 && (
                          <button
                            type="button"
                            onClick={() => setSipSellFormPrice(String(selectedHolding.ltp))}
                            style={{ fontSize: '9px', background: 'rgba(56, 189, 248, 0.15)', border: 'none', color: '#38bdf8', padding: '1px 6px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700 }}
                          >
                            Set LTP
                          </button>
                        )}
                      </div>
                      <input
                        type="number"
                        step="0.05"
                        placeholder="e.g. 405.85"
                        value={sipSellFormPrice}
                        onChange={e => setSipSellFormPrice(e.target.value)}
                        className="input-field"
                        style={{ borderColor: 'rgba(56, 189, 248, 0.4)', background: 'rgba(15, 23, 42, 0.8)' }}
                        required
                      />
                    </div>

                    <div>
                      <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SELL DATE</label>
                      <input
                        type="date"
                        value={sipSellFormDate}
                        onChange={e => setSipSellFormDate(e.target.value)}
                        className="input-field"
                        required
                      />
                    </div>
                  </div>

                  {/* Real-time P&L Preview Banner */}
                  {sellSharesNum > 0 && sellPriceNum > 0 && selectedHolding && (
                    <div style={{ background: estGrossProfit >= 0 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)', border: `1px solid ${estGrossProfit >= 0 ? 'rgba(52, 211, 153, 0.3)' : 'rgba(248, 113, 113, 0.3)'}`, padding: '12px 16px', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
                      <div>
                        <div style={{ fontSize: '11px', color: '#a5b4fc' }}>
                          Proceeds: <strong style={{ color: '#ffffff' }}>₹{sellVal.toFixed(2)}</strong> (Cost: ₹{costVal.toFixed(2)}) | Zerodha Est. Charges: <strong style={{ color: '#fbbf24' }}>₹{estSellCharges.toFixed(2)}</strong> (STT + ₹15.34 DP)
                        </div>
                        <div style={{ fontSize: '13px', fontWeight: 800, marginTop: '2px', color: estGrossProfit >= 0 ? '#34d399' : '#fb7185' }}>
                          Estimated Gross Realized P&L: {estGrossProfit >= 0 ? '+' : ''}₹{estGrossProfit.toFixed(2)} ({estProfitPct >= 0 ? '+' : ''}{estProfitPct.toFixed(2)}%)
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>ESTIMATED NET PROFIT</div>
                        <div style={{ fontSize: '18px', fontWeight: 900, color: estNetProfit >= 0 ? '#34d399' : '#fb7185' }}>
                          {estNetProfit >= 0 ? '+' : ''}₹{estNetProfit.toFixed(2)}
                        </div>
                      </div>
                    </div>
                  )}

                  <button
                    type="submit"
                    style={{
                      background: '#f59e0b',
                      color: '#ffffff',
                      border: 'none',
                      padding: '12px',
                      borderRadius: '8px',
                      fontWeight: 800,
                      cursor: 'pointer',
                      marginTop: '6px',
                      fontSize: '14px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '8px'
                    }}
                  >
                    <DollarSign size={16} />
                    Confirm & Record Sale of {sellSharesNum} Share(s)
                  </button>
                </form>
              );
            })()}

          </div>

          {/* View Switcher: Active Holdings vs Sold Stocks Realized History */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', background: 'rgba(15, 23, 42, 0.4)', padding: '12px 16px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: '14px', color: '#ffffff', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Filter size={16} style={{ color: '#38bdf8' }} />
              SIP Portfolio View:
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                onClick={() => setSipViewMode('holdings')}
                style={{
                  background: sipViewMode === 'holdings' ? '#10b981' : 'rgba(255,255,255,0.05)',
                  border: `1px solid ${sipViewMode === 'holdings' ? '#34d399' : 'rgba(255,255,255,0.1)'}`,
                  color: '#ffffff',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontWeight: 800,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}
              >
                📋 Active Holdings & Targets ({pullbackStockSummary.filter(s => s.netShares > 0 || (pullbackData[s.ticker] && pullbackData[s.ticker].in_watchlist !== false)).length})
              </button>

              <button
                type="button"
                onClick={() => setSipViewMode('sold')}
                style={{
                  background: sipViewMode === 'sold' ? '#f59e0b' : 'rgba(255,255,255,0.05)',
                  border: `1px solid ${sipViewMode === 'sold' ? '#fbbf24' : 'rgba(255,255,255,0.1)'}`,
                  color: '#ffffff',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontWeight: 800,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}
              >
                🏁 Sold Stocks & Realized History ({sipSoldTradesList.length})
              </button>
            </div>
          </div>

          {/* VIEW 1: ACTIVE HOLDINGS & WATCHLIST TABLE */}
          {sipViewMode === 'holdings' && (
            <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
                <div>
                  <h2 style={{ fontSize: '18px', fontWeight: 800, color: '#ffffff' }}>📋 Pullback SIP Targets & Alerts</h2>
                  <p style={{ fontSize: '12px', color: '#a5b4fc', margin: 0 }}>
                    Automated SIP triggers purchase whenever a stock pulls back 5% from its recent local peak (after a 7-day cool-down).
                  </p>
                </div>
                <span style={{ fontSize: '12px', color: '#38bdf8', fontWeight: 700 }}>
                  {pullbackStockSummary.filter(s => s.netShares > 0 || (pullbackData[s.ticker] && pullbackData[s.ticker].in_watchlist !== false)).length} Stocks Monitored
                </span>
              </div>

              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)', color: '#a5b4fc', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                      <th style={{ padding: '12px 14px' }}>Stock (Ticker)</th>
                      <th style={{ padding: '12px 14px' }}>Category</th>
                      <th style={{ padding: '12px 14px' }}>Shares</th>
                      <th style={{ padding: '12px 14px' }}>Cost Basis (Invested)</th>
                      <th style={{ padding: '12px 14px' }}>LTP (Current Value)</th>
                      <th style={{ padding: '12px 14px' }}>P&L</th>
                      <th style={{ padding: '12px 14px' }}>Local Peak</th>
                      <th style={{ padding: '12px 14px' }}>Target Buy Price</th>
                      <th style={{ padding: '12px 14px' }}>Days Since Last Buy</th>
                      <th style={{ padding: '12px 14px' }}>Allocation (%)</th>
                      <th style={{ padding: '12px 14px' }}>System Status</th>
                      <th style={{ padding: '12px 14px' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody style={{ color: '#e0e7ff' }}>
                    {pullbackStockSummary
                      .filter(s => s.netShares > 0 || (pullbackData[s.ticker] && pullbackData[s.ticker].in_watchlist !== false))
                      .map((s, idx) => {
                      const isBuyTriggered = s.signalClass === 'buy';
                      const isCooldown = s.signalClass === 'cooldown';
                      const isPending = s.signalClass === 'pending';
                      const allocPct = totalSipDeployedCost > 0 ? ((s.netCost / totalSipDeployedCost) * 100).toFixed(1) : '0.0';

                      let rowBg = idx % 2 === 0 ? 'rgba(255, 255, 255, 0.02)' : 'transparent';
                      if (isBuyTriggered) rowBg = 'rgba(52, 211, 153, 0.22)';
                      else if (isCooldown) rowBg = 'rgba(245, 158, 11, 0.05)';
                      else if (isPending) rowBg = 'rgba(168, 85, 247, 0.05)';

                      return (
                        <tr key={s.ticker} style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.08)', background: rowBg, borderLeft: isBuyTriggered ? '4px solid #34d399' : 'none' }}>
                          <td style={{ padding: '14px', fontWeight: 800 }}>
                            <div style={{ color: '#ffffff', fontSize: '14px' }}>{s.name} ({s.cleanSym})</div>
                          </td>
                          <td style={{ padding: '14px' }}>
                            <span style={{
                              background: s.category === 'Core' ? 'rgba(52, 211, 153, 0.2)' : (s.category === 'Growth' ? 'rgba(168, 85, 247, 0.2)' : 'rgba(56, 189, 248, 0.2)'),
                              color: s.category === 'Core' ? '#34d399' : (s.category === 'Growth' ? '#c084fc' : '#38bdf8'),
                              border: `1px solid ${s.category === 'Core' ? 'rgba(52, 211, 153, 0.3)' : (s.category === 'Growth' ? 'rgba(168, 85, 247, 0.3)' : 'rgba(56, 189, 248, 0.3)')}`,
                              padding: '2px 8px',
                              borderRadius: '4px',
                              fontSize: '11px',
                              fontWeight: 800
                            }}>
                              {s.category === 'Park' ? '🅿️ Park' : s.category}
                            </span>
                          </td>
                          <td style={{ padding: '14px', fontWeight: 800, color: '#ffffff' }}>{s.netShares}</td>
                          <td style={{ padding: '14px', fontWeight: 700 }}>
                            {s.netShares > 0 ? `₹${s.avgCost.toFixed(2)} (₹${s.netCost.toFixed(2)})` : 'N/A'}
                          </td>
                          <td style={{ padding: '14px', fontWeight: 800, color: '#38bdf8' }}>
                            {s.ltp > 0 ? `₹${s.ltp.toFixed(2)}` : 'Fetching...'} {s.netShares > 0 && `(₹${s.currentVal.toFixed(2)})`}
                          </td>
                          <td style={{ padding: '14px', fontWeight: 800, color: s.unrealizedPnl >= 0 ? '#34d399' : '#fb7185' }}>
                            {s.netShares > 0 ? `₹${s.unrealizedPnl.toFixed(2)} (${s.pnlPct >= 0 ? '+' : ''}${s.pnlPct.toFixed(2)}%)` : 'N/A'}
                          </td>
                          <td style={{ padding: '14px', fontWeight: 700, color: '#cbd5e1' }}>{s.peak > 0 ? `₹${s.peak.toFixed(2)}` : 'Fetching...'}</td>
                          <td style={{ padding: '14px', fontWeight: 900, color: s.category === 'Park' ? '#94a3b8' : '#34d399', background: s.category === 'Park' ? 'transparent' : 'rgba(52, 211, 153, 0.08)' }}>
                            {s.category === 'Park' ? '— (Parked)' : (s.targetBuyPrice > 0 ? `₹${s.targetBuyPrice.toFixed(2)}` : 'Fetching...')}
                          </td>
                          <td style={{ padding: '14px', fontWeight: 700, color: isBuyTriggered ? '#34d399' : '#e2e8f0' }}>
                            {s.daysSinceLastBuyStr}
                          </td>
                          <td style={{ padding: '14px', fontWeight: 800, color: '#a5b4fc' }}>
                            {allocPct}%
                          </td>
                          <td style={{ padding: '14px', whiteSpace: 'nowrap' }}>
                            <span style={{ 
                              fontSize: '11px', 
                              fontWeight: 800, 
                              padding: '6px 12px', 
                              borderRadius: '6px', 
                              whiteSpace: 'nowrap',
                              display: 'inline-block',
                              lineHeight: '1.4',
                              background: s.category === 'Park' ? 'rgba(56, 189, 248, 0.15)' : (isBuyTriggered ? '#10b981' : (isCooldown ? 'rgba(245, 158, 11, 0.2)' : (isPending ? 'rgba(168, 85, 247, 0.2)' : 'rgba(52, 211, 153, 0.15)'))),
                              color: s.category === 'Park' ? '#38bdf8' : (isBuyTriggered ? '#ffffff' : (isCooldown ? '#fde047' : (isPending ? '#c084fc' : '#34d399'))),
                              border: `1px solid ${s.category === 'Park' ? 'rgba(56, 189, 248, 0.3)' : (isBuyTriggered ? '#10b981' : (isCooldown ? '#fde047' : (isPending ? '#c084fc' : '#34d399')))}`
                            }}>
                              {s.systemStatus}
                            </span>
                          </td>
                          <td style={{ padding: '14px', whiteSpace: 'nowrap' }}>
                            <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                              <button
                                onClick={() => handleOpenSipEditModal(s)}
                                title="Edit stock details, category, or historical transactions"
                                style={{
                                  background: 'rgba(99, 102, 241, 0.15)',
                                  color: '#818cf8',
                                  border: '1px solid rgba(99, 102, 241, 0.3)',
                                  padding: '6px 10px',
                                  borderRadius: '6px',
                                  cursor: 'pointer',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '4px',
                                  fontWeight: 700,
                                  fontSize: '11px'
                                }}
                              >
                                <Edit3 size={13} />
                                Edit
                              </button>

                              <button
                                onClick={() => {
                                  setSipFormMode('BUY');
                                  setNewSipTicker(s.ticker);
                                  setNewSipName(s.name);
                                  setNewSipShares('1');
                                  setNewSipBuyPrice(s.ltp > 0 ? s.ltp.toFixed(2) : '');
                                  setTimeout(() => {
                                    const formEl = document.getElementById('sip-watchlist-form');
                                    if (formEl) {
                                      formEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                    }
                                    const priceInput = document.getElementById('new-sip-buy-price-input');
                                    if (priceInput) priceInput.focus();
                                  }, 50);
                                }}
                                title="Log additional buy transaction for this stock"
                                style={{
                                  background: 'rgba(52, 211, 153, 0.15)',
                                  color: '#34d399',
                                  border: '1px solid rgba(52, 211, 153, 0.3)',
                                  padding: '6px 10px',
                                  borderRadius: '6px',
                                  cursor: 'pointer',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '4px',
                                  fontWeight: 700,
                                  fontSize: '11px'
                                }}
                              >
                                <PlusCircle size={13} />
                                Log Buy
                              </button>

                              {s.netShares > 0 && (
                                <button
                                  onClick={() => {
                                    setSipSellModalStock({
                                      ticker: s.ticker,
                                      cleanSym: s.cleanSym,
                                      name: s.name,
                                      category: s.category,
                                      netShares: s.netShares,
                                      avgCost: s.avgCost,
                                      ltp: s.ltp
                                    });
                                    setSipSellModalShares('1');
                                    setSipSellModalPrice(s.ltp > 0 ? String(s.ltp) : '');
                                    setSipSellModalDate(new Date().toISOString().split('T')[0]);
                                  }}
                                  title="Record sold shares / exit position for this stock"
                                  style={{
                                    background: 'rgba(245, 158, 11, 0.15)',
                                    color: '#fbbf24',
                                    border: '1px solid rgba(245, 158, 11, 0.3)',
                                    padding: '6px 10px',
                                    borderRadius: '6px',
                                    cursor: 'pointer',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    fontWeight: 700,
                                    fontSize: '11px'
                                  }}
                                >
                                  <DollarSign size={13} />
                                  Log Sell
                                </button>
                              )}

                              <button
                                onClick={() => handleDeleteStockFromWatchlist(s.ticker)}
                                title="Remove stock from 5% SIP Watchlist"
                                style={{
                                  background: 'rgba(239, 68, 68, 0.15)',
                                  color: '#f87171',
                                  border: '1px solid rgba(239, 68, 68, 0.3)',
                                  padding: '6px 10px',
                                  borderRadius: '6px',
                                  cursor: 'pointer',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '4px',
                                  fontWeight: 700,
                                  fontSize: '11px'
                                }}
                              >
                                <Trash2 size={13} />
                                Remove
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr style={{ borderTop: '2px solid rgba(99, 102, 241, 0.5)', background: 'rgba(15, 23, 42, 0.95)', fontWeight: 900, color: '#ffffff' }}>
                      <td style={{ padding: '14px' }}>
                        <div style={{ fontSize: '13px', color: '#38bdf8' }}>📊 TOTAL PORTFOLIO</div>
                        <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 600 }}>Aligned with Zerodha Holdings</div>
                      </td>
                      <td style={{ padding: '14px', fontSize: '11px', color: '#34d399' }}>
                        {pullbackStockSummary.filter(s => s.netShares > 0).length} Holdings
                      </td>
                      <td style={{ padding: '14px' }}>
                        {pullbackStockSummary.filter(s => s.netShares > 0).reduce((sum, s) => sum + (Number(s.netShares) || 0), 0)}
                      </td>
                      <td style={{ padding: '14px', color: '#ffffff' }}>₹{totalSipDeployedCost.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td style={{ padding: '14px', color: '#38bdf8' }}>₹{totalSipCurrentVal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td style={{ padding: '14px', color: totalSipUnrealizedPnl >= 0 ? '#34d399' : '#fb7185' }}>
                        <div>{totalSipUnrealizedPnl >= 0 ? '+' : ''}₹{totalSipUnrealizedPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({((totalSipUnrealizedPnl / totalSipDeployedCost) * 100).toFixed(2)}%)</div>
                        <div style={{ fontSize: '10px', color: '#fbbf24', marginTop: '2px', fontWeight: 700 }}>Net: {totalSipNetPnl >= 0 ? '+' : ''}₹{totalSipNetPnl.toFixed(2)} (Tax: ₹{totalSipDeliveryTaxes.toFixed(2)})</div>
                      </td>
                      <td colSpan={6} style={{ padding: '14px', fontSize: '11px', color: '#a5b4fc' }}>
                        Zerodha Brokerage: ₹0.00 | STT: ₹{totalSipStt.toFixed(2)} | Stamp: ₹{totalSipStampDuty.toFixed(2)} | Exchange Txn + SEBI + GST: ₹{(totalSipExchangeTxn + totalSipGst).toFixed(2)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )}

          {/* VIEW 2: SOLD STOCKS & REALIZED HISTORY TABLE */}
          {sipViewMode === 'sold' && (
            <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
                <div>
                  <h2 style={{ fontSize: '18px', fontWeight: 800, color: '#ffffff' }}>🏁 Sold Stocks & Realized History</h2>
                  <p style={{ fontSize: '12px', color: '#a5b4fc', margin: 0 }}>
                    Chronological audit log of all sold shares with exact cost basis, realized profit/loss, and Zerodha delivery & DP charges.
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                  <span style={{ fontSize: '12px', color: '#38bdf8', fontWeight: 700 }}>
                    {sipSoldTradesList.length} Sale Transaction(s)
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setSipFormMode('SELL');
                      const formEl = document.getElementById('sip-watchlist-form');
                      if (formEl) formEl.scrollIntoView({ behavior: 'smooth' });
                    }}
                    style={{
                      background: 'rgba(245, 158, 11, 0.2)',
                      color: '#fbbf24',
                      border: '1px solid rgba(245, 158, 11, 0.4)',
                      padding: '6px 12px',
                      borderRadius: '6px',
                      fontSize: '11px',
                      fontWeight: 800,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}
                  >
                    <PlusCircle size={12} />
                    Record New Sale
                  </button>
                </div>
              </div>

              {sipSoldTradesList.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '48px 16px', background: 'rgba(15, 23, 42, 0.4)', borderRadius: '10px', border: '1px dashed rgba(255,255,255,0.1)' }}>
                  <AlertCircle size={32} style={{ color: '#a5b4fc', margin: '0 auto 10px' }} />
                  <div style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff' }}>No Sold Stock Transactions Recorded Yet</div>
                  <p style={{ fontSize: '12px', color: '#94a3b8', maxWidth: '440px', margin: '8px auto 16px' }}>
                    When you exit or sell shares from your SIP holdings, click "Log Sell" in the Active Holdings table or use the "Sell / Record Sold Stock" form above.
                  </p>
                  <button
                    type="button"
                    onClick={() => setSipViewMode('holdings')}
                    style={{ background: '#10b981', color: '#ffffff', border: 'none', padding: '8px 16px', borderRadius: '6px', fontWeight: 700, cursor: 'pointer', fontSize: '12px' }}
                  >
                    View Active Holdings
                  </button>
                </div>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)', color: '#a5b4fc', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                        <th style={{ padding: '12px 14px' }}>Stock (Ticker)</th>
                        <th style={{ padding: '12px 14px' }}>Category</th>
                        <th style={{ padding: '12px 14px' }}>Sell Date</th>
                        <th style={{ padding: '12px 14px' }}>Shares Sold</th>
                        <th style={{ padding: '12px 14px' }}>Avg Buy Price</th>
                        <th style={{ padding: '12px 14px' }}>Sell Price</th>
                        <th style={{ padding: '12px 14px' }}>Sale Value</th>
                        <th style={{ padding: '12px 14px' }}>Gross Realized P&L</th>
                        <th style={{ padding: '12px 14px' }}>Zerodha Charges (incl. DP)</th>
                        <th style={{ padding: '12px 14px' }}>Net Realized Profit</th>
                        <th style={{ padding: '12px 14px' }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody style={{ color: '#e0e7ff' }}>
                      {sipSoldTradesList.map((st, idx) => {
                        const isProfit = st.grossPnl >= 0;
                        const isNetProfit = st.netPnl >= 0;
                        return (
                          <tr key={st.id} style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.08)', background: idx % 2 === 0 ? 'rgba(255, 255, 255, 0.02)' : 'transparent' }}>
                            <td style={{ padding: '14px', fontWeight: 800 }}>
                              <div style={{ color: '#ffffff', fontSize: '14px' }}>{st.name}</div>
                              <div style={{ color: '#38bdf8', fontSize: '11px' }}>{st.cleanSym}.NS</div>
                            </td>
                            <td style={{ padding: '14px' }}>
                              <span style={{ background: st.category === 'Core' ? 'rgba(52, 211, 153, 0.2)' : 'rgba(168, 85, 247, 0.2)', color: st.category === 'Core' ? '#34d399' : '#c084fc', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 800 }}>
                                {st.category}
                              </span>
                            </td>
                            <td style={{ padding: '14px', color: '#cbd5e1', fontWeight: 700 }}>{st.sellDate}</td>
                            <td style={{ padding: '14px', fontWeight: 800, color: '#fbbf24' }}>{st.sharesSold} sh</td>
                            <td style={{ padding: '14px', color: '#cbd5e1' }}>₹{st.avgBuyPrice.toFixed(2)}</td>
                            <td style={{ padding: '14px', fontWeight: 800, color: '#38bdf8' }}>₹{st.sellPrice.toFixed(2)}</td>
                            <td style={{ padding: '14px', fontWeight: 700, color: '#ffffff' }}>₹{st.sellValue.toFixed(2)}</td>
                            <td style={{ padding: '14px', fontWeight: 800, color: isProfit ? '#34d399' : '#fb7185' }}>
                              {isProfit ? '+' : ''}₹{st.grossPnl.toFixed(2)} ({isProfit ? '+' : ''}{st.grossPnlPct.toFixed(2)}%)
                            </td>
                            <td style={{ padding: '14px', color: '#fbbf24', fontSize: '12px' }}>
                              ₹{st.taxes.toFixed(2)}
                            </td>
                            <td style={{ padding: '14px', fontWeight: 900, color: isNetProfit ? '#34d399' : '#fb7185' }}>
                              {isNetProfit ? '+' : ''}₹{st.netPnl.toFixed(2)}
                            </td>
                            <td style={{ padding: '14px', whiteSpace: 'nowrap' }}>
                              <button
                                onClick={() => handleDeleteSipTx(st.ticker, st.txIndex)}
                                title="Undo / Delete this sold transaction"
                                style={{
                                  background: 'rgba(239, 68, 68, 0.15)',
                                  color: '#f87171',
                                  border: '1px solid rgba(239, 68, 68, 0.3)',
                                  padding: '6px 10px',
                                  borderRadius: '6px',
                                  cursor: 'pointer',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '4px',
                                  fontWeight: 700,
                                  fontSize: '11px'
                                }}
                              >
                                <Trash2 size={13} />
                                Delete
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                    <tfoot>
                      {(() => {
                        const totalSoldShares = sipSoldTradesList.reduce((sum, st) => sum + st.sharesSold, 0);
                        const totalSoldVal = sipSoldTradesList.reduce((sum, st) => sum + st.sellValue, 0);
                        return (
                          <tr style={{ borderTop: '2px solid rgba(99, 102, 241, 0.5)', background: 'rgba(15, 23, 42, 0.95)', fontWeight: 900, color: '#ffffff' }}>
                            <td style={{ padding: '14px' }}>
                              <div style={{ fontSize: '13px', color: '#fbbf24' }}>🏁 TOTAL REALIZED</div>
                              <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 600 }}>All Sold Transactions</div>
                            </td>
                            <td style={{ padding: '14px', fontSize: '11px', color: '#38bdf8' }}>
                              {sipSoldTradesList.length} Sales
                            </td>
                            <td style={{ padding: '14px' }}>-</td>
                            <td style={{ padding: '14px', color: '#fbbf24' }}>{totalSoldShares} sh</td>
                            <td style={{ padding: '14px' }}>-</td>
                            <td style={{ padding: '14px' }}>-</td>
                            <td style={{ padding: '14px', color: '#ffffff' }}>₹{totalSoldVal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                            <td style={{ padding: '14px', color: totalSipRealizedProfit >= 0 ? '#34d399' : '#fb7185' }}>
                              {totalSipRealizedProfit >= 0 ? '+' : ''}₹{totalSipRealizedProfit.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </td>
                            <td style={{ padding: '14px', color: '#fbbf24' }}>
                              ₹{totalSipSellTaxes.toFixed(2)}
                            </td>
                            <td style={{ padding: '14px', color: totalSipRealizedNetProfit >= 0 ? '#34d399' : '#fb7185' }}>
                              {totalSipRealizedNetProfit >= 0 ? '+' : ''}₹{totalSipRealizedNetProfit.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </td>
                            <td style={{ padding: '14px' }}>-</td>
                          </tr>
                        );
                      })()}
                    </tfoot>
                  </table>
                </div>
              )}
            </div>
          )}

        </div>
      )}

      {/* Margin Trading (MTF) Manager Tab */}
      {activeTab === 'mtf' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {/* Top Filter & Accumulation View Mode Bar */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', background: 'rgba(15, 23, 42, 0.4)', padding: '12px 16px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: '14px', color: '#ffffff', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Filter size={16} style={{ color: '#fbbf24' }} />
              MTF Accumulation View Mode:
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                onClick={() => setMtfViewMode('overall')}
                style={{
                  background: mtfViewMode === 'overall' ? '#6366f1' : 'rgba(255,255,255,0.05)',
                  border: `1px solid ${mtfViewMode === 'overall' ? '#818cf8' : 'rgba(255,255,255,0.1)'}`,
                  color: '#ffffff',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontWeight: 800,
                  cursor: 'pointer'
                }}
              >
                📊 Overall Accumulation ({mtfSummaryList.length})
              </button>

              <button
                type="button"
                onClick={() => setMtfViewMode('active')}
                style={{
                  background: mtfViewMode === 'active' ? '#10b981' : 'rgba(255,255,255,0.05)',
                  border: `1px solid ${mtfViewMode === 'active' ? '#34d399' : 'rgba(255,255,255,0.1)'}`,
                  color: '#ffffff',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontWeight: 800,
                  cursor: 'pointer'
                }}
              >
                🟢 Active Positions ({mtfSummaryList.filter(t => t.status === 'Active').length})
              </button>

              <button
                type="button"
                onClick={() => setMtfViewMode('closed')}
                style={{
                  background: mtfViewMode === 'closed' ? '#f59e0b' : 'rgba(255,255,255,0.05)',
                  border: `1px solid ${mtfViewMode === 'closed' ? '#fbbf24' : 'rgba(255,255,255,0.1)'}`,
                  color: '#ffffff',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontWeight: 800,
                  cursor: 'pointer'
                }}
              >
                🏁 Closed Positions ({mtfSummaryList.filter(t => t.status === 'Closed').length})
              </button>
            </div>
          </div>

          {/* Executive Overview Cards */}
          {(() => {
            const activeCount = mtfSummaryList.filter(t => t.status === 'Active').length;
            const closedCount = mtfSummaryList.filter(t => t.status === 'Closed').length;

            const dispDeployed = mtfViewMode === 'closed' ? 0 : (mtfViewMode === 'active' ? activeMtfDeployedMargin : overallMtfDeployedMargin);
            const dispFunding = mtfViewMode === 'closed' ? 0 : (mtfViewMode === 'active' ? activeMtfBrokerFunding : overallMtfBrokerFunding);
            const dispGrossPnl = mtfViewMode === 'closed' ? closedMtfGrossPnl : (mtfViewMode === 'active' ? activeMtfGrossPnl : overallMtfGrossPnl);
            const dispCharges = mtfViewMode === 'closed' ? closedMtfCarryingCharges : (mtfViewMode === 'active' ? activeMtfCarryingCharges : overallMtfCarryingCharges);
            const dispNetPnl = mtfViewMode === 'closed' ? closedMtfNetPnl : (mtfViewMode === 'active' ? activeMtfNetPnl : overallMtfNetPnl);
            const dispInterest = mtfViewMode === 'closed' ? closedMtfInterest14 : (mtfViewMode === 'active' ? activeMtfInterest14 : overallMtfInterest14);

            return (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '16px' }}>
                <div className="glass-panel" style={{ padding: '18px', borderLeft: '4px solid #f59e0b' }}>
                  <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                    MARGIN DEPLOYED (YOU FUNDED)
                  </div>
                  <div style={{ fontSize: '22px', fontWeight: 900, color: '#ffffff' }}>
                    ₹{dispDeployed.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div style={{ fontSize: '11px', color: '#fbbf24', marginTop: '4px', fontWeight: 700 }}>
                    Actual cash margin invested
                  </div>
                </div>

                <div className="glass-panel" style={{ padding: '18px', borderLeft: '4px solid #6366f1' }}>
                  <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                    BROKER FUNDING LEVERAGE
                  </div>
                  <div style={{ fontSize: '22px', fontWeight: 900, color: '#818cf8' }}>
                    ₹{dispFunding.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>
                    Capital borrowed @ 14% p.a.
                  </div>
                </div>

                <div className="glass-panel" style={{ padding: '18px', borderLeft: `4px solid ${dispGrossPnl >= 0 ? '#10b981' : '#fb7185'}` }}>
                  <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                    GROSS P&L (BEFORE FEES)
                  </div>
                  <div style={{ fontSize: '22px', fontWeight: 900, color: dispGrossPnl >= 0 ? '#34d399' : '#fb7185' }}>
                    {dispGrossPnl >= 0 ? '+' : ''}₹{dispGrossPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>
                    Price movement before interest & fees
                  </div>
                </div>

                <div className="glass-panel" style={{ padding: '18px', borderLeft: '4px solid #ec4899' }}>
                  <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                    TOTAL MTF CARRYING COSTS
                  </div>
                  <div style={{ fontSize: '22px', fontWeight: 900, color: '#f472b6' }}>
                    ₹{dispCharges.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div style={{ fontSize: '11px', color: '#a5b4fc', marginTop: '4px' }}>
                    Interest (14%): ₹{dispInterest.toFixed(2)} + Tariff Fees
                  </div>
                </div>

                <div className="glass-panel" style={{ padding: '18px', borderLeft: `4px solid ${dispNetPnl >= 0 ? '#10b981' : '#fb7185'}` }}>
                  <div style={{ color: '#a5b4fc', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', marginBottom: '6px' }}>
                    REAL NET P&L (AFTER FEES)
                  </div>
                  <div style={{ fontSize: '22px', fontWeight: 900, color: dispNetPnl >= 0 ? '#34d399' : '#fb7185' }}>
                    {dispNetPnl >= 0 ? '+' : ''}₹{dispNetPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div style={{ fontSize: '11px', color: dispNetPnl >= 0 ? '#34d399' : '#fb7185', marginTop: '4px', fontWeight: 800 }}>
                    Net of all MTF interest & statutory charges
                  </div>
                </div>
              </div>
            );
          })()}

          {/* Form: Record New MTF Trade (With Customizable Broker Funding %) */}
          <div className="glass-panel" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff', marginBottom: '16px', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '10px' }}>
              ⚙️ Record New MTF Leveraged Trade
            </h3>

            <form onSubmit={handleRecordMtfTx} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px' }}>
              <div style={{ position: 'relative' }}>
                <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>TICKER SYMBOL</label>
                <input
                  type="text"
                  placeholder="Type 2+ letters: REL, HDFC, TATA..."
                  value={mtfTicker}
                  onChange={e => { setMtfTicker(e.target.value.toUpperCase()); setShowMtfDropdown(true); }}
                  onFocus={() => setShowMtfDropdown(true)}
                  onBlur={() => setTimeout(() => setShowMtfDropdown(false), 180)}
                  className="input-field"
                  required
                  autoComplete="off"
                />
                {showMtfDropdown && filteredMtfSuggestions.length > 0 && (
                  <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 999, background: 'rgba(15,15,30,0.98)', border: '1px solid rgba(99,102,241,0.4)', borderRadius: '8px', boxShadow: '0 8px 32px rgba(0,0,0,0.6)', maxHeight: '220px', overflowY: 'auto' }}>
                    {filteredMtfSuggestions.map(s => (
                      <div
                        key={s.symbol}
                        onMouseDown={() => {
                          setMtfTicker(s.symbol);
                          setShowMtfDropdown(false);
                          const ltp = liveLtps[s.symbol] || liveLtps[`${s.symbol}.NS`];
                          if (ltp && !mtfBuyPrice) setMtfBuyPrice(String(ltp));
                        }}
                        style={{ padding: '10px 14px', cursor: 'pointer', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                        onMouseEnter={e => e.currentTarget.style.background = 'rgba(99,102,241,0.15)'}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                      >
                        <div>
                          <div style={{ fontSize: '13px', fontWeight: 800, color: '#a5b4fc' }}>{s.symbol}</div>
                          <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>{s.name}</div>
                        </div>
                        {(liveLtps[s.symbol] || liveLtps[`${s.symbol}.NS`]) && (
                          <div style={{ fontSize: '12px', fontWeight: 700, color: '#34d399' }}>
                            ₹{(liveLtps[s.symbol] || liveLtps[`${s.symbol}.NS`]).toFixed(2)}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>BUY PRICE (₹)</label>
                <input 
                  type="number" 
                  step="0.05" 
                  placeholder="e.g. 1091.70" 
                  value={mtfBuyPrice} 
                  onChange={e => setMtfBuyPrice(e.target.value)} 
                  className="input-field" 
                  required 
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#34d399', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SHARES (QTY)</label>
                <input 
                  type="number" 
                  step="1" 
                  min="1" 
                  placeholder="e.g. 10" 
                  value={mtfShares} 
                  onChange={e => setMtfShares(e.target.value)} 
                  className="input-field" 
                  required 
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#818cf8', fontWeight: 800, display: 'block', marginBottom: '4px' }}>BROKER FUNDED (%)</label>
                <input 
                  type="number" 
                  step="0.1" 
                  placeholder="e.g. 68.0" 
                  value={mtfBrokerFundedPct} 
                  onChange={e => setMtfBrokerFundedPct(e.target.value)} 
                  className="input-field" 
                  style={{ borderColor: 'rgba(129, 140, 248, 0.4)' }}
                  required 
                />
                <span style={{ fontSize: '10px', color: '#fbbf24', marginTop: '2px', display: 'block', fontWeight: 700 }}>
                  Default 68.0% (You fund {(100.0 - (parseFloat(mtfBrokerFundedPct) || 68.0)).toFixed(1)}%)
                </span>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>BUY DATE</label>
                <input 
                  type="date" 
                  value={mtfBuyDate} 
                  onChange={e => setMtfBuyDate(e.target.value)} 
                  className="input-field" 
                  required
                />
              </div>

              <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                <button type="submit" style={{ width: '100%', background: '#6366f1', color: '#ffffff', border: 'none', padding: '12px', borderRadius: '8px', fontWeight: 800, cursor: 'pointer', fontSize: '14px' }}>
                  ➕ Record MTF Trade
                </button>
              </div>
            </form>
          </div>

          {/* MTF Positions Breakdown (INDmoney Style Cards) */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <h2 style={{ fontSize: '18px', fontWeight: 800, color: '#ffffff' }}>⚡ Margin Trading Facility (MTF) Positions</h2>
                <p style={{ fontSize: '12px', color: '#a5b4fc', margin: 0 }}>
                  Live tracking of margin borrowing, customizable broker funding %, daily 14% p.a. interest accrual, and percentage-based INDmoney/Zerodha tariff fees.
                </p>
              </div>
              <span style={{ fontSize: '12px', color: '#fbbf24', fontWeight: 800, background: 'rgba(245, 158, 11, 0.15)', padding: '4px 10px', borderRadius: '6px', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
                Interest Rate: 14.0% p.a. (Emotional Edge Buffer)
              </span>
            </div>

            {(() => {
              const displayList = mtfSummaryList.filter(t => {
                if (mtfViewMode === 'active') return t.status === 'Active';
                if (mtfViewMode === 'closed') return t.status === 'Closed';
                return true;
              });

              if (displayList.length === 0) {
                return (
                  <div style={{ textAlign: 'center', padding: '40px 0', color: '#a5b4fc' }}>
                    No MTF positions match the selected view mode (<strong>{mtfViewMode.toUpperCase()}</strong>).
                  </div>
                );
              }

              return (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '20px' }}>
                  {displayList.map(t => (
                    <div key={t.id} style={{ 
                      background: 'rgba(15, 23, 42, 0.75)', 
                      borderRadius: '14px', 
                      border: '1px solid rgba(99, 102, 241, 0.25)', 
                      padding: '20px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '16px'
                    }}>
                      {/* Header: Ticker, Status, Live Value */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div>
                          <div style={{ fontSize: '16px', fontWeight: 900, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            {t.cleanSym}
                            <span style={{ 
                              fontSize: '11px', 
                              padding: '2px 8px', 
                              borderRadius: '4px',
                              background: t.status === 'Active' ? 'rgba(52, 211, 153, 0.2)' : 'rgba(255,255,255,0.08)',
                              color: t.status === 'Active' ? '#34d399' : '#a5b4fc',
                              border: `1px solid ${t.status === 'Active' ? 'rgba(52, 211, 153, 0.4)' : 'rgba(255,255,255,0.1)'}`
                            }}>
                              ● {t.status}
                            </span>
                          </div>
                          <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>
                            Buy Date: <strong style={{ color: '#cbd5e1' }}>{t.buyDtStr}</strong> ({t.holdingDays} day{t.holdingDays === 1 ? '' : 's'} held)
                          </div>
                        </div>

                        <div style={{ textAlign: 'right' }}>
                          <div style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700 }}>CURRENT VALUE</div>
                          <div style={{ fontSize: '18px', fontWeight: 900, color: '#38bdf8' }}>
                            ₹{t.currentVal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </div>
                          <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                            LTP: ₹{t.ltp.toFixed(2)} ({t.shares} Qty)
                          </div>
                        </div>
                      </div>

                      {/* Section A: Invested Value & Customizable Funding Split */}
                      <div style={{ background: 'rgba(30, 41, 59, 0.5)', padding: '14px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                          <div style={{ fontSize: '12px', fontWeight: 800, color: '#a5b4fc' }}>
                            <span style={{ background: 'rgba(99, 102, 241, 0.2)', padding: '2px 6px', borderRadius: '4px', color: '#818cf8', marginRight: '6px' }}>A</span>
                            Invested Value
                          </div>
                          <div style={{ fontSize: '14px', fontWeight: 900, color: '#ffffff' }}>
                            ₹{t.totalBuyVal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </div>
                        </div>
                        
                        <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '10px' }}>
                          {t.shares} Qty at ₹{t.buy_price.toFixed(2)} Avg.
                        </div>

                        {/* Funding Progress Bar */}
                        <div style={{ height: '6px', borderRadius: '3px', background: 'rgba(255,255,255,0.1)', overflow: 'hidden', display: 'flex', marginBottom: '10px' }}>
                          <div style={{ width: `${t.brokerFundedPct}%`, background: '#818cf8' }} title={`Broker Funded (${t.brokerFundedPct}%)`}></div>
                          <div style={{ width: `${t.userFundedPct}%`, background: '#f59e0b' }} title={`You Funded (${t.userFundedPct}%)`}></div>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                          <div style={{ color: '#818cf8', fontWeight: 700 }}>
                            — Broker Funded ({t.brokerFundedPct.toFixed(1)}%): <strong style={{ color: '#ffffff' }}>₹{t.funding.toFixed(2)}</strong>
                          </div>
                          <div style={{ color: '#fbbf24', fontWeight: 700 }}>
                            — You Funded ({t.userFundedPct.toFixed(1)}%): <strong style={{ color: '#ffffff' }}>₹{t.marginPaid.toFixed(2)}</strong>
                          </div>
                        </div>
                      </div>

                      {/* Section B: Gross P&L vs Real Net P&L (Clear Visibility) */}
                      <div style={{ background: 'rgba(30, 41, 59, 0.5)', padding: '14px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                          <div style={{ fontSize: '12px', fontWeight: 800, color: '#a5b4fc' }}>
                            <span style={{ background: 'rgba(52, 211, 153, 0.2)', padding: '2px 6px', borderRadius: '4px', color: '#34d399', marginRight: '6px' }}>B</span>
                            Gross P&L (Before Fees)
                          </div>
                          <div style={{ fontSize: '14px', fontWeight: 800, color: t.grossPnl >= 0 ? '#34d399' : '#fb7185' }}>
                            {t.grossPnl >= 0 ? '+' : ''}₹{t.grossPnl.toFixed(2)}
                          </div>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '6px', paddingTop: '6px', borderTop: '1px dashed rgba(255,255,255,0.1)' }}>
                          <div style={{ fontSize: '12px', fontWeight: 900, color: '#ffffff' }}>
                            🎯 Real Net P&L (After MTF Charges):
                          </div>
                          <div style={{ textAlign: 'right' }}>
                            <div style={{ fontSize: '15px', fontWeight: 900, color: t.netPnl >= 0 ? '#34d399' : '#fb7185' }}>
                              {t.netPnl >= 0 ? '+' : ''}₹{t.netPnl.toFixed(2)}
                            </div>
                            <div style={{ fontSize: '10px', color: t.netReturnPct >= 0 ? '#34d399' : '#fb7185', fontWeight: 800 }}>
                              {t.netReturnPct >= 0 ? '+' : ''}{t.netReturnPct.toFixed(2)}% return on margin paid
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Section C: 🛡️ 5% Fixed Trailing Stop Loss Tracker (Adjusts for Charges + Interest Daily) */}
                      <div style={{ 
                        background: 'rgba(15, 23, 42, 0.9)', 
                        padding: '14px', 
                        borderRadius: '10px', 
                        border: `1px solid ${t.tslStatusBorder}` 
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                          <div style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 800, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <ShieldAlert size={14} style={{ color: t.tslStatusColor }} />
                            5% Trailing Stop Loss Level
                          </div>
                          <span style={{ 
                            fontSize: '11px', 
                            padding: '2px 8px', 
                            borderRadius: '4px', 
                            fontWeight: 800, 
                            background: t.tslStatusBg, 
                            color: t.tslStatusColor, 
                            border: `1px solid ${t.tslStatusBorder}` 
                          }}>
                            {t.tslStatusTag}
                          </span>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px', fontSize: '12px', marginBottom: '8px' }}>
                          <div>
                            <span style={{ color: '#94a3b8', fontSize: '10px', display: 'block' }}>PEAK STOCK PRICE (HIGH)</span>
                            <strong style={{ color: '#ffffff', fontSize: '13px' }}>₹{t.peakLtp.toFixed(2)}</strong>
                          </div>
                          <div>
                            <span style={{ color: '#94a3b8', fontSize: '10px', display: 'block' }}>GROSS 5% SL (STOCK DROP)</span>
                            <strong style={{ color: '#cbd5e1', fontSize: '13px' }}>₹{t.grossSlPrice.toFixed(2)}</strong>
                          </div>
                        </div>

                        <div style={{ padding: '8px 10px', background: 'rgba(30, 41, 59, 0.6)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                              <span style={{ fontSize: '11px', fontWeight: 900, color: '#fbbf24' }}>
                                🎯 DYNAMIC NET 5% SL PRICE LEVEL:
                              </span>
                              <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                                Gross SL (₹{t.grossSlPrice.toFixed(2)}) + Carrying Fees (₹{t.carryingCostPerShare.toFixed(2)}/sh)
                              </div>
                            </div>
                            <div style={{ textAlign: 'right' }}>
                              <div style={{ fontSize: '16px', fontWeight: 900, color: t.ltp <= t.netSlPrice ? '#f87171' : '#38bdf8' }}>
                                ₹{t.netSlPrice.toFixed(2)}
                              </div>
                              <div style={{ fontSize: '10px', color: t.tslBuffer >= 0 ? '#34d399' : '#f87171', fontWeight: 800 }}>
                                {t.tslBuffer >= 0 ? '+' : ''}₹{t.tslBuffer.toFixed(2)} ({t.tslBufferPct >= 0 ? '+' : ''}{t.tslBufferPct.toFixed(2)}% buffer)
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Charges Paid / Accrued Box (INDmoney / Zerodha Tariff Rates) */}
                      <div style={{ background: 'rgba(15, 23, 42, 0.9)', padding: '14px', borderRadius: '10px', border: '1px solid rgba(245, 158, 11, 0.2)' }}>
                        <div style={{ fontSize: '11px', color: '#fbbf24', fontWeight: 800, textTransform: 'uppercase', marginBottom: '10px', letterSpacing: '0.5px' }}>
                          💳 Charges Paid / Accrued during holding period
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                              <span style={{ color: '#e2e8f0', fontWeight: 700 }}>Interest for holding period (@ 14% p.a.)</span>
                              <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                                {t.buyDtStr} - {t.endDtStr} ({t.holdingDays} day{t.holdingDays === 1 ? '' : 's'} @ ₹{((t.funding * 0.14) / 365).toFixed(2)}/day)
                              </div>
                            </div>
                            <span style={{ fontWeight: 800, color: '#f472b6' }}>₹{t.interestCost14.toFixed(2)}</span>
                          </div>

                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                              <span style={{ color: '#cbd5e1' }}>Brokerage Charges</span>
                              <div style={{ fontSize: '10px', color: '#94a3b8' }}>0.05% per order (max ₹20/side)</div>
                            </div>
                            <span style={{ fontWeight: 700, color: '#cbd5e1' }}>₹{t.brokerage.toFixed(2)}</span>
                          </div>

                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                              <span style={{ color: '#cbd5e1' }}>Pledge / Unpledge Charges</span>
                              <div style={{ fontSize: '10px', color: '#94a3b8' }}>₹20 + 18% GST per ISIN</div>
                            </div>
                            <span style={{ fontWeight: 700, color: '#cbd5e1' }}>₹{t.pledgeCharges.toFixed(2)}</span>
                          </div>

                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                              <span style={{ color: '#cbd5e1' }}>Govt. & Statutory Charges</span>
                              <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                                STT: ₹{t.sttCost.toFixed(2)} | Stamp: ₹{t.stampDutyCost.toFixed(2)} | Txn/GST: ₹{(t.exchangeTxnFee + t.gstCost).toFixed(2)}
                              </div>
                            </div>
                            <span style={{ fontWeight: 700, color: '#cbd5e1' }}>₹{t.govtOtherCharges.toFixed(2)}</span>
                          </div>

                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.1)', fontWeight: 900 }}>
                            <span style={{ color: '#ffffff' }}>TOTAL MTF CARRYING CHARGES</span>
                            <span style={{ color: '#fb7185', fontSize: '13px' }}>₹{t.totalCarryingCost.toFixed(2)}</span>
                          </div>
                        </div>
                      </div>

                      {/* Card Actions */}
                      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '4px' }}>
                        {t.status === 'Active' && (
                          <button
                            onClick={() => handleCloseMtfTx(t.id)}
                            style={{
                              background: 'rgba(52, 211, 153, 0.15)',
                              color: '#34d399',
                              border: '1px solid rgba(52, 211, 153, 0.3)',
                              padding: '8px 14px',
                              borderRadius: '6px',
                              fontWeight: 800,
                              fontSize: '12px',
                              cursor: 'pointer'
                            }}
                          >
                            ✓ Log Exit & Close Trade
                          </button>
                        )}
                        <button
                          onClick={() => handleDeleteMtfTx(t.id)}
                          style={{
                            background: 'rgba(239, 68, 68, 0.15)',
                            color: '#f87171',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                            padding: '8px 14px',
                            borderRadius: '6px',
                            fontWeight: 800,
                            fontSize: '12px',
                            cursor: 'pointer'
                          }}
                        >
                          🗑️ Delete Position
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              );
            })()}
          </div>
        </div>
      )}

      {/* Exit Price Modal */}
      {editingTrade && (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(8px)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 9999 }}>
          <div className="glass-panel" style={{ padding: '32px', width: '100%', maxWidth: '420px', borderRadius: '14px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 800 }}>Close Position: {editingTrade.symbol}</h3>
              <button onClick={() => setEditingTrade(null)} style={{ background: 'none', border: 'none', color: '#a5b4fc', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <form onSubmit={handleExitTrade} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>EXIT PRICE (₹)</label>
                <input 
                  type="number" 
                  step="0.05" 
                  placeholder="e.g. 15.50" 
                  value={exitPriceInput} 
                  onChange={e => setExitPriceInput(e.target.value)} 
                  className="input-field" 
                  required 
                  autoFocus 
                />
              </div>

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button type="button" onClick={() => setEditingTrade(null)} style={{ background: 'none', border: '1px solid rgba(99, 102, 241, 0.3)', color: '#a5b4fc', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer' }}>Cancel</button>
                <button type="submit" style={{ background: '#10b981', color: '#ffffff', border: 'none', padding: '10px 20px', borderRadius: '8px', fontWeight: 800, cursor: 'pointer' }}>Save Exit</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Full Edit Trade Transaction Modal */}
      {fullEditTrade && (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(8px)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 99999 }}>
          <div className="glass-panel" style={{ padding: '32px', width: '100%', maxWidth: '520px', borderRadius: '14px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Edit3 size={20} style={{ color: '#14b8a6' }} />
                <h3 style={{ fontSize: '18px', fontWeight: 800, color: '#ffffff' }}>Edit Trade Transaction</h3>
              </div>
              <button onClick={() => setFullEditTrade(null)} style={{ background: 'none', border: 'none', color: '#a5b4fc', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <form onSubmit={handleSaveFullTradeEdit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>SYMBOL</label>
                  <input type="text" value={editSymbol} onChange={e => setEditSymbol(e.target.value)} className="input-field" required />
                </div>

                <div>
                  <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>INSTRUMENT TYPE</label>
                  <select value={editType} onChange={e => setEditType(e.target.value)} className="input-field">
                    <option value="Intraday">Intraday Buy</option>
                    <option value="Intraday Short">Intraday Short</option>
                    <option value="Stock Options">Stock Options (NSE F&O)</option>
                    <option value="Natural Gas Options">Natural Gas Options</option>
                    <option value="Crude Oil Options">Crude Oil Options</option>
                    <option value="Nifty Options">Nifty Options</option>
                    <option value="Delivery">Equity Delivery</option>
                  </select>
                </div>

                <div>
                  <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>ENTRY PRICE (₹)</label>
                  <input type="number" step="0.05" value={editEntryPrice} onChange={e => setEditEntryPrice(e.target.value)} className="input-field" required />
                </div>

                <div>
                  <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>QUANTITY</label>
                  <input type="number" value={editQuantity} onChange={e => setEditQuantity(e.target.value)} className="input-field" required />
                </div>

                <div>
                  <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>STOP LOSS (₹)</label>
                  <input type="number" step="0.05" value={editStopLoss} onChange={e => setEditStopLoss(e.target.value)} className="input-field" />
                </div>

                <div>
                  <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>TARGET PRICE (₹)</label>
                  <input type="number" step="0.05" value={editTargetPrice} onChange={e => setEditTargetPrice(e.target.value)} className="input-field" />
                </div>

                <div style={{ gridColumn: 'span 2' }}>
                  <label style={{ fontSize: '12px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '6px' }}>EXIT PRICE (₹)</label>
                  <input type="number" step="0.05" value={editExitPrice} onChange={e => setEditExitPrice(e.target.value)} className="input-field" placeholder="Leave blank if Open" />
                </div>
              </div>

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '8px' }}>
                <button type="button" onClick={() => setFullEditTrade(null)} style={{ background: 'none', border: '1px solid rgba(99, 102, 241, 0.3)', color: '#a5b4fc', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer' }}>Cancel</button>
                <button type="submit" style={{ background: '#14b8a6', color: '#ffffff', border: 'none', padding: '10px 20px', borderRadius: '8px', fontWeight: 800, cursor: 'pointer' }}>Save Changes</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* SIP Quick Sell Stock Modal */}
      {sipSellModalStock && (() => {
        const holding = pullbackStockSummary.find(s => s.ticker === sipSellModalStock.ticker) || sipSellModalStock;
        const availableShares = holding ? holding.netShares : (sipSellModalStock.netShares || 0);
        const avgCost = holding ? holding.avgCost : (sipSellModalStock.avgCost || 0);
        const ltp = holding ? holding.ltp : (sipSellModalStock.ltp || 0);

        const sellSharesNum = parseInt(sipSellModalShares) || 0;
        const sellPriceNum = parseFloat(sipSellModalPrice) || ltp;
        const sellVal = sellSharesNum * sellPriceNum;
        const costVal = sellSharesNum * avgCost;
        const estGrossProfit = sellVal - costVal;
        const estProfitPct = costVal > 0 ? (estGrossProfit / costVal) * 100 : 0;

        // Zerodha Sell Charges
        const stt = sellVal * 0.001;
        const txn = sellVal * 0.0000297;
        const gst = txn * 0.18;
        const dp = 15.34;
        const estSellCharges = stt + txn + gst + dp;
        const estNetProfit = estGrossProfit - estSellCharges;

        return (
          <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(8px)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 99999 }}>
            <div className="glass-panel" style={{ padding: '28px', width: '100%', maxWidth: '480px', borderRadius: '14px', display: 'flex', flexDirection: 'column', gap: '18px', border: '1px solid rgba(245, 158, 11, 0.4)' }}>
              
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(245, 158, 11, 0.2)', paddingBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <DollarSign size={20} style={{ color: '#fbbf24' }} />
                  <div>
                    <h3 style={{ fontSize: '17px', fontWeight: 800, color: '#ffffff', margin: 0 }}>
                      Record Stock Sale: {sipSellModalStock.cleanSym}
                    </h3>
                    <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>{sipSellModalStock.name}</div>
                  </div>
                </div>
                <button onClick={() => setSipSellModalStock(null)} style={{ background: 'none', border: 'none', color: '#a5b4fc', cursor: 'pointer' }}><X size={20} /></button>
              </div>

              {/* Holding Info Pill */}
              <div style={{ background: 'rgba(15, 23, 42, 0.7)', border: '1px solid rgba(255,255,255,0.08)', padding: '12px 14px', borderRadius: '8px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px' }}>
                <div>
                  <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>AVAILABLE</div>
                  <div style={{ fontSize: '15px', fontWeight: 900, color: '#34d399' }}>{availableShares} sh</div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>AVG COST</div>
                  <div style={{ fontSize: '15px', fontWeight: 900, color: '#ffffff' }}>₹{avgCost.toFixed(2)}</div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>MARKET LTP</div>
                  <div style={{ fontSize: '15px', fontWeight: 900, color: '#38bdf8' }}>₹{ltp.toFixed(2)}</div>
                </div>
              </div>

              <form onSubmit={handleConfirmSellModal} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <label style={{ fontSize: '11px', color: '#fbbf24', fontWeight: 800 }}>SHARES TO SELL</label>
                      <div style={{ display: 'flex', gap: '3px' }}>
                        <button type="button" onClick={() => setSipSellModalShares('1')} style={{ fontSize: '9px', background: 'rgba(255,255,255,0.08)', border: 'none', color: '#38bdf8', padding: '1px 4px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700 }}>1</button>
                        {availableShares > 1 && (
                          <button type="button" onClick={() => setSipSellModalShares(String(Math.max(1, Math.floor(availableShares / 2))))} style={{ fontSize: '9px', background: 'rgba(255,255,255,0.08)', border: 'none', color: '#fbbf24', padding: '1px 4px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700 }}>50%</button>
                        )}
                        <button type="button" onClick={() => setSipSellModalShares(String(availableShares))} style={{ fontSize: '9px', background: 'rgba(255,255,255,0.08)', border: 'none', color: '#34d399', padding: '1px 4px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700 }}>All</button>
                      </div>
                    </div>
                    <input
                      type="number"
                      step="1"
                      min="1"
                      max={availableShares}
                      value={sipSellModalShares}
                      onChange={e => setSipSellModalShares(e.target.value)}
                      className="input-field"
                      style={{ borderColor: 'rgba(245, 158, 11, 0.4)', background: 'rgba(15, 23, 42, 0.8)' }}
                      required
                      autoFocus
                    />
                  </div>

                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <label style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 800 }}>SELL PRICE (₹)</label>
                      {ltp > 0 && (
                        <button type="button" onClick={() => setSipSellModalPrice(String(ltp))} style={{ fontSize: '9px', background: 'rgba(56, 189, 248, 0.15)', border: 'none', color: '#38bdf8', padding: '1px 5px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700 }}>Set LTP</button>
                      )}
                    </div>
                    <input
                      type="number"
                      step="0.05"
                      placeholder="e.g. 405.85"
                      value={sipSellModalPrice}
                      onChange={e => setSipSellModalPrice(e.target.value)}
                      className="input-field"
                      style={{ borderColor: 'rgba(56, 189, 248, 0.4)', background: 'rgba(15, 23, 42, 0.8)' }}
                      required
                    />
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SELL EXECUTION DATE</label>
                  <input
                    type="date"
                    value={sipSellModalDate}
                    onChange={e => setSipSellModalDate(e.target.value)}
                    className="input-field"
                    required
                  />
                </div>

                {/* Real-time P&L Preview Banner */}
                {sellSharesNum > 0 && sellPriceNum > 0 && (
                  <div style={{ background: estGrossProfit >= 0 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)', border: `1px solid ${estGrossProfit >= 0 ? 'rgba(52, 211, 153, 0.3)' : 'rgba(248, 113, 113, 0.3)'}`, padding: '12px 14px', borderRadius: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <span style={{ fontSize: '11px', color: '#a5b4fc' }}>Gross Realized P&L:</span>
                      <span style={{ fontSize: '13px', fontWeight: 800, color: estGrossProfit >= 0 ? '#34d399' : '#fb7185' }}>
                        {estGrossProfit >= 0 ? '+' : ''}₹{estGrossProfit.toFixed(2)} ({estProfitPct >= 0 ? '+' : ''}{estProfitPct.toFixed(2)}%)
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px', fontSize: '11px', color: '#94a3b8' }}>
                      <span>Zerodha Est. Taxes & DP:</span>
                      <span style={{ color: '#fbbf24' }}>₹{estSellCharges.toFixed(2)}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '6px' }}>
                      <span style={{ fontSize: '12px', fontWeight: 800, color: '#ffffff' }}>Estimated Net Gain:</span>
                      <span style={{ fontSize: '16px', fontWeight: 900, color: estNetProfit >= 0 ? '#34d399' : '#fb7185' }}>
                        {estNetProfit >= 0 ? '+' : ''}₹{estNetProfit.toFixed(2)}
                      </span>
                    </div>
                  </div>
                )}

                <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '6px' }}>
                  <button
                    type="button"
                    onClick={() => setSipSellModalStock(null)}
                    style={{ background: 'none', border: '1px solid rgba(99, 102, 241, 0.3)', color: '#a5b4fc', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    style={{ background: '#f59e0b', color: '#ffffff', border: 'none', padding: '10px 20px', borderRadius: '8px', fontWeight: 800, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
                  >
                    <DollarSign size={15} />
                    Confirm Sale
                  </button>
                </div>
              </form>
            </div>
          </div>
        );
      })()}

      {/* SIP Edit Stock & Transactions Modal */}
      {sipEditModalStock && (() => {
        // Compute live net shares and average cost from editSipTxs
        let runningShares = 0;
        let runningCost = 0;
        editSipTxs.forEach(t => {
          const sh = Number(t.shares) || 0;
          const pr = Number(t.price) || 0;
          if (t.type === 'BUY') {
            runningShares += sh;
            runningCost += sh * pr;
          } else {
            const avg = runningShares > 0 ? runningCost / runningShares : pr;
            runningShares = Math.max(0, runningShares - sh);
            runningCost = runningShares * avg;
          }
        });
        const calculatedAvg = runningShares > 0 ? runningCost / runningShares : 0;
        const currentLtp = liveLtps[sipEditModalStock.cleanSym] || liveLtps[sipEditModalStock.ticker] || 0;

        return (
          <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(8px)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 99999, padding: '16px' }}>
            <div className="glass-panel" style={{ padding: '28px', width: '100%', maxWidth: '620px', maxHeight: '90vh', overflowY: 'auto', borderRadius: '14px', display: 'flex', flexDirection: 'column', gap: '18px', border: '1px solid rgba(99, 102, 241, 0.4)' }}>
              
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(99, 102, 241, 0.2)', paddingBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <Edit3 size={20} style={{ color: '#818cf8' }} />
                  <div>
                    <h3 style={{ fontSize: '18px', fontWeight: 800, color: '#ffffff', margin: 0 }}>
                      Edit Stock: {sipEditModalStock.cleanSym}
                    </h3>
                    <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>{sipEditModalStock.ticker}</div>
                  </div>
                </div>
                <button onClick={() => setSipEditModalStock(null)} style={{ background: 'none', border: 'none', color: '#a5b4fc', cursor: 'pointer' }}><X size={20} /></button>
              </div>

              <form onSubmit={handleSaveSipEdit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                
                {/* Stock Profile Inputs */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '12px' }}>
                  <div style={{ gridColumn: 'span 2' }}>
                    <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>COMPANY / ASSET NAME</label>
                    <input
                      type="text"
                      value={editSipName}
                      onChange={e => setEditSipName(e.target.value)}
                      className="input-field"
                      required
                    />
                  </div>

                  <div>
                    <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>INVESTMENT CATEGORY</label>
                    <select
                      value={editSipCategory}
                      onChange={e => setEditSipCategory(e.target.value)}
                      className="input-field"
                      style={{
                        borderColor: editSipCategory === 'Core' ? 'rgba(52, 211, 153, 0.4)' : (editSipCategory === 'Growth' ? 'rgba(168, 85, 247, 0.4)' : 'rgba(56, 189, 248, 0.4)'),
                        color: editSipCategory === 'Core' ? '#34d399' : (editSipCategory === 'Growth' ? '#c084fc' : '#38bdf8'),
                        fontWeight: 800
                      }}
                    >
                      <option value="Core" style={{ color: '#34d399' }}>Core (#1 High Edge Baseline)</option>
                      <option value="Growth" style={{ color: '#c084fc' }}>Growth (#2 Momentum High Beta)</option>
                      <option value="Park" style={{ color: '#38bdf8' }}>Park (ETF / Liquid Cash Reserve — No 5% Strategy)</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>LOCAL PEAK PRICE (₹)</label>
                    <input
                      type="number"
                      step="0.05"
                      placeholder="e.g. 405.85"
                      value={editSipPeak}
                      onChange={e => setEditSipPeak(e.target.value)}
                      className="input-field"
                    />
                  </div>
                </div>

                {/* Live Holding Impact Pill */}
                <div style={{ background: 'rgba(15, 23, 42, 0.8)', border: '1px solid rgba(255,255,255,0.08)', padding: '12px 16px', borderRadius: '10px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: '10px' }}>
                  <div>
                    <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>NET ACTIVE SHARES</div>
                    <div style={{ fontSize: '16px', fontWeight: 900, color: runningShares > 0 ? '#34d399' : '#94a3b8' }}>{runningShares} sh</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>CALCULATED AVG COST</div>
                    <div style={{ fontSize: '16px', fontWeight: 900, color: '#ffffff' }}>₹{calculatedAvg.toFixed(2)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>TOTAL INVESTED COST</div>
                    <div style={{ fontSize: '16px', fontWeight: 900, color: '#fbbf24' }}>₹{runningCost.toFixed(2)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>MARKET LTP</div>
                    <div style={{ fontSize: '16px', fontWeight: 900, color: '#38bdf8' }}>₹{currentLtp.toFixed(2)}</div>
                  </div>
                </div>

                {/* Transactions Editor Table */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <label style={{ fontSize: '12px', color: '#ffffff', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <FileText size={15} style={{ color: '#6366f1' }} />
                      Buy / Sell Transaction History ({editSipTxs.length})
                    </label>
                    <button
                      type="button"
                      onClick={() => {
                        setEditSipTxs(prev => [
                          ...prev,
                          {
                            id: Date.now(),
                            date: new Date().toISOString().split('T')[0],
                            shares: 1,
                            price: currentLtp > 0 ? currentLtp : 0,
                            type: 'BUY'
                          }
                        ]);
                      }}
                      style={{
                        background: 'rgba(52, 211, 153, 0.15)',
                        border: '1px solid rgba(52, 211, 153, 0.3)',
                        color: '#34d399',
                        padding: '4px 10px',
                        borderRadius: '6px',
                        fontSize: '11px',
                        fontWeight: 700,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px'
                      }}
                    >
                      <PlusCircle size={13} />
                      Add Transaction
                    </button>
                  </div>

                  {editSipTxs.length === 0 ? (
                    <div style={{ padding: '16px', textAlign: 'center', background: 'rgba(15, 23, 42, 0.4)', borderRadius: '8px', border: '1px dashed rgba(255,255,255,0.1)', color: '#94a3b8', fontSize: '12px' }}>
                      No transactions recorded (Watchlist stock with 0 shares). Click "Add Transaction" to log shares.
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '220px', overflowY: 'auto' }}>
                      {editSipTxs.map((tx, idx) => (
                        <div key={idx} style={{ display: 'grid', gridTemplateColumns: '95px 120px 85px 1fr 36px', gap: '8px', alignItems: 'center', background: 'rgba(15, 23, 42, 0.6)', border: `1px solid ${tx.type === 'BUY' ? 'rgba(52, 211, 153, 0.2)' : 'rgba(245, 158, 11, 0.2)'}`, padding: '8px 10px', borderRadius: '6px' }}>
                          <select
                            value={tx.type}
                            onChange={e => {
                              const newType = e.target.value;
                              setEditSipTxs(prev => prev.map((item, i) => i === idx ? { ...item, type: newType } : item));
                            }}
                            className="input-field"
                            style={{ padding: '6px 8px', fontSize: '11px', fontWeight: 800, color: tx.type === 'BUY' ? '#34d399' : '#fbbf24' }}
                          >
                            <option value="BUY">🟢 BUY</option>
                            <option value="SELL">🔴 SELL</option>
                          </select>

                          <input
                            type="date"
                            value={tx.date}
                            onChange={e => {
                              const newDate = e.target.value;
                              setEditSipTxs(prev => prev.map((item, i) => i === idx ? { ...item, date: newDate } : item));
                            }}
                            className="input-field"
                            style={{ padding: '6px 8px', fontSize: '11px' }}
                            required
                          />

                          <input
                            type="number"
                            step="1"
                            min="1"
                            placeholder="Qty"
                            value={tx.shares}
                            onChange={e => {
                              const newQty = e.target.value;
                              setEditSipTxs(prev => prev.map((item, i) => i === idx ? { ...item, shares: newQty } : item));
                            }}
                            className="input-field"
                            style={{ padding: '6px 8px', fontSize: '11px', fontWeight: 700 }}
                            required
                          />

                          <div style={{ position: 'relative' }}>
                            <input
                              type="number"
                              step="0.05"
                              min="0"
                              placeholder="Price ₹"
                              value={tx.price}
                              onChange={e => {
                                const newPrice = e.target.value;
                                setEditSipTxs(prev => prev.map((item, i) => i === idx ? { ...item, price: newPrice } : item));
                              }}
                              className="input-field"
                              style={{ padding: '6px 8px', fontSize: '11px', fontWeight: 700 }}
                              required
                            />
                          </div>

                          <button
                            type="button"
                            onClick={() => {
                              setEditSipTxs(prev => prev.filter((_, i) => i !== idx));
                            }}
                            style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#f87171', padding: '6px', borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                            title="Delete transaction"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '6px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '12px' }}>
                  <button
                    type="button"
                    onClick={() => setSipEditModalStock(null)}
                    style={{ background: 'none', border: '1px solid rgba(99, 102, 241, 0.3)', color: '#a5b4fc', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    style={{ background: '#6366f1', color: '#ffffff', border: 'none', padding: '10px 20px', borderRadius: '8px', fontWeight: 800, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
                  >
                    <Save size={15} />
                    Save All Changes
                  </button>
                </div>
              </form>
            </div>
          </div>
        );
      })()}



      {/* Bottom Navigation Bar (Mobile App Style) */}
      <div style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        display: 'flex',
        justifyContent: 'space-around',
        alignItems: 'center',
        background: 'rgba(15, 15, 26, 0.97)',
        borderTop: '1px solid rgba(99, 102, 241, 0.25)',
        backdropFilter: 'blur(12px)',
        padding: '8px 4px calc(8px + env(safe-area-inset-bottom, 0px)) 4px',
        zIndex: 9998
      }}>
        {[
          { key: 'home', label: 'Home', icon: Activity, color: '#6366f1' },
          { key: 'trades', label: 'Trades', icon: FileText, color: '#14b8a6' },
          { key: 'capital', label: 'Capital', icon: DollarSign, color: '#a855f7' },
          { key: 'sip', label: 'SIP', icon: TrendingUp, color: '#00b4d8' },
          { key: 'mtf', label: 'MTF', icon: Layers, color: '#f59e0b' },
          { key: 'settings', label: 'Settings', icon: Settings, color: '#ec4899' }
        ].map(navItem => {
          const NavIcon = navItem.icon;
          const isActive = activeTab === navItem.key;
          return (
            <button
              key={navItem.key}
              onClick={() => setActiveTab(navItem.key)}
              style={{
                background: 'none',
                border: 'none',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '4px',
                padding: '6px 10px',
                cursor: 'pointer',
                flex: 1,
                color: isActive ? navItem.color : '#6b7280'
              }}
            >
              <NavIcon size={20} strokeWidth={isActive ? 2.5 : 2} />
              <span style={{ fontSize: '11px', fontWeight: isActive ? 800 : 600 }}>
                {navItem.label}
              </span>
            </button>
          );
        })}
      </div>

    </div>
  );
}
