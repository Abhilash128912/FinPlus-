/**
 * useRiskDesk.js — State, actions and live-price wiring for the Risk Desk.
 *
 * The existing held-stock LTP poller in App.jsx is left untouched. Its prices are
 * accepted here as `externalLtps` and reused; this hook runs a SEPARATE, additive
 * poller only for Risk Desk open trades whose symbols that poller does not cover.
 */

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  loadRiskStore, saveRiskStore, createId, appendAudit, emptyStore,
  pushRiskStore, fetchRiskStore, mergeRiskStores, serverValidate
} from './risk_storage.js';
import {
  buildMonthView, buildDailySnapshot, buildAccountView,
  liveSymbolsFor, computePlannedRisk, isClosed, enrichTrades
} from './risk_engine.js';
import { buildAccrualState } from './accrual_engine.js';
import { currentMonthKey, DEFAULT_CONFIG, reapplyConfigToMonths } from './risk_model.js';
import { validateTradeEntry, validateWithdrawal, validateGrowthRelease } from './validation.js';
import { evaluateDay } from './scoring.js';

const LTP_INTERVAL_MS = 20000;

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export function useRiskDesk({ externalLtps = {} } = {}) {
  const [store, setStore] = useState(() => loadRiskStore());
  const [monthKey, setMonthKey] = useState(() => {
    const initial = loadRiskStore();
    const now = currentMonthKey();
    return initial.months.some(m => m.month_key === now) ? now : initial.months[0]?.month_key;
  });
  const [riskLtps, setRiskLtps] = useState({});
  const [ltpUpdatedAt, setLtpUpdatedAt] = useState(null);
  const [syncState, setSyncState] = useState({ status: 'idle', message: '' });

  const config = useMemo(() => ({ ...DEFAULT_CONFIG, ...(store.config || {}) }), [store.config]);
  const profiles = store.broker_charge_profiles || [];

  /* ── Persist locally on every change, then push to the server ──────────── */
  const commit = useCallback((updater, audit) => {
    setStore(prev => {
      let next = typeof updater === 'function' ? updater(prev) : updater;
      if (audit) next = appendAudit(next, audit);
      const saved = saveRiskStore(next);
      pushRiskStore(saved)
        .then(res => setSyncState(res.ok
          ? { status: 'synced', message: res.skipped ? 'Up to date' : `Synced to ${res.server || 'server'}` }
          : { status: 'offline', message: res.error || 'Offline — saved locally' }))
        .catch(() => setSyncState({ status: 'offline', message: 'Offline — saved locally' }));
      return saved;
    });
  }, []);

  /* ── Pull server state once on mount and merge ─────────────────────────── */
  useEffect(() => {
    let cancelled = false;
    fetchRiskStore().then(res => {
      if (cancelled || !res.ok) {
        if (!cancelled) setSyncState({ status: 'offline', message: 'Local only — backend unreachable' });
        return;
      }
      setStore(prev => saveRiskStore(mergeRiskStores(prev, res.store)));
      setSyncState({ status: 'synced', message: `Merged from ${res.server}` });
    });
    return () => { cancelled = true; };
  }, []);

  /* ── Live prices: additive poller for Risk Desk open trades only ───────── */
  const openSymbols = useMemo(() => liveSymbolsFor(store.trades || []), [store.trades]);
  const openSymbolsKey = openSymbols.join(',');
  const inFlight = useRef(false);

  useEffect(() => {
    const symbols = openSymbolsKey ? openSymbolsKey.split(',').filter(Boolean) : [];
    if (symbols.length === 0) return;

    const fetchRiskLtps = async () => {
      if (inFlight.current) return;
      inFlight.current = true;
      const plain = symbols.join(',');
      const withNs = symbols.map(s => (s.includes('=') || s.startsWith('^') || s.endsWith('.NS') ? s : `${s}.NS`)).join(',');
      const endpoints = [
        `http://localhost:8000/api/investment/yfinance-prices?symbols=${encodeURIComponent(plain)}`,
        `http://127.0.0.1:8000/api/investment/yfinance-prices?symbols=${encodeURIComponent(plain)}`,
        `https://finplus.onrender.com/api/investment/yfinance-prices?symbols=${encodeURIComponent(plain)}`,
        `http://localhost:5000/api/ltp?ticker=${encodeURIComponent(withNs)}`
      ];
      for (const ep of endpoints) {
        try {
          const res = await fetch(ep, { signal: AbortSignal.timeout(4000) });
          if (!res.ok) continue;
          const data = await res.json();
          const source = data?.prices && typeof data.prices === 'object'
            ? data.prices
            : data?.ltps && typeof data.ltps === 'object'
              ? data.ltps
              : data;
          if (!source || typeof source !== 'object') continue;
          const updated = {};
          for (const [k, v] of Object.entries(source)) {
            const sym = String(k).replace('.NS', '').trim().toUpperCase();
            const price = typeof v === 'number' ? v : Number(v?.price ?? v?.ltp ?? v ?? 0);
            if (price > 0) updated[sym] = price;
          }
          if (Object.keys(updated).length) {
            setRiskLtps(prev => ({ ...prev, ...updated }));
            setLtpUpdatedAt(new Date().toLocaleTimeString());
            break;
          }
        } catch (e) {
          // try next endpoint
        }
      }
      inFlight.current = false;
    };

    fetchRiskLtps();
    const timer = setInterval(fetchRiskLtps, LTP_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [openSymbolsKey]);

  /** Existing app prices first, Risk Desk poller fills the gaps. */
  const ltps = useMemo(() => ({ ...(externalLtps || {}), ...riskLtps }), [externalLtps, riskLtps]);

  /* ── Derived views ─────────────────────────────────────────────────────── */

  /** Full history, priced — the counter accrues continuously across months. */
  const allTrades = useMemo(
    () => enrichTrades({ trades: store.trades, profiles, config, ltps }),
    [store.trades, profiles, config, ltps]
  );

  const accrualState = useMemo(
    () => buildAccrualState({ trades: allTrades, config }),
    [allTrades, config]
  );

  const month = useMemo(
    () => store.months?.find(m => m.month_key === monthKey) || store.months?.[0],
    [store.months, monthKey]
  );

  const monthView = useMemo(
    () => (month ? buildMonthView({
      month,
      trades: store.trades,
      reserveTransfers: store.opportunity_reserve_transfers,
      profiles,
      config,
      ltps
    }) : null),
    [month, store.trades, store.opportunity_reserve_transfers, profiles, config, ltps]
  );

  const dailySnapshot = useMemo(
    () => buildDailySnapshot({ trades: store.trades, profiles, config }),
    [store.trades, profiles, config]
  );

  const accountView = useMemo(
    () => buildAccountView({
      trades: store.trades,
      cashLedger: store.broker_cash_ledger,
      growthLedger: store.growth_reserve_ledger,
      profiles,
      config
    }),
    [store.trades, store.broker_cash_ledger, store.growth_reserve_ledger, profiles, config]
  );

  /** Validation bound to the current month/day state. */
  const validate = useCallback(
    ({ trade, score, planned, correlation, segView }) => validateTradeEntry({
      trade,
      score,
      planned: planned || computePlannedRisk(trade, profiles, config),
      correlation,
      segView: segView || monthView?.segments?.find(s => s.id === trade?.segment),
      dailySnapshot,
      monthView,
      accrualState,
      profiles,
      config,
      recentTrades: allTrades.filter(isClosed)
    }),
    [profiles, config, monthView, dailySnapshot, accrualState, allTrades]
  );

  const todaySetups = useMemo(
    () => (store.trade_setups || []).filter(s => String(s.setup_date || '').slice(0, 10) === todayIso()),
    [store.trade_setups]
  );

  const dayDecision = useMemo(
    () => evaluateDay({ setups: todaySetups, monthView, dailySnapshot, profiles, config, validate }),
    [todaySetups, monthView, dailySnapshot, profiles, config, validate]
  );

  /* ── Actions ───────────────────────────────────────────────────────────── */

  const saveSetup = useCallback((setup) => {
    const id = setup.id || createId('setup');
    commit(
      prev => ({
        ...prev,
        trade_setups: setup.id
          ? prev.trade_setups.map(s => (s.id === setup.id ? { ...s, ...setup, updated_at: new Date().toISOString() } : s))
          : [...prev.trade_setups, { ...setup, id, setup_date: setup.setup_date || todayIso(), created_at: new Date().toISOString() }]
      }),
      { action: setup.id ? 'SETUP_UPDATED' : 'SETUP_RECORDED', entity: 'trade_setups', entity_id: id, month_key: monthKey, detail: { segment: setup.segment, symbol: setup.symbol } }
    );
    return id;
  }, [commit, monthKey]);

  const deleteSetup = useCallback((id) => {
    commit(
      prev => ({ ...prev, trade_setups: prev.trade_setups.filter(s => s.id !== id) }),
      { action: 'SETUP_DELETED', entity: 'trade_setups', entity_id: id, month_key: monthKey }
    );
  }, [commit, monthKey]);

  /**
   * Record a taken trade. Server re-validates; a disagreement is returned to the
   * caller for display rather than silently discarded.
   */
  const recordTrade = useCallback(async (trade, { overrideReason = null } = {}) => {
    const planned = computePlannedRisk(trade, profiles, config);
    const id = trade.id || createId('trade');
    const reserveAmount = Number(trade.reserve_risk_used) || 0;

    const record = {
      ...trade,
      id,
      status: 'OPEN',
      entry_date: trade.entry_date || new Date().toISOString(),
      planned_price_risk: planned.priceRisk,
      planned_total_risk: planned.totalRisk,
      estimated_charges: planned.estimatedCharges,
      estimated_charge_breakdown: planned.estimatedBreakdown,
      charge_profile_id: planned.chargeProfileId,
      daily_position_number: (dailySnapshot?.positionCount || 0) + 1,
      created_at: new Date().toISOString()
    };

    commit(prev => {
      let next = {
        ...prev,
        trades: [...prev.trades, record]
      };
      if (reserveAmount > 0) {
        // Auditable chain: Opportunity Reserve -> Segment -> Trade.
        next = {
          ...next,
          opportunity_reserve_transfers: [
            ...next.opportunity_reserve_transfers,
            {
              id: createId('rsv'),
              month_key: monthKey,
              to_segment: trade.segment,
              trade_id: id,
              amount: reserveAmount,
              reason: trade.reserve_reason || '',
              at: new Date().toISOString()
            }
          ]
        };
      }
      return next;
    }, {
      action: 'TRADE_RECORDED',
      entity: 'trades',
      entity_id: id,
      month_key: monthKey,
      override_reason: overrideReason,
      detail: {
        segment: trade.segment,
        symbol: trade.symbol,
        planned_total_risk: planned.totalRisk,
        reserve_used: reserveAmount,
        grade: trade.grade
      }
    });

    const server = await serverValidate({ action: 'TRADE_RECORDED', trade: record, month_key: monthKey });
    return { id, planned, server };
  }, [commit, profiles, config, monthKey, dailySnapshot]);

  const closeTrade = useCallback((id, { exit_price, exit_date, exit_reason, actual_charges }) => {
    commit(
      prev => ({
        ...prev,
        trades: prev.trades.map(t => (t.id === id ? {
          ...t,
          status: 'CLOSED',
          exit_price: Number(exit_price) || 0,
          exit_date: exit_date || new Date().toISOString(),
          exit_reason: exit_reason || '',
          actual_charges: actual_charges || t.actual_charges || null,
          updated_at: new Date().toISOString()
        } : t))
      }),
      { action: 'TRADE_CLOSED', entity: 'trades', entity_id: id, month_key: monthKey, detail: { exit_price, exit_reason } }
    );
  }, [commit, monthKey]);

  const setActualCharges = useCallback((id, breakdown, contractNoteRef) => {
    commit(
      prev => ({
        ...prev,
        trades: prev.trades.map(t => (t.id === id ? {
          ...t,
          actual_charges: breakdown,
          contract_note_ref: contractNoteRef || t.contract_note_ref || null,
          updated_at: new Date().toISOString()
        } : t))
      }),
      { action: 'ACTUAL_CHARGES_SET', entity: 'trades', entity_id: id, month_key: monthKey, detail: { contractNoteRef } }
    );
  }, [commit, monthKey]);

  const setManualLtp = useCallback((id, price) => {
    commit(prev => ({
      ...prev,
      trades: prev.trades.map(t => (t.id === id ? { ...t, manual_ltp: Number(price) || null } : t))
    }));
  }, [commit]);

  const addCashEntry = useCallback((entry) => {
    if (entry.type === 'WITHDRAWAL') {
      const v = validateWithdrawal({ amount: entry.amount, accountView });
      if (!v.ok) return v;
    }
    const id = createId('cash');
    commit(
      prev => ({ ...prev, broker_cash_ledger: [...prev.broker_cash_ledger, { ...entry, id, at: entry.at || new Date().toISOString() }] }),
      { action: `CASH_${entry.type}`, entity: 'broker_cash_ledger', entity_id: id, month_key: monthKey, detail: { amount: entry.amount, note: entry.note } }
    );
    return { ok: true, blocked: [], warnings: [] };
  }, [commit, accountView, monthKey]);

  const addGrowthEntry = useCallback((entry) => {
    if (entry.type === 'FROM_GROWTH') {
      const v = validateGrowthRelease({ amount: entry.amount, accountView, monthView });
      if (!v.ok) return v;
    }
    if (entry.type === 'TO_GROWTH' && Number(entry.amount) > accountView.withdrawableCash + 0.001) {
      return { ok: false, blocked: [{ code: 'INSUFFICIENT_CASH', message: `Only ${accountView.withdrawableCash.toFixed(2)} of realized cash is available to retain.`, severity: 'BLOCK' }], warnings: [] };
    }
    const id = createId('growth');
    commit(
      prev => ({ ...prev, growth_reserve_ledger: [...prev.growth_reserve_ledger, { ...entry, id, at: entry.at || new Date().toISOString() }] }),
      { action: entry.type, entity: 'growth_reserve_ledger', entity_id: id, month_key: monthKey, detail: { amount: entry.amount, note: entry.note } }
    );
    const warnings = entry.type === 'FROM_GROWTH'
      ? validateGrowthRelease({ amount: entry.amount, accountView, monthView }).warnings
      : [];
    return { ok: true, blocked: [], warnings };
  }, [commit, accountView, monthView, monthKey]);

  /** Config changes rebuild every open month so budgets and allocations follow. */
  const updateConfig = useCallback((patch) => {
    commit(
      prev => {
        const nextConfig = { ...prev.config, ...patch };
        return { ...prev, config: nextConfig, months: reapplyConfigToMonths(prev.months, nextConfig) };
      },
      { action: 'CONFIG_UPDATED', entity: 'config', detail: patch }
    );
  }, [commit]);

  /** Wipe Risk Desk data. Config is kept so the user does not re-enter their budget. */
  const resetAll = useCallback(({ keepConfig = true } = {}) => {
    commit(prev => {
      const fresh = emptyStore();
      const config = keepConfig ? prev.config : fresh.config;
      return {
        ...fresh,
        config,
        months: reapplyConfigToMonths(fresh.months, config),
        broker_charge_profiles: prev.broker_charge_profiles || fresh.broker_charge_profiles
      };
    }, { action: 'RISK_DESK_RESET', entity: 'store', detail: { keepConfig } });
  }, [commit]);

  return {
    store, config, profiles,
    monthKey, setMonthKey, months: store.months || [],
    month, monthView, dailySnapshot, accountView, dayDecision, todaySetups,
    accrualState, allTrades,
    ltps, ltpUpdatedAt, syncState, trackedSymbols: openSymbols,
    validate,
    actions: {
      saveSetup, deleteSetup, recordTrade, closeTrade,
      setActualCharges, setManualLtp, addCashEntry, addGrowthEntry, updateConfig, resetAll
    }
  };
}
