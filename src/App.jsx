import React, { useState, useEffect, useMemo } from 'react';
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

const API_BASE_URL = typeof window !== 'undefined' && window.location.origin.includes('http') ? window.location.origin : 'http://localhost:8000';
const RENDER_BACKEND_URL = 'https://finplus.onrender.com';
const STORAGE_KEY = 'finplus_3pillar_portfolio_v5';
const LEDGER_KEY = 'finplus_capital_ledger_v5';
const FREE_CASH_SWING_KEY = 'finplus_free_cash_swing_v5';
const FREE_CASH_LT_KEY = 'finplus_free_cash_lt_v5';

const INITIAL_POSITIONS = [
  {
    id: "pos_midhani_kite",
    ticker: "MIDHANI",
    name: "Mishra Dhatu Nigam Limited",
    segment: "SWING",
    shares: 3,
    buyPrice: 433.0,
    buyDate: "2026-08-23",
    target1: 467.64,
    stopLoss: 415.68,
    notes: "Zerodha Kite Swing Position"
  },
  {
    id: "pos_cupid_kite",
    ticker: "CUPID",
    name: "Cupid Limited",
    segment: "SWING",
    shares: 6,
    buyPrice: 289.95,
    buyDate: "2026-08-23",
    target1: 313.15,
    stopLoss: 278.35,
    notes: "Zerodha Kite Swing Position"
  },
  {
    id: "pos_kiriindus_kite",
    ticker: "KIRIINDUS",
    name: "Kiri Industries Limited",
    segment: "SWING",
    shares: 4,
    buyPrice: 462.0,
    buyDate: "2026-08-23",
    target1: 498.96,
    stopLoss: 443.52,
    notes: "Zerodha Kite Swing Position"
  },
  {
    id: "pos_rvnl_indmoney",
    ticker: "RVNL",
    name: "Rail Vikas Nigam Limited",
    segment: "LT",
    shares: 1,
    buyPrice: 229.90,
    buyDate: "2026-08-23",
    target1: 287.38,
    stopLoss: 0,
    notes: "INDmoney Long-Term Core Position"
  }
];

const INITIAL_CAPITAL_LEDGER = [
  {
    id: "cap_initial_kite",
    date: "2026-08-23",
    type: "INJECTION",
    amount: 5136.10,
    segment: "SWING",
    notes: "Zerodha Kite Capital (Invested + Free Cash)"
  },
  {
    id: "cap_initial_indmoney",
    date: "2026-08-23",
    type: "INJECTION",
    amount: 283.94,
    segment: "LT",
    notes: "INDmoney Long-Term Capital (Invested + Free Cash)"
  }
];

export default function App() {
  // ══════════════════════════════════════════════════════════════
  // ZONE 1: ALL REACT STATE HOOKS (Strictly First)
  // ══════════════════════════════════════════════════════════════
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

  // Free Cash with Broker (Baseline Initial Balances)
  const [swingFreeCashInput, setSwingFreeCashInput] = useState(() => {
    const saved = localStorage.getItem('finplus_free_cash_swing_v5') || localStorage.getItem(FREE_CASH_SWING_KEY);
    if (!saved || saved === '249.40' || saved === '249.4' || saved === '1233.12' || saved === '1233.1' || saved === '1287.16') return '';
    return saved;
  });
  const [ltFreeCashInput, setLtFreeCashInput] = useState(() => {
    const saved = localStorage.getItem(FREE_CASH_LT_KEY);
    return saved !== null ? saved : '54.04';
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
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      } catch(e) {}
    }
    return INITIAL_CAPITAL_LEDGER;
  });

  // Portfolio Positions State (Swing, Long-Term, Penny)
  const [positions, setPositions] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      } catch(e) {}
    }
    return INITIAL_POSITIONS;
  });

  // Sold History Ledger
  const [soldHistory, setSoldHistory] = useState(() => {
    const saved = localStorage.getItem('finplus_sold_history_v1');
    if (saved) {
      try { return JSON.parse(saved); } catch(e) {}
    }
    return [];
  });

  // Live LTP Polling State
  const [liveLtps, setLiveLtps] = useState({
    'MIDHANI': 423.95,
    'CUPID': 284.65,
    'KIRIINDUS': 477.90,
    'RVNL': 225.30
  });
  const [lastLtpUpdate, setLastLtpUpdate] = useState(() => new Date().toLocaleTimeString());
  const [isLtpLoading, setIsLtpLoading] = useState(false);

  // Modal: Record New Buy Form State
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

    // Always restore latest synced portfolio dataset from cloud/disk backup on app mount
    const endpoints = Array.from(new Set([RENDER_BACKEND_URL, API_BASE_URL].filter(Boolean)));
    for (const ep of endpoints) {
      fetch(`${ep}/api/backup/load`)
        .then(r => r.json())
        .then(res => {
          if (res && res.status === 'success' && res.data) {
            const { positions: diskPos, capitalLedger: diskLedger, soldHistory: diskSold, budget, split, freeCash } = res.data;
            if (Array.isArray(diskPos)) setPositions(diskPos);
            if (Array.isArray(diskLedger)) setCapitalLedger(diskLedger);
            if (Array.isArray(diskSold)) setSoldHistory(diskSold);
            if (budget) setMonthlyBudgetInput(budget);
            if (split) {
              if (split.swing !== undefined) setSwingPct(split.swing);
              if (split.lt !== undefined) setLtPct(split.lt);
              if (split.penny !== undefined) setPennyPct(split.penny);
            }
            if (freeCash) {
              const val = String(freeCash.swing || '').trim();
              if (val && val !== '249.40' && val !== '249.4' && val !== '1233.12' && val !== '1233.1' && val !== '1287.16') {
                setSwingFreeCashInput(val);
              } else {
                setSwingFreeCashInput('');
              }
              if (freeCash.lt !== undefined) setLtFreeCashInput(String(freeCash.lt));
              if (freeCash.penny !== undefined) setPennyFreeCashInput(String(freeCash.penny));
            }
          }
        })
        .catch(() => {});
    }
  }, []);

  // Save State to LocalStorage & Backend Disk Backup File
  useEffect(() => {
    localStorage.setItem('finplus_monthly_income_budget', monthlyBudgetInput);
    localStorage.setItem('finplus_split_swing', String(swingPct));
    localStorage.setItem('finplus_split_lt', String(ltPct));
    localStorage.setItem('finplus_split_penny', String(pennyPct));
    localStorage.setItem(FREE_CASH_SWING_KEY, swingFreeCashInput);
    localStorage.setItem('finplus_free_cash_swing_v5', swingFreeCashInput);
    localStorage.setItem(FREE_CASH_LT_KEY, ltFreeCashInput);
    localStorage.setItem(LEDGER_KEY, JSON.stringify(capitalLedger));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(positions));
    localStorage.setItem('finplus_sold_history_v1', JSON.stringify(soldHistory));

    // Auto disk backup sync to both local server & Render cloud
    const endpoints = Array.from(new Set([API_BASE_URL, RENDER_BACKEND_URL].filter(Boolean)));
    const backupPayload = JSON.stringify({
      positions,
      capitalLedger,
      soldHistory,
      freeCash: { swing: swingFreeCashInput, lt: ltFreeCashInput, penny: pennyFreeCashInput },
      budget: monthlyBudgetInput,
      split: { swing: swingPct, lt: ltPct, penny: pennyPct }
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
  }, [monthlyBudgetInput, swingPct, ltPct, pennyPct, capitalLedger, positions, soldHistory, swingFreeCash, ltFreeCash, pennyFreeCash]);

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
      if (item.type === 'INJECTION') {
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
      } else if (item.type === 'WITHDRAWAL') {
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

  // ── Holding Details Calculator ──
  const holdingCards = useMemo(() => {
    const today = new Date();
    return positions.map(pos => {
      const cleanSym = pos.ticker.replace('.NS', '').trim().toUpperCase();
      const ltp = liveLtps[cleanSym] || pos.buyPrice;
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
      if (pos.segment === 'LT') {
        estCharges = calculateINDmoneyCharges({ entry_price: pos.buyPrice, exit_price: ltp, quantity: pos.shares });
      } else {
        estCharges = calculateKiteDeliveryCharges({ entry_price: pos.buyPrice, exit_price: ltp, quantity: pos.shares });
      }

      return {
        ...pos,
        cleanSym,
        ltp,
        currentVal,
        costBasis,
        unrealizedPnl,
        pnlPct,
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

    const isStaleSwingCash = (val) => !val || val === '249.40' || val === '249.4' || val === '1233.12' || val === '1233.1' || val === '1287.16';
    const effectiveSwingFreeCash = (!isStaleSwingCash(swingFreeCashInput)) ? (parseFloat(swingFreeCashInput) || 0) : capitalMath.swing.available;
    const effectiveLtFreeCash = ltFreeCashInput ? (parseFloat(ltFreeCashInput) || 0) : capitalMath.lt.available;
    const effectivePennyFreeCash = pennyFreeCashInput ? (parseFloat(pennyFreeCashInput) || 0) : capitalMath.penny.available;

    const totalFreeCash = effectiveSwingFreeCash + effectiveLtFreeCash + effectivePennyFreeCash;
    const totalAccountCapital = totalCurrentVal + totalFreeCash; // Universal Account Net Worth = Live Value of ALL Holdings (Kite + INDmoney) + Effective Free Cash
    const totalBaseCapital = totalInvested + totalFreeCash;

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
        netPnl: swingNetPnl,
        netPct: swingNetPct,
        freeCash: effectiveSwingFreeCash,
        totalCap: swingCurrentVal + effectiveSwingFreeCash,
        broker: 'Zerodha Kite'
      },
      lt: {
        invested: ltInvested,
        currentVal: ltCurrentVal,
        grossPnl: ltGrossPnl,
        grossPct: ltGrossPct,
        estCharges: ltEstCharges,
        netPnl: ltNetPnl,
        netPct: ltNetPct,
        freeCash: effectiveLtFreeCash,
        totalCap: ltCurrentVal + effectiveLtFreeCash,
        broker: 'INDMONEY'
      },
      penny: {
        invested: pennyInvested,
        currentVal: pennyCurrentVal,
        grossPnl: pennyGrossPnl,
        grossPct: pennyGrossPct,
        estCharges: pennyEstCharges,
        netPnl: pennyNetPnl,
        netPct: pennyNetPct,
        freeCash: effectivePennyFreeCash,
        totalCap: pennyCurrentVal + effectivePennyFreeCash,
        broker: 'Zerodha Kite'
      }
    };
  }, [holdingCards, swingFreeCash, ltFreeCash, pennyFreeCash]);

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

    setPositions(prev => [newPos, ...prev]);
    setShowAddModal(false);
    setFormTicker('');
    setFormName('');
    setFormShares('1');
    setFormBuyPrice('');
    setFormTarget1('');
    setFormStopLoss('');
    setFormNotes('');
    showToast(`✅ Recorded purchase of ${shares} shares of ${ticker} in ${addSegment}!`);
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

    // ── AUTOMATIC FREE BROKER CASH RECYCLING ──
    // Capital engine (capitalMath) automatically recycles freed capital and net proceeds into available cash when positions & soldHistory update.
    // If custom free cash overrides were set, update them relative to current effective free cash, otherwise clear override to let engine compute.
    if (sellModalPos.segment === 'SWING') {
      if (swingFreeCashInput && swingFreeCashInput !== '249.40' && swingFreeCashInput !== '249.4') {
        setSwingFreeCashInput(prev => (Math.max(0, parseFloat(prev || '0') + netProceeds)).toFixed(2));
      } else {
        setSwingFreeCashInput('');
      }
    } else if (sellModalPos.segment === 'LT') {
      if (ltFreeCashInput) {
        setLtFreeCashInput(prev => (Math.max(0, parseFloat(prev || '0') + netProceeds)).toFixed(2));
      } else {
        setLtFreeCashInput('');
      }
    } else if (sellModalPos.segment === 'PENNY') {
      if (pennyFreeCashInput) {
        setPennyFreeCashInput(prev => (Math.max(0, parseFloat(prev || '0') + netProceeds)).toFixed(2));
      } else {
        setPennyFreeCashInput('');
      }
    }

    if (isFullSell) {
      setPositions(prev => prev.filter(p => p.id !== sellModalPos.id));
    } else {
      setPositions(prev => prev.map(p => p.id === sellModalPos.id ? { ...p, shares: p.shares - sellQty } : p));
    }

    setSellModalPos(null);
    showToast(`💰 Recorded sale of ${sellQty} sh ${sellModalPos.ticker}! Net P&L: ${charges.net_pnl >= 0 ? '+' : ''}₹${charges.net_pnl.toFixed(2)} (Recycled into ${sellModalPos.segment} Available Capital).`);
  };

  // ── Handle Capital Event (Injection / Withdrawal) ──
  const handleCapEventSubmit = (e) => {
    e.preventDefault();
    const amt = Number(capEventAmount);
    if (isNaN(amt) || amt <= 0) {
      showToast('❌ Please enter a valid capital amount.');
      return;
    }

    const newEvent = {
      id: `cap_${Date.now()}`,
      date: new Date().toISOString().split('T')[0],
      type: capEventType,
      amount: amt,
      segment: capEventSegment,
      notes: capEventNotes.trim() || `${capEventType === 'INJECTION' ? 'Capital Injected' : 'Capital Withdrawn'}`
    };

    setCapitalLedger(prev => [newEvent, ...prev]);
    setShowCapModal(false);
    setCapEventAmount('');
    setCapEventNotes('');
    showToast(`✅ Recorded ${capEventType} of ₹${amt.toLocaleString('en-IN')}!`);
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
              onClick={() => { setShowCapModal(true); }}
              style={{ background: 'rgba(16, 185, 129, 0.15)', border: '1px solid #10b981', color: '#10b981', padding: '8px 14px', borderRadius: '8px', fontWeight: 800, fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <Wallet size={14} />
              + Capital Event
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

            {/* ── GLOBAL EXECUTIVE CAPITAL & COMBINED PnL RIBBON (VISIBLE ON ALL TABS) ── */}
      <div style={{ background: '#0b1120', borderBottom: '1px solid rgba(255,255,255,0.08)', padding: '16px 24px' }}>
        <div style={{ maxWidth: '1400px', margin: '0 auto', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px' }}>
          
          {/* Card 1: Total Account Net Worth */}
          <div style={{ background: 'rgba(15, 23, 42, 0.8)', border: '1px solid rgba(56, 189, 248, 0.3)', borderRadius: '12px', padding: '14px 16px' }}>
            <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 800, textTransform: 'uppercase' }}>TOTAL ACCOUNT NET WORTH</div>
            <div style={{ fontSize: '22px', fontWeight: 900, color: '#38bdf8', marginTop: '4px' }}>
              ₹{portfolioSummary.totalAccountCapital.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div style={{ fontSize: '10px', color: '#a5b4fc', marginTop: '2px' }}>
              Holdings (Kite + INDmoney) ₹{portfolioSummary.totalCurrentVal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} • Free Cash (Kite + INDmoney) ₹{portfolioSummary.totalFreeCash.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>

          {/* Card 2: Net Realized Profit (Closed Trades) */}
          <div style={{ background: 'rgba(15, 23, 42, 0.8)', border: `1px solid ${(portfolioSummary.totalRealizedNetPnl || 0) >= 0 ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)'}`, borderRadius: '12px', padding: '14px 16px' }}>
            <div style={{ fontSize: '11px', color: (portfolioSummary.totalRealizedNetPnl || 0) >= 0 ? '#10b981' : '#f87171', fontWeight: 800, textTransform: 'uppercase' }}>
              {(portfolioSummary.totalRealizedNetPnl || 0) >= 0 ? 'NET REALIZED PROFIT (BOOKED)' : 'NET REALIZED LOSS (BOOKED)'}
            </div>
            <div style={{ fontSize: '22px', fontWeight: 900, color: (portfolioSummary.totalRealizedNetPnl || 0) >= 0 ? '#10b981' : '#f87171', marginTop: '4px' }}>
              {(portfolioSummary.totalRealizedNetPnl || 0) >= 0 ? '+' : ''}₹{(portfolioSummary.totalRealizedNetPnl || 0).toFixed(2)}
            </div>
            <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '2px' }}>
              From {soldHistory.length} Closed Trade{soldHistory.length === 1 ? '' : 's'} (Recycled)
            </div>
          </div>

          {/* Card 3: Net Unrealized P&L (Open Positions) */}
          <div style={{ background: 'rgba(15, 23, 42, 0.8)', border: `1px solid ${portfolioSummary.totalUnrealizedPnl >= 0 ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)'}`, borderRadius: '12px', padding: '14px 16px' }}>
            <div style={{ fontSize: '11px', color: portfolioSummary.totalUnrealizedPnl >= 0 ? '#10b981' : '#f87171', fontWeight: 800, textTransform: 'uppercase' }}>
              {portfolioSummary.totalUnrealizedPnl >= 0 ? 'NET UNREALIZED PROFIT (OPEN)' : 'NET UNREALIZED LOSS (OPEN)'}
            </div>
            <div style={{ fontSize: '22px', fontWeight: 900, color: portfolioSummary.totalUnrealizedPnl >= 0 ? '#10b981' : '#f87171', marginTop: '4px' }}>
              {portfolioSummary.totalUnrealizedPnl >= 0 ? '+' : ''}₹{portfolioSummary.totalUnrealizedPnl.toFixed(2)}
            </div>
            <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '2px' }}>
              Est. Taxes: -₹{(portfolioSummary.totalEstCharges || 0).toFixed(2)}
            </div>
          </div>

          {/* Card 4: TOTAL COMBINED LIFETIME PROFIT (Realized + Unrealized) */}
          <div style={{ background: 'linear-gradient(135deg, rgba(16,185,129,0.15), rgba(6,182,212,0.1))', border: `1.5px solid ${(portfolioSummary.totalCombinedNetPnl || 0) >= 0 ? '#10b981' : '#f87171'}`, borderRadius: '12px', padding: '14px 16px' }}>
<div style={{ fontSize: '11px', color: (portfolioSummary.totalCombinedNetPnl || 0) >= 0 ? '#10b981' : '#f87171', fontWeight: 900, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>⭐ TOTAL COMBINED P&amp;L</span>
              <span style={{ fontSize: '9px', padding: '1px 6px', borderRadius: '4px', background: (portfolioSummary.totalCombinedNetPnl || 0) >= 0 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)' }}>
                {(portfolioSummary.totalCombinedNetPnl || 0) >= 0 ? 'NET GAIN' : 'NET LOSS'}
              </span>
            </div>
            <div style={{ fontSize: '22px', fontWeight: 900, color: (portfolioSummary.totalCombinedNetPnl || 0) >= 0 ? '#10b981' : '#f87171', marginTop: '4px' }}>
              {(portfolioSummary.totalCombinedNetPnl || 0) >= 0 ? '+' : ''}₹{(portfolioSummary.totalCombinedNetPnl || 0).toFixed(2)}
            </div>
            <div style={{ fontSize: '10px', fontWeight: 800, color: (portfolioSummary.totalCombinedNetPnl || 0) >= 0 ? '#10b981' : '#f87171', marginTop: '2px' }}>
              Realized Booked + Live Open Gains
            </div>
          </div>

        </div>
      </div>

      {/* Main App Container */}
      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '24px' }}>

        {/* Navigation Tabs */}
        <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '14px', marginBottom: '24px', overflowX: 'auto' }}>
          {[
            { id: 'capital', label: '📊 3-Pillar Capital Engine', badge: `₹${capitalMath.totalNetCapital.toLocaleString('en-IN')}` },
            { id: 'swing', label: '⚡ Swing Trading (Kite)', badge: positions.filter(p => p.segment === 'SWING').length },
            { id: 'lt', label: '🛡️ Long-Term Core (INDmoney)', badge: positions.filter(p => p.segment === 'LT').length },
            { id: 'penny', label: '💎 Quality Penny SIP (Kite)', badge: positions.filter(p => p.segment === 'PENNY').length },
            { id: 'history', label: '📜 Realized P&L Ledger', badge: soldHistory.length },
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
            
            {/* Top Strategy Banner */}
            <div style={{ background: 'linear-gradient(135deg, rgba(15,23,42,0.9), rgba(30,41,59,0.7))', border: '1.5px solid rgba(56,189,248,0.3)', borderRadius: '16px', padding: '24px', boxShadow: '0 10px 30px rgba(0,0,0,0.3)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '20px' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                    <span style={{ background: 'linear-gradient(135deg, #10b981, #06b6d4)', color: '#090d16', fontWeight: 900, fontSize: '11px', padding: '4px 10px', borderRadius: '6px' }}>25% MONTHLY INCOME DISCIPLINE</span>
                    <span style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', border: '1px solid rgba(239, 68, 68, 0.3)', fontWeight: 800, fontSize: '11px', padding: '3px 8px', borderRadius: '6px' }}>🛑 Zero Day Trading</span>
                  </div>
                  <div style={{ fontSize: '24px', fontWeight: 900, color: '#ffffff', marginTop: '10px' }}>Disciplined Capital Allocator &amp; Rollover Engine</div>
                  <div style={{ fontSize: '13px', color: '#94a3b8', maxWidth: '750px', marginTop: '6px', lineHeight: 1.5 }}>
                    Your total capital injections are automatically divided into <strong>⚡ Swing Trading (60%)</strong>, <strong>🛡️ Long-Term Core (30%)</strong>, and <strong>💎 Quality Penny SIP (10%)</strong> with nearest whole rupee rounding. Unspent funds roll over automatically to preserve buying power.
                  </div>
                </div>

                {/* Monthly / Total Capital Input Control */}
                <div style={{ background: 'rgba(15, 23, 42, 0.8)', border: '1.5px solid #10b981', borderRadius: '12px', padding: '16px 20px', minWidth: '280px' }}>
                  <label style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, textTransform: 'uppercase', display: 'block', marginBottom: '6px' }}>Total Capital / Monthly Savings (₹)</label>
                  <input 
                    type="text" 
                    placeholder="e.g. 50000"
                    value={monthlyBudgetInput === '0' ? '' : monthlyBudgetInput} 
                    onChange={e => setMonthlyBudgetInput(e.target.value)}
                    style={{ width: '100%', background: '#090d16', border: '1.5px solid #10b981', color: '#10b981', fontSize: '22px', fontWeight: 900, padding: '8px 12px', borderRadius: '8px' }}
                  />
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '8px', fontSize: '11px' }}>
                    <div style={{ color: '#38bdf8', fontWeight: 700 }}>⚡ Swing ({swingPct}%): ₹{capitalMath.swing.budget.toLocaleString('en-IN')}</div>
                    <div style={{ color: '#10b981', fontWeight: 700 }}>🛡️ LT Core ({ltPct}%): ₹{capitalMath.lt.budget.toLocaleString('en-IN')}</div>
                    <div style={{ color: '#c084fc', fontWeight: 700 }}>💎 Penny SIP ({pennyPct}%): ₹{capitalMath.penny.budget.toLocaleString('en-IN')}</div>
                  </div>
                </div>
              </div>

              {/* Free Uninvested Cash with Brokers Control Panel */}
              <div style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1.5px solid rgba(16, 185, 129, 0.3)', borderRadius: '12px', padding: '16px', marginTop: '20px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
                  <div style={{ fontSize: '13px', fontWeight: 900, color: '#10b981', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span>💰 Free Uninvested Cash with Brokers (Match Account Balances)</span>
                  </div>
                  <span style={{ fontSize: '11px', color: '#a5b4fc', background: 'rgba(99, 102, 241, 0.15)', padding: '2px 8px', borderRadius: '6px' }}>
                    Total Free Cash: ₹{(swingFreeCash + ltFreeCash + pennyFreeCash).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px' }}>
                  <div>
                    <label style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 800, display: 'block', marginBottom: '4px' }}>⚡ SWING FREE CASH (Kite)</label>
                    <input 
                      type="text" 
                      placeholder="0.00"
                      value={swingFreeCashInput} 
                      onChange={e => {
                        const val = e.target.value;
                        setSwingFreeCashInput(val);
                        localStorage.setItem('finplus_free_cash_swing', val);
                      }}
                      style={{ width: '100%', background: '#090d16', border: '1px solid rgba(56, 189, 248, 0.4)', color: '#38bdf8', fontSize: '16px', fontWeight: 800, padding: '8px 12px', borderRadius: '8px' }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: '11px', color: '#10b981', fontWeight: 800, display: 'block', marginBottom: '4px' }}>🛡️ LONG-TERM FREE CASH (INDMONEY)</label>
                    <input 
                      type="text" 
                      placeholder="0.00"
                      value={ltFreeCashInput} 
                      onChange={e => {
                        const val = e.target.value;
                        setLtFreeCashInput(val);
                        localStorage.setItem('finplus_free_cash_lt', val);
                      }}
                      style={{ width: '100%', background: '#090d16', border: '1px solid rgba(16, 185, 129, 0.4)', color: '#10b981', fontSize: '16px', fontWeight: 800, padding: '8px 12px', borderRadius: '8px' }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: '11px', color: '#c084fc', fontWeight: 800, display: 'block', marginBottom: '4px' }}>💎 PENNY SIP FREE CASH (Kite)</label>
                    <input 
                      type="text" 
                      placeholder="0.00"
                      value={pennyFreeCashInput} 
                      onChange={e => {
                        const val = e.target.value;
                        setPennyFreeCashInput(val);
                        localStorage.setItem('finplus_free_cash_penny', val);
                      }}
                      style={{ width: '100%', background: '#090d16', border: '1px solid rgba(192, 132, 252, 0.4)', color: '#c084fc', fontSize: '16px', fontWeight: 800, padding: '8px 12px', borderRadius: '8px' }}
                    />
                  </div>
                </div>
              </div>

              {/* Sliders to Customize Percentage Splits */}
              <div style={{ background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '12px', padding: '16px', marginTop: '20px' }}>
                <div style={{ fontSize: '12px', fontWeight: 800, color: '#38bdf8', textTransform: 'uppercase', marginBottom: '12px' }}>⚙️ Split Percentage Targets</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', fontWeight: 700, marginBottom: '6px' }}>
                      <span style={{ color: '#38bdf8' }}>⚡ Swing Trading:</span>
                      <span>{swingPct}% (₹{capitalMath.swing.budget.toLocaleString('en-IN')})</span>
                    </div>
                    <input type="range" min="30" max="80" step="5" value={swingPct} onChange={e => setSwingPct(Number(e.target.value))} style={{ width: '100%', accentColor: '#38bdf8' }} />
                  </div>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', fontWeight: 700, marginBottom: '6px' }}>
                      <span style={{ color: '#10b981' }}>🛡️ Long-Term Core:</span>
                      <span>{ltPct}% (₹{capitalMath.lt.budget.toLocaleString('en-IN')})</span>
                    </div>
                    <input type="range" min="10" max="50" step="5" value={ltPct} onChange={e => setLtPct(Number(e.target.value))} style={{ width: '100%', accentColor: '#10b981' }} />
                  </div>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', fontWeight: 700, marginBottom: '6px' }}>
                      <span style={{ color: '#c084fc' }}>💎 Quality Penny SIP:</span>
                      <span>{pennyPct}% (₹{capitalMath.penny.budget.toLocaleString('en-IN')})</span>
                    </div>
                    <input type="range" min="5" max="30" step="5" value={pennyPct} onChange={e => setPennyPct(Number(e.target.value))} style={{ width: '100%', accentColor: '#c084fc' }} />
                  </div>
                </div>
              </div>
            </div>

            {/* 3 Pillar Summary Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '20px' }}>
              
              {/* Pillar 1: Swing Trading */}
              <div style={{ background: '#0f172a', border: '1.5px solid rgba(56, 189, 248, 0.4)', borderRadius: '16px', padding: '20px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <span style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', fontSize: '11px', fontWeight: 800, padding: '3px 8px', borderRadius: '6px' }}>PILLAR 1 • 60% (REVOLVING)</span>
                    <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700 }}>Broker: Zerodha Kite</span>
                  </div>
                  <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>⚡ Swing Trading Fund</div>
                  <div style={{ fontSize: '28px', fontWeight: 900, color: '#38bdf8', margin: '10px 0' }}>₹{capitalMath.swing.available.toLocaleString('en-IN')} <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 600 }}>available cash</span></div>
                  
                  <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: '10px', padding: '12px', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1' }}>
                      <span>New Injected Capital:</span>
                      <strong>₹{capitalMath.swing.injected.toLocaleString('en-IN')}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1' }}>
                      <span>Active Deployed (Revolving):</span>
                      <strong style={{ color: '#38bdf8' }}>₹{capitalMath.swing.deployed.toLocaleString('en-IN')}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1' }}>
                      <span>Realized Profits:</span>
                      <strong style={{ color: capitalMath.swing.realized >= 0 ? '#10b981' : '#f87171' }}>{capitalMath.swing.realized >= 0 ? '+' : ''}₹{capitalMath.swing.realized.toLocaleString('en-IN')}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#a5b4fc', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '6px', marginTop: '2px' }}>
                      <span>Total Revolving Pool:</span>
                      <strong style={{ color: '#a5b4fc' }}>₹{capitalMath.swing.totalPool.toLocaleString('en-IN')}</strong>
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
                    <span style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', fontSize: '11px', fontWeight: 800, padding: '3px 8px', borderRadius: '6px' }}>PILLAR 2 • 30%</span>
                    <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700 }}>Broker: INDMONEY</span>
                  </div>
                  <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>🛡️ Long-Term Core Quality</div>
                  <div style={{ fontSize: '28px', fontWeight: 900, color: '#10b981', margin: '10px 0' }}>₹{capitalMath.lt.available.toLocaleString('en-IN')} <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 600 }}>available cash</span></div>
                  
                  <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: '10px', padding: '12px', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1' }}>
                      <span>Total Allocated:</span>
                      <strong>₹{capitalMath.lt.injected.toLocaleString('en-IN')}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1' }}>
                      <span>Active Deployed:</span>
                      <strong style={{ color: '#10b981' }}>₹{capitalMath.lt.deployed.toLocaleString('en-IN')}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1' }}>
                      <span>Realized Profits:</span>
                      <strong style={{ color: capitalMath.lt.realized >= 0 ? '#10b981' : '#f87171' }}>{capitalMath.lt.realized >= 0 ? '+' : ''}₹{capitalMath.lt.realized.toLocaleString('en-IN')}</strong>
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
                    <span style={{ background: 'rgba(192, 132, 252, 0.15)', color: '#c084fc', fontSize: '11px', fontWeight: 800, padding: '3px 8px', borderRadius: '6px' }}>PILLAR 3 • 10%</span>
                    <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700 }}>Broker: Zerodha Kite</span>
                  </div>
                  <div style={{ fontSize: '18px', fontWeight: 900, color: '#ffffff' }}>💎 Quality Penny SIP</div>
                  <div style={{ fontSize: '28px', fontWeight: 900, color: '#c084fc', margin: '10px 0' }}>₹{capitalMath.penny.available.toLocaleString('en-IN')} <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 600 }}>available cash</span></div>
                  
                  <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: '10px', padding: '12px', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1' }}>
                      <span>Total Allocated:</span>
                      <strong>₹{capitalMath.penny.injected.toLocaleString('en-IN')}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1' }}>
                      <span>Active Deployed:</span>
                      <strong style={{ color: '#c084fc' }}>₹{capitalMath.penny.deployed.toLocaleString('en-IN')}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1' }}>
                      <span>Realized Profits:</span>
                      <strong style={{ color: capitalMath.penny.realized >= 0 ? '#10b981' : '#f87171' }}>{capitalMath.penny.realized >= 0 ? '+' : ''}₹{capitalMath.penny.realized.toLocaleString('en-IN')}</strong>
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

            {/* Capital Injections & Withdrawals Ledger Table */}
            <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '16px', padding: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' }}>
                <div style={{ fontSize: '15px', fontWeight: 800, color: '#ffffff' }}>📜 Capital Event Ledger (Injections &amp; Withdrawals)</div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  {capitalLedger.length > 0 && (
                    <button 
                      onClick={() => {
                        if (window.confirm('Reset and clear all capital injection/withdrawal records to ₹0?')) {
                          setCapitalLedger([]);
                          setMonthlyBudgetInput('0');
                          showToast('🧹 All capital records reset to ₹0!');
                        }
                      }}
                      style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#f87171', padding: '6px 12px', borderRadius: '6px', fontWeight: 800, fontSize: '11px', cursor: 'pointer' }}
                    >
                      🗑️ Reset to ₹0
                    </button>
                  )}
                  <button 
                    onClick={() => setShowCapModal(true)}
                    style={{ background: 'rgba(56, 189, 248, 0.15)', border: '1px solid rgba(56, 189, 248, 0.3)', color: '#38bdf8', padding: '6px 12px', borderRadius: '6px', fontWeight: 800, fontSize: '11px', cursor: 'pointer' }}
                  >
                    + Log Capital Event
                  </button>
                </div>
              </div>

              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                  <thead>
                    <tr style={{ background: 'rgba(255,255,255,0.03)', color: '#94a3b8', textAlign: 'left', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                      <th style={{ padding: '10px 12px' }}>DATE</th>
                      <th style={{ padding: '10px 12px' }}>EVENT TYPE</th>
                      <th style={{ padding: '10px 12px' }}>TARGET SEGMENT</th>
                      <th style={{ padding: '10px 12px' }}>AMOUNT (₹)</th>
                      <th style={{ padding: '10px 12px' }}>NOTES / REASON</th>
                      <th style={{ padding: '10px 12px', textAlign: 'right' }}>ACTION</th>
                    </tr>
                  </thead>
                  <tbody>
                    {capitalLedger.map((item, idx) => (
                      <tr key={item.id || idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        <td style={{ padding: '10px 12px', color: '#cbd5e1' }}>{item.date}</td>
                        <td style={{ padding: '10px 12px' }}>
                          <span style={{
                            padding: '3px 8px',
                            borderRadius: '4px',
                            fontWeight: 800,
                            fontSize: '10px',
                            background: item.type === 'INJECTION' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                            color: item.type === 'INJECTION' ? '#10b981' : '#f87171'
                          }}>
                            {item.type}
                          </span>
                        </td>
                        <td style={{ padding: '10px 12px', color: '#a5b4fc', fontWeight: 700 }}>{item.segment}</td>
                        <td style={{ padding: '10px 12px', fontWeight: 800, color: item.type === 'INJECTION' ? '#10b981' : '#f87171' }}>
                          {item.type === 'INJECTION' ? '+' : '-'}₹{Number(item.amount).toLocaleString('en-IN')}
                        </td>
                        <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{item.notes || '—'}</td>
                        <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                          <button 
                            onClick={() => {
                              if (window.confirm('Delete this capital event?')) {
                                setCapitalLedger(prev => prev.filter(c => c.id !== item.id));
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
                    ₹{portfolioSummary[activeTab]?.invested.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || '0.00'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#94a3b8', fontWeight: 800, textTransform: 'uppercase' }}>FREE BROKER CASH</div>
                  <div style={{ fontSize: '16px', fontWeight: 900, color: '#10b981', marginTop: '2px' }}>
                    ₹{portfolioSummary[activeTab]?.freeCash.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || '0.00'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#94a3b8', fontWeight: 800, textTransform: 'uppercase' }}>TOTAL SEGMENT CAPITAL</div>
                  <div style={{ fontSize: '16px', fontWeight: 900, color: '#38bdf8', marginTop: '2px' }}>
                    ₹{portfolioSummary[activeTab]?.totalCap.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || '0.00'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#fbbf24', fontWeight: 800, textTransform: 'uppercase' }}>EST. CHARGES</div>
                  <div style={{ fontSize: '16px', fontWeight: 900, color: '#fbbf24', marginTop: '2px' }}>
                    -₹{(portfolioSummary[activeTab]?.estCharges || 0).toFixed(2)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: '#94a3b8', fontWeight: 800, textTransform: 'uppercase' }}>NET UNREALIZED P&amp;L</div>
                  <div style={{ fontSize: '16px', fontWeight: 900, color: (portfolioSummary[activeTab]?.netPnl || 0) >= 0 ? '#10b981' : '#f87171', marginTop: '2px' }}>
                    {(portfolioSummary[activeTab]?.netPnl || 0) >= 0 ? '+' : ''}₹{(portfolioSummary[activeTab]?.netPnl || 0).toFixed(2)}
                    <span style={{ fontSize: '11px', marginLeft: '4px' }}>
                      ({(portfolioSummary[activeTab]?.netPct || 0) >= 0 ? '+' : ''}{(portfolioSummary[activeTab]?.netPct || 0).toFixed(2)}%)
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '1px' }}>
                    Gross: {(portfolioSummary[activeTab]?.grossPnl || 0) >= 0 ? '+' : ''}₹{(portfolioSummary[activeTab]?.grossPnl || 0).toFixed(2)} ({(portfolioSummary[activeTab]?.grossPct || 0) >= 0 ? '+' : ''}{(portfolioSummary[activeTab]?.grossPct || 0).toFixed(2)}%)
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
                      <th style={{ padding: '12px 14px' }}>EST. CHARGES</th>
                      <th style={{ padding: '12px 14px' }}>NET UNREALIZED P&amp;L</th>
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
                        <td style={{ padding: '12px 14px', fontWeight: 700, color: '#cbd5e1' }}>₹{h.costBasis.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td style={{ padding: '12px 14px', fontWeight: 900, color: '#38bdf8' }}>₹{h.ltp.toFixed(2)}</td>
                        <td style={{ padding: '12px 14px', fontWeight: 800, color: '#ffffff' }}>₹{h.currentVal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
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
                          <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                            Gross: {h.unrealizedPnl >= 0 ? '+' : ''}₹{h.unrealizedPnl.toFixed(2)} ({h.pnlPct >= 0 ? '+' : ''}{h.pnlPct.toFixed(2)}%)
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
                  <option value="SWING">⚡ Swing Trading (Zerodha Kite) — Avail: ₹{capitalMath.swing.available.toLocaleString('en-IN')}</option>
                  <option value="LT">🛡️ Long-Term Core (INDMONEY) — Avail: ₹{capitalMath.lt.available.toLocaleString('en-IN')}</option>
                  <option value="PENNY">💎 Quality Penny SIP (Zerodha Kite) — Avail: ₹{capitalMath.penny.available.toLocaleString('en-IN')}</option>
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
                  style={{ background: 'linear-gradient(135deg, #059669, #10b981)', color: '#090d16', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 900 }}
                >
                  Confirm Sale &amp; Recycle Capital
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

    </div>
  );
}
