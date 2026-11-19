/**
 * 0.10.0 desktop alerts: while the Owner is signed in, MOTH Code asks MOTH Cloud every minute for notable
 * news (a promotion, a finished successor, a problem) and shows it as a system notification, even while
 * the window is closed to the tray, plus an in-app toast. A promotion gets a confetti burst. The tray
 * icon's tooltip shows what MOTH is doing right now.
 */
import { accountStore, serverApi } from "./account";
import { createStore } from "./store";
import { isTauri } from "./backend";
import { LOUD, pushInbox } from "./inbox";

export type Alert = { id: number; ts: number; kind: string; tone: "promoted" | "success" | "problem" | "info"; message: string };
type AlertsState = { toasts: Alert[]; celebrate: number };

export const alertsStore = createStore<AlertsState>({ toasts: [], celebrate: 0 });
export const useAlerts = alertsStore.useStore;
export const dismissAlert = (id: number) => alertsStore.setState((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
export const celebrate = () => alertsStore.setState((s) => ({ celebrate: s.celebrate + 1 }));

const PREFS = "moth.alerts.prefs";
export type AlertPrefs = { notifications: boolean; keepInTray: boolean; infoAlerts: boolean; sounds: boolean; quiet: boolean };
// 2.0 quiet alerts: only promotions and problems pop up; everything else waits in the notification centre
const DEFAULT_PREFS: AlertPrefs = { notifications: true, keepInTray: true, infoAlerts: false, sounds: false, quiet: true };
const loud = (a: Alert) => !alertPrefs().quiet || LOUD.includes(a.tone);
export function alertPrefs(): AlertPrefs {
  try { return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS) || "{}") }; }
  catch { return { ...DEFAULT_PREFS }; }
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
    const all = after > 0 ? r.alerts : [];
    for (const a of all) pushInbox({ id: `alert:${a.id}`, ts: a.ts, tone: a.tone, title: TITLES[a.tone], message: a.message, kind: a.kind, view: "intelligence" });
    const fresh = all.filter((a) => (a.tone !== "info" || alertPrefs().infoAlerts) && loud(a));
    after = Math.max(after, r.latest);
    if (!fresh.length) return;
    alertsStore.setState((st) => ({
      toasts: [...st.toasts, ...fresh].slice(-4),
      celebrate: fresh.some((a) => a.tone === "promoted") ? st.celebrate + 1 : st.celebrate,
    }));
    void import("./sounds").then(({ sounds }) => (fresh.some((a) => a.tone === "promoted") ? sounds.flourish() : sounds.chime()));
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
    pushInbox({ tone, title: "Agent task", message: title, kind: a.kind, view: "workspace" });
    const hidden = typeof document !== "undefined" && document.hidden;
    if (loud(a) || hidden) {
      alertsStore.setState((st) => ({ toasts: [...st.toasts, a].slice(-4) }));
      void import("./sounds").then(({ sounds }) => sounds.chime());
    }
    if (hidden) void notify(a);
  }));
  // 2.0: finished scans go to the notification centre; serious findings also pop up
  void import("./events").then(({ subscribe }) => subscribe("scan", (e: Record<string, any>) => {
    if (e.kind !== "finished" || !e.scan) return;
    const c = e.scan.counts ?? {};
    const serious = (c.critical ?? 0) + (c.high ?? 0);
    const tone: Alert["tone"] = e.scan.status === "error" || serious ? "problem" : "success";
    const total = Object.values(c).reduce((n: number, v) => n + Number(v || 0), 0);
    const message = e.scan.status === "error" ? `Scan of ${e.scan.target} could not finish` :
      `Scan of ${e.scan.target} ${e.scan.status === "stopped" ? "stopped" : "finished"}: ${total} finding${total === 1 ? "" : "s"}${serious ? `, ${serious} serious` : ""}`;
    pushInbox({ id: `scan:${e.scan.id}:${e.scan.finished_at ?? ""}`, tone, title: "Security scan", message, kind: "scan", view: "chat" });
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
