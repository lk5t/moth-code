/**
 * Settings → Advanced → Diagnostics (0.9.0): what MOTH Cloud's background loops are doing, what the
 * self-repair supervisor fixed, and recent server warnings and errors (redacted on the server). "Copy
 * report" gives a plain-text summary to share when something needs a closer look.
 */
import { useState } from "react";
import { serverApi, useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { Button } from "@/components/ui/button";

type Any = Record<string, any>;
const path = "/v1/admin/evolution/diagnostics";
const load = (url: string) => serverApi<Any>(url);
const ago = (s: number | null | undefined) => s == null ? "no round yet" : s < 90 ? `${s} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
const at = (t: number) => new Date(t * 1000).toLocaleString();
const gb = (b: number) => `${(b / 1024 ** 3).toFixed(1)} GB`;

export function DiagnosticsPanel() {
  const server = useAccount((s) => s.serverUrl), token = useAccount((s) => s.token);
  const { data, error, reload } = useResource<Any>(path, [], undefined, server + "\0" + token, load);
  const [note, setNote] = useState<string | null>(null), [busy, setBusy] = useState(false);

  const check = async () => {
    setBusy(true);
    try {
      const r = await serverApi<Any>(`${path}/check`, { method: "POST" });
      setNote(r.repairs?.length ? `Repaired: ${r.repairs.map((x: Any) => x.issue).join("; ")}` : "Everything checked: nothing needed repair.");
      await reload();
    } catch (e) { setNote(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(data?.report ?? ""); setNote("Report copied."); } catch { setNote("Could not copy the report."); }
  };

  return <section aria-label="Diagnostics" className="rounded-xl border border-border p-4 text-xs">
    <div className="mb-2 flex flex-wrap items-center gap-2">
      <h3 className="text-sm font-medium">Diagnostics</h3>
      <span className="text-muted">MOTH Cloud checks and repairs itself every minute.</span>
      <span className="ml-auto flex gap-2">
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => void check()}>Check now</Button>
        <Button size="sm" variant="secondary" disabled={!data?.report} onClick={() => void copy()}>Copy report</Button>
      </span>
    </div>
    {note && <p role="status" className="mb-2 text-muted">{note}</p>}
    {error && <p className="text-warning">Diagnostics are unavailable: {String(error)}</p>}
    {data && <div className="space-y-3">
      <ul aria-label="Background loops" className="grid gap-1 sm:grid-cols-2">
        {data.loops.map((l: Any) => <li key={l.name} className="rounded-lg border border-border px-2 py-1">
          <span className="text-fg">{l.label}</span> · <span className={l.alive ? "text-faint" : "text-warning"}>{l.alive ? "running" : "stopped"}</span>
          <span className="text-faint"> · last round {ago(l.last_round_seconds_ago)}</span></li>)}
      </ul>
      <p className="text-muted">
        Serving: {data.serving.deployed_version ? `v${data.serving.deployed_version} ${data.serving.loaded ? "loaded" : "not loaded"}` : "no model deployed yet"}
        {data.serving.problem ? ` — ${data.serving.problem}` : ""} · Built-in worker: {data.cloud_worker.state}
        {data.cloud_worker.detail ? ` (${data.cloud_worker.detail})` : ""} · Disk: {gb(data.disk.free)} free of {gb(data.disk.total)}
      </p>
      <div>
        <p className="mb-1 text-faint">Recent self-repairs</p>
        {data.repairs.length ? <ul className="space-y-0.5">{data.repairs.slice(0, 10).map((r: Any, i: number) =>
          <li key={i}><span className="text-faint">{at(r.at)}</span> · {r.issue} → <span className={r.ok ? "text-fg" : "text-warning"}>{r.action}</span></li>)}</ul>
          : <p className="text-faint">None — nothing needed repair.</p>}
      </div>
      <details>
        <summary className="cursor-pointer text-muted hover:text-fg">Recent warnings and errors ({data.errors.length})</summary>
        <ul className="mt-1 max-h-64 space-y-0.5 overflow-auto font-mono text-[11px]">{data.errors.map((e: Any, i: number) =>
          <li key={i} className={e.level === "error" || e.level === "critical" ? "text-warning" : "text-muted"}>{at(e.at)} {e.logger}: {e.message}</li>)}</ul>
      </details>
    </div>}
  </section>;
}
