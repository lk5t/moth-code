/** 2.0 Security: every scan you confirmed in chat, with its findings, fixes and full log. */
import { useEffect, useMemo, useState } from "react";
import { Radar, ShieldCheck, Square, Trash2 } from "lucide-react";
import { get, del } from "@/lib/backend";
import { useEvent } from "@/lib/events";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { cn } from "@/lib/utils";
import { requestChat } from "@/components/SidebarCollections";
import { SEVERITIES, stopAllScans, type Scan } from "@/lib/scans";
import { ScanCard, SeverityBadge } from "./ScanCard";

const when = (t: number) => new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export function ScansView() {
  const [scans, setScans] = useState<Scan[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [log, setLog] = useState<Scan["log"]>([]);
  const reload = () => get<Scan[]>("/api/scans").then((s) => { setScans(s); setSelected((cur) => cur ?? s[0]?.id ?? null); }).catch(() => setScans([]));
  useEffect(() => { void reload(); }, []);
  useEvent("scan", (e) => { if (e.kind !== "progress") void reload(); else setScans((cur) => cur?.map((s) => s.id === e.scan.id ? { ...s, ...e.scan } : s) ?? cur); });
  useEffect(() => { if (selected) get<Scan>(`/api/scans/${selected}`).then((s) => setLog(s.log ?? [])).catch(() => setLog([])); }, [selected, scans?.find((s) => s.id === selected)?.status]);
  const running = useMemo(() => scans?.filter((s) => s.status === "running").length ?? 0, [scans]);
  const current = scans?.find((s) => s.id === selected) ?? null;

  if (scans && !scans.length) return <div className="h-full p-6"><EmptyState title="No scans yet">
    Ask MOTH in chat, for example “check 192.168.1.10 for vulnerabilities” or “scan 10.0.0.5 port 8080”. MOTH asks for your Yes before it scans anything, and only scan systems you own or may test.
    <div className="mt-3"><Button size="sm" onClick={() => requestChat(null)}><Radar /> Open chat</Button></div></EmptyState></div>;

  return <div className="flex h-full min-h-0">
    <aside className="flex w-64 shrink-0 flex-col border-r border-border">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <ShieldCheck className="size-4 text-accent" /><h1 className="flex-1 text-sm font-semibold">Security</h1>
        {running > 0 && <Button size="sm" variant="secondary" onClick={() => stopAllScans().then(reload)}><Square className="text-accent" /> Stop all</Button>}
      </div>
      <ul className="stagger min-h-0 flex-1 space-y-0.5 overflow-auto p-1.5">
        {scans?.map((s) => <li key={s.id}>
          <button onClick={() => setSelected(s.id)} className={cn("w-full rounded-md px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-surface-2", selected === s.id && "bg-surface-2")}>
            <div className="flex items-center gap-1.5"><span className={cn("size-1.5 shrink-0 rounded-full", s.status === "running" ? "bg-accent animate-pulse" : s.status === "done" ? "bg-success" : s.status === "error" ? "bg-danger" : "bg-faint")} />
              <span className="truncate font-mono text-fg">{s.target}</span></div>
            <div className="mt-0.5 flex items-center gap-1 text-[0.625rem] text-faint">{when(s.started_at)}
              {SEVERITIES.filter((v) => s.counts?.[v]).slice(0, 3).map((v) => <SeverityBadge key={v} s={v} className="ml-1 px-1 py-0 text-[0.5625rem]" />)}</div>
          </button></li>)}
      </ul>
    </aside>
    <section className="min-w-0 flex-1 overflow-auto p-4">
      {current && <div key={current.id} className="mx-auto flex max-w-3xl flex-col gap-3 animate-view-in">
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1"><div className="truncate font-mono text-sm font-semibold">{current.target}</div>
            <div className="text-[0.6875rem] text-muted">Confirmed {when(current.confirmed_at)} · {current.ports.length} ports · ran from this computer</div></div>
          <Button size="sm" variant="ghost" onClick={() => { void del(`/api/scans/${current.id}`).then(() => { setSelected(null); void reload(); }); }}><Trash2 /> Delete</Button>
        </div>
        <ScanCard id={current.id} />
        <details className="rounded-lg border border-border bg-surface text-xs">
          <summary className="cursor-pointer px-3 py-2 text-muted hover:text-fg">Activity log ({log?.length ?? 0} entries): every step MOTH took</summary>
          <ol className="max-h-72 overflow-auto border-t border-border p-2 font-mono text-[0.6875rem]">
            {log?.map((e, i) => <li key={i} className="flex gap-2 py-px"><span className="shrink-0 text-faint">{new Date(e.at * 1000).toLocaleTimeString()}</span>
              <span className="text-fg">{e.action}</span><span className="truncate text-muted">{Object.entries(e).filter(([k]) => k !== "at" && k !== "action").map(([k, v]) => `${k}=${String(v)}`).join(" ")}</span></li>)}
          </ol>
        </details>
      </div>}
    </section>
  </div>;
}
