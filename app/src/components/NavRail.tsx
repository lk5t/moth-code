import { NotificationCenter } from "./NotificationCenter";
import { useEffect, useState } from "react";
import { Brain, Home, MessageSquare, Network, Settings, PanelLeftClose, PanelLeftOpen, Plus, Search, X, FolderGit2 } from "lucide-react";
import { appStore, useApp } from "@/lib/app-state";
import { WORKSPACES, navigate, workspaceOf } from "@/lib/navigation";
import { Tip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { accountStore, useAccount } from "@/lib/account";
import { LivingMoth } from "./LivingMoth";
import { AccountMenu } from "@/features/account/AccountMenu";
import { SidebarCollections, requestChat } from "./SidebarCollections";
import { FeatureSearch } from "./FeatureSearch";

const ICONS = { home: Home, chat: MessageSquare, workspace: FolderGit2, intelligence: Brain, network: Network, settings: Settings } as Record<string, typeof Home>;

/** 2.3 sidebar: brand, New chat, search, Projects (folders with their chats) and Chats; the sections as small
 * icons at the bottom with the account. Collapses to an icon rail. */
export function NavRail() {
  const view = useApp((s) => s.view);
  const owner = useAccount((s) => s.user?.role === "owner");
  const user = useAccount((s) => s.user);
  const collapsed = useApp((s) => s.sidebarCollapsed), busy = useApp((s) => s.chatSession.busy);
  const [query, setQuery] = useState(""), [search, setSearch] = useState(""), [searching, setSearching] = useState(false);
  useEffect(() => { const t = setTimeout(() => setSearch(query), 200); return () => clearTimeout(t); }, [query]);
  useEffect(() => {
    const shortcut = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || !e.altKey) return;
      const target = ({ w: "workspace", i: "intelligence", s: "settings" } as const)[e.key.toLowerCase() as "w" | "i" | "s"];
      if (target === "intelligence" && accountStore.getState().user?.role !== "owner") return;  // 1.0.12: Owner only
      if (target) { e.preventDefault(); navigate(target === "workspace" && appStore.getState().workspaceMode === "chat" ? "chat" : target); }
    };
    window.addEventListener("keydown", shortcut); return () => window.removeEventListener("keydown", shortcut);
  }, []);
  const sections = WORKSPACES.filter((w) => (!w.ownerOnly || owner) && w.view !== "chat" && w.view !== "settings");
  const row = "flex h-8 w-full items-center gap-2.5 rounded-md px-2 text-[0.8125rem] text-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:outline focus-visible:outline-accent";

  if (collapsed) return <nav aria-label="Main workspaces" className="flex min-h-0 w-12 shrink-0 flex-col items-center gap-1 border-r border-border bg-bg py-2">
    <button aria-label="Expand sidebar" aria-expanded={false} onClick={() => appStore.setState({ sidebarCollapsed: false })} className="rounded p-2 text-muted hover:bg-surface-2 hover:text-fg"><PanelLeftOpen className="size-4" /></button>
    <Tip label="New chat"><button aria-label="New Chat" disabled={busy} onClick={() => requestChat(null)} className="rounded p-2 text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50"><Plus className="size-4" /></button></Tip>
    {WORKSPACES.filter((w) => !w.ownerOnly || owner).map((w) => { const Icon = ICONS[w.view] ?? Home, selected = workspaceOf(view) === w.view;
      return <Tip key={w.view} label={w.label}><button aria-label={w.label} aria-current={selected ? "page" : undefined} onClick={() => navigate(w.view)}
        className={cn("rounded p-2 text-muted hover:bg-surface-2 hover:text-fg", selected && "bg-surface-2 text-accent")}><Icon className="size-4" /></button></Tip>; })}
    <div className="flex-1" />
    <FeatureSearch compact />
    <AccountMenu />
  </nav>;

  return <nav aria-label="Main workspaces" className="flex min-h-0 w-12 shrink-0 flex-col border-r border-border bg-bg md:w-60">
    <div className="flex h-11 shrink-0 items-center gap-2 px-3">
      <LivingMoth className="size-5" /><span className="hidden text-[0.875rem] font-semibold tracking-tight md:inline">MOTH <span className="font-normal text-muted">Code</span></span>
      <button aria-label="Collapse sidebar" aria-expanded onClick={() => appStore.setState({ sidebarCollapsed: true })} className="ml-auto rounded p-1.5 text-muted hover:bg-surface-2 hover:text-fg"><PanelLeftClose className="size-4" /></button>
    </div>
    <div className="hidden shrink-0 space-y-0.5 px-2 md:block">
      <button aria-label="New Chat" disabled={busy} onClick={() => requestChat(null)} className={cn(row, "text-fg disabled:opacity-50")}><Plus className="size-4" />New chat</button>
      {searching
        ? <label className="flex h-8 items-center gap-2 rounded-md border border-border bg-surface px-2"><Search className="size-3.5 text-faint" />
            <input autoFocus aria-label="Search conversations" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search chats"
              onKeyDown={(e) => { if (e.key === "Escape") { setQuery(""); setSearching(false); } }} className="h-7 min-w-0 flex-1 bg-transparent text-xs outline-none" />
            <button aria-label="Close search" onClick={() => { setQuery(""); setSearching(false); }} className="text-faint hover:text-fg"><X className="size-3.5" /></button></label>
        : <button className={row} onClick={() => setSearching(true)}><Search className="size-4" />Search chats</button>}
      <button aria-label="Chat" aria-current={workspaceOf(view) === "chat" ? "page" : undefined} className={cn(row, workspaceOf(view) === "chat" && "bg-surface-2 text-fg")} onClick={() => navigate("chat")}><MessageSquare className="size-4" />Chat</button>
    </div>
    <div className="mx-3 my-2 hidden border-t border-border md:block" />
    <div className="hidden min-h-0 flex-1 flex-col px-1.5 md:flex"><SidebarCollections search={search} /></div>
    <div className="flex-1 md:hidden" />
    <div className="shrink-0 border-t border-border p-2">
      <div className="mb-1.5 flex items-center justify-center gap-0.5 md:justify-start">
        {sections.map((w) => { const Icon = ICONS[w.view] ?? Home, selected = workspaceOf(view) === w.view;
          return <Tip key={w.view} label={`${w.label} — ${w.description}`}><button aria-label={w.label} aria-current={selected ? "page" : undefined} onClick={() => navigate(w.view)}
            className={cn("rounded-md p-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-fg", selected && "bg-surface-2 text-accent")}><Icon className="size-4" /></button></Tip>; })}
        <span className="ml-auto hidden md:inline"><FeatureSearch compact /></span>
      </div>
      <div className="flex items-center gap-2 rounded-md px-1 py-1">
        <AccountMenu />
        <div className="hidden min-w-0 flex-1 md:block">
          <div className="truncate text-xs text-fg">{user ? user.username : "Not signed in"}</div>
          <div className="truncate text-[0.625rem] text-faint">{user ? `${user.plan ?? "Free"}${user.role === "owner" ? " · Owner" : ""}` : "Sign in to chat with MOTH"}</div>
        </div>
        <span className="hidden md:inline"><NotificationCenter /></span>
        <button aria-label="Settings" onClick={() => navigate("settings")} className="hidden rounded p-1.5 text-muted hover:bg-surface-2 hover:text-fg md:inline-flex"><Settings className="size-4" /></button>
      </div>
    </div>
  </nav>;
}
