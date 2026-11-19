/** 2.0: how big the whole app is drawn. Every size in the app is in rem, so one root font size scales it all. */
import { createStore } from "./store";

export const UI_SIZES = ["compact", "normal", "large"] as const;
export type UiSize = (typeof UI_SIZES)[number];
export const UI_SIZE_LABEL: Record<UiSize, string> = { compact: "Compact", normal: "Normal", large: "Large" };
/** root font size in px for each setting (Normal is how 1.x looked) */
export const ROOT_PX: Record<UiSize, number> = { compact: 14, normal: 16, large: 18 };
const KEY = "moth.uiSize";

function saved(): UiSize {
  try {
    const v = localStorage.getItem(KEY);
    if (v && (UI_SIZES as readonly string[]).includes(v)) return v as UiSize;
  } catch {
    /* storage unavailable */
  }
  return "compact";
}

export const uiSizeStore = createStore<{ size: UiSize }>({ size: saved() });
export const useUiSize = () => uiSizeStore.useStore((s) => s.size);

export function applyUiSize(size: UiSize = uiSizeStore.getState().size) {
  document.documentElement.dataset.uiSize = size;
  document.documentElement.style.fontSize = `${ROOT_PX[size]}px`;
}

export function setUiSize(size: UiSize) {
  uiSizeStore.setState({ size });
  try {
    localStorage.setItem(KEY, size);
  } catch {
    /* storage unavailable */
  }
  applyUiSize(size);
}

/** one step smaller (-1) or bigger (+1); stays within Compact..Large */
export function stepUiSize(dir: -1 | 1) {
  const i = UI_SIZES.indexOf(uiSizeStore.getState().size);
  setUiSize(UI_SIZES[Math.min(UI_SIZES.length - 1, Math.max(0, i + dir))]);
}

/** Ctrl/⌘ + and Ctrl/⌘ − change the size, Ctrl/⌘ 0 goes back to Compact. */
export function startUiSizeShortcuts() {
  applyUiSize();
  const onKey = (e: KeyboardEvent) => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    if (e.key === "=" || e.key === "+") { e.preventDefault(); stepUiSize(1); }
    else if (e.key === "-" || e.key === "_") { e.preventDefault(); stepUiSize(-1); }
    else if (e.key === "0") { e.preventDefault(); setUiSize("compact"); }
  };
  window.addEventListener("keydown", onKey);
  return () => window.removeEventListener("keydown", onKey);
}
