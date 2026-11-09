/** Chat: a clean, full-page conversation with MOTH (everyday questions, explanations, writing, code). */
import { useAccount } from "@/lib/account";
import { useEffect, useState } from "react";
import { Info, FolderOpen } from "lucide-react";
import { useCloudProgress } from "@/lib/cloud-progress";
import { useResource } from "@/lib/hooks";
import { get, put } from "@/lib/backend";
import { Badge } from "@/components/ui/badge";
import { openIntelligence, useApp } from "@/lib/app-state";
import { Switch } from "@/components/ui/switch";
import { ChatPanel } from "./ChatPanel";
import { modelLabel } from "@/lib/model-label";

type Any = Record<string, any>;
const pct = (x: number) => `${Math.round(x * 100)}%`;

/** The active model, where it runs and what it was measured to do well — so expectations are honest. */
function ModelBar() {
  const {data:cloud}=useCloudProgress();
  const {data:local}=useResource<Any|null>("/api/ondevice",["ondevice","settings"],null);
  const onDevice=local?.installed && local?.answer_on_device;
  const m=cloud?.current;
  const caps=Object.entries((m?.benchmarks ?? {}) as Record<string,Any>).filter(([,value])=>value.higher_is_better && Number.isFinite(value.value)).sort((a,b)=>b[1].value-a[1].value);
  return (
    <div className="flex min-h-8 shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-1 text-xs">
      <span className="min-w-0 truncate text-fg">{onDevice ? `${modelLabel(local.installed)} · on this computer` : m ? `${modelLabel(m)} · MOTH Cloud` : "No model available"}</span>
      {m?.params && <span className="text-muted">{(m.params / 1e6).toFixed(1)}M parameters</span>}
      {caps.slice(0, 2).map(([k, v]) => <Badge className="hidden lg:inline-flex" key={k} title="measured on held-out benchmarks">{k} {pct(v.value)}</Badge>)}
      <div className="flex-1" />
      <button className="flex cursor-pointer items-center gap-1 text-faint hover:text-fg" onClick={() => openIntelligence("overview")}>
        <Info className="size-3.5" />Model details
      </button>
    </div>
  );
}

export function ChatView() {
  const project = useApp((s) => s.project);
  const accountToken = useAccount(s => s.token);
  const accountServer = useAccount(s => s.serverUrl);
  const [shareProjectId, setShareProjectId] = useState<number | null>(null);
  const share = !!project && shareProjectId === project.id;
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setShareProjectId(null); setError(null); }, [project?.id, accountToken, accountServer]);
  const attach = async (enabled: boolean) => {
    if (!project || !enabled) { setShareProjectId(null); return; }
    setError(null);
    try {
      const consent = await get<{ granted: boolean }>(`/api/projects/${project.id}/cloud-consent`);
      if (!consent.granted) {
        if (!confirm(`Allow relevant excerpts from ${project.name} to be sent to MOTH Cloud at ${accountServer} for chat? They are not added to training data. Conversation history stays on this computer.`)) return;
        await put(`/api/projects/${project.id}/cloud-consent`, { granted: true });
      }
      setShareProjectId(project.id);
    } catch (e) { setError((e as Error).message); }
  };
  return (
    <div className="flex h-full flex-col">
      <ModelBar />
      {project && <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-1 text-xs text-muted">
        <FolderOpen className="size-3.5" /><span className="min-w-0 truncate">Context from {project.name}</span>
        <Switch aria-label="Attach approved project context" checked={share} onCheckedChange={attach} />
        <span className="text-faint">{share ? "Approved excerpts · not used for training" : "Not attached"}</span>
        {error && <span role="alert" className="text-danger">{error}</span>}
      </div>}
      <div className="min-h-0 flex-1"><ChatPanel general contextProjectId={share ? project?.id : null} /></div>
    </div>
  );
}
