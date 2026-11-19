/** 2.1: app size, animations, quiet alerts and sounds follow your MOTH account to your other computers. */
import { accountStore, serverApi } from "./account";
import { setUiSize, uiSizeStore, UI_SIZES, type UiSize } from "./ui-size";
import { motionStore, setMotion } from "./motion";
import { alertPrefs, setAlertPrefs } from "./alerts";

export interface Prefs { ui_size?: UiSize; motion?: boolean; quiet_alerts?: boolean; sounds?: boolean }

export function current(): Prefs {
  const a = alertPrefs();
  return { ui_size: uiSizeStore.getState().size, motion: motionStore.getState().on, quiet_alerts: a.quiet, sounds: a.sounds };
}

export function applyPrefs(p: Prefs) {
  if (p.ui_size && (UI_SIZES as readonly string[]).includes(p.ui_size) && p.ui_size !== uiSizeStore.getState().size) setUiSize(p.ui_size);
  if (typeof p.motion === "boolean" && p.motion !== motionStore.getState().on) setMotion(p.motion);
  const a = alertPrefs();
  const patch: Record<string, boolean> = {};
  if (typeof p.quiet_alerts === "boolean" && p.quiet_alerts !== a.quiet) patch.quiet = p.quiet_alerts;
  if (typeof p.sounds === "boolean" && p.sounds !== a.sounds) patch.sounds = p.sounds;
  if (Object.keys(patch).length) setAlertPrefs(patch);
}

let started = false;
let applying = false;
let timer: ReturnType<typeof setTimeout> | null = null;
let last = "";

async function pull() {
  if (!accountStore.getState().token) return;
  try {
    const r = await serverApi<{ preferences: Prefs }>("/v1/me/preferences", { retries: 0 });
    applying = true;
    if (Object.keys(r.preferences ?? {}).length) applyPrefs(r.preferences);
    else void push(true);  // first computer on this account: save what it uses
    last = JSON.stringify(current());
  } catch { /* offline or an older MOTH Cloud: settings stay on this computer */ }
  finally { applying = false; }
}

async function push(now = false) {
  if (!accountStore.getState().token || applying) return;
  const value = JSON.stringify(current());
  if (value === last && !now) return;
  last = value;
  try { await serverApi("/v1/me/preferences", { method: "PUT", json: current(), retries: 0 }); } catch { /* try again next change */ }
}

function schedule() {
  if (applying) return;
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => void push(), 800);
}

export function startPrefsSync() {
  if (started) return;
  started = true;
  let user = accountStore.getState().user?.id;
  void pull();
  accountStore.subscribe(() => {
    const id = accountStore.getState().user?.id;
    if (id !== user) { user = id; if (id) void pull(); }
  });
  uiSizeStore.subscribe(schedule);
  motionStore.subscribe(schedule);
  window.addEventListener("moth:alert-prefs", schedule);
}
