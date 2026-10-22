// Single place every /api request goes through.
// - X-Client-Id: an anonymous random id kept in this browser, so the server can scope history to it.
// - adminFetch: adds X-Admin-Token and prompts for it once when the server answers 401.

const CLIENT_ID_KEY = 'tl_client_id';
const ADMIN_TOKEN_KEY = 'tl_admin_token';

const randomId = () => {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
  // RFC 4122 v4 fallback for older browsers
  const b = new Uint8Array(16);
  window.crypto.getRandomValues(b);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, x => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
};

// Falls back to a per-session id when storage is blocked (private mode, disabled cookies)
let sessionClientId = null;
export const getClientId = () => {
  try {
    let id = localStorage.getItem(CLIENT_ID_KEY);
    if (!id) {
      id = randomId();
      localStorage.setItem(CLIENT_ID_KEY, id);
    }
    return id;
  } catch (e) {
    if (!sessionClientId) sessionClientId = randomId();
    return sessionClientId;
  }
};

export const api = (url, options = {}) =>
  fetch(url, { ...options, headers: { ...(options.headers || {}), 'X-Client-Id': getClientId() } });

export const postJson = (url, body) =>
  api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

const getAdminToken = () => { try { return sessionStorage.getItem(ADMIN_TOKEN_KEY) || ''; } catch (e) { return ''; } };
const setAdminToken = (t) => { try { sessionStorage.setItem(ADMIN_TOKEN_KEY, t); } catch (e) {} };

export const adminFetch = async (url, options = {}) => {
  const withToken = () => ({ ...options, headers: { ...(options.headers || {}), 'X-Admin-Token': getAdminToken() } });
  let res = await api(url, withToken());
  if (res.status === 401) {
    const t = window.prompt('This action needs the admin token (ADMIN_TOKEN in the server .env):');
    if (!t) return res;
    setAdminToken(t);
    res = await api(url, withToken());
  }
  return res;
};

// Server errors are {"detail": "<string>"}; older/validation responses may use a list of {msg}
export const errorMessage = async (res, fallback = 'Request failed') => {
  try {
    const data = await res.json();
    const d = data && data.detail;
    if (Array.isArray(d)) return d.map(e => (e && e.msg) || String(e)).join(', ') || fallback;
    if (typeof d === 'string' && d) return d;
    if (data && typeof data.message === 'string') return data.message;
  } catch (e) { /* non-JSON body */ }
  return res.status === 429 ? 'Too many requests. Please wait a moment and try again.' : `${fallback} (HTTP ${res.status})`;
};
