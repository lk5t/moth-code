/**
 * 0.10.0 desktop alerts: while the Owner is signed in, MOTH Code asks MOTH Cloud every minute for notable
 * news (a promotion, a finished successor, a problem) and shows it as a system notification, even while
 * the window is closed to the tray, plus an in-app toast. A promotion gets a confetti burst. The tray
 * icon's tooltip shows what MOTH is doing right now.
 */
import { accountStore, serverApi } from "./account";
import { createStore } from "./store";
import { isTauri } from "./backend";

export type Alert = { id: number; ts: number; kind: string; tone: "promoted" | "success" | "problem" | "info"; message: string };
type AlertsState = { toasts: Alert[]; celebrate: number };

export const alertsStore = createStore<AlertsState>({ toasts: [], celebrate: 0 });
export const useAlerts = alertsStore.useStore;
export const dismissAlert = (id: number) => alertsStore.setState((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
export const celebrate = () => alertsStore.setState((s) => ({ celebrate: s.celebrate + 1 }));

const PREFS = "moth.alerts.prefs";
export type AlertPrefs = { notifications: boolean; keepInTray: boolean; infoAlerts: boolean };
export function alertPrefs(): AlertPrefs {
  try { return { notifications: true, keepInTray: true, infoAlerts: false, ...JSON.parse(localStorage.getItem(PREFS) || "{}") }; }
  catch { return { notifications: true, keepInTray: true, infoAlerts: false }; }
}
export function setAlertPrefs(p: Partial<AlertPrefs>) {
  const next = { ...alertPrefs(), ...p };
  try { localStorage.setItem(PREFS, JSON.stringify(next)); } catch { /* per-viewer convenience only */ }
  void applyTray(next);
}

async function applyTray(p: AlertPrefs) {
  if (!isTauri()) return;
  try { const { invoke } = await import("@tauri-apps/api/core"); await invoke("tray_keep_running", { enabled: p.keepInTray }); } catch { /* older shell */ }
}

const TITLES: Record<Alert["tone"], string> = { promoted: "MOTH got smarter", success: "MOTH", problem: "MOTH needs a look", info: "MOTH" };

async function notify(a: Alert) {
  if (!isTauri() || !alertPrefs().notifications) return;
  try {
    const n = await import("@tauri-apps/plugin-notification");
    let ok = await n.isPermissionGranted();
    if (!ok) ok = (await n.requestPermission()) === "granted";
    if (ok) n.sendNotification({ title: TITLES[a.tone], body: a.message.slice(0, 220) });
  } catch { /* notifications unavailable: the in-app toast still shows */ }
}

let started = false;
let after = 0;

export async function pollAlerts(): Promise<void> {
  const s = accountStore.getState();
  if (s.user?.role !== "owner") return;
  try {
    const r = await serverApi<{ latest: number; alerts: Alert[]; status?: string }>(`/v1/admin/evolution/alerts?after=${after}`, { retries: 0 });
    if (r.status && isTauri()) {
      try { const { invoke } = await import("@tauri-apps/api/core"); await invoke("tray_set_status", { text: r.status }); } catch { /* older shell */ }
    }
    const fresh = after > 0 ? r.alerts.filter((a) => a.tone !== "info" || alertPrefs().infoAlerts) : [];
    after = Math.max(after, r.latest);
    if (!fresh.length) return;
    alertsStore.setState((st) => ({
      toasts: [...st.toasts, ...fresh].slice(-4),
      celebrate: fresh.some((a) => a.tone === "promoted") ? st.celebrate + 1 : st.celebrate,
    }));
    for (const a of fresh.slice(-3)) await notify(a);
  } catch { /* offline or signed out: try again next minute */ }
}

const TASK_DONE: Record<string, [Alert["tone"], string]> = {
  completed: ["success", "MOTH finished a task"], needs_review: ["problem", "MOTH finished — please review"],
  plan_ready: ["info", "MOTH's plan is ready for you"], model_incapable: ["problem", "MOTH couldn't do a task"],
  failed: ["problem", "A MOTH task failed"],
};
let taskAlerts = false;

/** 1.0 background tasks: a toast (and a system notification when the window is hidden) when a task ends. */
function startTaskAlerts() {
  if (taskAlerts) return;
  taskAlerts = true;
  void import("./events").then(({ subscribe }) => subscribe("task", (e: Record<string, any>) => {
    if (e.kind !== "status" || !TASK_DONE[e.status]) return;
    const [tone, title] = TASK_DONE[e.status];
    const a: Alert = { id: Date.now(), ts: Date.now() / 1000, kind: `task.${e.status}`, tone, message: title };
    alertsStore.setState((st) => ({ toasts: [...st.toasts, a].slice(-4) }));
    if (typeof document !== "undefined" && document.hidden) void notify(a);
  }));
}

export function startAlerts() {
  startTaskAlerts();
  if (started) return;
  started = true;
  void applyTray(alertPrefs());
  void pollAlerts();
  setInterval(() => void pollAlerts(), 60_000);
  let user = accountStore.getState().user?.id;
  accountStore.subscribe(() => {
    const id = accountStore.getState().user?.id;
    if (id !== user) { user = id; after = 0; void pollAlerts(); }
  });
}
