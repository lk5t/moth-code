/** 2.4: open chats as tabs above the conversation, like an editor's files. */
import { useEffect, useState } from "react";
import { MessageSquare, Plus, X } from "lucide-react";
import { useApp } from "@/lib/app-state";
import { useEvent } from "@/lib/events";
import { requestChat } from "@/components/SidebarCollections";
import { cn } from "@/lib/utils";

type Tab = { id: number; title: string };
const KEY = "moth.chatTabs", MAX = 8;

function load(): Tab[] {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(v) ? v.filter((t) => typeof t?.id === "number").slice(0, MAX) : []; }
  catch { return []; }
}
function store(tabs: Tab[]) { try { localStorage.setItem(KEY, JSON.stringify(tabs)); } catch { /* storage unavailable */ } }

/** Add or rename the open chat's tab (newest stays where it is; a new one goes at the end, oldest dropped). */
export function withTab(tabs: Tab[], id: number, title: string): Tab[] {
  const i = tabs.findIndex((t) => t.id === id);
  if (i >= 0) return tabs[i].title === title ? tabs : tabs.map((t) => (t.id === id ? { id, title } : t));
  return [...tabs, { id, title }].slice(-MAX);
}

export function ChatTabs() {
  const session = useApp((s) => s.chatSession);
  const [tabs, setTabs] = useState<Tab[]>(load);
  useEffect(() => {
    if (session.conversationId == null) return;
    setTabs((cur) => { const next = withTab(cur, session.conversationId!, session.title || "Chat"); if (next !== cur) store(next); return next; });
  }, [session.conversationId, session.title]);
  useEvent("conversations", (e) => {  // a deleted chat's tab goes too
    const gone: number[] = (e as { deleted?: number[] }).deleted ?? [];
    if (gone.length) setTabs((cur) => { const next = cur.filter((t) => !gone.includes(t.id)); store(next); return next; });
  });
  const close = (id: number) => {
    const next = tabs.filter((t) => t.id !== id);
    setTabs(next); store(next);
    if (session.conversationId === id) { const other = next.at(-1); requestChat(other?.id ?? null, other?.title); }
  };
  if (tabs.length < 2 && session.conversationId != null && tabs[0]?.id === session.conversationId) return null;  // one chat: no strip
  if (!tabs.length) return null;
  return <div role="tablist" aria-label="Open chats" className="flex h-8 shrink-0 items-end gap-px overflow-x-auto border-b border-border bg-bg px-1">
    {tabs.map((t) => { const active = t.id === session.conversationId;
      return <div key={t.id} role="tab" aria-selected={active} className={cn("group flex h-7 max-w-48 shrink-0 items-center gap-1.5 rounded-t-md border border-b-0 px-2 text-[0.6875rem]",
        active ? "border-border bg-surface text-fg" : "border-transparent text-muted hover:bg-surface-2 hover:text-fg")}>
        <button disabled={session.busy} className="flex min-w-0 items-center gap-1.5" title={t.title} onClick={() => requestChat(t.id, t.title)}>
          <MessageSquare className={cn("size-3 shrink-0", active && "text-accent")} /><span className="truncate">{t.title}</span></button>
        <button aria-label={`Close ${t.title}`} className="rounded p-0.5 text-faint opacity-0 hover:text-fg group-hover:opacity-100 aria-selected:opacity-100" onClick={() => close(t.id)}><X className="size-3" /></button>
      </div>; })}
    <button aria-label="New chat" title="New chat" disabled={session.busy} onClick={() => requestChat(null)} className="mb-0.5 ml-1 rounded p-1 text-faint hover:bg-surface-2 hover:text-fg"><Plus className="size-3.5" /></button>
  </div>;
}

