/** 2.4: colour themes and the accent colour. Every colour in the app is a CSS variable, so a theme only swaps those. */
import { createStore } from "./store";

export const THEMES = ["dark", "midnight", "graphite", "light"] as const;
export type Theme = (typeof THEMES)[number];
export const THEME_LABEL: Record<Theme, string> = { dark: "Dark", midnight: "Midnight", graphite: "Graphite", light: "Light" };

export const ACCENTS = ["red", "blue", "green", "purple", "orange", "pink"] as const;
export type Accent = (typeof ACCENTS)[number];
/** [accent, hover, r g b] */
export const ACCENT_RGB: Record<Accent, [string, string, string]> = {
  red: ["#c1121f", "#d81e2c", "193 18 31"], blue: ["#2f6fed", "#4a84f5", "47 111 237"], green: ["#1f9d63", "#27b673", "31 157 99"],
  purple: ["#7c4ddb", "#9165ea", "124 77 219"], orange: ["#e0701a", "#f0832e", "224 112 26"], pink: ["#d63384", "#e64d97", "214 51 132"],
};

const SURFACES: Record<Theme, Record<string, string>> = {
  dark: { bg: "#080808", surface: "#141414", "surface-2": "#1b1b1b", "surface-3": "#232323", border: "#262626", "border-strong": "#333333", fg: "#f5f5f5", muted: "#9a9a9a", faint: "#5f5f5f" },
  midnight: { bg: "#070a12", surface: "#0e1320", "surface-2": "#141a2a", "surface-3": "#1b2235", border: "#222a3d", "border-strong": "#2e3850", fg: "#eef1f8", muted: "#93a0b8", faint: "#5a6680" },
  graphite: { bg: "#18181b", surface: "#212125", "surface-2": "#2a2a2f", "surface-3": "#323238", border: "#3a3a41", "border-strong": "#4a4a52", fg: "#f4f4f5", muted: "#a1a1aa", faint: "#71717a" },
  light: { bg: "#f6f6f7", surface: "#ffffff", "surface-2": "#f0f0f2", "surface-3": "#e6e6ea", border: "#dcdce1", "border-strong": "#c8c8cf", fg: "#141416", muted: "#5c5c66", faint: "#8e8e98" },
};

const KEY = "moth.theme";
function saved(): { theme: Theme; accent: Accent } {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "{}");
    return { theme: THEMES.includes(v.theme) ? v.theme : "dark", accent: ACCENTS.includes(v.accent) ? v.accent : "red" };
  } catch { return { theme: "dark", accent: "red" }; }
}

export const themeStore = createStore(saved());
export const useTheme = () => themeStore.useStore((s) => s);

export function applyTheme(t = themeStore.getState()) {
  const root = document.documentElement, style = root.style;
  for (const [k, v] of Object.entries(SURFACES[t.theme])) style.setProperty(`--color-${k}`, v);
  const [accent, hover, rgb] = ACCENT_RGB[t.accent];
  style.setProperty("--color-accent", accent);
  style.setProperty("--color-accent-hover", hover);
  style.setProperty("--color-accent-soft", `rgb(${rgb} / 0.14)`);
  style.setProperty("--accent-rgb", rgb);
  style.setProperty("--shadow-glow", `0 0 0 1px rgb(${rgb} / 0.35), 0 0 18px rgb(${rgb} / 0.18)`);
  style.setProperty("--shadow-glow-strong", `0 0 0 1px rgb(${rgb} / 0.6), 0 0 28px rgb(${rgb} / 0.3)`);
  root.dataset.theme = t.theme;
  style.colorScheme = t.theme === "light" ? "light" : "dark";
}

export function setTheme(change: Partial<{ theme: Theme; accent: Accent }>) {
  themeStore.setState(change);
  try { localStorage.setItem(KEY, JSON.stringify(themeStore.getState())); } catch { /* storage unavailable */ }
  applyTheme();
}
