/** 2.4: your saved prompts — reuse common requests in one click. They follow your account (Settings sync). */
import { createStore } from "./store";

const KEY = "moth.savedPrompts", MAX = 30, MAX_LEN = 2000;
export const DEFAULT_PROMPTS = ["Explain this code step by step.", "Find the bug and fix it.", "Write tests for this.",
  "Review this for security problems."];

function saved(): string[] {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, MAX) : DEFAULT_PROMPTS; }
  catch { return DEFAULT_PROMPTS; }
}

export const promptsStore = createStore<{ prompts: string[] }>({ prompts: saved() });
export const useSavedPrompts = () => promptsStore.useStore((s) => s.prompts);

export function setPrompts(prompts: string[]) {
  const clean = [...new Set(prompts.map((p) => p.trim().slice(0, MAX_LEN)).filter(Boolean))].slice(0, MAX);
  promptsStore.setState({ prompts: clean });
  try { localStorage.setItem(KEY, JSON.stringify(clean)); } catch { /* storage unavailable */ }
}
export const savePrompt = (p: string) => setPrompts([p, ...promptsStore.getState().prompts]);
export const removePrompt = (p: string) => setPrompts(promptsStore.getState().prompts.filter((x) => x !== p));
