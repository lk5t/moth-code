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
}

const DEFAULT_SERVER = ((import.meta.env.VITE_MOTH_SERVER_URL as string | undefined) ?? "").replace(/\/$/, "");

function loadServerUrl(): string {
  try {
    return localStorage.getItem("moth.serverUrl") ?? DEFAULT_SERVER;
  } catch {
    return DEFAULT_SERVER;
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
});
export const useAccount = accountStore.useStore;

export const accountKey = (server: string, username: string) => `${server.replace(/\/$/, "")}|${username.toLowerCase()}`;

export class ServerError extends Error {
  constructor(public status: number, message: string, public reason?: string | null, public retryAfter?: number) {
    super(message);
  }
}

export async function serverApi<T = any>(
  path: string,
  init: RequestInit & { json?: unknown; token?: string | null; server?: string } = {},
): Promise<T> {
  const server = (init.server ?? accountStore.getState().serverUrl).replace(/\/$/, "");
  if (!server) throw new ServerError(0, "No MOTH Server is configured. Set its address in Settings → Account.");
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  const token = init.token === undefined ? accountStore.getState().token : init.token;
  if (token) headers.Authorization = `Bearer ${token}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(server + path, { ...init, headers, body });
  } catch {
    accountStore.setState({ offline: true });
    throw new ServerError(0, "Can't reach the MOTH Server. Local features keep working offline.");
  }
  accountStore.setState({ offline: false });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const d = await res.json();
      detail = typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail);
    } catch {
      /* not json */
    }
    if (res.status === 401 && token && path !== "/v1/auth/login") handleExpired();
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
export function setServerUrl(url: string) {
  const clean = url.trim().replace(/\/$/, "");
  try {
    localStorage.setItem("moth.serverUrl", clean);
  } catch {
    /* storage unavailable */
  }
  accountStore.setState({ serverUrl: clean });
  syncBackend();
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
      } catch (e) {
        // Offline: stay signed in with the stored session; local features are unaffected.
        if ((e as ServerError).status !== 0) accountStore.setState({ token: null, user: null });
      }
    }
  }
  accountStore.setState({ ready: true });
  syncBackend();
}

export async function login(username: string, password: string, remember = true) {
  const server = accountStore.getState().serverUrl;
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
