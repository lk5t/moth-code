/** 1.0: pick one of your GitHub repositories and clone it as a MOTH project. */
import { useEffect, useState } from "react";
import { GitBranch } from "lucide-react";
import { gh } from "@/lib/github";
import { cloneFromGitHub } from "@/features/workspace/project-actions";
import { Button } from "@/components/ui/button";

type Repo = { full_name: string; private: boolean; description: string | null };

/** 2.2: opened from the Home header's "Clone from GitHub" button; loads the list as soon as it appears. */
export function CloneGitHub({ onClose }: { onClose: () => void }) {
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const load = async () => {
    try { setRepos(await gh<Repo[]>("/api/github/repos")); setNote(null); } catch (e) { setNote(String((e as Error).message ?? e)); }
  };
  useEffect(() => { void load(); }, []);
  if (!repos) return <div className="flex items-center gap-2 rounded-xl border border-border bg-surface p-3 text-xs text-muted">
    <GitBranch className="size-3.5 text-accent" />{note ? <><span className="text-warning">{note}</span>
      <Button size="sm" variant="ghost" className="ml-auto" onClick={() => void load()}>Try again</Button>
      <button className="text-faint hover:text-fg" onClick={onClose}>Close</button></> : "Loading your GitHub repositories…"}</div>;
  const shown = repos.filter((r) => r.full_name.toLowerCase().includes(q.toLowerCase())).slice(0, 30);
  return <div className="animate-pop w-full rounded-xl border border-border bg-surface p-3 text-xs">
    <div className="mb-2 flex items-center gap-2"><GitBranch className="size-3.5 text-accent" /><span className="font-medium">Your GitHub repositories</span>
      <input aria-label="Filter repositories" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter" className="ml-auto h-7 w-40 rounded border border-border bg-bg px-2" />
      <button className="text-faint hover:text-fg" onClick={onClose}>Close</button></div>
    <ul className="stagger max-h-56 space-y-1 overflow-auto">{shown.map((r) => <li key={r.full_name}>
      <button className="lift flex w-full items-center gap-2 rounded border border-transparent px-2 py-1 text-left hover:border-border"
        onClick={() => void cloneFromGitHub(r.full_name).catch((e) => setNote(String((e as Error).message ?? e)))}>
        <span className="font-mono">{r.full_name}</span>{r.private && <span className="text-faint">private</span>}
        <span className="min-w-0 flex-1 truncate text-faint">{r.description ?? ""}</span></button></li>)}</ul>
    {note && <p className="mt-1 text-warning">{note}</p>}
  </div>;
}
