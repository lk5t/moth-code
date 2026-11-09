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
  if (!base) return <p className="p-4 text-sm text-muted-foreground">Open a project to inspect its structure.</p>;
  return <section className="h-full overflow-auto p-3 text-sm space-y-3" aria-label="Project intelligence">
    <p>Local project understanding. Analysis never executes project code or uploads it. Cloud context requires separate consent.</p>
    {(error || notice) && <p role="alert">{error || notice}</p>}
    {!data && !error && <p role="status">Analyzing authorized project files…</p>}
    {data?.scope_warning && <p>{data.scope_warning}</p>}
    <div className="flex gap-3"><button disabled={busy} onClick={() => void act(() => projectApi(base + "/refresh", "POST"))}>Refresh analysis</button>
      <button disabled={busy} onClick={() => {if (window.confirm("Delete this profile’s project index and memories? Project files are preserved. Refresh explicitly to enable indexing again.")) void act(async () => {await projectApi(base, "DELETE"); setMatches(null);});}}>Delete index and memory</button></div>
    {data?.disabled ? <p>Project intelligence is disabled. Refresh analysis to enable it again.</p> : data && <>
      <p>{data.summary}</p>{data.truncated && <p>Analysis is limited to the first 1,000 eligible files.</p>}
      <p>Framework evidence: {data.frameworks?.join(", ") || "None detected"}</p>
      <details><summary>Structure and configuration</summary><pre className="whitespace-pre-wrap">{Object.entries(data.structure || {}).map(([name, count]) => `${name}: ${count} files`).join("\n")}</pre><p>{data.configurations?.join(", ")}</p></details>
      <details><summary>Dependencies and import graph</summary>{data.dependencies?.map((d, i) => <p key={i}>{d.name} {d.version} · {d.source}</p>)}{data.imports?.map((e, i) => <p key={i}>{e.source}:{e.line} → {e.target} ({e.local ? "local" : "external or unresolved"})</p>)}</details>
      <details><summary>Potential issues and skipped files</summary><p>Static evidence only; import aliases and generated files can need manual review.</p>{[...(data.issues || []), ...(data.warnings || [])].map((e, i) => <p key={i}>{e.path}{e.line ? `:${e.line}` : ""} · {e.message}</p>)}</details>
      <details><summary>Recent changes and inspected files</summary>{data.recent_changes?.map((e, i) => <p key={i}>{e.kind}: {e.path}</p>)}<p>Opened: {data.inspected?.join(", ") || "None recorded"}</p></details>
      <form onSubmit={e => {e.preventDefault(); void act(async () => {const started=epoch.current; const found=await projectApi<{matches: {path: string}[]; affected_components: string[]}>(base + "/search?q=" + encodeURIComponent(query)); if (started===epoch.current) setMatches(found);});}}>
        <label>Find relevant files<input className="w-full border border-border p-1" value={query} onChange={e => setQuery(e.target.value)} maxLength={200} /></label><button disabled={busy || !query.trim()}>Search project</button>
      </form>{matches && <div><p>Relevant: {matches.matches.map(m => m.path).join(", ") || "No matches"}</p><p>Direct dependents: {matches.affected_components.join(", ") || "None found"}</p></div>}
      <details><summary>Confirmed project decisions</summary>{data.decisions?.map(d => <div key={d.id}><p>{d.content}</p><button disabled={busy} onClick={() => void act(() => projectApi(base + "/decisions/" + d.id, "DELETE"))}>Delete decision</button></div>)}
        <form onSubmit={e => {e.preventDefault(); void act(async () => {await projectApi(base + "/decisions", "POST", {text: decision, confirmed}); setDecision(""); setConfirmed(false);});}}>
          <label>Decision<textarea className="w-full border border-border p-1" value={decision} onChange={e => setDecision(e.target.value)} maxLength={2000} /></label>
          <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I confirm this project decision</label><button disabled={busy || !confirmed || !decision.trim()}>Save decision</button>
        </form>
      </details>
    </>}
    <details><summary>Advanced: legacy device-wide notes</summary><p>These older notes are shared on this device and are separate from profile-scoped project memory.</p><MemoryPanel /></details>
  </section>;
}
