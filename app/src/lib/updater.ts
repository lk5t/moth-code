/**
 * Automatic MOTH Code updates (Tauri 2 updater, served by the MOTH Cloud server this app is
 * connected to — the address in Settings → Connection, so no rebuild is needed when it changes).
 *
 * * checks at startup, every 6 hours, and immediately when MOTH Cloud says this version is too old;
 * * downloads in the background (retried with backoff if the connection drops — a failed download
 *   is discarded and started again, never installed);
 * * the update's minisign signature is verified by the updater against the public key built into
 *   the app, so a corrupted or forged update can't be installed;
 * * installs when the user restarts or closes MOTH Code; the only prompt is a quiet "Restart to
 *   update" in the status bar (or a required-update banner when the server demands it);
 * * settings, workspaces, accounts and local data live outside the install directory and are kept;
 * * after the restart the outcome is reported to MOTH Cloud, which pauses staged rollouts that fail.
 */
import { isTauri } from "./backend";
import { accountStore, normalizeServerUrl } from "./account";
import { APP_VERSION, CLIENT_HEADER } from "./endpoint";
import { createStore } from "./store";

export type UpdatePhase = "idle" | "checking" | "up-to-date" | "downloading" | "ready" | "installing" | "error" | "unavailable";

export interface UpdaterState {
  phase: UpdatePhase;
  version: string | null;
  notes: string | null;
  progress: number;
  error: string | null;
  lastCheck: number | null;
  dismissed: boolean;
}

export const updaterStore = createStore<UpdaterState>({
  phase: "idle", version: null, notes: null, progress: 0, error: null, lastCheck: null, dismissed: false,
});
export const useUpdater = updaterStore.useStore;

const CHECK_EVERY_MS = 6 * 3600 * 1000;
const PENDING_KEY = "moth.update.pending";
let busy = false;

function storage(key: string, value?: string | null): string | null {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
  return null;
}

export function installId(): string {
  let id = storage("moth.installId");
  if (!id) {
    id = crypto.randomUUID();
    storage("moth.installId", id);
  }
  return id;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function ulog(message: string) {
  import("@tauri-apps/api/core").then(({ invoke }) => invoke("update_log", { message })).catch(() => {});
}

/** Check the connected MOTH Cloud server for an update and download it in the background. */
export async function checkForUpdates(opts: { manual?: boolean } = {}): Promise<UpdaterState> {
  if (!isTauri()) {
    updaterStore.setState({ phase: "unavailable" });
    return updaterStore.getState();
  }
  if (busy || updaterStore.getState().phase === "ready") return updaterStore.getState();
  let server = "";
  try {
    server = normalizeServerUrl(accountStore.getState().serverUrl);
  } catch {
    server = "";
  }
  if (!server) {
    ulog("no MOTH Cloud address configured; not checking for updates");
    updaterStore.setState({ phase: "idle", error: null });
    return updaterStore.getState();
  }
  busy = true;
  try {
    updaterStore.setState({ phase: "checking", error: null });
    const { invoke } = await import("@tauri-apps/api/core");
    const found = await invoke<{ version: string; current_version: string; notes: string | null } | null>(
      "update_check", { server, installId: installId(), channel: "stable" });
    updaterStore.setState({ lastCheck: Date.now() });
    if (!found) {
      updaterStore.setState({ phase: "up-to-date", version: null });
      return updaterStore.getState();
    }
    updaterStore.setState({ phase: "downloading", version: found.version, notes: found.notes, progress: 0 });
    for (let attempt = 0; ; attempt++) {
      try {
        await invoke("update_download"); // the signature is verified before the bytes are accepted
        break;
      } catch (e) {
        if (attempt >= 4) throw e;
        await sleep(Math.min(60000, 2000 * 2 ** attempt)); // interrupted download: retry from scratch
      }
    }
    updaterStore.setState({ phase: "ready", progress: 100, dismissed: false });
    storage(PENDING_KEY, JSON.stringify({ from: APP_VERSION, to: found.version, at: Date.now() }));
    if (import.meta.env.VITE_MOTH_UPDATE_TEST === "1") installNow(); // automated update tests only
  } catch (e) {
    const msg = describeUpdateError(String((e as Error)?.message ?? e));
    ulog(`update error: ${String((e as Error)?.message ?? e)}`);
    updaterStore.setState({ phase: "error", error: msg });
    if (opts.manual) throw new Error(msg);
    report(false, updaterStore.getState().version, msg);
  } finally {
    busy = false;
  }
  return updaterStore.getState();
}

export function describeUpdateError(raw: string): string {
  if (/signature/i.test(raw)) return "The update's signature could not be verified, so it was not installed.";
  if (/error sending request|connect|dns|timed out|timeout/i.test(raw)) return "MOTH Cloud could not be reached to check for updates.";
  if (/https/i.test(raw)) return "Updates are only downloaded over HTTPS; set an https:// MOTH Cloud address.";
  return raw;
}

/** Install the downloaded update now (MOTH Code closes, installs and starts again). */
export async function installNow() {
  if (updaterStore.getState().phase !== "ready") return;
  updaterStore.setState({ phase: "installing" });
  const p = JSON.parse(storage(PENDING_KEY) ?? "{}");
  storage(PENDING_KEY, JSON.stringify({ ...p, installing: true }));
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("update_install"); // Windows: the installer starts and this app exits
    const { relaunch } = await import("@tauri-apps/plugin-process");
    await relaunch();
  } catch (e) {
    const msg = describeUpdateError(String((e as Error)?.message ?? e));
    updaterStore.setState({ phase: "error", error: msg });
    report(false, updaterStore.getState().version, msg);
  }
}

export const dismissUpdateNotice = () => updaterStore.setState({ dismissed: true });

async function report(ok: boolean, to: string | null, error?: string, from: string = APP_VERSION) {
  if (!to) return;
  try {
    const server = normalizeServerUrl(accountStore.getState().serverUrl);
    if (!server) return;
    await fetch(`${server}/v1/updates/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Moth-Client": CLIENT_HEADER, "X-Moth-Install-Id": installId() },
      body: JSON.stringify({ component: "desktop", from_version: from, to_version: to, ok, error: error?.slice(0, 1900) }),
    });
  } catch {
    /* best effort */
  }
}

/** After a restart: tell MOTH Cloud whether the last update installed (drives staged rollouts). */
export function reportPreviousUpdate() {
  const raw = storage(PENDING_KEY);
  if (!raw) return;
  const p = JSON.parse(raw);
  if (p.to === APP_VERSION) {
    report(true, p.to, undefined, p.from);
    storage(PENDING_KEY, null);
  } else if (p.installing) {
    report(false, p.to, "the update did not install (still running " + APP_VERSION + ")", p.from);
    storage(PENDING_KEY, null);
  }
}

let started = false;

/** Started when the window opens, independently of the local backend: if the backend is broken,
 *  an update is exactly what can fix it. */
export function startUpdater() {
  if (started || !isTauri()) return;
  started = true;
  ulog(`updater started (version ${APP_VERSION})`);
  reportPreviousUpdate();
  import("@tauri-apps/api/event")
    .then(({ listen }) => listen<{ downloaded: number; total: number | null }>("moth-update-progress", (e) => {
      const { downloaded, total } = e.payload;
      if (total) updaterStore.setState({ progress: Math.min(100, (downloaded / total) * 100) });
    }))
    .catch(() => {});
  setTimeout(() => checkForUpdates(), 5000);
  setInterval(() => checkForUpdates(), CHECK_EVERY_MS);
  let required = accountStore.getState().updateRequired;
  let server = accountStore.getState().serverUrl;
  accountStore.subscribe(() => {
    const s = accountStore.getState();
    if ((s.updateRequired && s.updateRequired !== required) || s.serverUrl !== server) checkForUpdates();
    required = s.updateRequired;
    server = s.serverUrl;
  });
  // Install a downloaded update when the user closes MOTH Code.
  import("@tauri-apps/api/window")
    .then(({ getCurrentWindow }) => getCurrentWindow().onCloseRequested(async (ev) => {
      if (updaterStore.getState().phase === "ready") {
        ev.preventDefault();
        await installNow();
      }
    }))
    .catch(() => {});
}
