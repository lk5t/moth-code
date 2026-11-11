/**
 * AI → AI Settings, everyday view: the few choices that matter, in plain words. Every control
 * writes the existing MOTH Cloud settings (evolution settings, trusted-data policy, storage);
 * parameter counts, optimiser settings and experiments stay in Advanced below.
 */
import { useState } from "react";
import { HardDrive } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { secure, formatBytes } from "@/features/owner/ops";
import { Card, CardContent } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Any = Record<string, any>;
const load = (url: string) => serverApi<Any>(url);
const BUDGETS = [["light", "Light", 2], ["balanced", "Balanced", 6], ["maximum", "Maximum", 24]] as const;

function Row({ title, help, children }: { title: string; help: string; children: React.ReactNode }) {
  return <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border py-3 last:border-0">
    <div className="min-w-0 max-w-xl"><p className="text-sm text-fg">{title}</p><p className="mt-0.5 text-xs text-muted">{help}</p></div>
    <div className="shrink-0">{children}</div>
  </div>;
}

export function AiSettings() {
  const server = useAccount((s) => s.serverUrl), token = useAccount((s) => s.token), scope = server + "\0" + token;
  const evo = useResource<Any>("/v1/admin/evolution/status", [], undefined, scope, load);
  const disc = useResource<Any>("/v1/admin/library/discovery", [], undefined, scope, load);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState<string | null>(null);
  const s = evo.data?.settings;
  const change = async (changes: Any) => {
    setBusy(true); setNotice(null);
    try { await secure(() => serverApi("/v1/admin/evolution/settings", { method: "PUT", json: { changes } })); await evo.reload(); }
    catch (e) { setNotice((e as Error).message); } finally { setBusy(false); }
  };
  const sources = async (ids: string[]) => {
    setBusy(true); setNotice(null);
    try { await secure(() => serverApi("/v1/admin/library/discovery", { method: "PUT", json: { changes: { approved_sources: ids } } })); await disc.reload(); }
    catch (e) { setNotice((e as Error).message); } finally { setBusy(false); }
  };
  const hours = s?.budget?.max_compute_hours_per_day;
  const approved: string[] = disc.data?.policy?.approved_sources ?? [];
  return <div className="space-y-3">
    <Card aria-label="Everyday AI settings"><CardContent className="p-4">
      <h2 className="text-sm font-medium">How MOTH evolves</h2>
      {!s ? <p className="mt-2 text-xs text-muted">{evo.error ? `Settings unavailable: ${evo.error}` : "Loading…"}</p> : <>
        <Row title="Keep evolving continuously" help="On: after each cycle MOTH plans the next one by itself. Off: it trains one cycle each time you press Start Evolution.">
          <Switch aria-label="Keep evolving continuously" checked={!!s.automatic} disabled={busy} onCheckedChange={(v) => void change({ automatic: v })} /></Row>
        <Row title="Plan training automatically" help="MOTH chooses steps, learning rate and batch size from its measured results and explains each change. Off: the fixed values in Advanced are used.">
          <Switch aria-label="Plan training automatically" checked={s.autopilot !== false} disabled={busy} onCheckedChange={(v) => void change({ autopilot: v })} /></Row>
        <Row title="Resource budget" help={`At most ${hours ?? "—"} hours of training per day on MOTH Cloud. Training also waits while people are using MOTH and never uses the last ${s.limits?.min_free_memory_gb ?? 1} GB of memory.`}>
          <div role="radiogroup" aria-label="Resource budget" className="flex rounded-lg border border-border p-0.5 text-xs">
            {BUDGETS.map(([id, label, h]) => <button key={id} role="radio" aria-checked={hours === h} disabled={busy}
              onClick={() => void change({ budget: { ...s.budget, max_compute_hours_per_day: h } })}
              className={cn("rounded-md px-3 py-1", hours === h ? "bg-accent text-white" : "text-muted hover:text-fg")}>{label}</button>)}
          </div></Row>
        <Row title="Use MOTH workers" help="Let enrolled workers (with their owners' consent) take training jobs. Each worker keeps its own limits and can stop at any time.">
          <Switch aria-label="Use MOTH workers" checked={s.cloud_workers !== false} disabled={busy} onCheckedChange={(v) => void change({ cloud_workers: v })} /></Row>
        <Row title="Deploy verified improvements automatically" help={`A new version must beat the current one on data it never trained on and pass every safety and quality gate. It first serves ${s.rollout?.canary_percent ?? 20}% of users while monitored and is rolled back if it misbehaves. Off: you deploy passed versions yourself.`}>
          <Switch aria-label="Deploy verified improvements automatically" checked={!!s.auto_deploy} disabled={busy} onCheckedChange={(v) => void change({ auto_deploy: v })} /></Row>
      </>}
    </CardContent></Card>

    <Card aria-label="Training data preferences"><CardContent className="p-4">
      <h2 className="text-sm font-medium">Training data</h2>
      <p className="mt-1 text-xs text-muted">Trusted, licensed sources MOTH may download and prepare. Coding sources come first. Your safety settings (Settings → Administration) are separate and never changed by Evolution.</p>
      {disc.error && <p className="mt-2 text-xs text-danger">{disc.error}</p>}
      <ul className="mt-2 grid gap-1 sm:grid-cols-2">{[...(disc.data?.discovered ?? [])].sort((a: Any, b: Any) => Number(b.domain === "code") - Number(a.domain === "code")).map((src: Any) => <li key={src.id}>
        <label className={cn("flex items-start gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-surface-2", !src.license_verified && "opacity-50")}>
          <input type="checkbox" className="mt-0.5 accent-[var(--color-accent)]" checked={approved.includes(src.id)} disabled={busy || !src.license_verified}
            onChange={(e) => void sources(e.target.checked ? [...approved, src.id] : approved.filter((x) => x !== src.id))} />
          <span><span className="text-fg">{src.name ?? src.id}</span> <span className="text-faint">· {src.license}{src.domain ? ` · ${src.domain}` : ""}</span></span>
        </label></li>)}</ul>
    </CardContent></Card>

    <StorageManager />
    {notice && <p role="alert" className="text-xs text-danger">{notice}</p>}
  </div>;
}

export function StorageManager() {
  const server = useAccount((s) => s.serverUrl), token = useAccount((s) => s.token);
  const { data, error, reload } = useResource<Any>("/v1/admin/evolution/storage", [], undefined, server + "\0" + token, load);
  const [picked, setPicked] = useState<string[]>([]), [busy, setBusy] = useState(false), [result, setResult] = useState<string | null>(null);
  const removable: Any[] = (data?.categories ?? []).flatMap((c: Any) => c.items.filter((i: Any) => !i.protected));
  const run = async (ids: string[]) => {
    if (!ids.length) return;
    setBusy(true); setResult(null);
    try {
      const r = await secure(() => serverApi<Any>("/v1/admin/evolution/storage/cleanup", { method: "POST", json: { items: ids } }));
      setResult(`Freed ${formatBytes(r.freed_bytes)}.` + (r.skipped.length ? ` ${r.skipped.length} kept: ${r.skipped[0].reason}.` : ""));
      setPicked([]); await reload();
    } catch (e) { setResult((e as Error).message); } finally { setBusy(false); }
  };
  return <Card aria-label="Storage"><CardContent className="p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="flex items-center gap-2 text-sm font-medium"><HardDrive className="size-4 text-accent" />Storage on MOTH Cloud</h2>
      {data?.disk && <span className="text-xs text-muted">{formatBytes(data.disk.free)} free of {formatBytes(data.disk.total)}</span>}
    </div>
    {error && <p className="mt-2 text-xs text-danger">{error}</p>}
    {Array.isArray(data?.categories) && data && <>
      <ul className="mt-3 space-y-1">{data.categories.map((c: Any) => <li key={c.id}><details className="rounded-md border border-border px-3 py-2">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-xs">
          <span className="text-fg">{c.label}</span><span className="text-muted">{formatBytes(c.bytes)}{c.removable_bytes > 0 && ` · ${formatBytes(c.removable_bytes)} removable`}</span></summary>
        <p className="mt-1 text-[11px] text-faint">{c.explanation}</p>
        <ul className="mt-2 space-y-0.5">{c.items.map((i: Any) => <li key={i.id} className="flex items-center gap-2 text-[11px]">
          <input type="checkbox" aria-label={`Remove ${i.label}`} disabled={i.protected || busy} checked={picked.includes(i.id)}
            onChange={(e) => setPicked((p) => e.target.checked ? [...p, i.id] : p.filter((x) => x !== i.id))} className="accent-[var(--color-accent)]" />
          <span className="min-w-0 flex-1 truncate text-muted" title={i.label}>{i.label}</span>
          <span className="shrink-0 text-faint">{i.protected ? `Kept: ${i.reason}` : formatBytes(i.bytes)}</span></li>)}
          {!c.items.length && <li className="text-[11px] text-faint">Nothing stored.</li>}</ul>
      </details></li>)}</ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" disabled={busy || !removable.length} onClick={() => void run(removable.map((i) => i.id))}>
          Clean up {formatBytes(data.removable_bytes)}</Button>
        {picked.length > 0 && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(picked)}>Remove {picked.length} selected</Button>}
        <span className="text-[11px] text-faint">The deployed model, rollback versions and data in use are always kept.</span>
      </div>
      {result && <p role="status" className="mt-2 text-xs text-muted">{result}</p>}
    </>}
  </CardContent></Card>;
}
