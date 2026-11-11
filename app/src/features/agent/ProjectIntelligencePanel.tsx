import { Button } from "@/components/ui/button";
import { useEffect, useRef, useState } from "react";
import { useApp } from "@/lib/app-state";
import { useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { projectApi } from "@/lib/project-intelligence";
import { MemoryPanel } from "./MemoryPanel";

type Evidence = {path: string; line?: number; message: string};
type Snapshot = {disabled?: boolean; summary?: string; scope_warning?: string; truncated?: boolean; frameworks?: string[]; configurations?: string[]; structure?: Record<string, number>; dependencies?: {name: string; version?: string; source: string}[]; imports?: {source: string; target: string; line: number; local: boolean}[]; issues?: Evidence[]; warnings?: Evidence[]; recent_changes?: {path: string; kind: string}[]; inspected?: string[]; decisions?: {id: number; title: string; content: string}[]};
const load = (path: string) => projectApi<Snapshot>(path);
export function ProjectIntelligencePanel() {
  const project = useApp(s => s.project);
  const token = useAccount(s => s.token), server = useAccount(s => s.serverUrl);
  const epoch = useRef(0);
  const identity = `${project?.id}\0${server}\0${token}`;
  const current = useRef(identity); if (current.current !== identity) {current.current = identity; ++epoch.current;}
  const base = project ? `/api/projects/${project.id}/intelligence` : null;
  const {data, error, reload} = useResource<Snapshot>(base, ["files", "project"], undefined, server + "\0" + token, load);
  const [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const [decision, setDecision] = useState(""), [confirmed, setConfirmed] = useState(false), [query, setQuery] = useState("");
  const [matches, setMatches] = useState<{matches: {path: string}[]; affected_components: string[]} | null>(null);
  useEffect(() => {setBusy(false); setNotice(""); setDecision(""); setConfirmed(false); setMatches(null); setQuery("");}, [base, token, server]);
  useEffect(() => {
    const refresh = () => {if (!document.hidden) void reload();};
    const timer = setInterval(refresh, 15000); document.addEventListener("visibilitychange", refresh);
    return () => {clearInterval(timer); document.removeEventListener("visibilitychange", refresh);};
  }, [reload]);
  async function act(action: () => Promise<unknown>) {
    const started = epoch.current; setBusy(true); setNotice("");
    try {await action(); if (started === epoch.current) await reload();} catch (e) {if (started === epoch.current) setNotice(String((e as Error).message));} finally {if (started === epoch.current) setBusy(false);}
  }
  if (!base) return <p className="p-4 text-sm text-muted">Open a project to inspect its structure.</p>;
  return <section className="h-full space-y-3 overflow-auto p-4 text-xs" aria-label="Project intelligence">
    <p className="text-muted">Local project understanding. Analysis never executes project code or uploads it. Cloud context requires separate consent.</p>
    {(error || notice) && <p role="alert" className="text-danger">{error || notice}</p>}
    {!data && !error && <p role="status" className="text-muted">Analyzing authorized project files…</p>}
    {data?.scope_warning && <p>{data.scope_warning}</p>}
    <div className="flex flex-wrap gap-2"><Button size="sm" variant="secondary" disabled={busy} onClick={() => void act(() => projectApi(base + "/refresh", "POST"))}>Refresh analysis</Button>
      <Button size="sm" variant="ghost" disabled={busy} onClick={() => {if (window.confirm("Delete this profile’s project index and memories? Project files are preserved. Refresh explicitly to enable indexing again.")) void act(async () => {await projectApi(base, "DELETE"); setMatches(null);});}}>Delete index and memory</Button></div>
    {data?.disabled ? <p>Project intelligence is disabled. Refresh analysis to enable it again.</p> : data && <>
      <p className="text-sm text-fg">{data.summary}</p>{data.truncated && <p>Analysis is limited to the first 1,000 eligible files.</p>}
      <p>Framework evidence: {data.frameworks?.join(", ") || "None detected"}</p>
      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-muted hover:text-fg">Structure and configuration</summary><pre className="whitespace-pre-wrap">{Object.entries(data.structure || {}).map(([name, count]) => `${name}: ${count} files`).join("\n")}</pre><p>{data.configurations?.join(", ")}</p></details>
      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-muted hover:text-fg">Dependencies and import graph</summary>{data.dependencies?.map((d, i) => <p key={i}>{d.name} {d.version} · {d.source}</p>)}{data.imports?.map((e, i) => <p key={i}>{e.source}:{e.line} → {e.target} ({e.local ? "local" : "external or unresolved"})</p>)}</details>
      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-muted hover:text-fg">Potential issues and skipped files</summary><p>Static evidence only; import aliases and generated files can need manual review.</p>{[...(data.issues || []), ...(data.warnings || [])].map((e, i) => <p key={i}>{e.path}{e.line ? `:${e.line}` : ""} · {e.message}</p>)}</details>
      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-muted hover:text-fg">Recent changes and inspected files</summary>{data.recent_changes?.map((e, i) => <p key={i}>{e.kind}: {e.path}</p>)}<p>Opened: {data.inspected?.join(", ") || "None recorded"}</p></details>
      <form onSubmit={e => {e.preventDefault(); void act(async () => {const started=epoch.current; const found=await projectApi<{matches: {path: string}[]; affected_components: string[]}>(base + "/search?q=" + encodeURIComponent(query)); if (started===epoch.current) setMatches(found);});}}>
        <label className="block text-muted">Find relevant files<input className="mt-1 w-full rounded-md border border-border bg-bg p-2 text-fg" value={query} onChange={e => setQuery(e.target.value)} maxLength={200} /></label><Button size="sm" variant="secondary" className="mt-2" type="submit" disabled={busy || !query.trim()}>Search project</Button>
      </form>{matches && <div className="rounded-lg border border-border p-3"><p>Relevant: {Array.from(new Set(matches.matches.map(m => m.path))).join(", ") || "No matches"}</p><p>Direct dependents: {matches.affected_components.join(", ") || "None found"}</p></div>}
      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-muted hover:text-fg">Confirmed project decisions</summary>{data.decisions?.map(d => <div key={d.id}><p>{d.content}</p><Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(() => projectApi(base + "/decisions/" + d.id, "DELETE"))}>Delete decision</Button></div>)}
        <form onSubmit={e => {e.preventDefault(); void act(async () => {await projectApi(base + "/decisions", "POST", {text: decision, confirmed}); setDecision(""); setConfirmed(false);});}}>
          <label className="mt-2 block text-muted">Decision<textarea className="mt-1 w-full rounded-md border border-border bg-bg p-2 text-fg" value={decision} onChange={e => setDecision(e.target.value)} maxLength={2000} /></label>
          <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I confirm this project decision</label><Button size="sm" className="mt-2" type="submit" disabled={busy || !confirmed || !decision.trim()}>Save decision</Button>
        </form>
      </details>
    </>}
    <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-muted hover:text-fg">Advanced: legacy device-wide notes</summary><p>These older notes are shared on this device and are separate from profile-scoped project memory.</p><MemoryPanel /></details>
  </section>;
}
