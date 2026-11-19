/** 2.0 notification centre: every alert lands here (tasks, scans, training news, updates); only the important
 * ones also pop up. Kept in this browser profile only (a per-viewer convenience). */
import { createStore } from "./store";

export type InboxTone = "promoted" | "success" | "problem" | "info";
export interface InboxItem { id: string; ts: number; tone: InboxTone; title: string; message: string; kind: string; read: boolean; view?: string }
const KEY = "moth.inbox";
const MAX = 100;

function load(): InboxItem[] {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(v) ? v.slice(0, MAX) : []; }
  catch { return []; }
}
export const inboxStore = createStore<{ items: InboxItem[] }>({ items: load() });
export const useInbox = inboxStore.useStore;

function save(items: InboxItem[]) {
  try { localStorage.setItem(KEY, JSON.stringify(items.slice(0, MAX))); } catch { /* storage unavailable */ }
}

export function pushInbox(item: Omit<InboxItem, "id" | "ts" | "read"> & { id?: string; ts?: number }) {
  const full: InboxItem = { id: item.id ?? `${item.kind}:${Date.now()}:${Math.random().toString(36).slice(2, 7)}`, ts: item.ts ?? Date.now() / 1000, read: false, ...item } as InboxItem;
  inboxStore.setState((s) => {
    if (s.items.some((x) => x.id === full.id)) return s;
    const items = [full, ...s.items].slice(0, MAX);
    save(items);
    return { items };
  });
}
export function markInboxRead() {
  inboxStore.setState((s) => { const items = s.items.map((x) => ({ ...x, read: true })); save(items); return { items }; });
}
export function clearInbox() { save([]); inboxStore.setState({ items: [] }); }
/** Only these pop up as toasts and system notifications by default; the rest wait quietly in the centre. */
export const LOUD: InboxTone[] = ["promoted", "problem"];
