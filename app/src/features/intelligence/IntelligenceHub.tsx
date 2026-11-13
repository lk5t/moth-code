import { useCloudProgress, refreshCloudProgress } from "@/lib/cloud-progress";
import { ErrorNotice } from "@/components/ErrorNotice";
import { OverviewSummary } from "./OverviewSummary";
import { EvolutionControl } from "./EvolutionControl";
import { EvolutionActivity } from "./EvolutionActivity";
import { AiSettings } from "./AiSettings";
import { GenesisSetup } from "./GenesisSetup";
import { modelLabel } from "@/lib/model-label";
import { useSavedSection } from "@/lib/use-saved-section";
import { useEffect, useState } from "react";
import { Brain, Database, History, SlidersHorizontal, ChevronDown, Orbit } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { useApp, appStore, aiTab, type AiTab } from "@/lib/app-state";
import { CloudActivity } from "@/features/activity/CloudActivity";
import { ActivityPanel } from "@/features/workspace/ActivityPanel";
import { formatNumber } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { EmptyState } from "@/components/ui/empty";
import { Card, CardContent } from "@/components/ui/card";
import { IntelligenceView } from "./IntelligenceView";
import { GrowthDiagnostics } from "./GrowthDiagnostics";
import { NetworkView } from "@/features/network/NetworkView";
import { NetworkTraining } from "@/features/training/NetworkTraining";
import { TrainingView } from "@/features/training/TrainingView";
import { ModelsView } from "@/features/models/ModelsView";
import { EvolutionPanel, CycleHistory, EvolutionVersions } from "@/features/owner/evolution";
import { IntelligencePanel } from "@/features/owner/intelligence";
import { WorkersPanel } from "@/features/owner/ops";
import { ModelOverview } from "@/features/owner/ModelOverview";
import { TrainingProgress } from "./TrainingProgress";
import { ModelTab } from "./ModelTab";

type Any = Record<string, any>;
const TABS: [AiTab, string, React.ReactNode][] = [
  ["evolution", "Evolution", <Brain />], ["model", "Model", <Orbit />], ["data", "Data", <Database />],
  ["history", "History", <History />], ["settings", "AI Settings", <SlidersHorizontal />],
];
/** Older views (Overview, Data, Activity, Training, Models) open the matching AI section. */
const VIEW_TAB: Record<string, AiTab> = { overview: "evolution", training: "evolution", data: "data", activity: "history", evolution: "history", models: "model" };

export function Advanced({ title, children }: { title: string; children: React.ReactNode }) {
  const [visited, setVisited] = useState(false);
  return <details className="rounded-xl border border-border bg-surface" onToggle={(e) => { if (e.currentTarget.open) setVisited(true); }}>
    <summary className="flex cursor-pointer items-center justify-between gap-3 p-4 text-sm font-medium text-fg">{title}<ChevronDown className="size-4 text-muted" /></summary>
    {visited && <div className="border-t border-border p-3 sm:p-4">{children}</div>}
  </details>;
}

export function IntelligenceHub() {
  const sessionToken = useAccount((s) => s.token);
  const signedIn = !!sessionToken;
  const owner = useAccount((s) => s.user?.role === "owner");
  const view = useApp((s) => s.view);
  const storedTab = useApp((s) => s.intelligenceTab);
  const network = view === "network";
  const tab: AiTab = VIEW_TAB[view] ?? aiTab(storedTab);
  const heading = network ? "Network" : "AI";
  const [dataSection, setDataSection] = useSavedSection<"local" | "cloud">("data", ["local", "cloud"], "local");
  const {data:p,error,updatedAt} = useCloudProgress();
  const [resources, setResources] = useState<Any | null>(null);
  useEffect(() => {
    setResources(null);
    if (!signedIn || !owner || network || tab !== "evolution") return;
    let alive = true;
    const load = () => {
      if(document.hidden) return;
      if (owner) serverApi<Any>("/v1/admin/evolution/resources").then((data) => { if (alive) setResources(data); }).catch(() => { if (alive) setResources(null); });
    };
    load(); const timer = setInterval(load, owner ? 5000 : 20000);
    return () => { alive = false; clearInterval(timer); };
  }, [sessionToken, owner, tab]);
  if (!signedIn) return <EmptyState title={network ? "Sign in to Network" : "Sign in to MOTH AI"}>MOTH's live training, compute, data and model history appear here.</EmptyState>;
  return <div className="h-full overflow-auto">
    <div className="mx-auto flex max-w-6xl flex-col gap-3 p-3 sm:p-4 lg:p-5">
      <header className="flex flex-wrap items-end justify-between gap-3"><div>
        <h1 className="text-2xl font-medium tracking-tight">{heading}</h1>
        <p className="mt-1 text-xs text-muted">{network ? "Workers, MOTH Cloud and your own computer's voluntary training." : "MOTH develops its native model by itself. Start or pause it, and follow exactly what it is doing."}</p>
      </div><span className="text-xs text-faint">{p?.current ? modelLabel(p.current) : p ? "No model yet" : error ? "Status unavailable" : "Loading status…"}</span></header>
      {error && <div className="space-y-2"><ErrorNotice error={`Live status unavailable: ${error}`} /><button className="text-xs text-accent" onClick={() => refreshCloudProgress()}>Retry connection</button></div>}
      {network ? <div className="flex flex-col gap-4">
        {owner && <NetworkTraining scope="network" />}<NetworkView embedded />{owner && <Advanced title="Worker assignments, permissions and resource limits"><WorkersPanel /></Advanced>}
      </div> :
      <Tabs value={tab} onValueChange={(value) => appStore.setState({view:"intelligence", intelligenceTab:value as AiTab})}>
        <TabsList aria-label="AI sections" className="mb-3 w-full justify-start">
          {TABS.map(([value, label, icon]) => <TabsTrigger key={value} value={value} className="[&_svg]:size-3.5">{icon}{label}</TabsTrigger>)}
        </TabsList>
        {tab === "evolution" && <TabsContent value="evolution" className="flex flex-col gap-4">
          <EvolutionControl progress={p} />
          {p?.current && <TrainingProgress progress={p} resources={resources} />}
          {p && <EvolutionActivity />}
          {p?.current ? <OverviewSummary progress={p} updatedAt={updatedAt} /> : owner && p && <Advanced title="Choose the model size and tokenizer yourself"><GenesisSetup /></Advanced>}
        </TabsContent>}
        {tab === "model" && <TabsContent value="model"><ModelTab progress={p} /></TabsContent>}
        {tab === "data" && <TabsContent value="data" className="flex flex-col gap-4">
          <Tabs value={dataSection} onValueChange={(value) => setDataSection(value as "local" | "cloud")}>
            <TabsList aria-label="Data sections"><TabsTrigger value="local">This computer</TabsTrigger><TabsTrigger value="cloud">Cloud library</TabsTrigger></TabsList>
            <TabsContent value="local"><TrainingView scope="data" /></TabsContent>
            <TabsContent value="cloud">
          <Card><CardContent className="flex flex-col gap-3 py-5 text-xs"><h2 className="text-sm font-medium">Approved training sources</h2>
            <p className="text-muted">Training and held-out evaluation data stay separate. Private projects and conversations require explicit consent.</p>
            {p?.datasets?.sources?.length ? p.datasets.sources.map((s: Any) => <div key={s.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2"><span>{s.name}</span><span className="text-muted">{s.license}{s.records != null && ` · ${formatNumber(s.records)} retained samples`}</span></div>) : <p className="text-faint">No prepared source measurements are available yet.</p>}
          </CardContent></Card>
          {owner && <IntelligencePanel sections={["library"]} />}
            </TabsContent>
          </Tabs>
        </TabsContent>}
        {tab === "history" && <TabsContent value="history" className="space-y-3">
          <IntelligenceView embedded focus="improvements" />
          <IntelligenceView embedded focus="history" />
          {owner && <><CycleHistory /><Advanced title="Experiments, weaknesses and evaluation details"><EvolutionPanel section="improvements" /><IntelligencePanel sections={["weak"]} /></Advanced>
            <Advanced title="Rollback to an accepted version"><EvolutionVersions reload={()=>{refreshCloudProgress();}} /></Advanced></>}
          <Advanced title="All activity"><CloudActivity /></Advanced>
          <Advanced title="Activity on this computer"><ActivityPanel all /></Advanced>
        </TabsContent>}
        {tab === "settings" && <TabsContent value="settings" className="space-y-3">
          {owner && <AiSettings />}
          <p className="pt-2 text-[10px] uppercase tracking-[0.22em] text-faint">Advanced</p>
          {owner ? <><GrowthDiagnostics /><EvolutionPanel section="advanced" /><Advanced title="Detailed model status"><ModelOverview /></Advanced><Advanced title="Local training and checkpoints"><TrainingView scope="training" /></Advanced><Advanced title="Model packages on this computer"><ModelsView /></Advanced><Advanced title="Feedback and shared knowledge"><IntelligencePanel sections={["feedback", "knowledge"]} /></Advanced></> : <p className="text-xs text-muted">Advanced training and deployment controls require the Owner.</p>}
        </TabsContent>}
      </Tabs>}
    </div>
  </div>;
}
