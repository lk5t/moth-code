/**
 * MOTH account client.
 *
 * Talks to the owner-operated MOTH Server. Session tokens are stored by the Rust shell in
 * the OS credential vault (Windows Credential Manager) — never in localStorage. In a plain
 * browser (development without Tauri) tokens are kept for the tab only (sessionStorage).
 * The local backend receives the active session in memory so it can use MOTH Cloud
 * features on the user's behalf; it never persists the token.
 */
import { invoke } from "@tauri-apps/api/core";
import { isTauri, put } from "./backend";
import { createStore } from "./store";
import { CLIENT_HEADER, hasOfficialServer, rememberLegacyServer, resolveServer, setDeveloperOverride } from "./endpoint";

export interface MothUser {
  id: number;
  username: string;
  email: string;
  role: "user" | "admin" | "owner";
  display_name: string;
  email_verified: boolean;
  avatar_url: string | null;
  settings: Record<string, unknown>;
  plan: string;
  referral_code: string;
  created_at: number;
}

export interface SavedAccount {
  server: string;
  username: string;
  display_name?: string | null;
  avatar_url?: string | null;
  role?: string | null;
  last_used: number;
}

interface AccountsFile {
  active: string | null;
  accounts: SavedAccount[];
}

export interface AccountState {
  serverUrl: string;
  user: MothUser | null;
  token: string | null;
  accounts: SavedAccount[];
  activeKey: string | null;
  ready: boolean;
  offline: boolean;
  /** Set when MOTH Cloud says this version is too old (HTTP 426); the updater takes over. */
  updateRequired: string | null;
}

function loadServerUrl(): string {
  try {
    return normalizeServerUrl(resolveServer());
  } catch {
    return "";
  }
}

export const accountStore = createStore<AccountState>({
  serverUrl: loadServerUrl(),
  user: null,
  token: null,
  accounts: [],
  activeKey: null,
  ready: false,
  offline: false,
  updateRequired: null,
});
export const useAccount = accountStore.useStore;

export const accountKey = (server: string, username: string) => `${server.replace(/\/$/, "")}|${username.toLowerCase()}`;

export class ServerError extends Error {
  constructor(public status: number, message: string, public reason?: string | null, public retryAfter?: number) {
    super(message);
  }
}

const RETRY_DELAYS_MS = [500, 1500, 4000];

/** Call MOTH Cloud. Every request declares the client version (so the server can refuse outdated
 *  clients before they touch data), times out instead of hanging, and safe requests (GET) are
 *  retried with exponential backoff on network errors and server errors. */
export async function serverApi<T = any>(
  path: string,
  init: RequestInit & { json?: unknown; token?: string | null; server?: string; timeoutMs?: number; retries?: number } = {},
): Promise<T> {
  const server = normalizeServerUrl(init.server ?? accountStore.getState().serverUrl);
  if (!server) throw new ServerError(0, "MOTH Cloud isn't configured in this build. Ask the MOTH team for an updated installer.");
  const headers: Record<string, string> = { "X-Moth-Client": CLIENT_HEADER, ...(init.headers as Record<string, string>) };
  const token = init.token === undefined ? accountStore.getState().token : init.token;
  if (token) headers.Authorization = `Bearer ${token}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const method = (init.method ?? "GET").toUpperCase();
  const retries = init.retries ?? (method === "GET" ? RETRY_DELAYS_MS.length : 0);
  let res: Response | null = null;
  for (let attempt = 0; ; attempt++) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), init.timeoutMs ?? 20000);
    try {
      res = await fetch(server + path, { ...init, method, headers, body, signal: ctl.signal });
    } catch {
      res = null;
    } finally {
      clearTimeout(timer);
    }
    const retryable = res === null || res.status >= 500;
    if (!retryable || attempt >= retries) break;
    await new Promise((r) => setTimeout(r, RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)]));
  }
  if (res === null) {
    accountStore.setState({ offline: true });
    throw new ServerError(0, "Can't reach MOTH Cloud right now. MOTH Code keeps trying in the background.");
  }
  accountStore.setState({ offline: false });
  if (!res.ok) {
    let detail = res.statusText;
    let extra: any = {};
    try {
      extra = await res.json();
      detail = typeof extra.detail === "string" ? extra.detail : JSON.stringify(extra.detail);
    } catch {
      /* not json */
    }
    if (res.status === 401 && token && path !== "/v1/auth/login") handleExpired();
    if (res.status === 426) accountStore.setState({ updateRequired: extra.min_version ?? "newer" });
    if (res.status === 404 && (!detail || detail === "Not Found") && path.startsWith("/v1/auth/")) {
      detail = `${server} doesn't look like MOTH Cloud. Check the server address in Settings → Advanced.`;
    }
    throw new ServerError(res.status, detail, res.headers.get("X-Moth-Reason"), Number(res.headers.get("Retry-After") ?? 0));
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

// ---- token storage (OS vault in the desktop app) --------------------------------------------
async function vaultLoad(): Promise<AccountsFile> {
  if (isTauri()) return invoke<AccountsFile>("accounts_load");
  try {
    return JSON.parse(sessionStorage.getItem("moth.devAccounts") ?? '{"active":null,"accounts":[]}');
  } catch {
    return { active: null, accounts: [] };
  }
}

async function vaultRemember(account: SavedAccount, token: string): Promise<AccountsFile> {
  if (isTauri()) return invoke<AccountsFile>("accounts_remember", { account, token });
  const f = await vaultLoad();
  const key = accountKey(account.server, account.username);
  const accounts = [account, ...f.accounts.filter((a) => accountKey(a.server, a.username) !== key)];
  sessionStorage.setItem("moth.devAccounts", JSON.stringify({ active: key, accounts }));
  sessionStorage.setItem(`moth.devToken.${key}`, token);
  return { active: key, accounts };
}

async function vaultActivate(key: string): Promise<string | null> {
  if (isTauri()) return invoke<string | null>("accounts_activate", { key });
  const f = await vaultLoad();
  sessionStorage.setItem("moth.devAccounts", JSON.stringify({ ...f, active: key }));
  return sessionStorage.getItem(`moth.devToken.${key}`);
}

async function vaultSignOut(key: string, forget: boolean): Promise<AccountsFile> {
  if (isTauri()) return invoke<AccountsFile>(forget ? "accounts_forget" : "accounts_sign_out", { key });
  sessionStorage.removeItem(`moth.devToken.${key}`);
  const f = await vaultLoad();
  const next = {
    active: f.active === key ? null : f.active,
    accounts: forget ? f.accounts.filter((a) => accountKey(a.server, a.username) !== key) : f.accounts,
  };
  sessionStorage.setItem("moth.devAccounts", JSON.stringify(next));
  return next;
}

/** Tell the local backend about the active session (memory only). */
async function syncBackend() {
  const s = accountStore.getState();
  await put("/api/account/session", {
    server_url: s.serverUrl || null,
    token: s.token,
    user: s.user ? { id: s.user.id, username: s.user.username, role: s.user.role, plan: s.user.plan } : null,
  }).catch(() => {});
}

function handleExpired() {
  const { activeKey } = accountStore.getState();
  accountStore.setState({ user: null, token: null });
  if (activeKey) vaultSignOut(activeKey, false).then((f) => accountStore.setState({ accounts: f.accounts, activeKey: null }));
  syncBackend();
}

// ---- public API -------------------------------------------------------------------------------
/**
 * Turn what the user typed into a server origin: adds the scheme when it is missing (http for local
 * addresses, https otherwise) and drops trailing paths such as /v1 or /cloud, so requests reach the API.
 */
export function normalizeServerUrl(input: string): string {
  let s = input.trim();
  if (!s) return "";
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) {
    const local = /^(localhost|127\.|\[::1\]|0\.0\.0\.0|192\.168\.|10\.)/i.test(s);
    s = (local ? "http://" : "https://") + s;
  }
  let u: URL;
  try {
    u = new URL(s);
  } catch {
    throw new ServerError(0, `"${input.trim()}" is not a valid server address. Example: https://moth.example.com`);
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") {
    throw new ServerError(0, "The server address must start with https:// (or http:// for a local test server).");
  }
  const path = u.pathname.replace(/\/+$/, "").replace(/\/(v1|cloud)(\/.*)?$/i, "");
  return u.origin + path;
}

/** Developer/testing only when the build has an official endpoint; otherwise the address the
 *  user was given. Pass "" to clear a developer override. */
export function setServerUrl(url: string) {
  const clean = url ? normalizeServerUrl(url) : "";
  if (hasOfficialServer()) setDeveloperOverride(clean || null);
  else rememberLegacyServer(clean);
  accountStore.setState({ serverUrl: clean || normalizeServerUrl(resolveServer()) });
  syncBackend();
}

const REFRESH_EVERY_MS = 24 * 3600 * 1000;
let refreshTimer: ReturnType<typeof setInterval> | null = null;

/** Rotate the session token (keeps remembered sessions alive without signing in again). */
export async function refreshSession(): Promise<boolean> {
  const { token, activeKey, accounts, user } = accountStore.getState();
  if (!token || !user) return false;
  try {
    const r = await serverApi<{ token: string; user: MothUser }>("/v1/auth/refresh", { method: "POST", retries: 2 });
    const acct = accounts.find((a) => accountKey(a.server, a.username) === activeKey);
    if (acct) await vaultRemember({ ...acct, last_used: Date.now() / 1000 }, r.token);
    accountStore.setState({ token: r.token, user: r.user });
    await syncBackend();
    return true;
  } catch {
    return false; // offline or an older server without /refresh: the current session stays valid
  }
}

function scheduleRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => refreshSession(), REFRESH_EVERY_MS);
}

export async function initAccounts() {
  const f = await vaultLoad().catch(() => ({ active: null, accounts: [] }) as AccountsFile);
  accountStore.setState({ accounts: f.accounts, activeKey: f.active });
  if (f.active) {
    const acct = f.accounts.find((a) => accountKey(a.server, a.username) === f.active);
    const token = await vaultActivate(f.active).catch(() => null);
    if (acct && token) {
      accountStore.setState({ serverUrl: acct.server, token });
      try {
        const user = await serverApi<MothUser>("/v1/me", { token, server: acct.server });
        accountStore.setState({ user });
        refreshSession();
      } catch (e) {
        // Offline: stay signed in with the stored session; it is restored when MOTH Cloud is back.
        const st = (e as ServerError).status;
        if (st !== 0 && st !== 426 && st < 500) accountStore.setState({ token: null, user: null });
      }
    }
  }
  scheduleRefresh();
  accountStore.setState({ ready: true });
  syncBackend();
}

/** Called by the connection monitor when MOTH Cloud becomes reachable again. */
export async function restoreSessionIfNeeded() {
  const { token, user } = accountStore.getState();
  if (token && !user) {
    try {
      accountStore.setState({ user: await serverApi<MothUser>("/v1/me") });
      await syncBackend();
    } catch {
      /* stays signed out of cloud features until the next attempt */
    }
  }
}

export async function login(username: string, password: string, remember = true) {
  const server = normalizeServerUrl(accountStore.getState().serverUrl);
  const r = await serverApi<{ token: string; user: MothUser; remember: boolean }>("/v1/auth/login", {
    method: "POST",
    token: null,
    json: { username, password, remember, device_name: navigator.platform ? `MOTH Code (${navigator.platform})` : "MOTH Code" },
  });
  const acct: SavedAccount = {
    server, username: r.user.username, display_name: r.user.display_name, avatar_url: r.user.avatar_url,
    role: r.user.role, last_used: Date.now() / 1000,
  };
  if (remember) {
    const f = await vaultRemember(acct, r.token);
    accountStore.setState({ accounts: f.accounts, activeKey: f.active });
  } else {
    accountStore.setState({ activeKey: null }); // session lives in memory only
  }
  accountStore.setState({ user: r.user, token: r.token });
  await syncBackend();
  return r.user;
}

export async function register(username: string, email: string, password: string, referralCode?: string) {
  return serverApi<{ message: string }>("/v1/auth/register", {
    method: "POST", token: null,
    json: { username, email, password, referral_code: referralCode || null },
  });
}

export const forgotPassword = (ident: string) =>
  serverApi<{ message: string }>("/v1/auth/forgot-password", { method: "POST", token: null, json: { username_or_email: ident } });

export const resendVerification = (ident: string) =>
  serverApi<{ message: string }>("/v1/auth/resend-verification", { method: "POST", token: null, json: { username_or_email: ident } });

export async function logout(forget = false) {
  const { activeKey, token } = accountStore.getState();
  if (token) await serverApi("/v1/auth/logout", { method: "POST" }).catch(() => {});
  if (activeKey) {
    const f = await vaultSignOut(activeKey, forget);
    accountStore.setState({ accounts: f.accounts });
  }
  accountStore.setState({ user: null, token: null, activeKey: null });
  await syncBackend();
}

/** Switch to a saved account. Returns false if it needs a password (signed out or expired). */
export async function switchAccount(key: string): Promise<boolean> {
  const acct = accountStore.getState().accounts.find((a) => accountKey(a.server, a.username) === key);
  if (!acct) return false;
  const token = await vaultActivate(key).catch(() => null);
  accountStore.setState({ serverUrl: acct.server, activeKey: key, token: token ?? null, user: null });
  if (!token) {
    await syncBackend();
    return false;
  }
  try {
    const user = await serverApi<MothUser>("/v1/me", { token, server: acct.server });
    accountStore.setState({ user });
    await syncBackend();
    return true;
  } catch {
    return false;
  }
}

export async function forgetAccount(key: string) {
  const f = await vaultSignOut(key, true);
  const s = accountStore.getState();
  accountStore.setState({ accounts: f.accounts, ...(s.activeKey === key ? { user: null, token: null, activeKey: null } : {}) });
  await syncBackend();
}

export async function refreshMe() {
  const user = await serverApi<MothUser>("/v1/me");
  accountStore.setState({ user });
  return user;
}

/** Run a sensitive server call; if the server asks for re-authentication, prompt and retry once. */
export async function withReauth<T>(fn: () => Promise<T>, askPassword: () => Promise<string | null>): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    if (!(e instanceof ServerError) || e.status !== 428) throw e;
    const pw = await askPassword();
    if (!pw) throw e;
    await serverApi("/v1/auth/reauth", { method: "POST", json: { password: pw } });
    return fn();
  }
}
