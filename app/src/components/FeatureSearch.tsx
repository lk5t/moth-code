import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { WORKSPACES, navigate } from "@/lib/navigation";
import { useAccount } from "@/lib/account";
import { openIntelligence } from "@/lib/app-state";

export function FeatureSearch() {
  const [open, setOpen] = useState(false), [query, setQuery] = useState(""), [active, setActive] = useState(0);
  const owner = useAccount((s) => s.user?.role === "owner");
  const input = useRef<HTMLInputElement>(null);
  const targets = [...WORKSPACES.map((w) => ({ ...w, run: () => navigate(w.view) })),
    { label: "Training", description: "Start, pause and inspect real progress", run: () => openIntelligence("training") },
    { label: "Evolution", description: "Experiments, evaluation, growth and rollback", run: () => openIntelligence("evolution") },
    ...(owner ? [{label: "Administration", description: "Owner users, billing, security and infrastructure", run: () => navigate("owner")}] : [])];
  const matches = targets.filter((t) => `${t.label} ${t.description}`.toLowerCase().includes(query.trim().toLowerCase())).sort((a,b) => Number(b.label.toLowerCase() === query.trim().toLowerCase()) - Number(a.label.toLowerCase() === query.trim().toLowerCase()));
  useEffect(() => {
    const shortcut = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setQuery(""); setActive(0); setOpen((v) => !v); } };
    window.addEventListener("keydown", shortcut); return () => window.removeEventListener("keydown", shortcut);
  }, []);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    input.current?.focus(); return () => previous?.focus();
  }, [open]);
  const choose = (index: number) => { const target = matches[index]; if (target) { target.run(); setOpen(false); } };
  return <>
    <button aria-label="Find a feature (Ctrl or Command K)" title="Find a feature · Ctrl/⌘ K" onClick={() => {setQuery(""); setActive(0); setOpen(true);}}
      className="flex h-9 w-full items-center justify-center gap-2 rounded-lg px-2 text-xs text-muted hover:bg-surface-2 focus-visible:outline focus-visible:outline-accent">
      <Search className="size-4 shrink-0" /><span className="hidden md:inline">Find a feature</span>
    </button>
    {open && <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-[15vh]" onMouseDown={(e) => {if(e.target === e.currentTarget) setOpen(false);}}>
      <div role="dialog" aria-label="Find a feature" aria-modal="true" className="w-full max-w-lg rounded-xl border border-border bg-bg p-3 shadow-xl"
        onKeyDown={(e) => {if(e.key === "Escape") {e.preventDefault(); setOpen(false);} if(e.key === "Tab") {e.preventDefault(); input.current?.focus();}}}>
        <input ref={input} aria-label="Search features" role="combobox" aria-expanded="true" aria-controls="feature-results" aria-activedescendant={matches.length ? `feature-${active}` : undefined}
          placeholder="Search workspaces and features…" value={query} className="w-full rounded-lg border border-border bg-surface p-3 text-sm outline-accent"
          onChange={(e) => {setQuery(e.target.value); setActive(0);}}
          onKeyDown={(e) => {if(e.key === "ArrowDown" || e.key === "ArrowUp") {e.preventDefault(); setActive((i) => (i + (e.key === "ArrowDown" ? 1 : -1) + matches.length) % Math.max(1, matches.length));} if(e.key === "Enter") {e.preventDefault(); choose(active);}}} />
        <div role="listbox" id="feature-results" aria-label="Matching features" className="mt-2 max-h-[50vh] overflow-auto">
          {matches.map((target, i) => <button id={`feature-${i}`} role="option" aria-selected={active === i} key={target.label} onClick={() => choose(i)}
            className={`flex w-full flex-col rounded px-3 py-2 text-left text-xs ${active === i ? "bg-surface-2 text-fg" : "text-muted"}`}>
            <span className="font-medium">{target.label}</span><span className="mt-0.5 text-faint">{target.description}</span>
          </button>)}
        </div>
        {!matches.length && <p className="p-3 text-xs text-muted">No matching feature. Try “training”, “dataset” or “updates”.</p>}
        <button className="mt-2 text-xs text-muted hover:text-fg" onClick={() => setOpen(false)}>Close · Escape</button>
      </div>
    </div>}
  </>;
}
