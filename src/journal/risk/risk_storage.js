/**
 * risk_storage.js — Local-first persistence with server-side validation.
 *
 * Local compute keeps the Android build usable offline. The backend re-validates
 * every state-changing action and owns the authoritative audit log; when it is
 * unreachable the action still lands locally and is queued for replay.
 */

import { generateMonths, DEFAULT_CONFIG } from './risk_model.js';
import { SEED_CHARGE_PROFILES } from './broker_profiles.js';
import { getCloudSyncServers } from '../journal_engine.js';

const STORE_KEY = 'finplus_risk_desk_v1';
const QUEUE_KEY = 'finplus_risk_audit_queue_v1';
const SCHEMA_VERSION = 1;

export function emptyStore() {
  return {
    schema_version: SCHEMA_VERSION,
    months: generateMonths(DEFAULT_CONFIG),
    segment_buckets_overrides: {},
    trade_setups: [],
    trades: [],
    daily_risk_snapshots: [],
    opportunity_reserve_transfers: [],
    broker_charge_profiles: SEED_CHARGE_PROFILES,
    broker_cash_ledger: [],
    growth_reserve_ledger: [],
    audit_log: [],
    config: { ...DEFAULT_CONFIG },
    updated_at: null
  };
}

/** Adds anything missing after a schema bump without discarding user data. */
function migrate(store) {
  const base = emptyStore();
  const merged = { ...base, ...store };
  merged.config = { ...base.config, ...(store.config || {}) };
  // Obsolete keys from the monthly-pool model, superseded by the daily counter
  // and openingDeductions. Dropped so stale values cannot resurface.
  delete merged.config.september;
  if (!Array.isArray(merged.months) || merged.months.length === 0) merged.months = base.months;
  if (!Array.isArray(merged.broker_charge_profiles) || merged.broker_charge_profiles.length === 0) {
    merged.broker_charge_profiles = base.broker_charge_profiles;
  }
  for (const k of [
    'trade_setups', 'trades', 'daily_risk_snapshots', 'opportunity_reserve_transfers',
    'broker_cash_ledger', 'growth_reserve_ledger', 'audit_log'
  ]) {
    if (!Array.isArray(merged[k])) merged[k] = [];
  }
  merged.schema_version = SCHEMA_VERSION;
  return merged;
}

export function loadRiskStore() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return emptyStore();
    return migrate(JSON.parse(raw) || {});
  } catch (e) {
    return emptyStore();
  }
}

let lastPushedJson = '';

export function saveRiskStore(store) {
  const next = { ...store, updated_at: new Date().toISOString() };
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(next));
  } catch (e) {
    // Quota or private mode — in-memory state still holds for this session.
  }
  return next;
}

export function createId(prefix = 'r') {
  const rand = typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
  return `${prefix}_${rand}`;
}

/* ────────────────────────────── Audit log ────────────────────────────── */

/**
 * Every state change goes through here. Reserve moves record the full
 * Opportunity Reserve → Segment → Trade chain required by §4.
 */
export function appendAudit(store, entry) {
  const record = {
    id: createId('audit'),
    at: new Date().toISOString(),
    action: entry.action,
    entity: entry.entity || null,
    entity_id: entry.entity_id || null,
    month_key: entry.month_key || null,
    detail: entry.detail || {},
    override_reason: entry.override_reason || null,
    server_confirmed: false
  };
  return { ...store, audit_log: [...(store.audit_log || []), record] };
}

/* ────────────────────────── Server round-trips ───────────────────────── */

async function tryServers(path, init) {
  for (const base of getCloudSyncServers()) {
    try {
      const res = await fetch(`${base}${path}`, {
        ...init,
        signal: AbortSignal.timeout(6000),
        headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) }
      });
      if (res.ok) return { ok: true, server: base, data: await res.json() };
    } catch (e) {
      // next candidate
    }
  }
  return { ok: false, error: 'Risk Desk backend unreachable — running on local validation only.' };
}

/**
 * Server-side re-validation. The local result is authoritative for UX responsiveness;
 * a server disagreement is surfaced to the user rather than silently applied.
 */
export async function serverValidate(payload) {
  const res = await tryServers('/api/risk/validate', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  if (!res.ok) return { available: false, agrees: null, blocked: [], error: res.error };
  return {
    available: true,
    agrees: !!res.data?.agrees,
    blocked: res.data?.blocked || [],
    warnings: res.data?.warnings || [],
    server: res.server
  };
}

export async function pushRiskStore(store) {
  const json = JSON.stringify({
    schema_version: SCHEMA_VERSION,
    months: store.months,
    trade_setups: store.trade_setups,
    trades: store.trades,
    opportunity_reserve_transfers: store.opportunity_reserve_transfers,
    broker_charge_profiles: store.broker_charge_profiles,
    broker_cash_ledger: store.broker_cash_ledger,
    growth_reserve_ledger: store.growth_reserve_ledger,
    audit_log: store.audit_log,
    config: store.config,
    updated_at: store.updated_at
  });
  if (json === lastPushedJson) return { ok: true, skipped: true };

  const res = await tryServers('/api/risk/sync', { method: 'POST', body: json });
  if (res.ok) lastPushedJson = json;
  return res;
}

export async function fetchRiskStore() {
  const res = await tryServers('/api/risk/sync', { method: 'GET' });
  if (!res.ok || !res.data) return { ok: false, error: res.error };
  return { ok: true, store: migrate(res.data), server: res.server };
}

/** Newest-wins merge on updated_at, with per-collection union by id. */
export function mergeRiskStores(local, remote) {
  if (!remote) return local;
  if (!local) return remote;

  const unionById = (a = [], b = []) => {
    const map = new Map();
    for (const row of [...a, ...b]) {
      if (!row) continue;
      const key = row.id || row.uuid || JSON.stringify(row);
      const existing = map.get(key);
      if (!existing) { map.set(key, row); continue; }
      const newer = String(row.updated_at || row.at || '') > String(existing.updated_at || existing.at || '') ? row : existing;
      map.set(key, newer);
    }
    return Array.from(map.values());
  };

  const remoteNewer = String(remote.updated_at || '') > String(local.updated_at || '');
  return {
    ...(remoteNewer ? remote : local),
    months: (remoteNewer ? remote.months : local.months) || local.months,
    trades: unionById(local.trades, remote.trades),
    trade_setups: unionById(local.trade_setups, remote.trade_setups),
    opportunity_reserve_transfers: unionById(local.opportunity_reserve_transfers, remote.opportunity_reserve_transfers),
    broker_cash_ledger: unionById(local.broker_cash_ledger, remote.broker_cash_ledger),
    growth_reserve_ledger: unionById(local.growth_reserve_ledger, remote.growth_reserve_ledger),
    audit_log: unionById(local.audit_log, remote.audit_log),
    broker_charge_profiles: unionById(local.broker_charge_profiles, remote.broker_charge_profiles),
    config: { ...(local.config || {}), ...(remoteNewer ? remote.config || {} : {}) },
    updated_at: remoteNewer ? remote.updated_at : local.updated_at
  };
}
