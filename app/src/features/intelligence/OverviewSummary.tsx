import { modelLabel } from "@/lib/model-label";
import { navigate } from "@/lib/navigation";
import { LivingMoth, IntelligencePulse } from "@/components/LivingMoth";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { GenesisSetup } from "./GenesisSetup";

type Any=Record<string,any>;
export function OverviewSummary({progress,updatedAt}:{progress:Any|null;updatedAt:number|null}) {
  const current=progress?.current, serving=progress?.serving;
  if(progress && !current) return <GenesisSetup />;
  const measured=progress?.improvement;
  return <Card><CardContent className="space-y-4 p-4">
    <div className="flex flex-wrap items-center gap-3"><LivingMoth className="size-10"/><div>
      <p className="text-[11px] text-muted">Active native model</p><h2 className="text-xl font-medium">{current ? modelLabel(current) : "No native model available"}</h2>
      {current && <p className="text-xs text-muted">Revision {current.revision ?? "not recorded"} · {typeof current.params === "number" ? current.params.toLocaleString()+" actual parameters" : "Parameter measurement unavailable"}</p>}
    </div><div className="ml-auto"><IntelligencePulse /></div></div>
    <div className="grid gap-3 text-xs sm:grid-cols-3">
      <div><p className="text-faint">Service</p><p>{serving ? serving.accepting_requests ? "Ready to answer" : serving.reason : current ? "Model loaded; service status not reported" : "Waiting for a native model"}</p></div>
      <div><p className="text-faint">Training</p><p>{progress?.training ? progress.training.paused ? "Paused" : progress.training.cycle?.status?.replaceAll("_"," ") ?? "No active experiment" : "Status unavailable"}</p></div>
      <div><p className="text-faint">Connected workers</p><p>{progress?.network?.workers_online ?? "Not reported"}</p></div>
    </div>
    <div className="text-xs"><p className="text-faint">Latest verified improvement</p><p>{measured?.verified && Number.isFinite(measured.primary_improvement)
      ? `${(measured.primary_improvement*100).toFixed(2)}% on the experiment’s held-out objective; required checks passed.`
      : "No verified improvement measurement recorded for the active model."}</p></div>
    {progress?.rollout?.filter((r:Any) => r.role === "canary").map((r:Any) => <p key={r.version} className="text-xs text-warning">Candidate release {r.version} is serving {r.percent}% of canary traffic. It is separate from the active stable model.</p>)}
    {progress?.training?.cycle?.waiting_reason && <p role="status" className="text-xs text-warning">{progress.training.cycle.waiting_reason}</p>}
    <div className="flex flex-wrap gap-2"><Button size="sm" onClick={() => navigate("chat")}>Open Chat</Button><Button size="sm" variant="secondary" onClick={() => navigate("workspace")}>Open Projects</Button>
      <span className="ml-auto self-center text-[10px] text-faint">{updatedAt ? `Status received ${new Date(updatedAt).toLocaleTimeString()}` : "Live status unavailable"}</span></div>
  </CardContent></Card>;
}
