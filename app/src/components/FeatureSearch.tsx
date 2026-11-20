/** 2.0 command bar (Ctrl/⌘ K): actions, chats (titles and message text), projects, sections and settings. */
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { useEffect, useMemo, useRef, useState } from "react";
import { Command, FileCode2, FolderGit2, MessageSquare, Search, Settings, Sparkles, Zap } from "lucide-react";
import { WORKSPACES, navigate } from "@/lib/navigation";
import { useAccount } from "@/lib/account";
import { appStore, openIntelligence, useApp } from "@/lib/app-state";
import { get } from "@/lib/backend";
import { cn } from "@/lib/utils";
import { UI_SIZES, UI_SIZE_LABEL, setUiSize } from "@/lib/ui-size";
import { motionStore, setMotion } from "@/lib/motion";
import { requestChat } from "./SidebarCollections";
import { stopAllScans } from "@/lib/scans";
import { openProjectPath, pickProject } from "@/features/workspace/project-actions";

export type CommandGroup = "Actions" | "Chats" | "Files" | "Projects" | "Go to" | "Settings";
export interface CommandItem { id: string; group: CommandGroup; label: string; description?: string; keys?: string; run: () => void }
interface MessageHit { conversation_id: number; title: string; snippet: string; project_id: number | null }

const ICON = { Actions: Zap, Chats: MessageSquare, Files: FileCode2, Projects: FolderGit2, "Go to": Sparkles, Settings } as const;
export const SETTINGS_TABS = ["Account", "Appearance", "Privacy & AI", "Plan & referrals", "Code agent", "Updates & about", "Advanced"];

/** Open a Settings tab, also when Settings is already showing. */
export function openSettingsTab(tab: string) {
  try { localStorage.setItem("moth.section.settings", tab); } catch { /* still navigates */ }
  window.dispatchEvent(new CustomEvent("moth:settings-tab", { detail: tab }));
  navigate("settings");
}

/** Simple fuzzy score: every query word must appear; earlier and label matches rank higher. */
export function score(item: Pick<CommandItem, "label" | "description" | "group">, query: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 1;
  const label = item.label.toLowerCase(), text = `${label} ${(item.description ?? "").toLowerCase()} ${item.group.toLowerCase()}`;
  let s = 0;
  for (const w of q.split(/\s+/)) {
    const i = text.indexOf(w);
    if (i < 0) return 0;
    s += label.startsWith(w) ? 6 : label.includes(w) ? 4 : 1;
  }
  return s + (label === q ? 10 : 0);
}

export function FeatureSearch({ compact = false }: { compact?: boolean } = {}) {
  const [open, setOpen] = useState(false), [query, setQuery] = useState(""), [active, setActive] = useState(0);
  const [hits, setHits] = useState<MessageHit[]>([]);
  const project = useApp((s) => s.project);
  const [files, setFiles] = useState<string[]>([]);  // 2.4: files of the open project
  useEffect(() => {
    if (!open || !project) { setFiles([]); return; }
    get<{ path: string; dir: boolean }[]>(`/api/projects/${project.id}/tree`).then((t) => setFiles(t.filter((e) => !e.dir).map((e) => e.path))).catch(() => setFiles([]));
  }, [open, project?.id]);
  const owner = useAccount((s) => s.user?.role === "owner");
  const projects = useApp((s) => s.projects);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);

  const items = useMemo<CommandItem[]>(() => {
    const out: CommandItem[] = [
      { id: "new-chat", group: "Actions", label: "New chat", description: "Start a fresh conversation with MOTH", run: () => requestChat(null) },
      { id: "open-project", group: "Actions", label: "Open a project folder", description: "Pick a folder to code in", run: () => void pickProject().catch(() => {}) },
      { id: "scan", group: "Actions", label: "Scan a server for vulnerabilities", description: "Type the address in chat; MOTH asks for your Yes first", run: () => { requestChat(null); } },
      { id: "stop-scans", group: "Actions", label: "Stop all scans", run: () => void stopAllScans().catch(() => {}) },
      { id: "report", group: "Actions", label: "Report a problem", description: "Send what went wrong with this app's recent logs", run: () => openSettingsTab("Updates & about") },
      { id: "sidebar", group: "Actions", label: "Show or hide the sidebar", run: () => appStore.setState((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })) },
      ...UI_SIZES.map((s) => ({ id: `size-${s}`, group: "Actions" as const, label: `App size: ${UI_SIZE_LABEL[s]}`, description: "Make the whole app smaller or bigger",
        keys: s === "compact" ? "Ctrl 0" : undefined, run: () => setUiSize(s) })),
      { id: "motion", group: "Actions", label: motionStore.getState().on ? "Turn animations off" : "Turn animations on", run: () => setMotion(!motionStore.getState().on) },
      ...WORKSPACES.filter((w) => owner || !w.ownerOnly).map((w) => ({ id: `go-${w.view}`, group: "Go to" as const, label: w.label, description: w.description, run: () => navigate(w.view) })),
      ...SETTINGS_TABS.filter((t) => owner || t !== "Advanced").map((t) => ({ id: `set-${t}`, group: "Settings" as const, label: `Settings: ${t}`, run: () => openSettingsTab(t) })),
      ...[...projects].sort((a, b) => (b.last_opened ?? 0) - (a.last_opened ?? 0)).slice(0, 20).map((p) => ({
        id: `project-${p.id}`, group: "Projects" as const, label: p.name, description: p.path, run: () => void openProjectPath(p.path).catch(() => {}) })),
    ];
    if (owner) out.push(
      { id: "ai-evolution", group: "Go to", label: "Evolution", description: "Start or pause MOTH's training and follow live progress", run: () => openIntelligence("evolution") },
      { id: "ai-data", group: "Go to", label: "Training data", description: "Datasets, tokenizer and data quality", run: () => openIntelligence("data") },
      { id: "ai-history", group: "Go to", label: "Model history", description: "Improvements, versions, promotions, rollback and activity", run: () => openIntelligence("history") },
      { id: "ai-settings", group: "Go to", label: "AI Settings", description: "Autonomous evolution, resource budget and advanced training options", run: () => openIntelligence("settings") },
      { id: "admin", group: "Go to", label: "Administration", description: "Owner users, billing, security and infrastructure", run: () => navigate("owner") });
    return out;
  }, [owner, projects, open]);

  // chats whose title or messages contain the query (debounced)
  useEffect(() => {
    const q = query.trim();
    if (!open || q.length < 2) { setHits([]); return; }
    const t = setTimeout(() => { get<MessageHit[]>(`/api/search/messages?q=${encodeURIComponent(q)}&limit=8`).then(setHits).catch(() => setHits([])); }, 180);
    return () => clearTimeout(t);
  }, [query, open]);

  const results = useMemo(() => {
    const ranked = items.map((it) => ({ it, s: score(it, query) })).filter((x) => x.s > 0).sort((a, b) => b.s - a.s).map((x) => x.it);
    const chats: CommandItem[] = hits.map((h) => ({ id: `chat-${h.conversation_id}`, group: "Chats", label: h.title, description: h.snippet || undefined,
      run: () => requestChat(h.conversation_id, h.title) }));
    const q = query.trim().toLowerCase();
    const fileHits: CommandItem[] = q.length < 2 ? [] : files
      .map((f) => ({ f, name: f.split("/").pop()!.toLowerCase() }))
      .filter(({ f, name }) => name.includes(q) || f.toLowerCase().includes(q))
      .sort((a, b) => Number(b.name.startsWith(q)) - Number(a.name.startsWith(q)) || a.f.length - b.f.length).slice(0, 8)
      .map(({ f }) => ({ id: `file-${f}`, group: "Files" as const, label: f.split("/").pop()!, description: f,
        run: () => { appStore.setState({ view: "workspace" }); void import("@/features/workspace/workspace-actions").then((m) => m.openFile(f)); } }));
    const all = query.trim() ? [...ranked.slice(0, 3), ...fileHits, ...chats, ...ranked.slice(3)] : ranked;
    return all.slice(0, 40);
  }, [items, hits, query, files]);

  useEffect(() => {
    const shortcut = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setQuery(""); setActive(0); setOpen((v) => !v); } };
    window.addEventListener("keydown", shortcut); return () => window.removeEventListener("keydown", shortcut);
  }, []);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    input.current?.focus(); return () => previous?.focus();
  }, [open]);
  useEffect(() => { list.current?.querySelector(`#cmd-${active}`)?.scrollIntoView({ block: "nearest" }); }, [active]);

  const choose = (index: number) => { const target = results[index]; if (target) { setOpen(false); target.run(); } };
  let lastGroup = "";
  return <>
    <button aria-label="Command bar (Ctrl or Command K)" title="Search and commands · Ctrl/⌘ K" onClick={() => { setQuery(""); setActive(0); setOpen(true); }}
      className="flex h-8 w-full items-center justify-center gap-2 rounded-md px-2 text-xs text-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:outline focus-visible:outline-accent md:justify-start">
      <Search className="size-4 shrink-0" />{!compact && <><span className="hidden flex-1 text-left md:inline">Search</span><kbd className="hidden rounded border border-border px-1 text-[0.625rem] text-faint md:inline">Ctrl K</kbd></>}
    </button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="top-[22%] w-full max-w-xl -translate-y-0 p-0">
      <DialogTitle className="sr-only">Command bar</DialogTitle><DialogDescription className="sr-only">Search chats, projects, actions and settings. Use arrows and Enter. Escape closes.</DialogDescription>
      <div className="flex items-center gap-2 border-b border-border px-3">
        <Command className="size-4 text-accent" />
        <input ref={input} aria-label="Search commands" role="combobox" aria-expanded="true" aria-controls="cmd-results" aria-activedescendant={results.length ? `cmd-${active}` : undefined}
          placeholder="Search chats, files, projects, actions, settings…" value={query} className="h-11 w-full bg-transparent text-sm outline-none placeholder:text-faint"
          onChange={(e) => { setQuery(e.target.value); setActive(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); setActive((i) => (i + (e.key === "ArrowDown" ? 1 : -1) + results.length) % Math.max(1, results.length)); }
            if (e.key === "Enter") { e.preventDefault(); choose(active); }
          }} />
      </div>
      <div ref={list} role="listbox" id="cmd-results" aria-label="Results" className="max-h-[55vh] overflow-auto p-1.5">
        {results.map((it, i) => {
          const header = it.group !== lastGroup ? it.group : null; lastGroup = it.group;
          const Icon = ICON[it.group];
          return <div key={it.id}>
            {header && <div className="px-2.5 pb-1 pt-2 text-[0.625rem] font-medium uppercase tracking-wider text-faint">{header}</div>}
            <button id={`cmd-${i}`} role="option" aria-selected={active === i} onMouseMove={() => setActive(i)} onClick={() => choose(i)}
              className={cn("flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-xs transition-colors animate-fade-in", active === i ? "bg-surface-2 text-fg" : "text-muted")}>
              <Icon className={cn("size-3.5 shrink-0", active === i && "text-accent")} />
              <span className="min-w-0 flex-1"><span className="block truncate font-medium">{it.label}</span>
                {it.description && <span className="block truncate text-[0.6875rem] text-faint">{it.description}</span>}</span>
              {it.keys && <kbd className="rounded border border-border px-1 text-[0.625rem] text-faint">{it.keys}</kbd>}
            </button>
          </div>;
        })}
        {!results.length && <p className="p-4 text-center text-xs text-muted">Nothing found for “{query}”.</p>}
      </div>
      <div className="flex gap-3 border-t border-border px-3 py-1.5 text-[0.625rem] text-faint"><span>↑↓ move</span><span>Enter open</span><span>Esc close</span></div>
    </DialogContent></Dialog>
  </>;
}
