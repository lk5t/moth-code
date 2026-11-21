/** 2.4: Home — this week's leaderboard and how MOTH's test scores changed across versions. */
import { Database, Trophy, TrendingUp } from "lucide-react";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { serverApi, useAccount } from "@/lib/account";
import { useCloudProgress } from "@/lib/cloud-progress";
import { useResource } from "@/lib/hooks";
import { cn } from "@/lib/utils";

type Any = Record<string, any>;
const fromCloud = (url: string) => serverApi<Any>(url);
const NICE: Record<string, string> = { code: "Coding", codegen: "Coding", python: "Python", math: "Maths", arithmetic: "Maths",
  conversation: "Conversation", dialogue: "Conversation", reasoning: "Reasoning", language: "Language", debugging: "Debugging" };
const nice = (k: string) => NICE[k.toLowerCase()] ?? NICE[k.toLowerCase().split(/[_-]/)[0]] ?? k.replace(/[_-]+/g, " ");

export function Leaderboard() {
  const server = useAccount((s) => s.serverUrl), token = useAccount((s) => s.token);
  const { data } = useResource<Any>(token ? "/v1/intelligence/leaderboard" : null, [], undefined, server + "\0" + token, fromCloud);
  if (!data) return null;
  const top: Any[] = data.top ?? [];
  return <section aria-label="Leaderboard" className="rounded-xl border border-border bg-surface p-3 text-xs">
    <h2 className="mb-2 flex items-center gap-1.5 font-medium"><Trophy className="size-3.5 text-accent" /> Top helpers this week</h2>
    {top.length ? <ol className="space-y-1">{top.map((r) => <li key={r.rank} className={cn("flex items-center gap-2 rounded-md px-1.5 py-1", r.you && "bg-accent-soft")}>
      <span className={cn("w-5 text-center font-mono", r.rank <= 3 ? "text-accent" : "text-faint")}>{r.rank}</span>
      <span className="min-w-0 flex-1 truncate text-fg">{r.username}{r.you && <span className="text-muted"> (you)</span>}</span>
      <span className="text-muted">{r.jobs} jobs{r.hours ? ` · ${r.hours} h` : ""}</span></li>)}</ol>
      : <p className="text-muted">No computers have trained MOTH this week yet. Be the first: Network → Add another computer.</p>}
    {data.you && data.you.rank > 10 && <p className="mt-1.5 text-muted">You are #{data.you.rank} with {data.you.jobs} jobs.</p>}
  </section>;
}

/** Each benchmark across the versions MOTH has had, as a small line (higher is better unless marked). */
export function BenchmarkTrend() {
  const { data: p } = useCloudProgress();
  const versions: Any[] = (p?.timeline ?? []).filter((v: Any) => v.benchmarks && Object.keys(v.benchmarks).length);
  if (versions.length < 2) return null;
  const keys = [...new Set(versions.flatMap((v) => Object.keys(v.benchmarks)))].filter((k) =>
    versions.filter((v) => Number.isFinite(v.benchmarks[k]?.value)).length >= 2).slice(0, 6);
  if (!keys.length) return null;
  return <section aria-label="Test scores" className="rounded-xl border border-border bg-surface p-3 text-xs">
    <h2 className="mb-2 flex items-center gap-1.5 font-medium"><TrendingUp className="size-3.5 text-accent" /> Test scores across versions</h2>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {keys.map((k) => {
        const pts = versions.map((v) => v.benchmarks[k]).filter((b) => b && Number.isFinite(b.value));
        const vals = pts.map((b) => Number(b.value)), higher = pts.at(-1)?.higher_is_better !== false;
        const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
        const path = vals.map((v, i) => `${i ? "L" : "M"}${(i / (vals.length - 1)) * 100},${28 - ((v - lo) / span) * 24}`).join(" ");
        const better = higher ? vals.at(-1)! >= vals[0] : vals.at(-1)! <= vals[0];
        const shown = (v: number) => higher && v <= 1 ? `${Math.round(v * 100)}%` : v.toFixed(2);
        return <div key={k} className="rounded-md border border-border p-2">
          <div className="flex items-baseline justify-between gap-1"><span className="truncate text-muted">{nice(k)}</span>
            <span className={cn("font-mono", better ? "text-success" : "text-warning")}>{shown(vals.at(-1)!)}</span></div>
          <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="mt-1 h-8 w-full" aria-hidden>
            <path d={path} fill="none" stroke="var(--color-accent)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" /></svg>
          <div className="text-[0.625rem] text-faint">{vals.length} versions · {higher ? "higher" : "lower"} is better</div>
        </div>;
      })}
    </div>
  </section>;
}

const short = (n: number) => n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n);

/** 2.5: the training data MOTH has (distinct tokens) against what a model of its size needs, and how many
 * times it has read it. Measured on MOTH Cloud; the bar fills as the library grows. */
export function DataMeter({ status }: { status?: Any | null }) {
  if (!status || !status.needed_tokens) return null;
  const have = Number(status.prepared_tokens || 0), need = Number(status.needed_tokens), pct = Math.min(1, have / need);
  const passes = typeof status.passes === "number" ? status.passes : null;
  return <section aria-label="Training data" className="rounded-xl border border-border bg-surface p-3 text-xs animate-slide-up">
    <h2 className="mb-2 flex items-center gap-1.5 font-medium"><Database className="size-3.5 text-accent" /> Training data
      <span className={cn("ml-auto rounded-full px-2 py-0.5 text-[0.625rem]", status.enough ? "bg-success/15 text-success" : "bg-warning/15 text-warning")}>
        {status.enough ? "enough for its size" : "growing"}</span></h2>
    <div className="flex items-baseline justify-between font-mono">
      <span className="text-fg"><AnimatedNumber value={have} /> <span className="text-faint">distinct tokens</span></span>
      <span className="text-muted">need ~{short(need)}</span>
    </div>
    <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct * 100)}>
      <div className={cn("h-full rounded-full transition-[width] duration-1000 ease-out", status.enough ? "bg-success" : "bg-accent", !status.enough && "shimmer")} style={{ width: `${Math.max(2, pct * 100)}%` }} />
    </div>
    <div className="mt-1.5 flex justify-between text-muted">
      <span>{status.sources ?? 0} sources · {short(Number(status.params || 0))} parameters</span>
      {passes != null && <span className={cn(passes > 2 ? "text-warning" : "text-muted")}>read {passes.toFixed(1)}× {passes > 2 ? "(more data coming)" : ""}</span>}
    </div>
  </section>;
}
