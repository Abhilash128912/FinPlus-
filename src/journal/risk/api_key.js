/**
 * api_key.js — shared secret for the Finplus backend.
 *
 * The key is TYPED IN BY THE USER and kept on their device. It is deliberately
 * not baked into the bundle: this is a public web app, so anything compiled in
 * is readable by anyone who views source and would be no protection at all.
 *
 * The server fails open until FINPLUS_API_KEY is configured on the host, so an
 * empty key here keeps working until the backend is locked down.
 */

const KEY_STORAGE = 'finplus_api_key';

export function getApiKey() {
  try {
    return (localStorage.getItem(KEY_STORAGE) || '').trim();
  } catch (e) {
    return '';
  }
}

export function setApiKey(value) {
  try {
    const v = String(value || '').trim();
    if (v) localStorage.setItem(KEY_STORAGE, v);
    else localStorage.removeItem(KEY_STORAGE);
    return true;
  } catch (e) {
    return false;
  }
}

export function hasApiKey() {
  return getApiKey().length > 0;
}

/** Headers for a private request. Omits the header entirely when no key is set. */
export function authHeaders(extra = {}) {
  const key = getApiKey();
  return key ? { ...extra, 'X-Finplus-Key': key } : { ...extra };
}

/** fetch() with the key attached. Same signature as fetch. */
export function authFetch(url, init = {}) {
  return fetch(url, { ...init, headers: authHeaders(init.headers || {}) });
}

/**
 * Ask a server whether the key it has is accepted.
 * @returns {{ ok, authRequired, keyValid, error }}
 */
export async function checkApiKey(baseUrl) {
  try {
    const health = await fetch(`${baseUrl}/api/health`, { signal: AbortSignal.timeout(8000) });
    if (!health.ok) return { ok: false, authRequired: null, keyValid: null, error: 'Server unreachable' };
    const info = await health.json();
    const authRequired = info?.auth === 'enabled';
    if (!authRequired) return { ok: true, authRequired: false, keyValid: true, error: null };

    const probe = await authFetch(`${baseUrl}/api/backup/load`, { signal: AbortSignal.timeout(8000) });
    return {
      ok: probe.ok,
      authRequired: true,
      keyValid: probe.status !== 401,
      error: probe.status === 401 ? 'Key rejected by the server' : null
    };
  } catch (e) {
    return { ok: false, authRequired: null, keyValid: null, error: e.message };
  }
}
