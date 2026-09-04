import React, { useState, useEffect, useMemo, useRef } from 'react';
import { 
  loadJournalEngine, 
  saveJournalEngine, 
  calculateZerodhaCharges,
  calculateINDmoneyCharges,
  calculateKiteDeliveryCharges,
  createTradeUUID,
  exportMasterJsonBackup, 
  importMasterJsonBackup
} from './journal/journal_engine';
import RiskDesk from './journal/risk/RiskDesk.jsx';
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
  DollarSign,
  Activity,
  FileText,
  Calendar,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  RotateCcw,
  Shield,
  Zap,
  Award,
  Wallet
} from 'lucide-react';

// Detect Capacitor/Android: window.location.origin = 'capacitor://localhost' which is NOT http.
// On mobile always use Render as the primary cloud backend; localhost is only valid on the dev machine.
const IS_CAPACITOR = typeof window !== 'undefined' && (window.location.origin.startsWith('capacitor://') || window.location.origin.startsWith('file://'));
const API_BASE_URL = IS_CAPACITOR ? 'https://finplus.onrender.com' : (window.location.origin.includes('http') ? window.location.origin : 'http://localhost:8000');
const RENDER_BACKEND_URL = 'https://finplus.onrender.com';
const STORAGE_KEY = 'finplus_3pillar_portfolio_v5';
const LEDGER_KEY = 'finplus_capital_ledger_v5';
const FREE_CASH_SWING_KEY = 'finplus_free_cash_swing_v5';
const FREE_CASH_LT_KEY = 'finplus_free_cash_lt_v5';
const SAVED_AT_KEY = 'finplus_saved_at_v1';
const FRESH_START_TAG = 'finplus_fresh_start_20260907_v2';

// Auto-purge stale trade caches on fresh start while retaining user settings
if (typeof window !== 'undefined') {
  try {
    if (localStorage.getItem('finplus_fresh_start_tag') !== FRESH_START_TAG) {
      localStorage.setItem('finplus_fresh_start_tag', FRESH_START_TAG);
      localStorage.setItem(STORAGE_KEY, JSON.stringify([]));
      localStorage.setItem(LEDGER_KEY, JSON.stringify([]));
      localStorage.setItem('finplus_sold_history_v1', JSON.stringify([]));
      localStorage.setItem('finplus_broker_adjustments_v1', JSON.stringify([]));
      localStorage.setItem('finplus_options_trades_v1', JSON.stringify([]));
      localStorage.setItem(FREE_CASH_SWING_KEY, '0');
      localStorage.setItem('finplus_free_cash_swing_v5', '0');
      localStorage.setItem(FREE_CASH_LT_KEY, '0');
      localStorage.setItem('finplus_free_cash_penny_v4', '0');
      localStorage.setItem('finplus_monthly_income_budget', '0');
      localStorage.setItem('finplus_pnl_v4_fresh', JSON.stringify([]));
      localStorage.setItem('finplus_opening_capital', '0');
      localStorage.setItem(SAVED_AT_KEY, String(Date.now()));
    }
  } catch(e) {}
}

// No hardcoded fallback positions or ledger entries.
// The app is 100% server-driven: all data comes from Render /api/backup/load on mount.
// If the server is unreachable and localStorage is also empty, the app starts blank (correct behaviour).
const INITIAL_POSITIONS = [];
const INITIAL_CAPITAL_LEDGER = [];


export default function App() {
  // ══════════════════════════════════════════════════════════════
  // ZONE 1: ALL REACT STATE HOOKS (Strictly First)
  // ══════════════════════════════════════════════════════════════

  // Gate: prevents auto-saving stale localStorage data to cloud before server load completes.
  // Without this, mobile opens with old localStorage → saves to Render → overwrites correct data.
  const serverLoaded = useRef(false);

  const [activeTab, setActiveTab] = useState('capital'); // 'capital', 'swing', 'lt', 'penny', 'history', 'settings'
  const [toastMsg, setToastMsg] = useState(null);

  // Stock Universe Data
  const [stockUniverse, setStockUniverse] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);

  // Capital Allocator State
  const [monthlyBudgetInput, setMonthlyBudgetInput] = useState(() => {
    return localStorage.getItem('finplus_monthly_income_budget') || '0';
  });
  const [swingPct, setSwingPct] = useState(() => Number(localStorage.getItem('finplus_split_swing')) || 60);
  const [ltPct, setLtPct] = useState(() => Number(localStorage.getItem('finplus_split_lt')) || 30);
  const [pennyPct, setPennyPct] = useState(() => Number(localStorage.getItem('finplus_split_penny')) || 10);

  // Free Cash — start from localStorage only. Server load sets correct values after mount.
  const [swingFreeCashInput, setSwingFreeCashInput] = useState(() => {
    return localStorage.getItem('finplus_free_cash_swing_v5') || localStorage.getItem(FREE_CASH_SWING_KEY) || '';
  });
  const [ltFreeCashInput, setLtFreeCashInput] = useState(() => {
    // 100% server and localStorage driven — no hardcoded numbers.
    return localStorage.getItem(FREE_CASH_LT_KEY) || '';
  });
  const [pennyFreeCashInput, setPennyFreeCashInput] = useState(() => {
    return localStorage.getItem('finplus_free_cash_penny_v4') || '';
  });

  const swingFreeCash = parseFloat(swingFreeCashInput) || 0;
  const ltFreeCash = parseFloat(ltFreeCashInput) || 0;
  const pennyFreeCash = parseFloat(pennyFreeCashInput) || 0;

  // Capital Ledger (Injections & Withdrawals)
  const [capitalLedger, setCapitalLedger] = useState(() => {
    const saved = localStorage.getItem(LEDGER_KEY);
    if (saved !== null) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      } catch(e) {}
    }
    return INITIAL_CAPITAL_LEDGER;
  });

  // Portfolio Positions State (Swing, Long-Term, Penny)
  const [positions, setPositions] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved !== null) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      } catch(e) {}
    }
    return INITIAL_POSITIONS;
  });

  // Sold History Ledger
  const [soldHistory, setSoldHistory] = useState(() => {
    const saved = localStorage.getItem('finplus_sold_history_v1');
    if (saved !== null) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      } catch(e) {}
    }
    return [];
  });

  // Broker Adjustments Ledger State (AMC fees, DP charges, Dividends, Interest, Corrections)
  const [brokerAdjustments, setBrokerAdjustments] = useState(() => {
    const saved = localStorage.getItem('finplus_broker_adjustments_v1');
    if (saved !== null) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      } catch(e) {}
    }
    return [];
  });

  // Options & F&O Trades Event Log State
  const [optionsTrades, setOptionsTrades] = useState(() => {
    const saved = localStorage.getItem('finplus_options_trades_v1');
    if (saved !== null) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      } catch(e) {}
    }
    return [];
  });

  // Modal: Log Broker Adjustment Form State
  const [showLogAdjModal, setShowLogAdjModal] = useState(false);
  const [logAdjDate, setLogAdjDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [logAdjBroker, setLogAdjBroker] = useState('Zerodha Kite'); // 'Zerodha Kite', 'INDmoney'
  const [logAdjSegment, setLogAdjSegment] = useState('SWING'); // 'SWING', 'LT', 'PENNY', 'OPTIONS', 'ALL'
  const [logAdjType, setLogAdjType] = useState('AMC_CHARGE'); // 'AMC_CHARGE', 'DP_CHARGE', 'INTEREST_CREDIT', 'DIVIDEND_RECEIVED', 'PLEDGE_CHARGE', 'CORRECTION', 'MANUAL_INJECTION', 'MANUAL_WITHDRAWAL', 'OTHER'
  const [logAdjAmount, setLogAdjAmount] = useState('');
  const [logAdjNotes, setLogAdjNotes] = useState('');

  // Modal: Record Options Trade Form State
  const [showAddOptionModal, setShowAddOptionModal] = useState(false);
  const [optEntryDate, setOptEntryDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [optInstrument, setOptInstrument] = useState('');
  const [optQty, setOptQty] = useState('50');
  const [optEntryPrice, setOptEntryPrice] = useState('');
  const [optFundedBy, setOptFundedBy] = useState('SWING'); // Mandatory: 'SWING', 'LT', 'PENNY', 'GENERAL'
  const [optStatus, setOptStatus] = useState('OPEN'); // 'OPEN', 'CLOSED'
  const [optExitDate, setOptExitDate] = useState('');
  const [optExitPrice, setOptExitPrice] = useState('');
  const [optCharges, setOptCharges] = useState('40');
  const [optNotes, setOptNotes] = useState('');

  // Modal: EOD Daily Reconciliation State
  const [showReconcileModal, setShowReconcileModal] = useState(false);
  const [reconBroker, setReconBroker] = useState('Zerodha Kite');
  const [reconSegment, setReconSegment] = useState('SWING');
  const [reconActualCash, setReconActualCash] = useState('');

  // Live LTP Polling State — initialized fresh
  const [liveLtps, setLiveLtps] = useState({});
  const [lastLtpUpdate, setLastLtpUpdate] = useState(() => new Date().toLocaleTimeString());
  const [isLtpLoading, setIsLtpLoading] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [addSegment, setAddSegment] = useState('SWING'); // 'SWING', 'LT', 'PENNY'
  const [formTicker, setFormTicker] = useState('');
  const [formName, setFormName] = useState('');
  const [formShares, setFormShares] = useState('1');
  const [formBuyPrice, setFormBuyPrice] = useState('');
  const [formBuyDate, setFormBuyDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [formTarget1, setFormTarget1] = useState('');
  const [formStopLoss, setFormStopLoss] = useState('');
  const [formNotes, setFormNotes] = useState('');

  // Modal: Sell Active Position Form State
  const [sellModalPos, setSellModalPos] = useState(null);
  const [sellFormShares, setSellFormShares] = useState('1');
  const [sellFormPrice, setSellFormPrice] = useState('');
  const [sellFormDate, setSellFormDate] = useState(() => new Date().toISOString().split('T')[0]);

  // Modal: Past Closed Trade Form State
  const [showPastSoldModal, setShowPastSoldModal] = useState(false);
  const [pastSoldSegment, setPastSoldSegment] = useState('SWING');
  const [pastSoldTicker, setPastSoldTicker] = useState('');
  const [pastSoldName, setPastSoldName] = useState('');
  const [pastSoldShares, setPastSoldShares] = useState('1');
  const [pastSoldBuyPrice, setPastSoldBuyPrice] = useState('');
  const [pastSoldBuyDate, setPastSoldBuyDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [pastSoldSellPrice, setPastSoldSellPrice] = useState('');
  const [pastSoldSellDate, setPastSoldSellDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [pastSoldNotes, setPastSoldNotes] = useState('');
  const [showPastSoldSuggestions, setShowPastSoldSuggestions] = useState(false);

  // Modal: Capital Event Form State
  const [showCapModal, setShowCapModal] = useState(false);
  const [capEventType, setCapEventType] = useState('INJECTION');
  const [capEventAmount, setCapEventAmount] = useState('');
  const [capEventSegment, setCapEventSegment] = useState('ALL');
  const [capEventNotes, setCapEventNotes] = useState('');
  // Modal: Broker Cash Adjustment Form State
  const [showCashAdjModal, setShowCashAdjModal] = useState(false);
  const [adjSwingCash, setAdjSwingCash] = useState('');
  const [adjLtCash, setAdjLtCash] = useState('');
  const [adjPennyCash, setAdjPennyCash] = useState('');

  const showToast = (msg) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 3500);
  };

  // ══════════════════════════════════════════════════════════════
  // ZONE 2: ALL REACT SIDE-EFFECTS (Strictly Second)
  // ══════════════════════════════════════════════════════════════
  // Load NSE stock database on mount
  useEffect(() => {
    const parseUniverse = (data) => {
      if (!Array.isArray(data)) return [];
      return data.map(d => ({
        symbol: d.symbol || d.ticker || d.Symbol || d.s,
        name: d.name || d.companyName || d.Name || d.n || d.symbol || d.s,
        ltp: Number(d.ltp || d.price || 0)
      })).filter(d => d.symbol);
    };

    fetch('/stock_universe.json')
      .then(r => r.json())
      .then(data => {
        const parsed = parseUniverse(data);
        if (parsed.length > 0) setStockUniverse(parsed);
      })
      .catch(() => {
        fetch('/nse_stocks.json')
          .then(r => r.json())
          .then(data => {
            const parsed = parseUniverse(data);
            if (parsed.length > 0) setStockUniverse(parsed);
          })
          .catch(() => {});
      });

    // On mount: fetch from all endpoints, pick the dataset with the newest savedAt timestamp.
    // Smart Union-Merge ensures no local or cloud trade is ever lost or wiped out on reload.
    const endpoints = Array.from(new Set([RENDER_BACKEND_URL, API_BASE_URL].filter(Boolean)));
    const localSavedAt = Number(localStorage.getItem(SAVED_AT_KEY)) || 0;
    let bestSavedAt = localSavedAt;

    const mergeLists = (localList, serverList, preferServer = false) => {
      const map = new Map();
      const primary = preferServer ? (serverList || []) : (localList || []);
      const secondary = preferServer ? (localList || []) : (serverList || []);

      primary.forEach(item => {
        if (item) {
          const key = item.id || `${item.ticker || item.symbol}_${item.buyDate || item.sellDate || item.date || item.entryDate}`;
          map.set(key, item);
        }
      });
      secondary.forEach(item => {
        if (item) {
          const key = item.id || `${item.ticker || item.symbol}_${item.buyDate || item.sellDate || item.date || item.entryDate}`;
          if (!map.has(key)) map.set(key, item);
        }
      });
      return Array.from(map.values());
    };

    const applyDataset = (res) => {
      if (!res || res.status !== 'success' || !res.data) return;
      const incomingSavedAt = Number(res.data.savedAt) || 0;
      const preferServer = incomingSavedAt >= localSavedAt;

      const { positions: diskPos, capitalLedger: diskLedger, soldHistory: diskSold, brokerAdjustments: diskAdj, optionsTrades: diskOpt, budget, split, freeCash } = res.data;

      const isCleanSlate = Boolean(res.data.isFreshStart || incomingSavedAt >= 1788500000000);
      if (isCleanSlate && preferServer) {
        setSoldHistory(diskSold || []);
        setPositions(diskPos || []);
        setBrokerAdjustments(diskAdj || []);
        setOptionsTrades(diskOpt || []);
      } else {
        // Merge soldHistory and build a lookup set of all sold trade IDs and tickers
        let mergedSold = [];
        setSoldHistory(prev => {
          mergedSold = mergeLists(prev, diskSold, preferServer);
          return mergedSold;
        });

        const soldKeys = new Set();
        (mergedSold.length > 0 ? mergedSold : diskSold || []).forEach(s => {
          if (s && s.id) soldKeys.add(s.id);
          if (s && s.ticker) soldKeys.add(s.ticker);
        });

        // Filter positions to ensure no sold stock is ever added back to active positions
        const validDiskPos = (diskPos || []).filter(p => p && !soldKeys.has(p.id) && !soldKeys.has(p.ticker));
        setPositions(prev => {
          const filteredPrev = (prev || []).filter(p => p && !soldKeys.has(p.id) && !soldKeys.has(p.ticker));
          return mergeLists(filteredPrev, validDiskPos, preferServer);
        });
        if (Array.isArray(diskAdj)) setBrokerAdjustments(prev => mergeLists(prev, diskAdj, preferServer));
        if (Array.isArray(diskOpt)) setOptionsTrades(prev => mergeLists(prev, diskOpt, preferServer));
      }

      if (preferServer || incomingSavedAt > bestSavedAt) {
        bestSavedAt = incomingSavedAt;
        if (Array.isArray(diskLedger)) setCapitalLedger(diskLedger);
        if (budget !== undefined && budget !== null) setMonthlyBudgetInput(String(budget));
        if (split) {
          if (split.swing !== undefined) setSwingPct(split.swing);
          if (split.lt !== undefined) setLtPct(split.lt);
          if (split.penny !== undefined) setPennyPct(split.penny);
        }
        if (freeCash) {
          if (freeCash.swing !== undefined) setSwingFreeCashInput(String(freeCash.swing));
          if (freeCash.lt !== undefined) setLtFreeCashInput(String(freeCash.lt));
          if (freeCash.penny !== undefined) setPennyFreeCashInput(String(freeCash.penny));
        }
      }

      // Mark server loaded so background sync can save changes to cloud
      serverLoaded.current = true;
    };

    // Fallback timer: ensure serverLoaded unlocks after 2.5s even if backend fetch is slow or offline
    const fallbackTimer = setTimeout(() => {
      serverLoaded.current = true;
    }, 2500);

    for (const ep of endpoints) {
      fetch(`${ep}/api/backup/load`)
        .then(r => r.json())
        .then(applyDataset)
        .catch(() => { serverLoaded.current = true; });
    }

    return () => clearTimeout(fallbackTimer);
  }, []);


  // Save State to LocalStorage & Backend Disk Backup File
  useEffect(() => {
    const savedAt = Date.now();
    // Always save to localStorage immediately with timestamp (fast, local-only).
    localStorage.setItem(SAVED_AT_KEY, String(savedAt));
    localStorage.setItem('finplus_monthly_income_budget', monthlyBudgetInput);
    localStorage.setItem('finplus_split_swing', String(swingPct));
    localStorage.setItem('finplus_split_lt', String(ltPct));
    localStorage.setItem('finplus_split_penny', String(pennyPct));
    localStorage.setItem(FREE_CASH_SWING_KEY, swingFreeCashInput);
    localStorage.setItem('finplus_free_cash_swing_v5', swingFreeCashInput);
    localStorage.setItem(FREE_CASH_LT_KEY, ltFreeCashInput);
    localStorage.setItem('finplus_free_cash_penny_v4', pennyFreeCashInput);
    localStorage.setItem(LEDGER_KEY, JSON.stringify(capitalLedger));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(positions));
    localStorage.setItem('finplus_sold_history_v1', JSON.stringify(soldHistory));
    localStorage.setItem('finplus_broker_adjustments_v1', JSON.stringify(brokerAdjustments));
    localStorage.setItem('finplus_options_trades_v1', JSON.stringify(optionsTrades));

    // Cloud save: ONLY after server data has been loaded or fallback timer unlocked (serverLoaded gate).
    if (!serverLoaded.current) return;

    const endpoints = Array.from(new Set([API_BASE_URL, RENDER_BACKEND_URL].filter(Boolean)));
    const backupPayload = JSON.stringify({
      positions,
      capitalLedger,
      soldHistory,
      brokerAdjustments,
      optionsTrades,
      freeCash: { swing: swingFreeCashInput, lt: ltFreeCashInput, penny: pennyFreeCashInput },
      budget: monthlyBudgetInput,
      split: { swing: swingPct, lt: ltPct, penny: pennyPct },
      savedAt
    });

    for (const ep of endpoints) {
      try {
        fetch(`${ep}/api/backup/save`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: backupPayload
        }).catch(() => {});
      } catch(e) {}
    }
  }, [monthlyBudgetInput, swingPct, ltPct, pennyPct, capitalLedger, positions, soldHistory, brokerAdjustments, optionsTrades, swingFreeCash, ltFreeCash, pennyFreeCash]);

  // Live LTP Poller (Only for Active Held Stocks)
  useEffect(() => {
    const heldSymbols = Array.from(new Set(positions.filter(p => p.shares > 0).map(p => p.ticker.replace('.NS', '').trim().toUpperCase()))).filter(Boolean);
    if (heldSymbols.length === 0) return;

    const fetchLivePrices = async () => {
      setIsLtpLoading(true);
      const symQueryWithNS = heldSymbols.map(s => s.endsWith('.NS') ? s : `${s}.NS`).join(',');
      const symQueryPlain = heldSymbols.join(',');
      
      const endpoints = [
        `http://localhost:5000/api/ltp?ticker=${encodeURIComponent(symQueryWithNS)}`,
        `http://127.0.0.1:5000/api/ltp?ticker=${encodeURIComponent(symQueryWithNS)}`,
        `http://localhost:8000/api/investment/yfinance-prices?symbols=${encodeURIComponent(symQueryPlain)}`,
        `http://127.0.0.1:8000/api/investment/yfinance-prices?symbols=${encodeURIComponent(symQueryPlain)}`,
        `https://finplus.onrender.com/api/investment/yfinance-prices?symbols=${encodeURIComponent(symQueryPlain)}`,
        `https://finplus-g0b5.onrender.com/api/ltp?ticker=${encodeURIComponent(symQueryWithNS)}`
      ];

      for (const ep of endpoints) {
        try {
          const res = await fetch(ep, { signal: AbortSignal.timeout(4000) });
          if (res.ok) {
            const data = await res.json();
            if (data && typeof data === 'object') {
              const sourceMap = data.prices && typeof data.prices === 'object' ? data.prices : data;
              const updated = {};
              for (const [k, v] of Object.entries(sourceMap)) {
                const sym = k.replace('.NS', '').trim().toUpperCase();
                const price = typeof v === 'number' ? v : Number(v?.price || v?.ltp || v || 0);
                if (price > 0) updated[sym] = price;
              }
              if (Object.keys(updated).length > 0) {
                setLiveLtps(prev => ({ ...prev, ...updated }));
                setLastLtpUpdate(new Date().toLocaleTimeString());
                break;
              }
            }
          }
        } catch(e) {}
      }
      setIsLtpLoading(false);
    };

    fetchLivePrices();
    const timer = setInterval(fetchLivePrices, 20000);
    return () => clearInterval(timer);
  }, [positions]);

  // ══════════════════════════════════════════════════════════════
  // ZONE 3: ALL COMPUTED MEMOS (Strictly After States & Effects)
  // ══════════════════════════════════════════════════════════════
  // Search suggestions for New Buy Modal
  const stockSuggestions = useMemo(() => {
    const q = formTicker.trim().toUpperCase();
    if (!q || q.length < 1 || !stockUniverse.length) return [];
    const exactSym = [];
    const nameMatches = [];
    for (const item of stockUniverse) {
      const sym = (item.symbol || '').toUpperCase();
      const name = (item.name || '').toUpperCase();
      if (sym.startsWith(q)) exactSym.push(item);
      else if (sym.includes(q) || name.includes(q)) nameMatches.push(item);
      if (exactSym.length + nameMatches.length >= 15) break;
    }
    return [...exactSym, ...nameMatches].slice(0, 10);
  }, [formTicker, stockUniverse]);

  // Search suggestions for Past Closed Trade Modal
  const pastSoldSuggestions = useMemo(() => {
    const q = pastSoldTicker.trim().toUpperCase();
    if (!q || q.length < 1 || !stockUniverse.length) return [];
    const exactSym = [];
    const nameMatches = [];
    for (const item of stockUniverse) {
      const sym = (item.symbol || '').toUpperCase();
      const name = (item.name || '').toUpperCase();
      if (sym.startsWith(q)) exactSym.push(item);
      else if (sym.includes(q) || name.includes(q)) nameMatches.push(item);
      if (exactSym.length + nameMatches.length >= 15) break;
    }
    return [...exactSym, ...nameMatches].slice(0, 10);
  }, [pastSoldTicker, stockUniverse]);

  // ── Capital Engine Math (Nearest Rupee Rounding) ──
  const capitalMath = useMemo(() => {
    const totalBudget = Number(monthlyBudgetInput) || 0;

    // Total Injections & Withdrawals from Ledger
    let totalInjectedFromLedger = 0;
    let totalWithdrawn = 0;
    let swingInjected = 0;
    let ltInjected = 0;
    let pennyInjected = 0;

    capitalLedger.forEach(item => {
      const amt = Number(item.amount) || 0;
      const isPositive = item.type === 'INJECTION' || item.type === 'ADJUSTMENT_GAIN';
      const isNegative = item.type === 'WITHDRAWAL' || item.type === 'ADJUSTMENT_LOSS';

      if (isPositive) {
        totalInjectedFromLedger += amt;
        if (item.segment === 'ALL') {
          swingInjected += Math.round(amt * (swingPct / 100));
          ltInjected += Math.round(amt * (ltPct / 100));
          pennyInjected += Math.round(amt * (pennyPct / 100));
        } else if (item.segment === 'SWING') {
          swingInjected += amt;
        } else if (item.segment === 'LT') {
          ltInjected += amt;
        } else if (item.segment === 'PENNY') {
          pennyInjected += amt;
        }
      } else if (isNegative) {
        totalWithdrawn += amt;
        if (item.segment === 'ALL') {
          swingInjected -= Math.round(amt * (swingPct / 100));
          ltInjected -= Math.round(amt * (ltPct / 100));
          pennyInjected -= Math.round(amt * (pennyPct / 100));
        } else if (item.segment === 'SWING') {
          swingInjected -= amt;
        } else if (item.segment === 'LT') {
          ltInjected -= amt;
        } else if (item.segment === 'PENNY') {
          pennyInjected -= amt;
        }
      }
    });

    // Deployed Capital in Active Positions
    let swingDeployed = 0;
    let ltDeployed = 0;
    let pennyDeployed = 0;

    positions.forEach(p => {
      if (p.shares > 0) {
        const cost = p.shares * p.buyPrice;
        if (p.segment === 'SWING') swingDeployed += cost;
        else if (p.segment === 'LT') ltDeployed += cost;
        else if (p.segment === 'PENNY') pennyDeployed += cost;
      }
    });

    // Realized Net Profits from Sold Trades (Recycled Capital)
    let swingRealized = 0;
    let ltRealized = 0;
    let pennyRealized = 0;

    soldHistory.forEach(s => {
      const pnl = Number(s.netPnl) || 0;
      if (s.segment === 'SWING') swingRealized += pnl;
      else if (s.segment === 'LT') ltRealized += pnl;
      else if (s.segment === 'PENNY') pennyRealized += pnl;
    });

    // ── Capital Allocation Logic (60% / 30% / 10% Automatic Split & Clean Free Cash) ──
    let swingAllocated = 0;
    let ltAllocated = 0;
    let pennyAllocated = 0;

    if (totalBudget > 0) {
      // 1. If user inputs Capital / Monthly Budget, split automatically by target percentages (60%, 30%, 10%)
      swingAllocated = Math.round(totalBudget * (swingPct / 100));
      ltAllocated = Math.round(totalBudget * (ltPct / 100));
      pennyAllocated = Math.round(totalBudget * (pennyPct / 100));
    } else if (capitalLedger.length > 0) {
      // 2. If capital is logged in ledger, use the ledger allocated amounts
      swingAllocated = swingInjected;
      ltAllocated = ltInjected;
      pennyAllocated = pennyInjected;
    } else {
      // 3. Baseline if no budget and no ledger: Deployed stocks + Free Cash in broker
      swingAllocated = Math.round(swingDeployed + swingFreeCash);
      ltAllocated = Math.round(ltDeployed + ltFreeCash);
      pennyAllocated = Math.round(pennyDeployed + pennyFreeCash);
    }

    const totalAllocated = swingAllocated + ltAllocated + pennyAllocated;

    // ── Pillar Buying Power Logic ──
    // Long-Term & Penny: Permanent deployment (Allocated - Deployed + Realized Profits)
    const ltAvailable = Math.max(0, Math.round(ltAllocated + ltRealized - ltDeployed));
    const pennyAvailable = Math.max(0, Math.round(pennyAllocated + pennyRealized - pennyDeployed));

    // Swing Trading: Revolving Capital (Available Cash = Injected Allocated + Realized Profits - Active Deployed Stocks)
    const swingAvailable = Math.max(0, Math.round(swingAllocated + swingRealized - swingDeployed));
    const swingTotalPool = Math.round(swingDeployed + swingAvailable);

    const totalRealizedPnl = swingRealized + ltRealized + pennyRealized;
    const totalNetCapital = Math.round(swingTotalPool + (ltDeployed + ltAvailable) + (pennyDeployed + pennyAvailable));

    return {
      totalBudget,
      totalInjected: Math.round(totalAllocated),
      totalWithdrawn: Math.round(totalWithdrawn),
      totalNetCapital,
      swing: {
        budget: Math.round((totalBudget || totalAllocated) * (swingPct / 100)),
        injected: Math.round(swingAllocated),
        deployed: Math.round(swingDeployed),
        realized: Math.round(swingRealized),
        available: swingAvailable,
        totalPool: swingTotalPool,
        broker: 'Zerodha Kite'
      },
      lt: {
        budget: Math.round((totalBudget || totalAllocated) * (ltPct / 100)),
        injected: Math.round(ltAllocated),
        deployed: Math.round(ltDeployed),
        realized: Math.round(ltRealized),
        available: ltAvailable,
        broker: 'INDMONEY'
      },
      penny: {
        budget: Math.round((totalBudget || totalAllocated) * (pennyPct / 100)),
        injected: Math.round(pennyAllocated),
        deployed: Math.round(pennyDeployed),
        realized: Math.round(pennyRealized),
        available: pennyAvailable,
        broker: 'Zerodha Kite'
      }
    };
  }, [monthlyBudgetInput, swingPct, ltPct, pennyPct, capitalLedger, positions, soldHistory, swingFreeCash, ltFreeCash, pennyFreeCash]);

  // ── Universal Segment Data Engine (Section 2 & 3 Universal Segment Formulas) ──
  const segmentLedgers = useMemo(() => {
    const processSegment = (segmentKey, defaultBroker) => {
      let injected = 0;
      let withdrawn = 0;
      capitalLedger.forEach(item => {
        const amt = Number(item.amount) || 0;
        const multiplier = item.segment === 'ALL' ? (segmentKey === 'SWING' ? (swingPct/100) : segmentKey === 'LT' ? (ltPct/100) : (pennyPct/100)) : 1;
        if (item.segment === segmentKey || item.segment === 'ALL') {
          if (item.type === 'INJECTION' || item.type === 'ADJUSTMENT_GAIN') injected += amt * multiplier;
          else if (item.type === 'WITHDRAWAL' || item.type === 'ADJUSTMENT_LOSS') withdrawn += amt * multiplier;
        }
      });

      const segPositions = positions.filter(p => p.segment === segmentKey);
      let holdingsValue = 0;
      let costOfOpenHoldings = 0;
      let openBuySideCharges = 0;
      let openEstExitCharges = 0;

      segPositions.forEach(p => {
        const cleanSym = p.ticker.replace('.NS', '').trim().toUpperCase();
        let ltp = liveLtps[cleanSym] || p.buyPrice;

        const val = p.shares * ltp;
        const buyCost = p.shares * p.buyPrice;
        holdingsValue += val;
        costOfOpenHoldings += buyCost;

        const chg = defaultBroker === 'INDmoney'
          ? calculateINDmoneyCharges({ entry_price: p.buyPrice, exit_price: ltp, quantity: p.shares })
          : calculateKiteDeliveryCharges({ entry_price: p.buyPrice, exit_price: ltp, quantity: p.shares });

        const buyTaxes = (chg.stamp_duty || 0) + ((chg.stt || 0) / 2);
        openBuySideCharges += buyTaxes;
        openEstExitCharges += Math.max(0, (chg.total || 0) - buyTaxes);
      });

      const segClosed = soldHistory.filter(s => s.segment === segmentKey);
      let totalSellProceeds = 0;
      let totalClosedBuyCost = 0;
      let totalClosedCharges = 0;
      let realizedPnl = 0;

      segClosed.forEach(s => {
        const proceeds = (Number(s.shares) || 0) * (Number(s.sellPrice) || 0);
        const buyCost = (Number(s.shares) || 0) * (Number(s.buyPrice) || 0);
        const charges = Number(s.taxes) || 0;
        const netPnl = Number(s.netPnl) || (proceeds - buyCost - charges);

        totalSellProceeds += proceeds;
        totalClosedBuyCost += buyCost;
        totalClosedCharges += charges;
        realizedPnl += netPnl;
      });

      let netAdjustments = 0;
      brokerAdjustments.forEach(a => {
        if (a.segment === segmentKey || a.segment === 'ALL') {
          const amt = Number(a.amount) || 0;
          const typeUpper = (a.type || '').toUpperCase();
          if (['INTEREST_CREDIT', 'DIVIDEND_RECEIVED', 'MANUAL_INJECTION', 'CREDIT'].includes(typeUpper)) {
            netAdjustments += Math.abs(amt);
          } else if (['AMC_CHARGE', 'DP_CHARGE', 'PLEDGE_CHARGE', 'MANUAL_WITHDRAWAL', 'DEBIT'].includes(typeUpper)) {
            netAdjustments -= Math.abs(amt);
          } else {
            netAdjustments += amt;
          }
        }
      });

      const totalBuyValue = costOfOpenHoldings + totalClosedBuyCost;
      const totalChargesPaid = openBuySideCharges + totalClosedCharges;
      const calculatedFreeCash = (injected - withdrawn) - totalBuyValue + totalSellProceeds - totalChargesPaid + netAdjustments;

      const manualInputStr = segmentKey === 'SWING' ? swingFreeCashInput : segmentKey === 'LT' ? ltFreeCashInput : pennyFreeCashInput;
      const freeCash = manualInputStr !== '' ? (parseFloat(manualInputStr) || 0) : Math.max(0, calculatedFreeCash);

      const segmentNetWorth = freeCash + holdingsValue;
      const unrealizedPnl = holdingsValue - costOfOpenHoldings;
      const netCapitalContributed = injected - withdrawn;
      const totalSegmentPnl = segmentNetWorth - netCapitalContributed;

      return {
        broker: defaultBroker,
        injected,
        withdrawn,
        netCapitalContributed,
        freeCash,
        calculatedFreeCash: Math.max(0, calculatedFreeCash),
        holdingsValue,
        costOfOpenHoldings,
        realizedPnl,
        unrealizedPnl,
        estExitCharges: openEstExitCharges,
        totalSegmentPnl,
        segmentNetWorth,
        openCount: segPositions.length,
        closedCount: segClosed.length
      };
    };

    const swing = processSegment('SWING', 'Zerodha Kite');
    const lt = processSegment('LT', 'INDmoney');
    const penny = processSegment('PENNY', 'INDmoney');

    let optionsOpenValuation = 0;
    let optionsRealizedPnl = 0;
    let optionsCapitalUsed = 0;
    let optionsOpenCount = 0;
    let optionsClosedCount = 0;

    optionsTrades.forEach(o => {
      const qty = Number(o.qty) || 0;
      const entryP = Number(o.entryPrice) || 0;
      const exitP = Number(o.exitPrice) || 0;
      const chg = Number(o.charges) || 0;
      const cap = qty * entryP;

      if (o.status === 'CLOSED') {
        optionsClosedCount++;
        const pnl = Number(o.netPnl) || ((exitP - entryP) * qty - chg);
        optionsRealizedPnl += pnl;
      } else {
        optionsOpenCount++;
        optionsCapitalUsed += cap;
        optionsOpenValuation += exitP > 0 ? (exitP * qty) : cap;
      }
    });

    const options = {
      broker: 'Zerodha Kite (F&O)',
      freeCash: 0,
      holdingsValue: optionsOpenValuation,
      costOfOpenHoldings: optionsCapitalUsed,
      realizedPnl: optionsRealizedPnl,
      unrealizedPnl: optionsOpenValuation - optionsCapitalUsed,
      estExitCharges: optionsOpenCount * 40,
      segmentNetWorth: optionsOpenValuation + optionsRealizedPnl,
      openCount: optionsOpenCount,
      closedCount: optionsClosedCount
    };

    const grandTotalNetWorth = swing.segmentNetWorth + lt.segmentNetWorth + penny.segmentNetWorth + options.segmentNetWorth;

    return { swing, lt, penny, options, grandTotalNetWorth };
  }, [capitalLedger, positions, soldHistory, brokerAdjustments, optionsTrades, liveLtps, swingPct, ltPct, pennyPct, swingFreeCashInput, ltFreeCashInput, pennyFreeCashInput]);

  // ── Holding Details Calculator ──
  const holdingCards = useMemo(() => {
    const today = new Date();
    return positions.map(pos => {
      const cleanSym = pos.ticker.replace('.NS', '').trim().toUpperCase();
      let ltp = liveLtps[cleanSym] || pos.buyPrice;
      const currentVal = pos.shares * ltp;
      const costBasis = pos.shares * pos.buyPrice;
      const unrealizedPnl = currentVal - costBasis;
      const pnlPct = costBasis > 0 ? (unrealizedPnl / costBasis) * 100 : 0;

      // Holding Days Counter
      let holdingDays = 0;
      if (pos.buyDate) {
        const dt = new Date(pos.buyDate);
        if (!isNaN(dt.getTime())) {
          holdingDays = Math.max(0, Math.floor((today - dt) / (1000 * 60 * 60 * 24)));
        }
      }

      // Brokerage Calculator
      let estCharges = { total: 0, stt: 0, dp_charges: 0 };
      if (pos.segment === 'LT' || pos.segment === 'PENNY') {
        estCharges = calculateINDmoneyCharges({ entry_price: pos.buyPrice, exit_price: ltp, quantity: pos.shares });
      } else {
        estCharges = calculateKiteDeliveryCharges({ entry_price: pos.buyPrice, exit_price: ltp, quantity: pos.shares });
      }

      const grossUnrealizedPnl = unrealizedPnl;
      const netUnrealizedPnl = grossUnrealizedPnl - (estCharges.total || 0);
      const netPnlPct = costBasis > 0 ? (netUnrealizedPnl / costBasis) * 100 : 0;

      return {
        ...pos,
        cleanSym,
        ltp,
        currentVal,
        costBasis,
        grossUnrealizedPnl,
        unrealizedPnl: netUnrealizedPnl, // NET Unrealized P&L (after estimated charges)
        pnlPct: netPnlPct,
        holdingDays,
        estCharges
      };
    });
  }, [positions, liveLtps]);

  // ── Consolidated Portfolio & Capital Summary (Across All Platforms & Segments) ──
  const portfolioSummary = useMemo(() => {
    let totalInvested = 0;
    let totalCurrentVal = 0;
    let swingInvested = 0;
    let swingCurrentVal = 0;
    let ltInvested = 0;
    let ltCurrentVal = 0;
    let pennyInvested = 0;
    let pennyCurrentVal = 0;

    holdingCards.forEach(h => {
      const cost = Number(h.costBasis) || 0;
      const val = Number(h.currentVal) || cost;
      totalInvested += cost;
      totalCurrentVal += val;

      if (h.segment === 'SWING') {
        swingInvested += cost;
        swingCurrentVal += val;
      } else if (h.segment === 'LT') {
        ltInvested += cost;
        ltCurrentVal += val;
      } else if (h.segment === 'PENNY') {
        pennyInvested += cost;
        pennyCurrentVal += val;
      }
    });

    let totalEstCharges = 0;
    let swingEstCharges = 0;
    let ltEstCharges = 0;
    let pennyEstCharges = 0;

    holdingCards.forEach(h => {
      const chg = Number(h.estCharges?.total) || 0;
      totalEstCharges += chg;
      if (h.segment === 'SWING') swingEstCharges += chg;
      else if (h.segment === 'LT') ltEstCharges += chg;
      else if (h.segment === 'PENNY') pennyEstCharges += chg;
    });

    const grossUnrealizedPnl = totalCurrentVal - totalInvested;
    const grossUnrealizedPct = totalInvested > 0 ? (grossUnrealizedPnl / totalInvested) * 100 : 0;
    
    // Net Unrealized PnL (After Est. Brokerage, STT, DP Charges, Stamp Duty & GST)
    const totalUnrealizedPnl = grossUnrealizedPnl - totalEstCharges;
    const totalUnrealizedPct = totalInvested > 0 ? (totalUnrealizedPnl / totalInvested) * 100 : 0;

    // Realized Closed Trade Totals & Sold Cost Basis
    let totalRealizedNetPnl = 0;
    let totalRealizedGrossPnl = 0;
    let totalRealizedTaxes = 0;
    let totalSoldInvested = 0;

    soldHistory.forEach(s => {
      totalRealizedNetPnl += Number(s.netPnl) || 0;
      totalRealizedGrossPnl += Number(s.grossPnl) || 0;
      totalRealizedTaxes += Number(s.taxes) || 0;
      totalSoldInvested += (Number(s.shares) || 0) * (Number(s.buyPrice) || 0);
    });

    // Total Combined Lifetime PnL (Realized + Unrealized Post-Tax)
    const totalCombinedNetPnl = totalUnrealizedPnl + totalRealizedNetPnl;
    const totalCombinedGrossPnl = grossUnrealizedPnl + totalRealizedGrossPnl;
    const totalCombinedTaxes = totalEstCharges + totalRealizedTaxes;
    const totalCombinedPct = totalInvested > 0 ? (totalCombinedNetPnl / totalInvested) * 100 : 0;

    // Segment Gross PnL
    const swingGrossPnl = swingCurrentVal - swingInvested;
    const swingGrossPct = swingInvested > 0 ? (swingGrossPnl / swingInvested) * 100 : 0;

    const ltGrossPnl = ltCurrentVal - ltInvested;
    const ltGrossPct = ltInvested > 0 ? (ltGrossPnl / ltInvested) * 100 : 0;

    const pennyGrossPnl = pennyCurrentVal - pennyInvested;
    const pennyGrossPct = pennyInvested > 0 ? (pennyGrossPnl / pennyInvested) * 100 : 0;

    // Segment Net PnL (After Est. Brokerage & Taxes)
    const swingNetPnl = swingGrossPnl - swingEstCharges;
    const swingNetPct = swingInvested > 0 ? (swingNetPnl / swingInvested) * 100 : 0;

    const ltNetPnl = ltGrossPnl - ltEstCharges;
    const ltNetPct = ltInvested > 0 ? (ltNetPnl / ltInvested) * 100 : 0;

    const pennyNetPnl = pennyGrossPnl - pennyEstCharges;
    const pennyNetPct = pennyInvested > 0 ? (pennyNetPnl / pennyInvested) * 100 : 0;

    // Uninvested Broker Cash: Use revolving available cash from capital engine when manual cash is unaligned
    const revolvingSwingCash = capitalMath.swing.available;
    const revolvingLtCash = capitalMath.lt.available;
    const revolvingPennyCash = capitalMath.penny.available;

    const effectiveSwingFreeCash = parseFloat(swingFreeCashInput) || 0;
    const effectiveLtFreeCash = parseFloat(ltFreeCashInput) || 0;
    const effectivePennyFreeCash = parseFloat(pennyFreeCashInput) || 0;

    const totalFreeCash = effectiveSwingFreeCash + effectiveLtFreeCash + effectivePennyFreeCash;
    
    // Base Cost Capital = Capital Injected from Ledger + Net Realized Profits Booked
    const totalInjectedLedger = capitalMath.totalInjected > 0 ? capitalMath.totalInjected : totalInvested;
    const totalBaseCapital = totalInjectedLedger + totalRealizedNetPnl;
    
    // Total Account Net Worth = Total Base Capital + Net Unrealized Open PnL (Post-Tax)
    // (Consolidated Net Worth = Live Holdings + Actual Uninvested Cash)
    const totalAccountCapital = totalCurrentVal + totalFreeCash <= totalBaseCapital + totalUnrealizedPnl + 50
      ? totalCurrentVal + totalFreeCash
      : totalBaseCapital + totalUnrealizedPnl;

    return {
      totalInvested,
      totalCurrentVal,
      totalUnrealizedPnl,
      totalUnrealizedPct,
      totalFreeCash,
      totalAccountCapital,
      totalBaseCapital,
      totalEstCharges,
      grossUnrealizedPnl,
      grossUnrealizedPct,
      totalRealizedNetPnl,
      totalRealizedGrossPnl,
      totalRealizedTaxes,
      totalCombinedNetPnl,
      totalCombinedGrossPnl,
      totalCombinedTaxes,
      totalCombinedPct,
      swing: {
        invested: swingInvested,
        currentVal: swingCurrentVal,
        grossPnl: swingGrossPnl,
        grossPct: swingGrossPct,
        estCharges: swingEstCharges,
        estExitCharges: swingEstCharges,
        netPnl: swingNetPnl,
        unrealizedPnl: swingNetPnl,
        netPct: swingNetPct,
        freeCash: effectiveSwingFreeCash,
        segmentNetWorth: swingCurrentVal + effectiveSwingFreeCash,
        realizedPnl: (soldHistory || []).filter(s => s.segment === 'SWING').reduce((acc, s) => acc + (Number(s.netPnl) || 0), 0),
        broker: 'Zerodha Kite'
      },
      lt: {
        invested: ltInvested,
        currentVal: ltCurrentVal,
        grossPnl: ltGrossPnl,
        grossPct: ltGrossPct,
        estCharges: ltEstCharges,
        estExitCharges: ltEstCharges,
        netPnl: ltNetPnl,
        unrealizedPnl: ltNetPnl,
        netPct: ltNetPct,
        freeCash: effectiveLtFreeCash,
        segmentNetWorth: ltCurrentVal + effectiveLtFreeCash,
        realizedPnl: (soldHistory || []).filter(s => s.segment === 'LT').reduce((acc, s) => acc + (Number(s.netPnl) || 0), 0),
        broker: 'INDMONEY'
      },
      penny: {
        invested: pennyInvested,
        currentVal: pennyCurrentVal,
        grossPnl: pennyGrossPnl,
        grossPct: pennyGrossPct,
        estCharges: pennyEstCharges,
        estExitCharges: pennyEstCharges,
        netPnl: pennyNetPnl,
        unrealizedPnl: pennyNetPnl,
        netPct: pennyNetPct,
        freeCash: effectivePennyFreeCash,
        segmentNetWorth: pennyCurrentVal + effectivePennyFreeCash,
        realizedPnl: (soldHistory || []).filter(s => s.segment === 'PENNY').reduce((acc, s) => acc + (Number(s.netPnl) || 0), 0),
        broker: 'INDMONEY'
      }
    };
  }, [holdingCards, swingFreeCash, ltFreeCash, pennyFreeCash, capitalMath, swingFreeCashInput, ltFreeCashInput, pennyFreeCashInput]);

  // ── Handle Add Position ──
  const handleAddPositionSubmit = (e) => {
    e.preventDefault();
    const ticker = formTicker.trim().toUpperCase();
    const shares = Number(formShares) || 1;
    const buyPrice = Number(formBuyPrice) || 0;
    const requiredCapital = shares * buyPrice;

    if (!ticker || buyPrice <= 0 || shares <= 0) {
      showToast('❌ Please enter a valid Symbol, Share Count, and Buy Price.');
      return;
    }

    // Seamless baseline capital allocation - no popup blockers for initial portfolio setup

    const newPos = {
      id: `pos_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
      ticker,
      name: formName.trim() || ticker,
      segment: addSegment,
      shares,
      buyPrice,
      buyDate: formBuyDate,
      target1: Number(formTarget1) || (addSegment === 'SWING' ? buyPrice * 1.08 : 0),
      stopLoss: Number(formStopLoss) || (addSegment === 'SWING' ? buyPrice * 0.96 : 0),
      notes: formNotes.trim()
    };

    // Deduct buy capital from the segment's broker free cash
    if (addSegment === 'SWING') {
      setSwingFreeCashInput(prev => Math.max(0, (parseFloat(prev || '0') || 0) - requiredCapital).toFixed(2));
    } else if (addSegment === 'LT') {
      setLtFreeCashInput(prev => Math.max(0, (parseFloat(prev || '0') || 0) - requiredCapital).toFixed(2));
    } else if (addSegment === 'PENNY') {
      setPennyFreeCashInput(prev => Math.max(0, (parseFloat(prev || '0') || 0) - requiredCapital).toFixed(2));
    }

    setPositions(prev => [newPos, ...prev]);
    setShowAddModal(false);
    setFormTicker('');
    setFormName('');
    setFormShares('1');
    setFormBuyPrice('');
    setFormTarget1('');
    setFormStopLoss('');
    setFormNotes('');
    showToast(`✅ Recorded purchase of ${shares} sh ${ticker} in ${addSegment}! ₹${requiredCapital.toFixed(2)} deducted from Free Cash.`);
  };

  // ── Handle Sell / Realize Trade ──
  const handleOpenSellModal = (pos) => {
    setSellModalPos(pos);
    setSellFormShares(String(pos.shares));
    setSellFormPrice(String(pos.ltp || pos.buyPrice));
    setSellFormDate(new Date().toISOString().split('T')[0]);
  };

    // ── Handle Past Closed Trade Submission ──
  const handlePastSoldSubmit = (e) => {
    e.preventDefault();
    const cleanSym = pastSoldTicker.replace('.NS', '').trim().toUpperCase();
    const shares = Number(pastSoldShares);
    const buyPrice = Number(pastSoldBuyPrice);
    const sellPrice = Number(pastSoldSellPrice);

    if (!cleanSym) {
      showToast('❌ Please enter a valid stock symbol.');
      return;
    }
    if (isNaN(shares) || shares <= 0) {
      showToast('❌ Please enter valid shares.');
      return;
    }
    if (isNaN(buyPrice) || buyPrice <= 0 || isNaN(sellPrice) || sellPrice <= 0) {
      showToast('❌ Please enter valid buy and sell prices.');
      return;
    }

    // Taxes & Brokerage
    let taxes = 0;
    const broker = pastSoldSegment === 'LT' ? 'INDMONEY' : 'Zerodha Kite';
    if (pastSoldSegment === 'LT') {
      const chg = calculateINDmoneyCharges({ entry_price: buyPrice, exit_price: sellPrice, quantity: shares });
      taxes = chg.total || 0;
    } else {
      const chg = calculateKiteDeliveryCharges({ entry_price: buyPrice, exit_price: sellPrice, quantity: shares });
      taxes = chg.total || 0;
    }

    const grossPnl = (sellPrice - buyPrice) * shares;
    const netPnl = grossPnl - taxes;
    const costBasis = buyPrice * shares;
    const returnPct = costBasis > 0 ? (netPnl / costBasis) * 100 : 0;

    let holdingDays = 0;
    if (pastSoldBuyDate && pastSoldSellDate) {
      const d1 = new Date(pastSoldBuyDate);
      const d2 = new Date(pastSoldSellDate);
      if (!isNaN(d1.getTime()) && !isNaN(d2.getTime())) {
        holdingDays = Math.max(0, Math.floor((d2 - d1) / (1000 * 60 * 60 * 24)));
      }
    }

    const newSoldRecord = {
      id: `sold_${Date.now()}`,
      ticker: cleanSym,
      name: pastSoldName.trim() || cleanSym,
      segment: pastSoldSegment,
      shares,
      buyPrice,
      sellPrice,
      buyDate: pastSoldBuyDate,
      sellDate: pastSoldSellDate,
      holdingDays,
      grossPnl,
      taxes,
      netPnl,
      returnPct,
      broker,
      notes: pastSoldNotes.trim() || 'Recorded Past Closed Trade'
    };

    setSoldHistory(prev => [newSoldRecord, ...prev]);
    setShowPastSoldModal(false);
    setPastSoldTicker('');
    setPastSoldName('');
    setPastSoldShares('1');
    setPastSoldBuyPrice('');
    setPastSoldSellPrice('');
    setPastSoldNotes('');
    showToast(`✅ Recorded closed trade for ${cleanSym} with Net P&L of ${netPnl >= 0 ? '+' : ''}₹${netPnl.toFixed(2)}!`);
  };

  const handleSellSubmit = (e) => {
    e.preventDefault();
    if (!sellModalPos) return;

    const sellQty = Number(sellFormShares) || 0;
    const sellPrice = Number(sellFormPrice) || 0;

    if (sellQty <= 0 || sellQty > sellModalPos.shares || sellPrice <= 0) {
      showToast('❌ Invalid sell quantity or exit price.');
      return;
    }

    const isFullSell = sellQty === sellModalPos.shares;

    // Calculate exact Brokerage & Charges
    let charges = { total: 0, gross_pnl: 0, net_pnl: 0 };
    if (sellModalPos.segment === 'LT') {
      charges = calculateINDmoneyCharges({ entry_price: sellModalPos.buyPrice, exit_price: sellPrice, quantity: sellQty });
    } else {
      charges = calculateKiteDeliveryCharges({ entry_price: sellModalPos.buyPrice, exit_price: sellPrice, quantity: sellQty });
    }

    const soldRecord = {
      id: `sold_${Date.now()}`,
      ticker: sellModalPos.ticker,
      name: sellModalPos.name,
      segment: sellModalPos.segment,
      shares: sellQty,
      buyPrice: sellModalPos.buyPrice,
      sellPrice,
      buyDate: sellModalPos.buyDate,
      sellDate: sellFormDate,
      holdingDays: sellModalPos.holdingDays,
      broker: sellModalPos.segment === 'LT' ? 'INDMONEY' : 'Zerodha Kite',
      turnover: sellQty * sellPrice,
      grossPnl: charges.gross_pnl,
      taxes: charges.total,
      netPnl: charges.net_pnl,
      returnPct: sellModalPos.buyPrice > 0 ? ((sellPrice - sellModalPos.buyPrice) / sellModalPos.buyPrice) * 100 : 0
    };

    setSoldHistory(prev => [soldRecord, ...prev]);

    // Net cash actually recovered from this sale (turnover minus brokerage/taxes)
    const netProceeds = soldRecord.turnover - charges.total;

    // ── AUTOMATIC FREE BROKER CASH RECYCLING ──
    // Always add net sale proceeds to the broker free cash for that segment.
    // Use 0 as base when the field is blank (never clear on sell — that caused free cash to disappear).
    if (sellModalPos.segment === 'SWING') {
      setSwingFreeCashInput(prev => {
        const base = parseFloat(prev || '0') || 0;
        return (Math.max(0, base + netProceeds)).toFixed(2);
      });
    } else if (sellModalPos.segment === 'LT') {
      setLtFreeCashInput(prev => {
        const base = parseFloat(prev || '0') || 0;
        return (Math.max(0, base + netProceeds)).toFixed(2);
      });
    } else if (sellModalPos.segment === 'PENNY') {
      setPennyFreeCashInput(prev => {
        const base = parseFloat(prev || '0') || 0;
        return (Math.max(0, base + netProceeds)).toFixed(2);
      });
    }

    if (isFullSell) {
      setPositions(prev => prev.filter(p => p.id !== sellModalPos.id));
    } else {
      setPositions(prev => prev.map(p => p.id === sellModalPos.id ? { ...p, shares: p.shares - sellQty } : p));
    }

    setSellModalPos(null);
    showToast(`💰 Recorded sale of ${sellQty} sh ${sellModalPos.ticker}! Net P&L: ${charges.net_pnl >= 0 ? '+' : ''}₹${charges.net_pnl.toFixed(2)} (Recycled into ${sellModalPos.segment} Available Capital).`);
  };

  // ── Handle Capital Event (Injection / Withdrawal / Other Loss or Gain Adjustments) ──
  const handleCapEventSubmit = (e) => {
    e.preventDefault();
    const amt = Number(capEventAmount);
    if (isNaN(amt) || amt <= 0) {
      showToast('❌ Please enter a valid capital amount.');
      return;
    }

    let defaultNote = 'Capital Injected';
    if (capEventType === 'WITHDRAWAL') defaultNote = 'Capital Withdrawn';
    else if (capEventType === 'ADJUSTMENT_LOSS') defaultNote = 'Other Loss / Adjustment (Intraday/Options/Broker Charge)';
    else if (capEventType === 'ADJUSTMENT_GAIN') defaultNote = 'Other Gain / Adjustment (Intraday Gain/Dividends)';

    const newEvent = {
      id: `cap_${Date.now()}`,
      date: new Date().toISOString().split('T')[0],
      type: capEventType,
      amount: amt,
      segment: capEventSegment,
      notes: capEventNotes.trim() || defaultNote
    };

    // Update free cash balance according to adjustment event
    const isAddition = capEventType === 'INJECTION' || capEventType === 'ADJUSTMENT_GAIN';
    if (capEventSegment === 'SWING') {
      setSwingFreeCashInput(prev => {
        const base = parseFloat(prev || '0') || 0;
        return isAddition ? (base + amt).toFixed(2) : Math.max(0, base - amt).toFixed(2);
      });
    } else if (capEventSegment === 'LT') {
      setLtFreeCashInput(prev => {
        const base = parseFloat(prev || '0') || 0;
        return isAddition ? (base + amt).toFixed(2) : Math.max(0, base - amt).toFixed(2);
      });
    } else if (capEventSegment === 'PENNY') {
      setPennyFreeCashInput(prev => {
        const base = parseFloat(prev || '0') || 0;
        return isAddition ? (base + amt).toFixed(2) : Math.max(0, base - amt).toFixed(2);
      });
    } else if (capEventSegment === 'ALL') {
      const swingShare = Math.round(amt * (swingPct / 100));
      const ltShare = Math.round(amt * (ltPct / 100));
      const pennyShare = Math.round(amt * (pennyPct / 100));
      setSwingFreeCashInput(prev => {
        const base = parseFloat(prev || '0') || 0;
        return isAddition ? (base + swingShare).toFixed(2) : Math.max(0, base - swingShare).toFixed(2);
      });
      setLtFreeCashInput(prev => {
        const base = parseFloat(prev || '0') || 0;
        return isAddition ? (base + ltShare).toFixed(2) : Math.max(0, base - ltShare).toFixed(2);
      });
      setPennyFreeCashInput(prev => {
        const base = parseFloat(prev || '0') || 0;
        return isAddition ? (base + pennyShare).toFixed(2) : Math.max(0, base - pennyShare).toFixed(2);
      });
    }

    setCapitalLedger(prev => [newEvent, ...prev]);
    setShowCapModal(false);
    setCapEventAmount('');
    setCapEventNotes('');
    showToast(`✅ Recorded ${defaultNote} of ₹${(amt || 0).toLocaleString('en-IN')}!`);
  };

  const handleExportBackup = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify({
      positions,
      capitalLedger,
      soldHistory,
      budget: monthlyBudgetInput,
      split: { swing: swingPct, lt: ltPct, penny: pennyPct }
    }, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `finplus_portfolio_backup_${new Date().toISOString().split('T')[0]}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    showToast('✅ Portfolio backup JSON exported successfully!');
  };

  const handleImportBackup = (e) => {
    const fileReader = new FileReader();
    if (e.target.files && e.target.files[0]) {
      fileReader.readAsText(e.target.files[0], "UTF-8");
      fileReader.onload = (event) => {
        try {
          const parsed = JSON.parse(event.target.result);
          if (parsed && typeof parsed === 'object') {
            if (Array.isArray(parsed.positions)) setPositions(parsed.positions);
            if (Array.isArray(parsed.capitalLedger)) setCapitalLedger(parsed.capitalLedger);
            if (Array.isArray(parsed.soldHistory)) setSoldHistory(parsed.soldHistory);
            if (parsed.budget) setMonthlyBudgetInput(parsed.budget);
            if (parsed.split) {
              if (parsed.split.swing) setSwingPct(parsed.split.swing);
              if (parsed.split.lt) setLtPct(parsed.split.lt);
              if (parsed.split.penny) setPennyPct(parsed.split.penny);
            }
            showToast('✅ Portfolio backup JSON imported successfully!');
          }
        } catch(err) {
          showToast('❌ Invalid JSON backup file.');
        }
      };
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: '#090d16', color: '#f8fafc', fontFamily: 'Inter, system-ui, -apple-system, sans-serif' }}>
      
      {/* Toast Notification */}
      {toastMsg && (
        <div style={{ position: 'fixed', bottom: '24px', right: '24px', zIndex: 9999, background: 'rgba(15, 23, 42, 0.95)', border: '1.5px solid #38bdf8', color: '#ffffff', padding: '14px 20px', borderRadius: '12px', boxShadow: '0 10px 30px rgba(0,0,0,0.5)', fontWeight: 700, fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>{toastMsg}</span>
        </div>
      )}

      {/* Main Top Header */}
      <header style={{ background: '#0f172a', borderBottom: '1px solid rgba(255,255,255,0.08)', padding: '16px 24px', position: 'sticky', top: 0, zIndex: 100 }}>
        <div style={{ maxWidth: '1400px', margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
          
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{ background: 'linear-gradient(135deg, #10b981, #06b6d4)', padding: '8px 12px', borderRadius: '10px', fontWeight: 900, fontSize: '16px', color: '#090d16', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Shield size={18} />
              <span>FINPLUS</span>
            </div>
            <div>
              <div style={{ fontSize: '16px', fontWeight: 900, color: '#ffffff', letterSpacing: '-0.02em' }}>3-Pillar Disciplined Portfolio Journal</div>
              <div style={{ fontSize: '11px', color: '#94a3b8' }}>25% Monthly Income Strategy • Zero Day Trading • Kite &amp; INDmoney Accounting</div>
            </div>
          </div>

          {/* Quick Actions & LTP Poller Status */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            {lastLtpUpdate && (
              <span style={{ fontSize: '11px', color: '#a5b4fc', background: 'rgba(99, 102, 241, 0.12)', border: '1px solid rgba(99, 102, 241, 0.25)', padding: '4px 10px', borderRadius: '20px' }}>
                🟢 Held Stocks LTP Live: {lastLtpUpdate}
              </span>
            )}
            <button 
              onClick={handleExportBackup}
              title="Download offline JSON backup file"
              style={{ background: 'rgba(148, 163, 184, 0.12)', border: '1px solid rgba(148, 163, 184, 0.25)', color: '#cbd5e1', padding: '8px 12px', borderRadius: '8px', fontWeight: 700, fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px' }}
            >
              <Download size={14} />
              <span>Export</span>
            </button>
            <label 
              title="Import JSON backup file"
              style={{ background: 'rgba(148, 163, 184, 0.12)', border: '1px solid rgba(148, 163, 184, 0.25)', color: '#cbd5e1', padding: '8px 12px', borderRadius: '8px', fontWeight: 700, fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', margin: 0 }}
            >
              <Upload size={14} />
              <span>Import</span>
              <input type="file" accept=".json" onChange={handleImportBackup} style={{ display: 'none' }} />
            </label>
            <button 
              onClick={() => {
                setAdjSwingCash(swingFreeCashInput);
                setAdjLtCash(ltFreeCashInput);
                setAdjPennyCash(pennyFreeCashInput);
                setShowCashAdjModal(true);
              }}
              style={{ background: 'rgba(56, 189, 248, 0.15)', border: '1px solid #38bdf8', color: '#38bdf8', padding: '8px 14px', borderRadius: '8px', fontWeight: 800, fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              ⚙️ Align Free Cash
            </button>

            <button 
              onClick={() => { setShowAddModal(true); }}
              style={{ background: 'linear-gradient(135deg, #0284c7, #38bdf8)', color: '#090d16', border: 'none', padding: '8px 16px', borderRadius: '8px', fontWeight: 900, fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <PlusCircle size={14} />
              Record New Buy
            </button>
          </div>

        </div>
      </header>

            {/* ── GLOBAL EXECUTIVE CAPITAL & AUDITABLE SEGMENT LEDGER RIBBON (SECTION 2e SPEC) ── */}
      <div style={{ background: '#0b1120', borderBottom: '1px solid rgba(255,255,255,0.08)', padding: '18px 24px' }}>
        <div style={{ maxWidth: '1400px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          
          {/* Header Bar: Grand Total Net Worth & Total Unrealized P&L */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'linear-gradient(135deg, rgba(15,23,42,0.95), rgba(30,41,59,0.85))', border: '1.5px solid #38bdf8', borderRadius: '14px', padding: '16px 20px', flexWrap: 'wrap', gap: '14px' }}>
            <div style={{ display: 'flex', gap: '24px', alignItems: 'center', flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.05em' }}>GRAND TOTAL ACCOUNT NET WORTH</div>
                <div style={{ fontSize: '26px', fontWeight: 900, color: '#ffffff', marginTop: '2px' }}>
                  ₹{(segmentLedgers.grandTotalNetWorth || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              </div>

              {/* Dedicated Total Net Unrealized P&L Summary Box */}
              <div style={{ background: 'rgba(56, 189, 248, 0.08)', border: '1.5px solid rgba(56, 189, 248, 0.3)', borderRadius: '10px', padding: '8px 16px' }}>
                <div style={{ fontSize: '10px', color: '#38bdf8', fontWeight: 800, textTransform: 'uppercase' }}>TOTAL NET UNREALIZED P&amp;L (AFTER CHARGES)</div>
                <div style={{ fontSize: '18px', fontWeight: 900, color: portfolioSummary.totalUnrealizedPnl >= 0 ? '#10b981' : '#f87171', marginTop: '2px' }}>
                  {portfolioSummary.totalUnrealizedPnl >= 0 ? '+' : ''}₹{portfolioSummary.totalUnrealizedPnl.toFixed(2)}
                  <span style={{ fontSize: '12px', marginLeft: '6px', fontWeight: 800 }}>({portfolioSummary.totalUnrealizedPct >= 0 ? '+' : ''}{portfolioSummary.totalUnrealizedPct.toFixed(2)}%)</span>
                </div>
                <div style={{ fontSize: '9px', color: '#64748b', marginTop: '1px' }}>
                  Gross P&amp;L: ₹{portfolioSummary.grossUnrealizedPnl.toFixed(2)} | Est. Exit Charges: -₹{portfolioSummary.totalEstCharges.toFixed(2)}
                </div>
              </div>

              {/* Total Booked Realized P&L Summary Box */}
              <div style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1.5px solid rgba(16, 185, 129, 0.3)', borderRadius: '10px', padding: '8px 16px' }}>
                <div style={{ fontSize: '10px', color: '#10b981', fontWeight: 800, textTransform: 'uppercase' }}>TOTAL REALIZED P&amp;L (BOOKED)</div>
                <div style={{ fontSize: '18px', fontWeight: 900, color: portfolioSummary.totalRealizedNetPnl >= 0 ? '#10b981' : '#f87171', marginTop: '2px' }}>
                  {portfolioSummary.totalRealizedNetPnl >= 0 ? '+' : ''}₹{portfolioSummary.totalRealizedNetPnl.toFixed(2)}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <button 
                onClick={() => setShowReconcileModal(true)}
                style={{ background: 'rgba(16, 185, 129, 0.18)', border: '1px solid #10b981', color: '#10b981', padding: '8px 14px', borderRadius: '8px', fontWeight: 800, fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                ⚖️ EOD Daily Reconciliation
              </button>
              <button 
                onClick={() => setShowLogAdjModal(true)}
                style={{ background: 'rgba(245, 158, 11, 0.18)', border: '1px solid #f59e0b', color: '#f59e0b', padding: '8px 14px', borderRadius: '8px', fontWeight: 800, fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                📜 + Log Broker Adjustment
              </button>
              <button 
                onClick={() => setShowAddOptionModal(true)}
                style={{ background: 'rgba(192, 132, 252, 0.18)', border: '1px solid #c084fc', color: '#c084fc', padding: '8px 14px', borderRadius: '8px', fontWeight: 800, fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                ⚡ + Record Options Trade
              </button>
            </div>
          </div>

          {/* Section 2e: Per-Segment Audit Breakdown Grid (Unblended 4-Line Metrics) */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px' }}>
            
            {/* 1. Swing Trading (Kite) */}
            <div style={{ background: 'rgba(15, 23, 42, 0.8)', border: '1px solid rgba(56, 189, 248, 0.3)', borderRadius: '12px', padding: '14px 16px' }}>
              <div style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 800, textTransform: 'uppercase', display: 'flex', justifyContent: 'space-between' }}>
                <span>⚡ SWING TRADING</span>
                <span style={{ fontSize: '10px', color: '#94a3b8' }}>Zerodha Kite</span>
              </div>
              <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff', margin: '4px 0 8px 0' }}>
                ₹{(segmentLedgers.swing.segmentNetWorth || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '11px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>1. Free Cash (INDmoney):</span>
                  <span style={{ color: '#38bdf8', fontWeight: 800 }}>₹{(segmentLedgers.swing.freeCash || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>2. Holdings Value:</span>
                  <span style={{ color: '#ffffff', fontWeight: 800 }}>₹{(segmentLedgers.swing.holdingsValue || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>3. Realized P&amp;L (Booked):</span>
                  <span style={{ color: segmentLedgers.swing.realizedPnl >= 0 ? '#10b981' : '#f87171', fontWeight: 800 }}>
                    {segmentLedgers.swing.realizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.swing.realizedPnl.toFixed(2)}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>4. Unrealized P&amp;L (Open):</span>
                  <span style={{ color: segmentLedgers.swing.unrealizedPnl >= 0 ? '#10b981' : '#f87171', fontWeight: 800 }}>
                    {segmentLedgers.swing.unrealizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.swing.unrealizedPnl.toFixed(2)}
                  </span>
                </div>
                <div style={{ fontSize: '10px', color: '#64748b', textAlign: 'right', marginTop: '-2px' }}>
                  Est. Exit Charges: -₹{segmentLedgers.swing.estExitCharges.toFixed(2)}
                </div>
              </div>
            </div>

            {/* 2. Long-Term Core (INDmoney) */}
            <div style={{ background: 'rgba(15, 23, 42, 0.8)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: '12px', padding: '14px 16px' }}>
              <div style={{ fontSize: '11px', color: '#10b981', fontWeight: 800, textTransform: 'uppercase', display: 'flex', justifyContent: 'space-between' }}>
                <span>🛡️ LONG-TERM CORE</span>
                <span style={{ fontSize: '10px', color: '#94a3b8' }}>INDmoney</span>
              </div>
              <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff', margin: '4px 0 8px 0' }}>
                ₹{(segmentLedgers.lt.segmentNetWorth || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '11px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>1. Free Cash (INDmoney):</span>
                  <span style={{ color: '#10b981', fontWeight: 800 }}>₹{(segmentLedgers.lt.freeCash || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>2. Holdings Value:</span>
                  <span style={{ color: '#ffffff', fontWeight: 800 }}>₹{(segmentLedgers.lt.holdingsValue || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>3. Realized P&amp;L (Booked):</span>
                  <span style={{ color: segmentLedgers.lt.realizedPnl >= 0 ? '#10b981' : '#f87171', fontWeight: 800 }}>
                    {segmentLedgers.lt.realizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.lt.realizedPnl.toFixed(2)}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>4. Unrealized P&amp;L (Open):</span>
                  <span style={{ color: segmentLedgers.lt.unrealizedPnl >= 0 ? '#10b981' : '#f87171', fontWeight: 800 }}>
                    {segmentLedgers.lt.unrealizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.lt.unrealizedPnl.toFixed(2)}
                  </span>
                </div>
                <div style={{ fontSize: '10px', color: '#64748b', textAlign: 'right', marginTop: '-2px' }}>
                  Est. Exit Charges: -₹{segmentLedgers.lt.estExitCharges.toFixed(2)}
                </div>
              </div>
            </div>

            {/* 3. Quality Penny SIP (INDmoney) */}
            <div style={{ background: 'rgba(15, 23, 42, 0.8)', border: '1px solid rgba(192, 132, 252, 0.3)', borderRadius: '12px', padding: '14px 16px' }}>
              <div style={{ fontSize: '11px', color: '#c084fc', fontWeight: 800, textTransform: 'uppercase', display: 'flex', justifyContent: 'space-between' }}>
                <span>💎 QUALITY PENNY SIP</span>
                <span style={{ fontSize: '10px', color: '#94a3b8' }}>INDmoney</span>
              </div>
              <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff', margin: '4px 0 8px 0' }}>
                ₹{(segmentLedgers.penny.segmentNetWorth || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '11px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>1. Free Cash (INDmoney):</span>
                  <span style={{ color: '#c084fc', fontWeight: 800 }}>₹{(segmentLedgers.penny.freeCash || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>2. Holdings Value:</span>
                  <span style={{ color: '#ffffff', fontWeight: 800 }}>₹{(segmentLedgers.penny.holdingsValue || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>3. Realized P&amp;L (Booked):</span>
                  <span style={{ color: segmentLedgers.penny.realizedPnl >= 0 ? '#10b981' : '#f87171', fontWeight: 800 }}>
                    {segmentLedgers.penny.realizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.penny.realizedPnl.toFixed(2)}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>4. Unrealized P&amp;L (Open):</span>
                  <span style={{ color: segmentLedgers.penny.unrealizedPnl >= 0 ? '#10b981' : '#f87171', fontWeight: 800 }}>
                    {segmentLedgers.penny.unrealizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.penny.unrealizedPnl.toFixed(2)}
                  </span>
                </div>
                <div style={{ fontSize: '10px', color: '#64748b', textAlign: 'right', marginTop: '-2px' }}>
                  Est. Exit Charges: -₹{segmentLedgers.penny.estExitCharges.toFixed(2)}
                </div>
              </div>
            </div>

            {/* 4. Options & F&O Trading (Section 3 Event Log) */}
            <div style={{ background: 'rgba(15, 23, 42, 0.8)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: '12px', padding: '14px 16px' }}>
              <div style={{ fontSize: '11px', color: '#f59e0b', fontWeight: 800, textTransform: 'uppercase', display: 'flex', justifyContent: 'space-between' }}>
                <span>⚡ OPTIONS / F&amp;O</span>
                <span style={{ fontSize: '10px', color: '#94a3b8' }}>Zerodha F&amp;O</span>
              </div>
              <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff', margin: '4px 0 8px 0' }}>
                ₹{(segmentLedgers.options.segmentNetWorth || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '11px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>1. Capital Used (Open):</span>
                  <span style={{ color: '#f59e0b', fontWeight: 800 }}>₹{(segmentLedgers.options.costOfOpenHoldings || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>2. Open Options Valuation:</span>
                  <span style={{ color: '#ffffff', fontWeight: 800 }}>₹{(segmentLedgers.options.holdingsValue || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>3. Realized P&amp;L (Booked):</span>
                  <span style={{ color: segmentLedgers.options.realizedPnl >= 0 ? '#10b981' : '#f87171', fontWeight: 800 }}>
                    {segmentLedgers.options.realizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.options.realizedPnl.toFixed(2)}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>4. Open Trades Count:</span>
                  <span style={{ color: '#cbd5e1', fontWeight: 800 }}>{segmentLedgers.options.openCount} Open / {segmentLedgers.options.closedCount} Closed</span>
                </div>
              </div>
            </div>

          </div>

        </div>
      </div>

      {/* Main App Container */}
      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '24px' }}>

        {/* Navigation Tabs */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '14px', marginBottom: '24px' }}>
          {[
            { id: 'capital', label: '📊 3-Pillar Capital Engine', badge: `₹${(segmentLedgers?.grandTotalNetWorth || portfolioSummary?.totalAccountCapital || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` },
            { id: 'swing', label: '⚡ Swing Trading (Kite)', badge: positions.filter(p => p.segment === 'SWING').length },
            { id: 'lt', label: '🛡️ Long-Term Core (INDmoney)', badge: positions.filter(p => p.segment === 'LT').length },
            { id: 'penny', label: '💎 Quality Penny SIP (INDmoney)', badge: positions.filter(p => p.segment === 'PENNY').length },
            { id: 'options', label: '⚡ Options & F&O Log', badge: optionsTrades.length },
            { id: 'adjustments', label: '📜 Broker Adjustments', badge: brokerAdjustments.length },
            { id: 'history', label: '📜 Realized P&L Ledger', badge: soldHistory.length },
            { id: 'riskdesk', label: '🎯 Risk Desk' },
            { id: 'settings', label: '⚙️ Backup & Settings' }
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              style={{
                background: activeTab === t.id ? 'rgba(56, 189, 248, 0.15)' : 'rgba(255, 255, 255, 0.03)',
                border: `1.5px solid ${activeTab === t.id ? '#38bdf8' : 'rgba(255, 255, 255, 0.08)'}`,
                color: activeTab === t.id ? '#ffffff' : '#94a3b8',
                padding: '10px 18px',
                borderRadius: '10px',
                fontWeight: 800,
                fontSize: '13px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                whiteSpace: 'nowrap'
              }}
            >
              <span>{t.label}</span>
              {t.badge !== undefined && (
                <span style={{ fontSize: '11px', padding: '2px 7px', borderRadius: '10px', background: activeTab === t.id ? '#38bdf8' : 'rgba(255,255,255,0.08)', color: activeTab === t.id ? '#090d16' : '#cbd5e1', fontWeight: 900 }}>
                  {t.badge}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* ── TAB 1: CAPITAL ALLOCATOR & ROLLOVER ENGINE ── */}
        {activeTab === 'capital' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            


            {/* 3 Statement-Reconciled Pillar Cards (No Synthetic Capital Math) */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '20px' }}>
              
              {/* Pillar 1: Swing Trading */}
              <div style={{ background: '#0f172a', border: '1.5px solid rgba(56, 189, 248, 0.4)', borderRadius: '16px', padding: '20px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <span style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', fontSize: '11px', fontWeight: 800, padding: '3px 8px', borderRadius: '6px' }}>PILLAR 1 • SWING TRADING</span>
                    <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700 }}>Zerodha Kite</span>
                  </div>
                  <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>⚡ Swing Trading Fund</div>
                  <div style={{ fontSize: '26px', fontWeight: 900, color: '#38bdf8', margin: '8px 0 14px 0' }}>
                    ₹{(segmentLedgers.swing.segmentNetWorth || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 600, marginLeft: '6px' }}>Segment Net Worth</span>
                  </div>
                  
                  <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: '10px', padding: '12px', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>1. Free Cash (Kite):</span>
                      <strong style={{ color: '#38bdf8' }}>₹{(segmentLedgers.swing.freeCash || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>2. Active Holdings Value:</span>
                      <strong style={{ color: '#ffffff' }}>₹{(segmentLedgers.swing.holdingsValue || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>3. Realized P&amp;L (Booked):</span>
                      <strong style={{ color: segmentLedgers.swing.realizedPnl >= 0 ? '#10b981' : '#f87171' }}>{segmentLedgers.swing.realizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.swing.realizedPnl.toFixed(2)}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>4. Unrealized P&amp;L (Open):</span>
                      <strong style={{ color: segmentLedgers.swing.unrealizedPnl >= 0 ? '#10b981' : '#f87171' }}>{segmentLedgers.swing.unrealizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.swing.unrealizedPnl.toFixed(2)}</strong>
                    </div>
                  </div>
                </div>

                <button 
                  onClick={() => { setAddSegment('SWING'); setShowAddModal(true); }}
                  style={{ width: '100%', background: 'linear-gradient(135deg, #0284c7, #38bdf8)', color: '#090d16', border: 'none', padding: '10px', borderRadius: '8px', fontWeight: 900, fontSize: '13px', cursor: 'pointer' }}
                >
                  + Record Swing Buy
                </button>
              </div>

              {/* Pillar 2: Long-Term Quality */}
              <div style={{ background: '#0f172a', border: '1.5px solid rgba(16, 185, 129, 0.4)', borderRadius: '16px', padding: '20px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <span style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', fontSize: '11px', fontWeight: 800, padding: '3px 8px', borderRadius: '6px' }}>PILLAR 2 • LONG-TERM CORE</span>
                    <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700 }}>INDmoney</span>
                  </div>
                  <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>🛡️ Long-Term Core Quality</div>
                  <div style={{ fontSize: '26px', fontWeight: 900, color: '#10b981', margin: '8px 0 14px 0' }}>
                    ₹{(segmentLedgers.lt.segmentNetWorth || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 600, marginLeft: '6px' }}>Segment Net Worth</span>
                  </div>
                  
                  <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: '10px', padding: '12px', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>1. Free Cash (INDmoney):</span>
                      <strong style={{ color: '#10b981' }}>₹{(segmentLedgers.lt.freeCash || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>2. Active Holdings Value:</span>
                      <strong style={{ color: '#ffffff' }}>₹{(segmentLedgers.lt.holdingsValue || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>3. Realized P&amp;L (Booked):</span>
                      <strong style={{ color: segmentLedgers.lt.realizedPnl >= 0 ? '#10b981' : '#f87171' }}>{segmentLedgers.lt.realizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.lt.realizedPnl.toFixed(2)}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>4. Unrealized P&amp;L (Open):</span>
                      <strong style={{ color: segmentLedgers.lt.unrealizedPnl >= 0 ? '#10b981' : '#f87171' }}>{segmentLedgers.lt.unrealizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.lt.unrealizedPnl.toFixed(2)}</strong>
                    </div>
                  </div>
                </div>

                <button 
                  onClick={() => { setAddSegment('LT'); setShowAddModal(true); }}
                  style={{ width: '100%', background: 'linear-gradient(135deg, #059669, #10b981)', color: '#090d16', border: 'none', padding: '10px', borderRadius: '8px', fontWeight: 900, fontSize: '13px', cursor: 'pointer' }}
                >
                  + Record LT Quality Buy
                </button>
              </div>

              {/* Pillar 3: Quality Penny SIP */}
              <div style={{ background: '#0f172a', border: '1.5px solid rgba(192, 132, 252, 0.4)', borderRadius: '16px', padding: '20px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <span style={{ background: 'rgba(192, 132, 252, 0.15)', color: '#c084fc', fontSize: '11px', fontWeight: 800, padding: '3px 8px', borderRadius: '6px' }}>PILLAR 3 • QUALITY PENNY SIP</span>
                    <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700 }}>INDmoney</span>
                  </div>
                  <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>💎 Quality Penny SIP</div>
                  <div style={{ fontSize: '26px', fontWeight: 900, color: '#c084fc', margin: '8px 0 14px 0' }}>
                    ₹{(segmentLedgers.penny.segmentNetWorth || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 600, marginLeft: '6px' }}>Segment Net Worth</span>
                  </div>
                  
                  <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: '10px', padding: '12px', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>1. Free Cash (INDmoney):</span>
                      <strong style={{ color: '#c084fc' }}>₹{(segmentLedgers.penny.freeCash || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>2. Active Holdings Value:</span>
                      <strong style={{ color: '#ffffff' }}>₹{(segmentLedgers.penny.holdingsValue || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>3. Realized P&amp;L (Booked):</span>
                      <strong style={{ color: segmentLedgers.penny.realizedPnl >= 0 ? '#10b981' : '#f87171' }}>{segmentLedgers.penny.realizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.penny.realizedPnl.toFixed(2)}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>4. Unrealized P&amp;L (Open):</span>
                      <strong style={{ color: segmentLedgers.penny.unrealizedPnl >= 0 ? '#10b981' : '#f87171' }}>{segmentLedgers.penny.unrealizedPnl >= 0 ? '+' : ''}₹{segmentLedgers.penny.unrealizedPnl.toFixed(2)}</strong>
                    </div>
                  </div>
                </div>

                <button 
                  onClick={() => { setAddSegment('PENNY'); setShowAddModal(true); }}
                  style={{ width: '100%', background: 'linear-gradient(135deg, #7c3aed, #c084fc)', color: '#090d16', border: 'none', padding: '10px', borderRadius: '8px', fontWeight: 900, fontSize: '13px', cursor: 'pointer' }}
                >
                  + Record Penny SIP Buy
                </button>
              </div>

            </div>


          </div>
        )}

                {/* ── TABS 2, 3, 4: ACTIVE HOLDINGS (SWING, LT, PENNY) ── */}
        {(activeTab === 'swing' || activeTab === 'lt' || activeTab === 'penny') && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            
            {/* Segment Executive Capital & PnL Ribbon */}
            <div style={{ background: 'linear-gradient(135deg, rgba(15,23,42,0.95), rgba(30,41,59,0.8))', border: '1.5px solid rgba(255,255,255,0.1)', borderRadius: '16px', padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
                <div>
                  <div style={{ fontSize: '20px', fontWeight: 900, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {activeTab === 'swing' && '⚡ Active Swing Trading Positions'}
                    {activeTab === 'lt' && '🛡️ Long-Term Core Quality Portfolio'}
                    {activeTab === 'penny' && '💎 Quality Penny SIP Accumulation'}
                  </div>
                  <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                    Broker: <strong style={{ color: activeTab === 'lt' ? '#10b981' : '#38bdf8' }}>{activeTab === 'lt' ? 'INDMONEY (Zero Delivery Brokerage, ₹14.75 DP)' : 'Zerodha Kite (Free Delivery, ₹15.34 DP)'}</strong>
                  </div>
                </div>

                <button 
                  onClick={() => { setAddSegment(activeTab.toUpperCase()); setShowAddModal(true); }}
                  style={{ background: 'linear-gradient(135deg, #0284c7, #38bdf8)', color: '#090d16', border: 'none', padding: '10px 18px', borderRadius: '8px', fontWeight: 900, fontSize: '13px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <PlusCircle size={15} />
                  + Record {activeTab.toUpperCase()} Buy
                </button>
              </div>

              {/* Segment-Specific Metrics Row */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px', background: 'rgba(0,0,0,0.3)', padding: '12px 16px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div>
                  <div style={{ fontSize: '10px', color: '#94a3b8', fontWeight: 800, textTransform: 'uppercase' }}>DEPLOYED CAPITAL</div>
                  <div style={{ fontSize: '16px', fontWeight: 900, color: '#ffffff', marginTop: '2px' }}>
                    ₹{(portfolioSummary[activeTab]?.invested || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#94a3b8', fontWeight: 800, textTransform: 'uppercase' }}>FREE BROKER CASH</div>
                  <div style={{ fontSize: '16px', fontWeight: 900, color: '#10b981', marginTop: '2px' }}>
                    ₹{(portfolioSummary[activeTab]?.freeCash || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#94a3b8', fontWeight: 800, textTransform: 'uppercase' }}>TOTAL SEGMENT CAPITAL</div>
                  <div style={{ fontSize: '16px', fontWeight: 900, color: '#38bdf8', marginTop: '2px' }}>
                    ₹{(portfolioSummary[activeTab]?.totalCap || portfolioSummary[activeTab]?.segmentNetWorth || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#94a3b8', fontWeight: 800, textTransform: 'uppercase' }}>1. GROSS P&amp;L (BROKER)</div>
                  <div style={{ fontSize: '15px', fontWeight: 900, color: (portfolioSummary[activeTab]?.grossPnl || 0) >= 0 ? '#10b981' : '#f87171', marginTop: '2px' }}>
                    {(portfolioSummary[activeTab]?.grossPnl || 0) >= 0 ? '+' : ''}₹{(portfolioSummary[activeTab]?.grossPnl || 0).toFixed(2)}
                    <span style={{ fontSize: '11px', marginLeft: '4px' }}>
                      ({(portfolioSummary[activeTab]?.grossPct || 0) >= 0 ? '+' : ''}{(portfolioSummary[activeTab]?.grossPct || 0).toFixed(2)}%)
                    </span>
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#fbbf24', fontWeight: 800, textTransform: 'uppercase' }}>2. EST. CHARGES</div>
                  <div style={{ fontSize: '15px', fontWeight: 900, color: '#fbbf24', marginTop: '2px' }}>
                    -₹{(portfolioSummary[activeTab]?.estCharges || 0).toFixed(2)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#38bdf8', fontWeight: 800, textTransform: 'uppercase' }}>3. NET P&amp;L (IN POCKET)</div>
                  <div style={{ fontSize: '15px', fontWeight: 900, color: (portfolioSummary[activeTab]?.netPnl || 0) >= 0 ? '#10b981' : '#f87171', marginTop: '2px' }}>
                    {(portfolioSummary[activeTab]?.netPnl || 0) >= 0 ? '+' : ''}₹{(portfolioSummary[activeTab]?.netPnl || 0).toFixed(2)}
                    <span style={{ fontSize: '11px', marginLeft: '4px' }}>
                      ({(portfolioSummary[activeTab]?.netPct || 0) >= 0 ? '+' : ''}{(portfolioSummary[activeTab]?.netPct || 0).toFixed(2)}%)
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Holdings Table */}
            {holdingCards.filter(p => p.segment === activeTab.toUpperCase()).length === 0 ? (
              <div style={{ background: '#0f172a', border: '1.5px dashed rgba(255,255,255,0.12)', borderRadius: '16px', padding: '40px 20px', textAlign: 'center' }}>
                <div style={{ fontSize: '32px', marginBottom: '10px' }}>📂</div>
                <div style={{ fontSize: '15px', fontWeight: 800, color: '#ffffff' }}>No Active {activeTab.toUpperCase()} Holdings</div>
                <div style={{ fontSize: '12px', color: '#94a3b8', maxWidth: '420px', margin: '6px auto 16px' }}>
                  You currently own zero shares in this segment. Capital is safely held as cash reserve.
                </div>
                <button 
                  onClick={() => { setAddSegment(activeTab.toUpperCase()); setShowAddModal(true); }}
                  style={{ background: 'rgba(56, 189, 248, 0.15)', border: '1px solid #38bdf8', color: '#38bdf8', padding: '8px 18px', borderRadius: '8px', fontWeight: 800, fontSize: '12px', cursor: 'pointer' }}
                >
                  + Add Your First Purchase
                </button>
              </div>
            ) : (
              <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '16px', overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                  <thead>
                    <tr style={{ background: 'rgba(255,255,255,0.03)', color: '#94a3b8', textAlign: 'left', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                      <th style={{ padding: '12px 14px' }}>STOCK</th>
                      <th style={{ padding: '12px 14px' }}>QTY</th>
                      <th style={{ padding: '12px 14px' }}>BUY AVG (₹)</th>
                      <th style={{ padding: '12px 14px' }}>INVESTED (₹)</th>
                      <th style={{ padding: '12px 14px' }}>LIVE LTP (₹)</th>
                      <th style={{ padding: '12px 14px' }}>CURRENT VAL (₹)</th>
                      <th style={{ padding: '12px 14px' }}>GROSS P&amp;L (BROKER)</th>
                      <th style={{ padding: '12px 14px' }}>EST. CHARGES</th>
                      <th style={{ padding: '12px 14px' }}>NET P&amp;L (IN POCKET)</th>
                      <th style={{ padding: '12px 14px' }}>HOLDING DAYS</th>
                      {activeTab === 'swing' && <th style={{ padding: '12px 14px' }}>TARGET / SL</th>}
                      <th style={{ padding: '12px 14px', textAlign: 'right' }}>ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdingCards.filter(p => p.segment === activeTab.toUpperCase()).map(h => (
                      <tr key={h.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        <td style={{ padding: '12px 14px' }}>
                          <div style={{ fontWeight: 900, color: '#ffffff', fontSize: '13px' }}>{h.cleanSym}</div>
                          <div style={{ fontSize: '10px', color: '#94a3b8' }}>{h.name}</div>
                        </td>
                        <td style={{ padding: '12px 14px', fontWeight: 800, color: '#a5b4fc' }}>{h.shares}</td>
                        <td style={{ padding: '12px 14px', color: '#cbd5e1' }}>₹{h.buyPrice.toFixed(2)}</td>
                        <td style={{ padding: '12px 14px', fontWeight: 700, color: '#cbd5e1' }}>₹{(h.costBasis || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td style={{ padding: '12px 14px', fontWeight: 900, color: '#38bdf8' }}>₹{h.ltp.toFixed(2)}</td>
                        <td style={{ padding: '12px 14px', fontWeight: 800, color: '#ffffff' }}>₹{(h.currentVal || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td style={{ padding: '12px 14px' }}>
                          <div style={{ fontWeight: 900, color: h.unrealizedPnl >= 0 ? '#10b981' : '#f87171', fontSize: '13px' }}>
                            {h.unrealizedPnl >= 0 ? '+' : ''}₹{h.unrealizedPnl.toFixed(2)}
                          </div>
                          <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                            ({h.pnlPct >= 0 ? '+' : ''}{h.pnlPct.toFixed(2)}%)
                          </div>
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          <div style={{ color: '#fbbf24', fontWeight: 800, fontSize: '12px' }}>
                            -₹{(h.estCharges?.total || 0).toFixed(2)}
                          </div>
                          <div style={{ fontSize: '9px', color: '#94a3b8' }}>
                            STT: ₹{(h.estCharges?.stt || 0).toFixed(1)} | DP: ₹{(h.estCharges?.dp_charges || 0).toFixed(1)}
                          </div>
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          <div style={{ fontWeight: 900, color: (h.unrealizedPnl - (h.estCharges?.total || 0)) >= 0 ? '#10b981' : '#f87171', fontSize: '13px' }}>
                            {(h.unrealizedPnl - (h.estCharges?.total || 0)) >= 0 ? '+' : ''}₹{(h.unrealizedPnl - (h.estCharges?.total || 0)).toFixed(2)}
                          </div>
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          <span style={{ background: 'rgba(255,255,255,0.05)', padding: '3px 8px', borderRadius: '6px', color: '#cbd5e1', fontWeight: 700, fontSize: '11px' }}>
                            {h.holdingDays} day{h.holdingDays === 1 ? '' : 's'}
                          </span>
                        </td>
                        {activeTab === 'swing' && (
                          <td style={{ padding: '12px 14px', fontSize: '11px' }}>
                            <div style={{ color: '#10b981' }}>Tgt: ₹{h.target1 ? h.target1.toFixed(2) : '—'}</div>
                            <div style={{ color: '#f87171' }}>SL: ₹{h.stopLoss ? h.stopLoss.toFixed(2) : '—'}</div>
                          </td>
                        )}
                        <td style={{ padding: '12px 14px', textAlign: 'right' }}>
                          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '6px' }}>
                            <button
                              onClick={() => handleOpenSellModal(h)}
                              style={{ background: 'rgba(16, 185, 129, 0.15)', border: '1px solid #10b981', color: '#10b981', padding: '5px 10px', borderRadius: '6px', fontWeight: 800, fontSize: '11px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}
                            >
                              <DollarSign size={12} />
                              Sell &amp; Exit
                            </button>
                            <button
                              onClick={() => {
                                if (window.confirm(`Delete ${h.cleanSym} record?`)) {
                                  setPositions(prev => prev.filter(p => p.id !== h.id));
                                }
                              }}
                              style={{ background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.25)', color: '#f87171', padding: '5px 8px', borderRadius: '6px', cursor: 'pointer' }}
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

          </div>
        )}

        {/* ── TAB 5: REALIZED SOLD HISTORY LEDGER ── */}
        {activeTab === 'history' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <div style={{ fontSize: '20px', fontWeight: 900, color: '#ffffff' }}>📜 Realized Gains &amp; Tax Journal</div>
                <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                  All historical closed trades with exact Brokerage, STT, and DP charges deducted. Realized capital is automatically recycled into available cash.
                </div>
              </div>

              <button 
                onClick={() => setShowPastSoldModal(true)}
                style={{ background: 'linear-gradient(135deg, #10b981, #06b6d4)', color: '#090d16', border: 'none', padding: '10px 18px', borderRadius: '8px', fontWeight: 900, fontSize: '13px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <PlusCircle size={15} />
                + Record Past Closed Trade
              </button>
            </div>

            {soldHistory.length === 0 ? (
              <div style={{ background: '#0f172a', border: '1.5px dashed rgba(255,255,255,0.12)', borderRadius: '16px', padding: '40px 20px', textAlign: 'center' }}>
                <div style={{ fontSize: '32px', marginBottom: '10px' }}>📜</div>
                <div style={{ fontSize: '15px', fontWeight: 800, color: '#ffffff' }}>No Closed / Sold Trades Yet</div>
                <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                  When you sell any active position, its net realized profit and tax breakdown will appear here.
                </div>
              </div>
            ) : (
              <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '16px', overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                  <thead>
                    <tr style={{ background: 'rgba(255,255,255,0.03)', color: '#94a3b8', textAlign: 'left', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                      <th style={{ padding: '12px 14px' }}>STOCK &amp; SEGMENT</th>
                      <th style={{ padding: '12px 14px' }}>QTY</th>
                      <th style={{ padding: '12px 14px' }}>BUY AVG (₹)</th>
                      <th style={{ padding: '12px 14px' }}>SELL PRICE (₹)</th>
                      <th style={{ padding: '12px 14px' }}>HOLD DURATION</th>
                      <th style={{ padding: '12px 14px' }}>GROSS P&amp;L</th>
                      <th style={{ padding: '12px 14px' }}>BROKER / TAXES</th>
                      <th style={{ padding: '12px 14px' }}>NET REALIZED P&amp;L</th>
                      <th style={{ padding: '12px 14px', textAlign: 'right' }}>ACTION</th>
                    </tr>
                  </thead>
                  <tbody>
                    {soldHistory.map((s, idx) => (
                      <tr key={s.id || idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        <td style={{ padding: '12px 14px' }}>
                          <div style={{ fontWeight: 900, color: '#ffffff' }}>{s.ticker.replace('.NS', '')}</div>
                          <div style={{ fontSize: '10px', color: '#a5b4fc', fontWeight: 700 }}>{s.segment} • {s.broker}</div>
                        </td>
                        <td style={{ padding: '12px 14px', fontWeight: 800 }}>{s.shares}</td>
                        <td style={{ padding: '12px 14px', color: '#cbd5e1' }}>₹{Number(s.buyPrice).toFixed(2)}</td>
                        <td style={{ padding: '12px 14px', fontWeight: 800, color: '#38bdf8' }}>₹{Number(s.sellPrice).toFixed(2)}</td>
                        <td style={{ padding: '12px 14px', color: '#cbd5e1' }}>{s.holdingDays} day{s.holdingDays === 1 ? '' : 's'}</td>
                        <td style={{ padding: '12px 14px', fontWeight: 800, color: s.grossPnl >= 0 ? '#10b981' : '#f87171' }}>
                          {s.grossPnl >= 0 ? '+' : ''}₹{Number(s.grossPnl).toFixed(2)}
                        </td>
                        <td style={{ padding: '12px 14px', color: '#fbbf24', fontSize: '11px' }}>
                          -₹{Number(s.taxes).toFixed(2)}
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          <div style={{ fontWeight: 900, fontSize: '13px', color: s.netPnl >= 0 ? '#10b981' : '#f87171' }}>
                            {s.netPnl >= 0 ? '+' : ''}₹{Number(s.netPnl).toFixed(2)}
                          </div>
                          <div style={{ fontSize: '10px', color: s.returnPct >= 0 ? '#10b981' : '#f87171' }}>
                            ({s.returnPct >= 0 ? '+' : ''}{Number(s.returnPct).toFixed(2)}%)
                          </div>
                        </td>
                        <td style={{ padding: '12px 14px', textAlign: 'right' }}>
                          <button 
                            onClick={() => {
                              if (window.confirm('Delete this sold history entry?')) {
                                setSoldHistory(prev => prev.filter(item => item.id !== s.id));
                              }
                            }}
                            style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', padding: '4px' }}
                          >
                            <Trash2 size={13} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

          </div>
        )}

        {/* ── TAB 6: BACKUP & SETTINGS ── */}
        {/* ── TAB: RISK DESK — opportunity-based fund & risk manager ── */}
        {activeTab === 'riskdesk' && (
          <RiskDesk externalLtps={liveLtps} />
        )}

        {activeTab === 'settings' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '700px' }}>
            <div style={{ fontSize: '20px', fontWeight: 900, color: '#ffffff' }}>⚙️ Master JSON Backups &amp; Data Integrity</div>
            
            <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '16px', padding: '20px' }}>
              <div style={{ fontSize: '14px', fontWeight: 800, color: '#ffffff', marginBottom: '8px' }}>Export Master Portfolio Backup</div>
              <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '14px' }}>
                Download a clean JSON snapshot containing all your 25% income allocations, capital events, active holdings, and sold trades.
              </div>
              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                <button 
                  onClick={() => {
                    const backupData = {
                      version: '3pillar_v1',
                      timestamp: new Date().toISOString(),
                      monthly_budget: monthlyBudgetInput,
                      split_swing: swingPct,
                      split_lt: ltPct,
                      split_penny: pennyPct,
                      swing_free_cash: swingFreeCashInput,
                      lt_free_cash: ltFreeCashInput,
                      penny_free_cash: pennyFreeCashInput,
                      capital_ledger: capitalLedger,
                      positions,
                      sold_history: soldHistory
                    };
                    const blob = new Blob([JSON.stringify(backupData, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `finplus_3pillar_backup_${new Date().toISOString().split('T')[0]}.json`;
                    a.click();
                    showToast('✅ Master backup downloaded successfully!');
                  }}
                  style={{ background: 'linear-gradient(135deg, #0284c7, #38bdf8)', color: '#090d16', border: 'none', padding: '10px 18px', borderRadius: '8px', fontWeight: 900, fontSize: '13px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <Download size={14} />
                  Download JSON Backup
                </button>

                <label style={{ background: 'rgba(16, 185, 129, 0.15)', border: '1px solid #10b981', color: '#10b981', padding: '10px 18px', borderRadius: '8px', fontWeight: 800, fontSize: '13px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Upload size={14} />
                  Restore / Import JSON Backup
                  <input
                    type="file"
                    accept=".json"
                    style={{ display: 'none' }}
                    onChange={e => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      const reader = new FileReader();
                      reader.onload = (event) => {
                        try {
                          const data = JSON.parse(event.target.result);
                          if (data.positions) setPositions(data.positions);
                          if (data.sold_history) setSoldHistory(data.sold_history);
                          if (data.capital_ledger) setCapitalLedger(data.capital_ledger);
                          if (data.monthly_budget) setMonthlyBudgetInput(data.monthly_budget);
                          if (data.swing_free_cash !== undefined) {
                            setSwingFreeCashInput(String(data.swing_free_cash));
                            localStorage.setItem('finplus_free_cash_swing', String(data.swing_free_cash));
                          }
                          if (data.lt_free_cash !== undefined) {
                            setLtFreeCashInput(String(data.lt_free_cash));
                            localStorage.setItem('finplus_free_cash_lt', String(data.lt_free_cash));
                          }
                          if (data.penny_free_cash !== undefined) {
                            setPennyFreeCashInput(String(data.penny_free_cash));
                            localStorage.setItem('finplus_free_cash_penny', String(data.penny_free_cash));
                          }
                          showToast('✅ Master backup restored successfully!');
                        } catch (err) {
                          showToast('❌ Invalid JSON backup file.');
                        }
                      };
                      reader.readAsText(file);
                    }}
                  />
                </label>
              </div>
            </div>

            {/* ── DANGER ZONE: START AFRESH / RESET ── */}
            <div style={{ background: 'rgba(239, 68, 68, 0.05)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: '16px', padding: '20px' }}>
              <div style={{ fontSize: '14px', fontWeight: 800, color: '#f87171', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <RotateCcw size={16} color="#f87171" />
                Start Afresh / Reset All Numbers
              </div>
              <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '14px', lineHeight: '1.5' }}>
                Removes all active holdings, past closed trades, options contracts, ledger entries, and resets free cash balances to ₹0 for starting afresh. Your capital splits (Swing/LT/Penny), formulas, and risk limits remain completely intact.
              </div>
              <button
                onClick={async () => {
                  if (!window.confirm("⚠️ START AFRESH CONFIRMATION\n\nAre you sure you want to remove all positions, closed trades, options trades, ledger events, and set cash to ₹0?\n\nAll your configuration, split ratios, and risk rules will remain intact.")) {
                    return;
                  }
                  const freshTimestamp = Date.now();
                  setPositions([]);
                  setSoldHistory([]);
                  setOptionsTrades([]);
                  setCapitalLedger([]);
                  setBrokerAdjustments([]);
                  setSwingFreeCashInput('0');
                  setLtFreeCashInput('0');
                  setPennyFreeCashInput('0');
                  setMonthlyBudgetInput('0');
                  setLiveLtps({});

                  localStorage.setItem(STORAGE_KEY, JSON.stringify([]));
                  localStorage.setItem(LEDGER_KEY, JSON.stringify([]));
                  localStorage.setItem('finplus_sold_history_v1', JSON.stringify([]));
                  localStorage.setItem('finplus_broker_adjustments_v1', JSON.stringify([]));
                  localStorage.setItem('finplus_options_trades_v1', JSON.stringify([]));
                  localStorage.setItem(FREE_CASH_SWING_KEY, '0');
                  localStorage.setItem('finplus_free_cash_swing_v5', '0');
                  localStorage.setItem(FREE_CASH_LT_KEY, '0');
                  localStorage.setItem('finplus_free_cash_penny_v4', '0');
                  localStorage.setItem('finplus_monthly_income_budget', '0');
                  localStorage.setItem('finplus_pnl_v4_fresh', JSON.stringify([]));
                  localStorage.setItem(SAVED_AT_KEY, String(freshTimestamp));

                  const cleanPayload = {
                    positions: [],
                    capitalLedger: [],
                    soldHistory: [],
                    brokerAdjustments: [],
                    optionsTrades: [],
                    freeCash: { swing: '0', lt: '0', penny: '0' },
                    budget: '0',
                    split: { swing: swingPct, lt: ltPct, penny: pennyPct },
                    savedAt: freshTimestamp,
                    force_reset: true,
                    reset: true,
                    isFreshStart: true
                  };

                  const endpoints = Array.from(new Set([API_BASE_URL, RENDER_BACKEND_URL].filter(Boolean)));
                  for (const ep of endpoints) {
                    try {
                      await fetch(`${ep}/api/backup/save`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(cleanPayload)
                      });
                    } catch(e) {}
                  }
                  showToast('✨ Clean slate established! App ready for fresh start.');
                }}
                style={{
                  background: 'linear-gradient(135deg, #dc2626, #ef4444)',
                  color: '#ffffff',
                  border: 'none',
                  padding: '10px 20px',
                  borderRadius: '8px',
                  fontWeight: 900,
                  fontSize: '13px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  boxShadow: '0 4px 14px rgba(239, 68, 68, 0.3)'
                }}
              >
                <RotateCcw size={14} />
                Start Afresh (Reset Numbers to 0)
              </button>
            </div>
          </div>
        )}

      </div>

            {/* ── MODAL: RECORD PAST CLOSED TRADE ── */}
      {showPastSoldModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
          <div style={{ background: '#0f172a', border: '1.5px solid rgba(16, 185, 129, 0.4)', borderRadius: '16px', padding: '24px', width: '100%', maxWidth: '520px', boxShadow: '0 20px 50px rgba(0,0,0,0.6)', maxHeight: '90vh', overflowY: 'auto' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>Record Past Closed Trade</div>
              <button onClick={() => setShowPastSoldModal(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <form onSubmit={handlePastSoldSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              
              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>PILLAR / SEGMENT</label>
                <select 
                  value={pastSoldSegment} 
                  onChange={e => setPastSoldSegment(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}
                >
                  <option value="SWING">⚡ Swing Trading (Zerodha Kite)</option>
                  <option value="LT">🛡️ Long-Term Core (INDMONEY)</option>
                  <option value="PENNY">💎 Quality Penny SIP (Zerodha Kite)</option>
                </select>
              </div>

              <div style={{ position: 'relative' }}>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>
                  STOCK SYMBOL (NSE) <span style={{ color: '#38bdf8', fontSize: '10px', fontWeight: 600 }}>• Auto-search 2,414 stocks</span>
                </label>
                <input 
                  type="text" 
                  placeholder="Type symbol or company name (e.g. REL, TATA, TIMEX)..." 
                  value={pastSoldTicker} 
                  onChange={e => {
                    setPastSoldTicker(e.target.value.toUpperCase());
                    setShowPastSoldSuggestions(true);
                  }}
                  onFocus={() => setShowPastSoldSuggestions(true)}
                  required
                  autoComplete="off"
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(56, 189, 248, 0.4)', color: '#ffffff', padding: '10px 12px', borderRadius: '8px', fontWeight: 800, fontSize: '13px' }}
                />

                {showPastSoldSuggestions && pastSoldSuggestions.length > 0 && (
                  <div style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    right: 0,
                    zIndex: 1000,
                    background: '#0b1120',
                    border: '1.5px solid #38bdf8',
                    borderRadius: '8px',
                    marginTop: '4px',
                    maxHeight: '200px',
                    overflowY: 'auto',
                    boxShadow: '0 12px 30px rgba(0,0,0,0.8)'
                  }}>
                    {pastSoldSuggestions.map((item, idx) => (
                      <div
                        key={item.symbol || idx}
                        onClick={() => {
                          setPastSoldTicker(item.symbol);
                          setPastSoldName(item.name || item.symbol);
                          setShowPastSoldSuggestions(false);
                        }}
                        style={{ padding: '10px 14px', borderBottom: idx < pastSoldSuggestions.length - 1 ? '1px solid rgba(255,255,255,0.06)' : 'none', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                        onMouseEnter={e => e.currentTarget.style.background = 'rgba(56, 189, 248, 0.15)'}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                      >
                        <div>
                          <div style={{ fontWeight: 900, color: '#38bdf8', fontSize: '13px' }}>{item.symbol}</div>
                          <div style={{ fontSize: '11px', color: '#cbd5e1' }}>{item.name}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SHARES (QTY)</label>
                  <input 
                    type="number" 
                    min="1" 
                    value={pastSoldShares} 
                    onChange={e => setPastSoldShares(e.target.value)}
                    required
                    style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>BUY PRICE (₹)</label>
                  <input 
                    type="number" 
                    step="0.05" 
                    placeholder="e.g. 450.00" 
                    value={pastSoldBuyPrice} 
                    onChange={e => setPastSoldBuyPrice(e.target.value)}
                    required
                    style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>BUY DATE</label>
                  <input 
                    type="date" 
                    value={pastSoldBuyDate} 
                    onChange={e => setPastSoldBuyDate(e.target.value)}
                    style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SELL / EXIT PRICE (₹)</label>
                  <input 
                    type="number" 
                    step="0.05" 
                    placeholder="e.g. 500.00" 
                    value={pastSoldSellPrice} 
                    onChange={e => setPastSoldSellPrice(e.target.value)}
                    required
                    style={{ width: '100%', background: '#090d16', border: '1.5px solid #38bdf8', color: '#38bdf8', fontSize: '16px', padding: '10px', borderRadius: '8px', fontWeight: 900 }}
                  />
                </div>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SELL / EXIT DATE</label>
                <input 
                  type="date" 
                  value={pastSoldSellDate} 
                  onChange={e => setPastSoldSellDate(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }}
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>EXIT NOTES / REASON (OPTIONAL)</label>
                <input 
                  type="text" 
                  placeholder="e.g. Hit 1:2 R:R Target, Trailing SL hit, etc." 
                  value={pastSoldNotes} 
                  onChange={e => setPastSoldNotes(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button 
                  type="button" 
                  onClick={() => setShowPastSoldModal(false)}
                  style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', color: '#cbd5e1', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 700 }}
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  style={{ background: 'linear-gradient(135deg, #10b981, #06b6d4)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}
                >
                  Record Closed Trade
                </button>
              </div>

            </form>

          </div>
        </div>
      )}

      {/* ── MODAL: RECORD NEW BUY ── */}
      {showAddModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
          <div style={{ background: '#0f172a', border: '1.5px solid rgba(56, 189, 248, 0.4)', borderRadius: '16px', padding: '24px', width: '100%', maxWidth: '480px', boxShadow: '0 20px 50px rgba(0,0,0,0.6)' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>Record New Purchase</div>
              <button onClick={() => setShowAddModal(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <form onSubmit={handleAddPositionSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              
              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SELECT PILLAR / SEGMENT</label>
                <select 
                  value={addSegment} 
                  onChange={e => setAddSegment(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}
                >
                  <option value="SWING">⚡ Swing Trading (Zerodha Kite) — Free Cash: ₹{(segmentLedgers?.swing?.freeCash || 0).toLocaleString('en-IN')}</option>
                  <option value="LT">🛡️ Long-Term Core (INDMONEY) — Free Cash: ₹{(segmentLedgers?.lt?.freeCash || 0).toLocaleString('en-IN')}</option>
                  <option value="PENNY">💎 Quality Penny SIP (INDmoney) — Free Cash: ₹{(segmentLedgers?.penny?.freeCash || 0).toLocaleString('en-IN')}</option>
                </select>
              </div>

              <div style={{ position: 'relative' }}>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>
                  STOCK SYMBOL (NSE) <span style={{ color: '#38bdf8', fontSize: '10px', fontWeight: 600 }}>• Auto-search 2,414 stocks</span>
                </label>
                <input 
                  type="text" 
                  placeholder="Type symbol or company name (e.g. REL, TATA, TIMEX)..." 
                  value={formTicker} 
                  onChange={e => {
                    setFormTicker(e.target.value.toUpperCase());
                    setShowSuggestions(true);
                  }}
                  onFocus={() => setShowSuggestions(true)}
                  required
                  autoComplete="off"
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(56, 189, 248, 0.4)', color: '#ffffff', padding: '10px 12px', borderRadius: '8px', fontWeight: 800, fontSize: '13px' }}
                />

                {/* Autocomplete Dropdown */}
                {showSuggestions && stockSuggestions.length > 0 && (
                  <div style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    right: 0,
                    zIndex: 1000,
                    background: '#0b1120',
                    border: '1.5px solid #38bdf8',
                    borderRadius: '8px',
                    marginTop: '4px',
                    maxHeight: '220px',
                    overflowY: 'auto',
                    boxShadow: '0 12px 30px rgba(0,0,0,0.8)'
                  }}>
                    {stockSuggestions.map((item, idx) => (
                      <div
                        key={item.symbol || idx}
                        onClick={() => {
                          setFormTicker(item.symbol);
                          setFormName(item.name || item.symbol);
                          if (item.ltp && item.ltp > 0 && !formBuyPrice) {
                            setFormBuyPrice(String(item.ltp));
                          }
                          setShowSuggestions(false);
                        }}
                        style={{
                          padding: '10px 14px',
                          borderBottom: idx < stockSuggestions.length - 1 ? '1px solid rgba(255,255,255,0.06)' : 'none',
                          cursor: 'pointer',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          transition: 'background 0.15s ease'
                        }}
                        onMouseEnter={e => e.currentTarget.style.background = 'rgba(56, 189, 248, 0.15)'}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                      >
                        <div>
                          <div style={{ fontWeight: 900, color: '#38bdf8', fontSize: '13px' }}>
                            {item.symbol}
                          </div>
                          <div style={{ fontSize: '11px', color: '#cbd5e1', marginTop: '1px' }}>
                            {item.name}
                          </div>
                        </div>
                        {item.ltp > 0 && (
                          <div style={{ textAlign: 'right' }}>
                            <div style={{ fontSize: '12px', fontWeight: 800, color: '#10b981' }}>
                              ₹{Number(item.ltp).toFixed(2)}
                            </div>
                            <div style={{ fontSize: '9px', color: '#94a3b8' }}>Latest LTP</div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SHARES</label>
                  <input 
                    type="number" 
                    min="1" 
                    value={formShares} 
                    onChange={e => setFormShares(e.target.value)}
                    required
                    style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>BUY PRICE (₹)</label>
                  <input 
                    type="number" 
                    step="any" 
                    placeholder="e.g. 19.33" 
                    value={formBuyPrice} 
                    onChange={e => setFormBuyPrice(e.target.value)}
                    required
                    style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}
                  />
                </div>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>PURCHASE DATE</label>
                <input 
                  type="date" 
                  value={formBuyDate} 
                  onChange={e => setFormBuyDate(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }}
                />
              </div>

              {addSegment === 'SWING' && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  <div>
                    <label style={{ fontSize: '11px', color: '#10b981', fontWeight: 700, display: 'block', marginBottom: '4px' }}>TARGET 1:2 R:R (₹)</label>
                    <input 
                      type="number" 
                      step="any" 
                      placeholder="Optional target" 
                      value={formTarget1} 
                      onChange={e => setFormTarget1(e.target.value)}
                      style={{ width: '100%', background: '#090d16', border: '1px solid rgba(16, 185, 129, 0.3)', color: '#ffffff', padding: '10px', borderRadius: '8px' }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: '11px', color: '#f87171', fontWeight: 700, display: 'block', marginBottom: '4px' }}>STOP LOSS (₹)</label>
                    <input 
                      type="number" 
                      step="any" 
                      placeholder="Optional SL" 
                      value={formStopLoss} 
                      onChange={e => setFormStopLoss(e.target.value)}
                      style={{ width: '100%', background: '#090d16', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#ffffff', padding: '10px', borderRadius: '8px' }}
                    />
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button 
                  type="button" 
                  onClick={() => setShowAddModal(false)}
                  style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', color: '#cbd5e1', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 700 }}
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  style={{ background: 'linear-gradient(135deg, #0284c7, #38bdf8)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}
                >
                  Record Purchase
                </button>
              </div>

            </form>

          </div>
        </div>
      )}

      {/* ── MODAL: SELL & EXIT POSITION ── */}
      {sellModalPos && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
          <div style={{ background: '#0f172a', border: '1.5px solid #10b981', borderRadius: '16px', padding: '24px', width: '100%', maxWidth: '440px', boxShadow: '0 20px 50px rgba(0,0,0,0.6)' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>Sell &amp; Realize Trade</div>
                <div style={{ fontSize: '11px', color: '#a5b4fc' }}>{sellModalPos.cleanSym} • {sellModalPos.segment} ({sellModalPos.segment === 'LT' ? 'INDMONEY' : 'Zerodha Kite'})</div>
              </div>
              <button onClick={() => setSellModalPos(null)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <form onSubmit={handleSellSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              
              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SHARES TO SELL (MAX {sellModalPos.shares})</label>
                <input 
                  type="number" 
                  min="1" 
                  max={sellModalPos.shares}
                  value={sellFormShares} 
                  onChange={e => setSellFormShares(e.target.value)}
                  required
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>EXIT / SALE PRICE (₹)</label>
                <input 
                  type="number" 
                  step="any" 
                  value={sellFormPrice} 
                  onChange={e => setSellFormPrice(e.target.value)}
                  required
                  style={{ width: '100%', background: '#090d16', border: '1px solid #10b981', color: '#10b981', fontSize: '18px', padding: '10px', borderRadius: '8px', fontWeight: 900 }}
                />
              </div>

              {/* ── LIVE P&L PREVIEW (auto-calculates on every keystroke) ── */}
              {(() => {
                const qty = Number(sellFormShares) || 0;
                const exitP = Number(sellFormPrice) || 0;
                if (qty <= 0 || exitP <= 0 || !sellModalPos) return null;
                const preview = sellModalPos.segment === 'LT'
                  ? calculateINDmoneyCharges({ entry_price: sellModalPos.buyPrice, exit_price: exitP, quantity: qty })
                  : calculateKiteDeliveryCharges({ entry_price: sellModalPos.buyPrice, exit_price: exitP, quantity: qty });
                const isProfit = preview.net_pnl >= 0;
                const color = isProfit ? '#10b981' : '#f87171';
                const currentFreeCash = sellModalPos.segment === 'SWING' ? swingFreeCash
                  : sellModalPos.segment === 'LT' ? ltFreeCash : pennyFreeCash;
                const newFreeCash = currentFreeCash + (exitP * qty) - preview.total;
                return (
                  <div style={{ background: isProfit ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)', border: `1px solid ${isProfit ? 'rgba(16,185,129,0.35)' : 'rgba(239,68,68,0.35)'}`, borderRadius: '10px', padding: '14px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 800, marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      📊 Live P&amp;L Preview
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
                      <div style={{ color: '#94a3b8' }}>Invested</div>
                      <div style={{ color: '#ffffff', fontWeight: 700, textAlign: 'right' }}>₹{(sellModalPos.buyPrice * qty).toFixed(2)}</div>
                      <div style={{ color: '#94a3b8' }}>Sale Value</div>
                      <div style={{ color: '#ffffff', fontWeight: 700, textAlign: 'right' }}>₹{(exitP * qty).toFixed(2)}</div>
                      <div style={{ color: '#94a3b8' }}>Gross P&amp;L</div>
                      <div style={{ color: preview.gross_pnl >= 0 ? '#10b981' : '#f87171', fontWeight: 700, textAlign: 'right' }}>
                        {preview.gross_pnl >= 0 ? '+' : ''}₹{preview.gross_pnl.toFixed(2)}
                      </div>
                      <div style={{ color: '#94a3b8' }}>Est. Charges (STT+DP+Tax)</div>
                      <div style={{ color: '#f87171', fontWeight: 700, textAlign: 'right' }}>-₹{preview.total.toFixed(2)}</div>
                      <div style={{ borderTop: `1px solid ${isProfit ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`, paddingTop: '8px', color: color, fontWeight: 900, fontSize: '13px' }}>NET P&amp;L</div>
                      <div style={{ borderTop: `1px solid ${isProfit ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`, paddingTop: '8px', color, fontWeight: 900, fontSize: '13px', textAlign: 'right' }}>
                        {isProfit ? '+' : ''}₹{preview.net_pnl.toFixed(2)}
                      </div>
                      <div style={{ color: '#a5b4fc', fontSize: '11px', marginTop: '4px' }}>Free Cash after sale</div>
                      <div style={{ color: '#a5b4fc', fontWeight: 700, textAlign: 'right', fontSize: '11px', marginTop: '4px' }}>₹{newFreeCash.toFixed(2)}</div>
                    </div>
                  </div>
                );
              })()}

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SALE DATE</label>
                <input 
                  type="date" 
                  value={sellFormDate} 
                  onChange={e => setSellFormDate(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button 
                  type="button" 
                  onClick={() => setSellModalPos(null)}
                  style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', color: '#cbd5e1', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 700 }}
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  style={{ background: Number(sellFormPrice) > 0 && Number(sellFormPrice) < sellModalPos.buyPrice ? 'linear-gradient(135deg, #dc2626, #f87171)' : 'linear-gradient(135deg, #059669, #10b981)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}
                >
                  {Number(sellFormPrice) > 0 && Number(sellFormPrice) < sellModalPos.buyPrice ? '⚠️ Confirm Loss & Record' : 'Confirm Sale & Recycle Capital'}
                </button>
              </div>

            </form>

          </div>
        </div>
      )}

      {/* ── MODAL: LOG CAPITAL EVENT (INJECTION / WITHDRAWAL) ── */}
      {showCapModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
          <div style={{ background: '#0f172a', border: '1.5px solid #10b981', borderRadius: '16px', padding: '24px', width: '100%', maxWidth: '440px', boxShadow: '0 20px 50px rgba(0,0,0,0.6)' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>Log Capital Event</div>
              <button onClick={() => setShowCapModal(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <form onSubmit={handleCapEventSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              
              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>EVENT TYPE</label>
                <select 
                  value={capEventType} 
                  onChange={e => setCapEventType(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}
                >
                  <option value="INJECTION">➕ Capital Injection (Fresh Deposit / 25% Savings)</option>
                  <option value="WITHDRAWAL">➖ Capital Withdrawal (Cash Taken Out)</option>
                  <option value="ADJUSTMENT_LOSS">📉 Other Loss / Adjustment (Intraday, Options, Charges)</option>
                  <option value="ADJUSTMENT_GAIN">📈 Other Gain / Adjustment (Intraday Gain, Dividends, Broker Credit)</option>
                </select>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>TARGET SEGMENT</label>
                <select 
                  value={capEventSegment} 
                  onChange={e => setCapEventSegment(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}
                >
                  <option value="ALL">🌐 All Segments (Auto-split 60% Swing, 30% LT, 10% Penny)</option>
                  <option value="SWING">⚡ Swing Trading Only</option>
                  <option value="LT">🛡️ Long-Term Core Only</option>
                  <option value="PENNY">💎 Quality Penny Only</option>
                </select>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>AMOUNT (₹ - Whole Rupees)</label>
                <input 
                  type="number" 
                  step="1" 
                  placeholder="e.g. 1312" 
                  value={capEventAmount} 
                  onChange={e => setCapEventAmount(e.target.value)}
                  required
                  style={{ width: '100%', background: '#090d16', border: '1.5px solid #10b981', color: '#10b981', fontSize: '20px', padding: '10px', borderRadius: '8px', fontWeight: 900 }}
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>NOTES / DESCRIPTION</label>
                <input 
                  type="text" 
                  placeholder="e.g. August 2026 25% Income Allocation" 
                  value={capEventNotes} 
                  onChange={e => setCapEventNotes(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button 
                  type="button" 
                  onClick={() => setShowCapModal(false)}
                  style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', color: '#cbd5e1', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 700 }}
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  style={{ background: 'linear-gradient(135deg, #059669, #10b981)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}
                >
                  Log Event
                </button>
              </div>

            </form>

          </div>
        </div>
      )}

      {/* ── MODAL: ALIGN / ADJUST BROKER FREE CASH ── */}
      {showCashAdjModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
          <div style={{ background: '#0f172a', border: '1.5px solid #10b981', borderRadius: '16px', padding: '24px', width: '100%', maxWidth: '440px', boxShadow: '0 20px 50px rgba(0,0,0,0.6)' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>⚙️ Align Broker Free Cash</div>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>Match system free cash with your exact Zerodha / INDmoney statement balance</div>
              </div>
              <button onClick={() => setShowCashAdjModal(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <form onSubmit={(e) => {
              e.preventDefault();
              setSwingFreeCashInput(adjSwingCash);
              setLtFreeCashInput(adjLtCash);
              setPennyFreeCashInput(adjPennyCash);
              setShowCashAdjModal(false);
              showToast('✅ Broker Free Cash balances aligned and synchronized successfully!');
            }} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

              <div>
                <label style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 800, display: 'block', marginBottom: '4px' }}>⚡ SWING FREE CASH (Kite)</label>
                <input 
                  type="number" 
                  step="any"
                  value={adjSwingCash} 
                  onChange={e => setAdjSwingCash(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid #38bdf8', color: '#38bdf8', fontSize: '18px', padding: '10px', borderRadius: '8px', fontWeight: 900 }}
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#10b981', fontWeight: 800, display: 'block', marginBottom: '4px' }}>🛡️ LONG-TERM FREE CASH (INDmoney)</label>
                <input 
                  type="number" 
                  step="any"
                  value={adjLtCash} 
                  onChange={e => setAdjLtCash(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid #10b981', color: '#10b981', fontSize: '18px', padding: '10px', borderRadius: '8px', fontWeight: 900 }}
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#c084fc', fontWeight: 800, display: 'block', marginBottom: '4px' }}>💎 PENNY SIP FREE CASH (Kite)</label>
                <input 
                  type="number" 
                  step="any"
                  value={adjPennyCash} 
                  onChange={e => setAdjPennyCash(e.target.value)}
                  style={{ width: '100%', background: '#090d16', border: '1px solid #c084fc', color: '#c084fc', fontSize: '18px', padding: '10px', borderRadius: '8px', fontWeight: 900 }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button 
                  type="button" 
                  onClick={() => setShowCashAdjModal(false)}
                  style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', color: '#cbd5e1', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 700 }}
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  style={{ background: 'linear-gradient(135deg, #059669, #10b981)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}
                >
                  Align &amp; Save Cash
                </button>
              </div>

            </form>

          </div>
        </div>
      )}

      {/* ── MODAL: LOG BROKER ADJUSTMENT (SECTION 4 SPEC) ── */}
      {showLogAdjModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
          <div style={{ background: '#0f172a', border: '1.5px solid #f59e0b', borderRadius: '16px', padding: '24px', width: '100%', maxWidth: '460px', boxShadow: '0 20px 50px rgba(0,0,0,0.6)' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>📜 Log Broker Adjustment</div>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>Log non-trade cash movements (AMC fees, DP charges, Dividends, Interest, Corrections)</div>
              </div>
              <button onClick={() => setShowLogAdjModal(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <form onSubmit={(e) => {
              e.preventDefault();
              if (!logAdjAmount || isNaN(logAdjAmount)) return;
              const newAdj = {
                id: `adj_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
                date: logAdjDate,
                broker: logAdjBroker,
                segment: logAdjSegment,
                type: logAdjType,
                amount: parseFloat(logAdjAmount),
                notes: logAdjNotes
              };
              setBrokerAdjustments(prev => [newAdj, ...prev]);
              setShowLogAdjModal(false);
              setLogAdjAmount('');
              setLogAdjNotes('');
              showToast('✅ Broker Adjustment logged to cash ledger!');
            }} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>DATE</label>
                  <input type="date" value={logAdjDate} onChange={e => setLogAdjDate(e.target.value)} required style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }} />
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>BROKER</label>
                  <select value={logAdjBroker} onChange={e => setLogAdjBroker(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}>
                    <option value="Zerodha Kite">Zerodha Kite</option>
                    <option value="INDmoney">INDmoney</option>
                  </select>
                </div>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>TARGET SEGMENT</label>
                <select value={logAdjSegment} onChange={e => setLogAdjSegment(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}>
                  <option value="SWING">⚡ Swing Trading</option>
                  <option value="LT">🛡️ Long-Term Core</option>
                  <option value="PENNY">💎 Quality Penny SIP</option>
                  <option value="OPTIONS">⚡ Options / F&amp;O</option>
                  <option value="ALL">🌐 All Segments</option>
                </select>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>ADJUSTMENT TYPE</label>
                <select value={logAdjType} onChange={e => setLogAdjType(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}>
                  <option value="AMC_CHARGE">🔴 AMC Charge (- Debit)</option>
                  <option value="DP_CHARGE">🔴 DP Charge (- Debit)</option>
                  <option value="PLEDGE_CHARGE">🔴 Pledge / Margin Fee (- Debit)</option>
                  <option value="MANUAL_WITHDRAWAL">🔴 Manual Capital Withdrawal (- Debit)</option>
                  <option value="INTEREST_CREDIT">🟢 Interest Credit (+ Credit)</option>
                  <option value="DIVIDEND_RECEIVED">🟢 Dividend Received (+ Credit)</option>
                  <option value="MANUAL_INJECTION">🟢 Manual Capital Injection (+ Credit)</option>
                  <option value="CORRECTION">⚠️ Correction (Broker Error / EOD Audit)</option>
                  <option value="OTHER">ℹ️ Other Adjustment</option>
                </select>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>AMOUNT (₹)</label>
                <input type="number" step="any" placeholder="e.g. 150 or -150" value={logAdjAmount} onChange={e => setLogAdjAmount(e.target.value)} required style={{ width: '100%', background: '#090d16', border: '1.5px solid #f59e0b', color: '#f59e0b', fontSize: '18px', padding: '10px', borderRadius: '8px', fontWeight: 900 }} />
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>AUDIT NOTES (Mandatory for Corrections)</label>
                <input type="text" placeholder="e.g. Q2 Zerodha AMC Fee" value={logAdjNotes} onChange={e => setLogAdjNotes(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }} />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button type="button" onClick={() => setShowLogAdjModal(false)} style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', color: '#cbd5e1', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 700 }}>Cancel</button>
                <button type="submit" style={{ background: 'linear-gradient(135deg, #f59e0b, #d97706)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}>Log Adjustment</button>
              </div>
            </form>

          </div>
        </div>
      )}

      {/* ── MODAL: RECORD OPTIONS TRADE (SECTION 3 SPEC) ── */}
      {showAddOptionModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
          <div style={{ background: '#0f172a', border: '1.5px solid #c084fc', borderRadius: '16px', padding: '24px', width: '100%', maxWidth: '480px', boxShadow: '0 20px 50px rgba(0,0,0,0.6)' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>⚡ Record Options / F&amp;O Trade</div>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>Event log with mandatory "Funded By" origin segment traceability</div>
              </div>
              <button onClick={() => setShowAddOptionModal(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <form onSubmit={(e) => {
              e.preventDefault();
              if (!optInstrument || !optEntryPrice) return;
              const entryP = parseFloat(optEntryPrice) || 0;
              const exitP = parseFloat(optExitPrice) || 0;
              const qty = parseInt(optQty, 10) || 1;
              const chg = parseFloat(optCharges) || 40;
              const netPnl = optStatus === 'CLOSED' ? ((exitP - entryP) * qty - chg) : 0;

              const newOpt = {
                id: `opt_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
                entryDate: optEntryDate,
                instrument: optInstrument.toUpperCase(),
                qty,
                entryPrice: entryP,
                capitalUsed: qty * entryP,
                fundedBy: optFundedBy,
                exitDate: optExitDate,
                exitPrice: exitP,
                charges: chg,
                netPnl,
                status: optStatus,
                notes: optNotes
              };

              setOptionsTrades(prev => [newOpt, ...prev]);
              setShowAddOptionModal(false);
              setOptInstrument('');
              setOptEntryPrice('');
              setOptExitPrice('');
              showToast('⚡ Options Trade logged to event ledger!');
            }} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>ENTRY DATE</label>
                  <input type="date" value={optEntryDate} onChange={e => setOptEntryDate(e.target.value)} required style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }} />
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#c084fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>INSTRUMENT SYMBOL</label>
                  <input type="text" placeholder="e.g. NIFTY 24500 CE" value={optInstrument} onChange={e => setOptInstrument(e.target.value)} required style={{ width: '100%', background: '#090d16', border: '1px solid #c084fc', color: '#c084fc', padding: '10px', borderRadius: '8px', fontWeight: 900 }} />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>QTY / LOTS</label>
                  <input type="number" value={optQty} onChange={e => setOptQty(e.target.value)} required style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }} />
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>ENTRY PRICE (₹)</label>
                  <input type="number" step="any" placeholder="e.g. 125.50" value={optEntryPrice} onChange={e => setOptEntryPrice(e.target.value)} required style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }} />
                </div>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 800, display: 'block', marginBottom: '4px' }}>FUNDED BY (Mandatory Origin Segment)</label>
                <select value={optFundedBy} onChange={e => setOptFundedBy(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1.5px solid #38bdf8', color: '#38bdf8', padding: '10px', borderRadius: '8px', fontWeight: 900 }}>
                  <option value="SWING">⚡ Swing Trading (Capital freed from Swing Exit)</option>
                  <option value="LT">🛡️ Long-Term Core</option>
                  <option value="PENNY">💎 Quality Penny SIP</option>
                  <option value="GENERAL">💵 General Free Cash Reserve</option>
                </select>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>STATUS</label>
                  <select value={optStatus} onChange={e => setOptStatus(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}>
                    <option value="OPEN">🟠 OPEN Position</option>
                    <option value="CLOSED">🟢 CLOSED Position</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>EST. CHARGES (₹)</label>
                  <input type="number" value={optCharges} onChange={e => setOptCharges(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }} />
                </div>
              </div>

              {optStatus === 'CLOSED' && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', background: 'rgba(16,185,129,0.08)', padding: '10px', borderRadius: '8px', border: '1px solid rgba(16,185,129,0.3)' }}>
                  <div>
                    <label style={{ fontSize: '11px', color: '#10b981', fontWeight: 700, display: 'block', marginBottom: '4px' }}>EXIT DATE</label>
                    <input type="date" value={optExitDate} onChange={e => setOptExitDate(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid #10b981', color: '#ffffff', padding: '8px', borderRadius: '6px' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '11px', color: '#10b981', fontWeight: 700, display: 'block', marginBottom: '4px' }}>EXIT PRICE (₹)</label>
                    <input type="number" step="any" placeholder="e.g. 180.00" value={optExitPrice} onChange={e => setOptExitPrice(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid #10b981', color: '#10b981', padding: '8px', borderRadius: '6px', fontWeight: 900 }} />
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button type="button" onClick={() => setShowAddOptionModal(false)} style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', color: '#cbd5e1', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 700 }}>Cancel</button>
                <button type="submit" style={{ background: 'linear-gradient(135deg, #c084fc, #a855f7)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}>Save Options Trade</button>
              </div>
            </form>

          </div>
        </div>
      )}

      {/* ── MODAL: DAILY EOD RECONCILIATION (SECTION 5 SPEC) ── */}
      {showReconcileModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
          <div style={{ background: '#0f172a', border: '1.5px solid #10b981', borderRadius: '16px', padding: '24px', width: '100%', maxWidth: '460px', boxShadow: '0 20px 50px rgba(0,0,0,0.6)' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>⚖️ Daily EOD Reconciliation</div>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>Compare calculated Cash Ledger vs actual broker app balance</div>
              </div>
              <button onClick={() => setShowReconcileModal(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SELECT BROKER &amp; SEGMENT</label>
                <select value={reconSegment} onChange={e => {
                  setReconSegment(e.target.value);
                  setReconBroker(e.target.value === 'LT' || e.target.value === 'PENNY' ? 'INDmoney' : 'Zerodha Kite');
                }} style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}>
                  <option value="SWING">⚡ Swing Trading (Zerodha Kite)</option>
                  <option value="LT">🛡️ Long-Term Core (INDmoney)</option>
                  <option value="PENNY">💎 Quality Penny SIP (INDmoney)</option>
                </select>
              </div>

              <div style={{ background: 'rgba(56, 189, 248, 0.08)', border: '1px solid rgba(56, 189, 248, 0.3)', borderRadius: '10px', padding: '12px' }}>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>Calculated Free Cash from Ledger (Section 2a):</div>
                <div style={{ fontSize: '20px', fontWeight: 900, color: '#38bdf8', marginTop: '2px' }}>
                  ₹{(segmentLedgers[reconSegment.toLowerCase()]?.calculatedFreeCash || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#10b981', fontWeight: 800, display: 'block', marginBottom: '4px' }}>ACTUAL FREE CASH SHOWN IN BROKER APP (₹)</label>
                <input 
                  type="number" 
                  step="any" 
                  placeholder="e.g. 734.63" 
                  value={reconActualCash} 
                  onChange={e => setReconActualCash(e.target.value)} 
                  style={{ width: '100%', background: '#090d16', border: '1.5px solid #10b981', color: '#10b981', fontSize: '20px', padding: '10px', borderRadius: '8px', fontWeight: 900 }} 
                />
              </div>

              {reconActualCash !== '' && !isNaN(reconActualCash) && (
                <div style={{ background: 'rgba(245, 158, 11, 0.08)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: '10px', padding: '12px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8' }}>Audit Variance (Actual − Calculated):</div>
                  <div style={{ fontSize: '18px', fontWeight: 900, color: (parseFloat(reconActualCash) - (segmentLedgers[reconSegment.toLowerCase()]?.calculatedFreeCash || 0)) >= 0 ? '#10b981' : '#f87171', marginTop: '2px' }}>
                    {(parseFloat(reconActualCash) - (segmentLedgers[reconSegment.toLowerCase()]?.calculatedFreeCash || 0)) >= 0 ? '+' : ''}₹{(parseFloat(reconActualCash) - (segmentLedgers[reconSegment.toLowerCase()]?.calculatedFreeCash || 0)).toFixed(2)}
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button type="button" onClick={() => setShowReconcileModal(false)} style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', color: '#cbd5e1', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 700 }}>Cancel</button>
                <button 
                  type="button" 
                  onClick={() => {
                    const actualVal = parseFloat(reconActualCash);
                    if (isNaN(actualVal)) return;
                    const calculatedVal = segmentLedgers[reconSegment.toLowerCase()]?.calculatedFreeCash || 0;
                    const variance = actualVal - calculatedVal;

                    if (Math.abs(variance) > 0.01) {
                      const newCorr = {
                        id: `adj_corr_${Date.now()}`,
                        date: new Date().toISOString().split('T')[0],
                        broker: reconBroker,
                        segment: reconSegment,
                        type: 'CORRECTION',
                        amount: variance,
                        notes: `EOD Variance reconciliation vs ${reconBroker} statement as of ${new Date().toISOString().split('T')[0]}`
                      };
                      setBrokerAdjustments(prev => [newCorr, ...prev]);
                    }

                    if (reconSegment === 'SWING') setSwingFreeCashInput(reconActualCash);
                    else if (reconSegment === 'LT') setLtFreeCashInput(reconActualCash);
                    else if (reconSegment === 'PENNY') setPennyFreeCashInput(reconActualCash);

                    setShowReconcileModal(false);
                    setReconActualCash('');
                    showToast(`✅ EOD Reconciliation logged! Free Cash updated to ₹${actualVal.toFixed(2)}`);
                  }} 
                  style={{ background: 'linear-gradient(135deg, #059669, #10b981)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}
                >
                  Log Audit Correction &amp; Reconcile
                </button>
              </div>
              <button onClick={() => setShowAddOptionModal(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <form onSubmit={(e) => {
              e.preventDefault();
              if (!optInstrument || !optEntryPrice) return;
              const entryP = parseFloat(optEntryPrice) || 0;
              const exitP = parseFloat(optExitPrice) || 0;
              const qty = parseInt(optQty, 10) || 1;
              const chg = parseFloat(optCharges) || 40;
              const netPnl = optStatus === 'CLOSED' ? ((exitP - entryP) * qty - chg) : 0;

              const newOpt = {
                id: `opt_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
                entryDate: optEntryDate,
                instrument: optInstrument.toUpperCase(),
                qty,
                entryPrice: entryP,
                capitalUsed: qty * entryP,
                fundedBy: optFundedBy,
                exitDate: optExitDate,
                exitPrice: exitP,
                charges: chg,
                netPnl,
                status: optStatus,
                notes: optNotes
              };

              setOptionsTrades(prev => [newOpt, ...prev]);
              setShowAddOptionModal(false);
              setOptInstrument('');
              setOptEntryPrice('');
              setOptExitPrice('');
              showToast('⚡ Options Trade logged to event ledger!');
            }} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>ENTRY DATE</label>
                  <input type="date" value={optEntryDate} onChange={e => setOptEntryDate(e.target.value)} required style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }} />
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#c084fc', fontWeight: 700, display: 'block', marginBottom: '4px' }}>INSTRUMENT SYMBOL</label>
                  <input type="text" placeholder="e.g. NIFTY 24500 CE" value={optInstrument} onChange={e => setOptInstrument(e.target.value)} required style={{ width: '100%', background: '#090d16', border: '1px solid #c084fc', color: '#c084fc', padding: '10px', borderRadius: '8px', fontWeight: 900 }} />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>QTY / LOTS</label>
                  <input type="number" value={optQty} onChange={e => setOptQty(e.target.value)} required style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }} />
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>ENTRY PRICE (₹)</label>
                  <input type="number" step="any" placeholder="e.g. 125.50" value={optEntryPrice} onChange={e => setOptEntryPrice(e.target.value)} required style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }} />
                </div>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 800, display: 'block', marginBottom: '4px' }}>FUNDED BY (Mandatory Origin Segment)</label>
                <select value={optFundedBy} onChange={e => setOptFundedBy(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1.5px solid #38bdf8', color: '#38bdf8', padding: '10px', borderRadius: '8px', fontWeight: 900 }}>
                  <option value="SWING">⚡ Swing Trading (Capital freed from Swing Exit)</option>
                  <option value="LT">🛡️ Long-Term Core</option>
                  <option value="PENNY">💎 Quality Penny SIP</option>
                  <option value="GENERAL">💵 General Free Cash Reserve</option>
                </select>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>STATUS</label>
                  <select value={optStatus} onChange={e => setOptStatus(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}>
                    <option value="OPEN">🟠 OPEN Position</option>
                    <option value="CLOSED">🟢 CLOSED Position</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>EST. CHARGES (₹)</label>
                  <input type="number" value={optCharges} onChange={e => setOptCharges(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px' }} />
                </div>
              </div>

              {optStatus === 'CLOSED' && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', background: 'rgba(16,185,129,0.08)', padding: '10px', borderRadius: '8px', border: '1px solid rgba(16,185,129,0.3)' }}>
                  <div>
                    <label style={{ fontSize: '11px', color: '#10b981', fontWeight: 700, display: 'block', marginBottom: '4px' }}>EXIT DATE</label>
                    <input type="date" value={optExitDate} onChange={e => setOptExitDate(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid #10b981', color: '#ffffff', padding: '8px', borderRadius: '6px' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '11px', color: '#10b981', fontWeight: 700, display: 'block', marginBottom: '4px' }}>EXIT PRICE (₹)</label>
                    <input type="number" step="any" placeholder="e.g. 180.00" value={optExitPrice} onChange={e => setOptExitPrice(e.target.value)} style={{ width: '100%', background: '#090d16', border: '1px solid #10b981', color: '#10b981', padding: '8px', borderRadius: '6px', fontWeight: 900 }} />
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button type="button" onClick={() => setShowAddOptionModal(false)} style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', color: '#cbd5e1', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 700 }}>Cancel</button>
                <button type="submit" style={{ background: 'linear-gradient(135deg, #c084fc, #a855f7)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}>Save Options Trade</button>
              </div>
            </form>

          </div>
        </div>
      )}

      {/* ── MODAL: DAILY EOD RECONCILIATION (SECTION 5 SPEC) ── */}
      {showReconcileModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
          <div style={{ background: '#0f172a', border: '1.5px solid #10b981', borderRadius: '16px', padding: '24px', width: '100%', maxWidth: '460px', boxShadow: '0 20px 50px rgba(0,0,0,0.6)' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>⚖️ Daily EOD Reconciliation</div>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>Compare calculated Cash Ledger vs actual broker app balance</div>
              </div>
              <button onClick={() => setShowReconcileModal(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}><X size={20} /></button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, display: 'block', marginBottom: '4px' }}>SELECT BROKER &amp; SEGMENT</label>
                <select value={reconSegment} onChange={e => {
                  setReconSegment(e.target.value);
                  setReconBroker(e.target.value === 'LT' || e.target.value === 'PENNY' ? 'INDmoney' : 'Zerodha Kite');
                }} style={{ width: '100%', background: '#090d16', border: '1px solid rgba(255,255,255,0.15)', color: '#ffffff', padding: '10px', borderRadius: '8px', fontWeight: 800 }}>
                  <option value="SWING">⚡ Swing Trading (Zerodha Kite)</option>
                  <option value="LT">🛡️ Long-Term Core (INDmoney)</option>
                  <option value="PENNY">💎 Quality Penny SIP (INDmoney)</option>
                </select>
              </div>

              <div style={{ background: 'rgba(56, 189, 248, 0.08)', border: '1px solid rgba(56, 189, 248, 0.3)', borderRadius: '10px', padding: '12px' }}>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>Calculated Free Cash from Ledger (Section 2a):</div>
                <div style={{ fontSize: '20px', fontWeight: 900, color: '#38bdf8', marginTop: '2px' }}>
                  ₹{(segmentLedgers[reconSegment.toLowerCase()]?.calculatedFreeCash || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#10b981', fontWeight: 800, display: 'block', marginBottom: '4px' }}>ACTUAL FREE CASH SHOWN IN BROKER APP (₹)</label>
                <input 
                  type="number" 
                  step="any" 
                  placeholder="e.g. 734.63" 
                  value={reconActualCash} 
                  onChange={e => setReconActualCash(e.target.value)} 
                  style={{ width: '100%', background: '#090d16', border: '1.5px solid #10b981', color: '#10b981', fontSize: '20px', padding: '10px', borderRadius: '8px', fontWeight: 900 }} 
                />
              </div>

              {reconActualCash !== '' && !isNaN(reconActualCash) && (
                <div style={{ background: 'rgba(245, 158, 11, 0.08)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: '10px', padding: '12px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8' }}>Audit Variance (Actual − Calculated):</div>
                  <div style={{ fontSize: '18px', fontWeight: 900, color: (parseFloat(reconActualCash) - (segmentLedgers[reconSegment.toLowerCase()]?.calculatedFreeCash || 0)) >= 0 ? '#10b981' : '#f87171', marginTop: '2px' }}>
                    {(parseFloat(reconActualCash) - (segmentLedgers[reconSegment.toLowerCase()]?.calculatedFreeCash || 0)) >= 0 ? '+' : ''}₹{(parseFloat(reconActualCash) - (segmentLedgers[reconSegment.toLowerCase()]?.calculatedFreeCash || 0)).toFixed(2)}
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button type="button" onClick={() => setShowReconcileModal(false)} style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', color: '#cbd5e1', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 700 }}>Cancel</button>
                <button 
                  type="button" 
                  onClick={() => {
                    const actualVal = parseFloat(reconActualCash);
                    if (isNaN(actualVal)) return;
                    const calculatedVal = segmentLedgers[reconSegment.toLowerCase()]?.calculatedFreeCash || 0;
                    const variance = actualVal - calculatedVal;

                    if (Math.abs(variance) > 0.01) {
                      const newCorr = {
                        id: `adj_corr_${Date.now()}`,
                        date: new Date().toISOString().split('T')[0],
                        broker: reconBroker,
                        segment: reconSegment,
                        type: 'CORRECTION',
                        amount: variance,
                        notes: `EOD Variance reconciliation vs ${reconBroker} statement as of ${new Date().toISOString().split('T')[0]}`
                      };
                      setBrokerAdjustments(prev => [newCorr, ...prev]);
                    }

                    if (reconSegment === 'SWING') setSwingFreeCashInput(reconActualCash);
                    else if (reconSegment === 'LT') setLtFreeCashInput(reconActualCash);
                    else if (reconSegment === 'PENNY') setPennyFreeCashInput(reconActualCash);

                    setShowReconcileModal(false);
                    setReconActualCash('');
                    showToast(`✅ EOD Reconciliation logged! Free Cash updated to ₹${actualVal.toFixed(2)}`);
                  }} 
                  style={{ background: 'linear-gradient(135deg, #059669, #10b981)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}
                >
                  Log Audit Correction &amp; Reconcile
                </button>
              </div>
            </div>

          </div>
        </div>
      )}

      </div>
  );
}
