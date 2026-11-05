/**
 * MOTH Cloud connection monitor: checks /v1/health in the background, reconnects with exponential
 * backoff (2 s → 60 s) after network failures, restores the session when MOTH Cloud is back, and
 * exposes one quiet status for the status bar — never a popup.
 */
import { accountStore, normalizeServerUrl, restoreSessionIfNeeded } from "./account";
import { APP_VERSION, CLIENT_HEADER } from "./endpoint";
import { createStore } from "./store";

export type ConnectionStatus = "connecting" | "online" | "reconnecting" | "offline" | "unconfigured";

export interface ConnectionState {
  status: ConnectionStatus;
  serverVersion: string | null;
  apiVersion: number | null;
  minDesktop: string | null;
  latencyMs: number | null;
  failures: number;
  nextRetryAt: number | null;
}

export const connectionStore = createStore<ConnectionState>({
  status: "connecting", serverVersion: null, apiVersion: null, minDesktop: null, latencyMs: null, failures: 0,
  nextRetryAt: null,
});
export const useConnection = connectionStore.useStore;

const ONLINE_POLL_MS = 60_000;
const MAX_BACKOFF_MS = 60_000;
let timer: ReturnType<typeof setTimeout> | null = null;
let started = false;

export function versionLess(a: string, b: string): boolean {
  const pa = a.split(/[.+-]/).slice(0, 3).map(Number);
  const pb = b.split(/[.+-]/).slice(0, 3).map(Number);
  for (let i = 0; i < 3; i++) if ((pa[i] ?? 0) !== (pb[i] ?? 0)) return (pa[i] ?? 0) < (pb[i] ?? 0);
  return false;
}

export function backoffMs(failures: number): number {
  return Math.min(MAX_BACKOFF_MS, 2000 * 2 ** Math.max(0, failures - 1));
}

export async function checkNow(): Promise<ConnectionState> {
  if (timer) clearTimeout(timer);
  const server = (() => {
    try {
      return normalizeServerUrl(accountStore.getState().serverUrl);
    } catch {
      return "";
    }
  })();
  const prev = connectionStore.getState();
  if (!server) {
    connectionStore.setState({ status: "unconfigured" });
    return connectionStore.getState();
  }
  const t0 = performance.now();
  const ctl = new AbortController();
  const abort = setTimeout(() => ctl.abort(), 10000);
  try {
    const r = await fetch(`${server}/v1/health`, { headers: { "X-Moth-Client": CLIENT_HEADER }, signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const h = await r.json();
    const minDesktop = h.min_client_versions?.desktop ?? null;
    connectionStore.setState({
      status: "online", serverVersion: h.version ?? null, apiVersion: h.api_version ?? null, minDesktop,
      latencyMs: Math.round(performance.now() - t0), failures: 0, nextRetryAt: null,
    });
    if (minDesktop && versionLess(APP_VERSION, minDesktop)) accountStore.setState({ updateRequired: minDesktop });
    accountStore.setState({ offline: false });
    if (prev.status !== "online") restoreSessionIfNeeded();
    schedule(ONLINE_POLL_MS);
  } catch {
    const failures = prev.failures + 1;
    const wait = backoffMs(failures);
    connectionStore.setState({
      status: failures >= 3 ? "offline" : prev.status === "online" || prev.status === "connecting" ? "reconnecting" : prev.status,
      failures, latencyMs: null, nextRetryAt: Date.now() + wait,
    });
    accountStore.setState({ offline: true });
    schedule(wait);
  } finally {
    clearTimeout(abort);
  }
  return connectionStore.getState();
}

function schedule(ms: number) {
  if (timer) clearTimeout(timer);
  timer = setTimeout(checkNow, ms);
}

export function startConnectionMonitor() {
  if (started) return;
  started = true;
  checkNow();
  // react immediately when the OS reports the network is back, and when the server address changes
  window.addEventListener("online", () => checkNow());
  let lastServer = accountStore.getState().serverUrl;
  accountStore.subscribe?.(() => {
    const s = accountStore.getState().serverUrl;
    if (s !== lastServer) {
      lastServer = s;
      connectionStore.setState({ failures: 0, status: "connecting" });
      checkNow();
    }
  });
}
