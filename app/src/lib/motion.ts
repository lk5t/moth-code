/** 2.0: animations on or off (they also switch off when the system asks for reduced motion). */
import { createStore } from "./store";

const KEY = "moth.motion";
function saved(): boolean {
  try { return localStorage.getItem(KEY) !== "off"; } catch { return true; }
}
export const motionStore = createStore<{ on: boolean }>({ on: saved() });
export const useMotion = () => motionStore.useStore((s) => s.on);

export function applyMotion(on = motionStore.getState().on) {
  document.documentElement.dataset.motion = on ? "on" : "off";
}
export function setMotion(on: boolean) {
  motionStore.setState({ on });
  try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* storage unavailable */ }
  applyMotion(on);
}
