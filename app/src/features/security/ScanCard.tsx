/** 2.0: a scan inside the chat — the Yes/No question, live progress, findings popping in, the result. */
import { useState } from "react";
import { AlertTriangle, CheckCircle2, Radar, ShieldAlert, ShieldCheck, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { SEV_STYLE, SEVERITIES, askAbout, runStronger, stopScan, useScan, type AuditReport, type Finding, type ScanPlan } from "@/lib/scans";
import { MessageCircleQuestion } from "lucide-react";

export function SeverityBadge({ s, className }: { s: Finding["severity"]; className?: string }) {
  return <span className={cn("inline-flex shrink-0 items-center rounded border px-1.5 py-px text-[0.625rem] font-semibold uppercase tracking-wide", SEV_STYLE[s], className)}>{s}</span>;
}

export function ConfirmScan({ plan, onYes, onNo, busy }: { plan: ScanPlan; onYes: () => void; onNo: () => void; busy?: boolean }) {
  return <div className="w-full max-w-xl rounded-xl border border-accent/40 bg-surface p-3 shadow-glow animate-spring">
    <div className="flex items-start gap-2.5">
      <ShieldAlert className="mt-0.5 size-4 shrink-0 text-accent" />
      <div className="min-w-0 text-[0.8125rem]">
        <div>I'm about to scan <span className="font-mono font-semibold text-fg">{plan.describe}</span> from this computer.</div>
        <div className="mt-1 text-xs text-muted">Only do this on systems you own or have permission to test. The scan only looks: it checks open ports, versions and settings and changes nothing.</div>
        <div className="mt-2.5 flex gap-2">
          <Button size="sm" disabled={busy} onClick={onYes}><Radar /> Yes, scan it</Button>
          <Button size="sm" variant="secondary" disabled={busy} onClick={onNo}>No</Button>
        </div>
      </div>
    </div>
  </div>;
}

export function ScanCard({ id, compact = false }: { id: string; compact?: boolean }) {
  const [scan, setScan] = useScan(id);
  const [asking, setAsking] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!scan) return <div className="h-16 w-full max-w-xl animate-pulse rounded-xl border border-border bg-surface" />;
  const running = scan.status === "running";
  const total = SEVERITIES.reduce((n, s) => n + (scan.counts?.[s] ?? 0), 0);
  return <div className={cn("w-full max-w-2xl overflow-hidden rounded-xl border bg-surface", running ? "border-accent/50 working-glow" : "border-border")}>
    <div className="flex items-center gap-2 border-b border-border px-3 py-2">
      {running ? <span className="relative flex size-4 items-center justify-center"><span className="absolute size-3 rounded-full bg-accent animate-ping-soft" /><Radar className="relative size-4 text-accent" /></span>
        : scan.status === "done" ? (total ? <AlertTriangle className="size-4 text-warning" /> : <ShieldCheck className="size-4 text-success" />)
        : <Square className="size-3.5 text-muted" />}
      <div className="min-w-0 flex-1">
        <div className="truncate text-[0.8125rem] font-medium">Scan of <span className="font-mono">{scan.target}</span></div>
        <div className={cn("text-[0.6875rem]", running ? "shimmer-text" : "text-muted")}>{scan.error ?? scan.phase}{running && ` · ${Math.round(scan.progress * 100)}%`}</div>
      </div>
      {running && <Button size="sm" variant="secondary" onClick={() => stopScan(scan.id)}><Square className="text-accent" /> Stop</Button>}
    </div>
    {running && <Progress value={scan.progress * 100} className="rounded-none" />}
    <div className="space-y-2 p-3">
      {scan.open_ports.length > 0 && <div className="flex flex-wrap gap-1">{scan.open_ports.map((o) =>
        <span key={`${o.host}:${o.port}`} className="rounded border border-border bg-surface-2 px-1.5 py-px font-mono text-[0.6875rem] animate-pop" title={o.banner}>{o.port}<span className="text-faint">/{o.service}</span></span>)}</div>}
      {!running && scan.status !== "error" && !scan.open_ports.length && <div className="text-xs text-muted">No open ports among the {scan.ports.length} checked: nothing is listening, or a firewall drops the connections.</div>}
      {scan.findings.length > 0 && <ul className="space-y-1.5">{scan.findings.slice(0, compact ? 5 : 50).map((f, i) =>
        <li key={i} className="rounded-lg border border-border bg-bg/60 p-2 animate-found">
          <div className="flex items-center gap-2"><SeverityBadge s={f.severity} /><span className="min-w-0 flex-1 truncate text-xs font-medium text-fg">{f.title}</span>
            <span className="shrink-0 font-mono text-[0.625rem] text-faint">{f.port ? `:${f.port}` : ""}{f.ref ? ` · ${f.ref}` : ""}</span></div>
          {!compact && <><div className="mt-1 text-[0.6875rem] text-muted">{f.evidence}</div><div className="mt-0.5 text-[0.6875rem] text-fg"><span className="text-success">Fix:</span> {f.fix}</div>
            <AskButton onClick={() => askAbout(f)} /></>}
        </li>)}</ul>}
      {!running && scan.status === "done" && !total && scan.open_ports.length > 0 && <div className="flex items-center gap-1.5 text-xs text-success"><CheckCircle2 className="size-3.5" />Nothing stood out in the safe checks.</div>}
      {scan.stronger.filter((x) => x.status === "offered" || x.result).map((st) =>
        <div key={st.id} className="rounded-lg border border-warning/30 bg-warning/5 p-2 text-[0.6875rem]">
          <div className="font-medium text-fg">{st.title} <span className="font-mono text-faint">{st.host}:{st.port}</span></div>
          <div className="mt-0.5 text-muted">{st.result ?? st.what}</div>
          {st.status === "offered" && (asking === st.id
            ? <div className="mt-1.5 flex items-center gap-2"><span className="text-warning">This step does more than look. Run it?</span>
                <Button size="sm" onClick={() => { setErr(null); runStronger(scan.id, st.id).then(setScan).catch((e) => setErr((e as Error).message)).finally(() => setAsking(null)); }}>Yes, run it</Button>
                <Button size="sm" variant="secondary" onClick={() => setAsking(null)}>No</Button></div>
            : <Button size="sm" variant="secondary" className="mt-1.5" onClick={() => setAsking(st.id)}>Run this step…</Button>)}
        </div>)}
      {err && <div role="alert" className="text-[0.6875rem] text-danger">{err}</div>}
    </div>
  </div>;
}

function AskButton({ onClick }: { onClick: () => void }) {
  return <button onClick={onClick} className="mt-1 inline-flex items-center gap-1 rounded px-1 text-[0.6875rem] text-accent hover:bg-accent-soft">
    <MessageCircleQuestion className="size-3" />Ask MOTH</button>;
}

/** 2.1: results of a code, dependency or configuration check, shown in chat. */
export function ReportCard({ report }: { report: AuditReport }) {
  const total = report.total;
  return <div className="w-full max-w-2xl overflow-hidden rounded-xl border border-border bg-surface animate-spring">
    <div className="flex items-center gap-2 border-b border-border px-3 py-2">
      {total ? <AlertTriangle className="size-4 text-warning" /> : <ShieldCheck className="size-4 text-success" />}
      <div className="min-w-0 flex-1"><div className="text-[0.8125rem] font-medium">{report.kind}</div>
        <div className="text-[0.6875rem] text-muted">{report.note}</div></div>
      <div className="flex gap-1">{SEVERITIES.filter((v) => report.counts?.[v]).map((v) => <SeverityBadge key={v} s={v} className="px-1" />)}</div>
    </div>
    <div className="space-y-1.5 p-3">
      {!total && <div className="flex items-center gap-1.5 text-xs text-success"><CheckCircle2 className="size-3.5" />Nothing stood out.</div>}
      <ul className="space-y-1.5">{report.findings.slice(0, 50).map((f, i) =>
        <li key={i} className="rounded-lg border border-border bg-bg/60 p-2 animate-found" style={{ animationDelay: `${Math.min(i, 10) * 40}ms` }}>
          <div className="flex items-center gap-2"><SeverityBadge s={f.severity} /><span className="min-w-0 flex-1 truncate text-xs font-medium text-fg">{f.title}</span>
            <span className="shrink-0 font-mono text-[0.625rem] text-faint">{f.ref}</span></div>
          <div className="mt-1 font-mono text-[0.6875rem] text-muted">{f.where}</div>
          <div className="mt-0.5 truncate text-[0.6875rem] text-muted" title={f.evidence}>{f.evidence}</div>
          <div className="mt-0.5 text-[0.6875rem] text-fg"><span className="text-success">Fix:</span> {f.fix}</div>
          <AskButton onClick={() => askAbout(f)} />
        </li>)}</ul>
      {total > 50 && <div className="text-[0.6875rem] text-muted">+{total - 50} more (see the full write-up below).</div>}
    </div>
  </div>;
}
