import { modelLabel } from "@/lib/model-label";
import { useEffect, useRef, useState } from "react";
import { Activity, Brain, Database, GitBranch, Network, ChevronDown } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { useApp, openIntelligence, type IntelligenceTab } from "@/lib/app-state";
import { cn, formatNumber } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { EmptyState } from "@/components/ui/empty";
import { Card, CardContent } from "@/components/ui/card";
import { MothEmblem } from "@/components/MothEmblem";
import { IntelligenceView } from "./IntelligenceView";
import { GenesisPanel } from "./GenesisPanel";
import { EvolutionView } from "@/features/evolution/EvolutionView";
import { NetworkView } from "@/features/network/NetworkView";
import { NetworkTraining, ParticipantSwitch } from "@/features/training/NetworkTraining";
import { TrainingView } from "@/features/training/TrainingView";
import { ModelsView } from "@/features/models/ModelsView";
import { EvolutionPanel } from "@/features/owner/evolution";
import { IntelligencePanel } from "@/features/owner/intelligence";
import { ModelsPanel, WorkersPanel } from "@/features/owner/ops";
import { ModelOverview } from "@/features/owner/ModelOverview";
import { TrainingProgress } from "./TrainingProgress";

type Any = Record<string, any>;
const TABS: [IntelligenceTab, string, React.ReactNode][] = [
  ["overview", "Overview", <Brain />], ["training", "Training", <Activity />],
  ["evolution", "Evolution", <GitBranch />], ["network", "Network", <Network />], ["data", "Data", <Database />],
];

export function Advanced({ title, children }: { title: string; children: React.ReactNode }) {
  const [visited, setVisited] = useState(false);
  return <details className="rounded-xl border border-border bg-surface" onToggle={(e) => { if (e.currentTarget.open) setVisited(true); }}>
    <summary className="flex cursor-pointer items-center justify-between gap-3 p-4 text-sm font-medium text-fg">{title}<ChevronDown className="size-4 text-muted" /></summary>
    {visited && <div className="border-t border-border p-3 sm:p-4">{children}</div>}
  </details>;
}

/** Each satellite is an actual decoder layer or labelled group of layers, not a simulated neuron. */
export function ModelActivity({ progress, resources }: { progress: Any | null; resources: Any | null }) {
  const model = progress?.current;
  const layers = Math.max(0, Number(model?.config?.n_layers ?? 0));
  const visible = Math.min(layers, 12);
  const [selected, setSelected] = useState(0);
  const [recent, setRecent] = useState(false);
  const previousStep = useRef<number | null>(null);
  const running = resources?.training?.running ?? [];
  const step = running.reduce((n: number, e: Any) => n + Number(e.progress?.step ?? 0), 0);
  useEffect(() => {
    const changed = previousStep.current !== null && step > previousStep.current;
    previousStep.current = step;
    setRecent(changed);
    if (!changed) return;
    const timer = setTimeout(() => setRecent(false), 5000);
    return () => clearTimeout(timer);
  }, [step]);
  const status = progress?.training?.paused ? "Paused by the Owner" : progress?.training?.cycle?.status?.replaceAll("_", " ") ?? "Waiting for an eligible cycle";
  const selectedStart = visible ? Math.floor(Math.min(selected, visible - 1) * layers / visible) + 1 : 0;
  const selectedEnd = visible ? Math.floor((Math.min(selected, visible - 1) + 1) * layers / visible) : 0;
  return <Card className="overflow-hidden">
    <CardContent className="grid gap-2 p-4 sm:grid-cols-[minmax(250px,1fr)_1fr] sm:p-6">
      <div className="relative flex min-w-0 items-center justify-center">
        <svg viewBox="0 0 380 270" className="mx-auto w-full max-w-md" role="group" aria-label="MOTH architecture and measured activity">
          <circle cx="190" cy="134" r="95" fill="none" className="stroke-border" strokeDasharray="3 7" />
          {Array.from({ length: visible }, (_, i) => {
            const a = i / visible * Math.PI * 2 - Math.PI / 2;
            const x = 190 + Math.cos(a) * 110, y = 134 + Math.sin(a) * 105;
            const from = Math.floor(i * layers / visible) + 1, to = Math.floor((i + 1) * layers / visible);
            return <g key={i}>
              <line x1="190" y1="134" x2={x} y2={y} className={cn("stroke-border", recent && "stroke-accent motion-safe:animate-pulse")} strokeWidth="1.5" />
              <g role="button" tabIndex={0} aria-label={`Inspect layer ${from}${to > from ? ` through ${to}` : ""}`}
                aria-pressed={selected === i} onClick={() => setSelected(i)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(i); } }} className="cursor-pointer outline-none focus:opacity-70">
                <circle cx={x} cy={y} r="18" className={cn("fill-surface-2 stroke-border transition-colors", i === selected && "stroke-accent")} strokeWidth="1.5" />
                <text x={x} y={y + 3} textAnchor="middle" className="fill-fg text-[10px]">{from === to ? from : `${from}–${to}`}</text>
              </g>
            </g>;
          })}
          <circle cx="190" cy="134" r="53" className="fill-bg stroke-border" />
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-1 pb-1">
          <MothEmblem className={cn("size-12", recent && "motion-safe:animate-pulse")} />
          <span className="text-[11px] font-medium">{model ? modelLabel(model) : "MOTH"}</span>
        </div>
      </div>
      <div className="flex min-w-0 flex-col justify-center gap-4">
        <div><p className="text-[11px] uppercase tracking-[0.18em] text-faint">One native lineage</p>
          <h2 className="mt-1 text-xl font-medium tracking-tight">{model ? modelLabel(model) : "Model status unavailable"}</h2>
          <p className="mt-1 text-xs text-muted">Revision {model?.revision ?? "not recorded"} · Step {model?.training?.step ?? model?.training?.steps ?? "not reported"}</p>
          <p className="mt-1 text-xs text-muted">{model?.params != null ? `${formatNumber(model.params)} actual parameters` : "Parameters have not been measured"}</p>
        </div>
        <div className="flex items-center gap-2 text-xs"><span className={cn("size-1.5 rounded-full", recent ? "bg-success" : "bg-faint")} />{recent ? "Training progress received" : status}</div>
        {model?.initialization === "random-untrained" && <p className="text-xs text-warning">Fresh, untrained baseline. Training and evaluations determine its capabilities.</p>}
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div className="min-w-0"><p className="text-faint">Tokenizer identity</p><p className="mt-1 truncate font-mono text-fg" title={model?.tokenizer_fingerprint}>{model?.tokenizer_fingerprint ?? "Not recorded"}</p></div>
          <div><p className="text-faint">Architecture</p><p className="mt-1 text-fg">{layers ? `${layers} layers · ${model.config.d_model} dimensions` : "Not available"}</p></div>
          <div><p className="text-faint">Connected workers</p><p className="mt-1 text-fg">{progress?.network ? `${progress.network.gpu_online} GPU · ${progress.network.cpu_online} CPU` : "Not available"}</p></div>
          {resources?.local && <>
            <div><p className="text-faint">Server CPU</p><p className="mt-1 text-fg">{resources.local.cpu_count} cores · {resources.local.cpu_percent != null ? `${resources.local.cpu_percent.toFixed(0)}% in use` : "usage not measured"}</p></div>
            <div><p className="text-faint">Free memory</p><p className="mt-1 text-fg">{resources.local.memory?.available != null ? `${(resources.local.memory.available / 1024 ** 3).toFixed(1)} GB` : "Not measured"}</p></div>
          </>}
        </div>
        {model?.milestone?.reasons?.length > 0 && <div className="text-xs text-muted"><p>Next public milestone requirements</p><ul className="mt-1 list-inside list-disc">{model.milestone.reasons.slice(0, 4).map((reason: string) => <li key={reason}>{reason}</li>)}</ul></div>}
        {visible > 0 && <p className="text-xs text-muted">Layer {selectedStart}{selectedEnd > selectedStart && `–${selectedEnd}`} selected · {model.config.n_heads} attention heads per layer. A pulse means reported training steps increased.</p>}
        {progress?.training?.cycle?.waiting_reason && <p role="status" className="rounded-lg border border-border bg-bg p-3 text-xs text-muted">{progress.training.cycle.waiting_reason}</p>}
      </div>
    </CardContent>
  </Card>;
}

export function IntelligenceHub() {
  const signedIn = useAccount((s) => !!s.token);
  const owner = useAccount((s) => s.user?.role === "owner");
  const view = useApp((s) => s.view);
  const storedTab = useApp((s) => s.intelligenceTab);
  const tab: IntelligenceTab = view === "evolution" ? "evolution" : view === "network" ? "network" : view === "training" || view === "models" ? "training" : storedTab ?? "overview";
  const [visited, setVisited] = useState<Set<string>>(() => new Set([tab]));
  const [p, setP] = useState<Any | null>(null);
  const [resources, setResources] = useState<Any | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setVisited((s) => new Set([...s, tab])); }, [tab]);
  useEffect(() => {
    if (!signedIn) return;
    let alive = true;
    const load = () => {
      serverApi<Any>("/v1/intelligence/progress").then((data) => { if (alive) { setP(data); setError(null); } }).catch((e) => { if (alive) { setP(null); setResources(null); setError("Live status unavailable: " + e.message); } });
      if (owner) serverApi<Any>("/v1/admin/evolution/resources").then((data) => { if (alive) setResources(data); }).catch(() => { if (alive) setResources(null); });
    };
    load(); const timer = setInterval(load, owner ? 5000 : 20000);
    return () => { alive = false; clearInterval(timer); };
  }, [signedIn, owner]);
  if (!signedIn) return <EmptyState title="Sign in to Intelligence">MOTH's live training, compute, data and model history appear here.</EmptyState>;
  return <div className="h-full overflow-auto">
    <div className="mx-auto flex max-w-6xl flex-col gap-3 p-3 sm:p-4 lg:p-5">
      <header className="flex flex-wrap items-end justify-between gap-3"><div>
        <p className="text-[10px] uppercase tracking-[0.22em] text-accent">MOTH / Intelligence</p>
        <h1 className="mt-1 text-2xl font-medium tracking-tight">Intelligence</h1>
        <p className="mt-1 text-xs text-muted">One place for the native model, its training, its computers and the data it learns from.</p>
      </div><span className="text-xs text-faint">{p?.current ? modelLabel(p.current) : "Model status unavailable"}</span></header>
      {error && <p role="alert" className="rounded-lg border border-border p-3 text-xs text-danger">{error}</p>}
      <Tabs value={tab} onValueChange={(value) => openIntelligence(value as IntelligenceTab)}>
        <TabsList aria-label="Intelligence sections" className="mb-3 w-full justify-start">
          {TABS.map(([value, label, icon]) => <TabsTrigger key={value} value={value} className="[&_svg]:size-3.5">{icon}{label}</TabsTrigger>)}
        </TabsList>
        {(visited.has("overview") || tab === "overview") && <TabsContent forceMount hidden={tab !== "overview"} value="overview" className="flex flex-col gap-5 data-[state=inactive]:hidden">
          <ModelActivity progress={p} resources={resources} /><IntelligenceView embedded />
        </TabsContent>}
        {(visited.has("training") || tab === "training") && <TabsContent forceMount hidden={tab !== "training"} value="training" className="flex flex-col gap-4 data-[state=inactive]:hidden">
          <TrainingProgress progress={p} resources={resources} />
          {owner ? <><NetworkTraining /><GenesisPanel /><Advanced title="Baseline, selected workers and detailed model status"><ModelOverview /></Advanced><Advanced title="Local training and checkpoints"><TrainingView /></Advanced><Advanced title="Model packages on this computer"><ModelsView /></Advanced><Advanced title="Cloud model registry and evaluation data"><ModelsPanel /></Advanced></> : <><EvolutionView /><ParticipantSwitch /></>}
        </TabsContent>}
        {(visited.has("evolution") || tab === "evolution") && <TabsContent forceMount hidden={tab !== "evolution"} value="evolution" className="flex flex-col gap-4 data-[state=inactive]:hidden">
          <EvolutionView />{owner && <Advanced title="Research, growth approvals, evaluations and rollback"><EvolutionPanel /></Advanced>}
        </TabsContent>}
        {(visited.has("network") || tab === "network") && <TabsContent forceMount hidden={tab !== "network"} value="network" className="flex flex-col gap-4 data-[state=inactive]:hidden">
          <NetworkView />{owner && <Advanced title="Worker assignments, permissions and resource limits"><WorkersPanel /></Advanced>}
        </TabsContent>}
        {(visited.has("data") || tab === "data") && <TabsContent forceMount hidden={tab !== "data"} value="data" className="flex flex-col gap-4 data-[state=inactive]:hidden">
          <Card><CardContent className="flex flex-col gap-3 py-5 text-xs"><h2 className="text-sm font-medium">Approved training sources</h2>
            <p className="text-muted">Training and held-out evaluation data stay separate. Private projects and conversations require explicit consent.</p>
            {p?.datasets?.sources?.length ? p.datasets.sources.map((s: Any) => <div key={s.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2"><span>{s.name}</span><span className="text-muted">{s.license}{s.records != null && ` · ${formatNumber(s.records)} retained samples`}</span></div>) : <p className="text-faint">No prepared source measurements are available yet.</p>}
          </CardContent></Card>
          {owner && <IntelligencePanel />}
        </TabsContent>}
      </Tabs>
    </div>
  </div>;
}
