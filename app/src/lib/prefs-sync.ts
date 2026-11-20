/** 2.1: app size, animations, quiet alerts and sounds follow your MOTH account to your other computers. */
import { accountStore, serverApi } from "./account";
import { setUiSize, uiSizeStore, UI_SIZES, type UiSize } from "./ui-size";
import { motionStore, setMotion } from "./motion";
import { alertPrefs, setAlertPrefs } from "./alerts";
import { ACCENTS, THEMES, setTheme, themeStore, type Accent, type Theme } from "./theme";
import { promptsStore, setPrompts } from "./saved-prompts";

export interface Prefs { ui_size?: UiSize; motion?: boolean; quiet_alerts?: boolean; sounds?: boolean; theme?: Theme; accent?: Accent; saved_prompts?: string[] }

export function current(): Prefs {
  const a = alertPrefs();
  const t = themeStore.getState();
  return { ui_size: uiSizeStore.getState().size, motion: motionStore.getState().on, quiet_alerts: a.quiet, sounds: a.sounds,
    theme: t.theme, accent: t.accent, saved_prompts: promptsStore.getState().prompts };
}

export function applyPrefs(p: Prefs) {
  if (p.ui_size && (UI_SIZES as readonly string[]).includes(p.ui_size) && p.ui_size !== uiSizeStore.getState().size) setUiSize(p.ui_size);
  if (typeof p.motion === "boolean" && p.motion !== motionStore.getState().on) setMotion(p.motion);
  const t = themeStore.getState();  // 2.4
  const look: { theme?: Theme; accent?: Accent } = {};
  if (p.theme && THEMES.includes(p.theme) && p.theme !== t.theme) look.theme = p.theme;
  if (p.accent && ACCENTS.includes(p.accent) && p.accent !== t.accent) look.accent = p.accent;
  if (Object.keys(look).length) setTheme(look);
  if (Array.isArray(p.saved_prompts) && JSON.stringify(p.saved_prompts) !== JSON.stringify(promptsStore.getState().prompts)) setPrompts(p.saved_prompts);
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
  themeStore.subscribe(schedule);
  promptsStore.subscribe(schedule);
  window.addEventListener("moth:alert-prefs", schedule);
}
