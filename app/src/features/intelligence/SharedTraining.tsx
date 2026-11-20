/**
 * 2.3.2: shared training, explained. When several computers train MOTH together, the run is split into rounds:
 * each computer trains its own part of the data on a copy of MOTH, then MOTH Cloud combines the parts into one
 * improved MOTH and checks it before the next round. This tab shows that as a picture, in plain words.
 */
import { useEffect, useState } from "react";
import { Cloud, Cpu, Laptop, Monitor } from "lucide-react";
import { serverApi } from "@/lib/account";
import { formatNumber, whenVisible } from "@/lib/utils";
import { MothEmblem } from "@/components/MothEmblem";
import { cn } from "@/lib/utils";

type Any = Record<string, any>;

export function partState(j: Any): { label: string; tone: "done" | "busy" | "wait" | "off" } {
  if (j.status === "completed") return { label: "done", tone: "done" };
  if (j.status === "leased") return { label: `training${j.progress != null ? ` · ${Math.round(j.progress * 100)}%` : ""}`, tone: "busy" };
  if (j.status === "queued") return { label: j.progress ? `waiting for a computer (the last one stopped at ${Math.round(j.progress * 100)}%)` : "waiting for a computer", tone: "wait" };
  return { label: "skipped (no computer took it in time)", tone: "off" };
}

/** MOTH in the middle, one computer per part around it; data flows in while they train. */
function RoundPicture({ jobs }: { jobs: Any[] }) {
  const n = Math.max(1, jobs.length), R = 92, C = 130;
  return <svg viewBox="0 0 260 260" className="mx-auto h-64 w-64 shrink-0" role="img" aria-label="Computers training their parts of this round">
    <circle cx={C} cy={C} r={R} fill="none" stroke="var(--color-border)" strokeDasharray="2 6" />
    {jobs.map((j, i) => {
      const a = (i / n) * Math.PI * 2 - Math.PI / 2, x = C + R * Math.cos(a), y = C + R * Math.sin(a);
      const st = partState(j).tone;
      return <g key={j.shard}>
        <line x1={x} y1={y} x2={C} y2={C} stroke={st === "wait" || st === "off" ? "var(--color-border)" : "var(--color-accent)"}
          strokeOpacity={st === "done" ? 0.9 : 0.6} strokeWidth={st === "done" ? 2 : 1.5}
          strokeDasharray={st === "busy" ? "4 6" : st === "wait" ? "2 5" : undefined} className={st === "busy" ? "shared-flow" : undefined} />
        <circle cx={x} cy={y} r={17} fill="var(--color-surface-2)" stroke={st === "done" ? "var(--color-success)" : st === "busy" ? "var(--color-accent)" : "var(--color-border-strong)"} strokeWidth={1.5} />
        {st === "busy" && <circle cx={x} cy={y} r={17} fill="none" stroke="var(--color-accent)" className="shared-ping" style={{ transformOrigin: `${x}px ${y}px` }} />}
        <text x={x} y={y + 4} textAnchor="middle" fontSize="11" fill={st === "wait" || st === "off" ? "var(--color-faint)" : "var(--color-fg)"}>{st === "done" ? "✓" : j.shard + 1}</text>
      </g>;
    })}
    <circle cx={C} cy={C} r={34} fill="var(--color-surface)" stroke="var(--color-accent)" strokeOpacity={0.5} className="shared-core" style={{ transformOrigin: `${C}px ${C}px` }} />
    <foreignObject x={C - 22} y={C - 22} width={44} height={44}><MothEmblem motion="idle" className="size-11" /></foreignObject>
  </svg>;
}

export function SharedTraining() {
  const [d, setD] = useState<Any | null>(null), [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const load = () => serverApi<Any>("/v1/admin/evolution/contributions").then((v) => { setD(v); setErr(null); }).catch((e) => setErr(e.message));
    load(); const t = setInterval(whenVisible(load), 5000); return () => clearInterval(t);
  }, []);
  if (!d) return <p role="status" className="text-xs text-muted">{err ?? "Loading shared training…"}</p>;
  const exp = d.experiment;
  const explain = <p className="text-xs leading-relaxed text-muted">
    When more than one computer is training MOTH, the work is split into <b className="text-fg">rounds</b>. In each round every
    computer trains its own <b className="text-fg">part</b> of the data on a copy of MOTH. MOTH Cloud then combines the parts into one
    improved MOTH and checks it on data it never trained on; a round that makes MOTH worse is thrown away. A computer that
    stops (sleep, shut down, busy) for 20 minutes loses its part to the next free computer, and if nobody takes a part, the
    round goes on without it.</p>;
  if (!exp) return <div className="space-y-3 rounded-xl border border-border bg-surface p-4">
    <h2 className="text-sm font-medium">Shared training</h2>{explain}
    <p className="text-xs text-faint">No shared run right now: MOTH is training on one computer, or resting.</p></div>;
  const jobs: Any[] = [...(exp.current_jobs ?? [])].sort((a, b) => a.shard - b.shard);
  const doneParts = jobs.filter((j) => j.status === "completed").length;
  const last = exp.history?.at(-1);
  const round = Math.min((exp.round ?? 0) + 1, exp.rounds ?? 1);
  return <div className="space-y-4">
    <section className="rounded-xl border border-border bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">Experiment #{exp.id} · round {round} of {exp.rounds}</h2>
        <span className="text-xs text-muted">{doneParts} of {jobs.length} parts done this round · {formatNumber(exp.local_steps ?? 0)} steps per part</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3"><div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: `${((exp.round ?? 0) / Math.max(1, exp.rounds)) * 100}%` }} /></div>
      <div className="mt-3 flex flex-col items-center gap-4 md:flex-row md:items-start">
        <RoundPicture jobs={jobs} />
        <ul className="w-full min-w-0 flex-1 space-y-1.5 text-xs">
          {jobs.map((j) => { const s = partState(j);
            return <li key={j.shard} className="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5">
              <span className="w-12 shrink-0 text-faint">Part {j.shard + 1}</span>
              {j.worker?.name === "MOTH Cloud server" ? <Cloud className="size-3.5 text-accent" /> : j.worker?.this_app ? <Laptop className="size-3.5 text-accent" /> : j.worker ? <Monitor className="size-3.5 text-accent" /> : <Cpu className="size-3.5 text-faint" />}
              <span className="min-w-0 flex-1 truncate text-fg">{j.worker ? `${j.worker.name}${j.worker.this_app ? " (this computer)" : ""}` : "—"}</span>
              <span className={cn("shrink-0", s.tone === "done" ? "text-success" : s.tone === "busy" ? "text-accent" : "text-muted")}>{s.label}</span>
            </li>; })}
          {last && <li className="pt-1 text-muted">Last round {last.accepted
            ? <>made MOTH better: its test score went from {last.probe_before.toFixed(3)} to <span className="text-success">{last.probe_after.toFixed(3)}</span> (lower is better).</>
            : <>was thrown away: it made MOTH worse ({last.probe_before.toFixed(3)} → {last.probe_after.toFixed(3)}).</>}</li>}
        </ul>
      </div>
      <div className="mt-3">{explain}</div>
    </section>
    {exp.contributors?.length > 0 && <section className="rounded-xl border border-border bg-surface p-4 text-xs">
      <h3 className="mb-2 text-sm font-medium">Who has helped in this run</h3>
      <ul className="space-y-1">{exp.contributors.map((c: Any) => <li key={c.worker_id} className="flex items-center gap-2">
        <span className={cn("rounded px-1.5 py-px text-[0.625rem]", c.compute === "gpu" ? "bg-accent-soft text-accent" : "bg-surface-2 text-muted")}>{c.compute === "gpu" ? "GPU" : "CPU"}</span>
        <span className="min-w-0 flex-1 truncate text-fg">{c.name}{c.this_app ? " (this computer)" : ""}</span>
        <span className="text-muted">{formatNumber(c.tokens)} tokens · {c.rounds} round{c.rounds === 1 ? "" : "s"}</span></li>)}</ul>
    </section>}
  </div>;
}
