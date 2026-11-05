/**
 * Automatic MOTH Code updates (Tauri 2 updater, served by MOTH Cloud).
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
}

export const updaterStore = createStore<UpdaterState>({
  phase: "idle", version: null, notes: null, progress: 0, error: null, lastCheck: null,
});
export const useUpdater = updaterStore.useStore;

const CHECK_EVERY_MS = 6 * 3600 * 1000;
const PENDING_KEY = "moth.update.pending";
let pending: any = null;
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

/** Check MOTH Cloud for an update and download it in the background. */
export async function checkForUpdates(opts: { manual?: boolean } = {}): Promise<UpdaterState> {
  if (!isTauri()) {
    updaterStore.setState({ phase: "unavailable" });
    return updaterStore.getState();
  }
  if (busy || updaterStore.getState().phase === "ready") return updaterStore.getState();
  busy = true;
  try {
    updaterStore.setState({ phase: "checking", error: null });
    const { check } = await import("@tauri-apps/plugin-updater");
    const update = await check({ headers: { "X-Moth-Install-Id": installId(), "X-Moth-Client": CLIENT_HEADER }, timeout: 30000 });
    updaterStore.setState({ lastCheck: Date.now() });
    if (!update) {
      updaterStore.setState({ phase: "up-to-date", version: null });
      return updaterStore.getState();
    }
    updaterStore.setState({ phase: "downloading", version: update.version, notes: update.body ?? null, progress: 0 });
    for (let attempt = 0; ; attempt++) {
      let total = 0;
      let done = 0;
      try {
        await update.download((ev: any) => {
          if (ev.event === "Started") total = ev.data.contentLength ?? 0;
          if (ev.event === "Progress") {
            done += ev.data.chunkLength;
            updaterStore.setState({ progress: total ? Math.min(100, (done / total) * 100) : 0 });
          }
        });
        break;
      } catch (e) {
        if (attempt >= 4) throw e;
        await sleep(Math.min(60000, 2000 * 2 ** attempt)); // interrupted download: retry from scratch
      }
    }
    pending = update;
    updaterStore.setState({ phase: "ready", progress: 100 });
    storage(PENDING_KEY, JSON.stringify({ from: APP_VERSION, to: update.version, at: Date.now() }));
  } catch (e) {
    const msg = String((e as Error)?.message ?? e);
    updaterStore.setState({ phase: "error", error: msg });
    if (opts.manual) throw e;
    report(false, updaterStore.getState().version, msg);
  } finally {
    busy = false;
  }
  return updaterStore.getState();
}

/** Install the downloaded update now (MOTH Code restarts). */
export async function installNow() {
  if (!pending) return;
  updaterStore.setState({ phase: "installing" });
  const p = JSON.parse(storage(PENDING_KEY) ?? "{}");
  storage(PENDING_KEY, JSON.stringify({ ...p, installing: true }));
  try {
    await pending.install(); // Windows: the installer runs and the app exits
    const { relaunch } = await import("@tauri-apps/plugin-process");
    await relaunch();
  } catch (e) {
    const msg = String((e as Error)?.message ?? e);
    updaterStore.setState({ phase: "error", error: msg });
    report(false, pending?.version ?? null, msg);
  }
}

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

export function startUpdater() {
  if (started || !isTauri()) return;
  started = true;
  reportPreviousUpdate();
  setTimeout(() => checkForUpdates(), 5000);
  setInterval(() => checkForUpdates(), CHECK_EVERY_MS);
  let required = accountStore.getState().updateRequired;
  accountStore.subscribe(() => {
    const r = accountStore.getState().updateRequired;
    if (r && r !== required) checkForUpdates();
    required = r;
  });
  // Install a downloaded update when the user closes MOTH Code.
  import("@tauri-apps/api/window")
    .then(({ getCurrentWindow }) => getCurrentWindow().onCloseRequested(async (ev) => {
      if (updaterStore.getState().phase === "ready" && pending) {
        ev.preventDefault();
        await installNow();
      }
    }))
    .catch(() => {});
}
