/** Chat: a clean, full-page conversation with MOTH (everyday questions, explanations, writing, code). */
import { useAccount } from "@/lib/account";
import { useEffect, useState } from "react";
import { Info, FolderOpen } from "lucide-react";
import { useCloudProgress } from "@/lib/cloud-progress";
import { useResource } from "@/lib/hooks";
import { get, put } from "@/lib/backend";
import { openIntelligence, useApp } from "@/lib/app-state";
import { Switch } from "@/components/ui/switch";
import { ChatPanel } from "./ChatPanel";
import { modelLabel } from "@/lib/model-label";

type Any = Record<string, any>;

/** The active model, where it runs and what it was measured to do well — so expectations are honest. */
export function ModelBar() {
  const {data:cloud}=useCloudProgress();
  const {data:local}=useResource<Any|null>("/api/ondevice",["ondevice","settings"],null);
  const onDevice=local?.installed && local?.answer_on_device;
  const m=cloud?.current;
  return (
    <div className="flex min-w-0 max-w-[45%] items-center gap-2 text-[11px]">
      <span className="min-w-0 truncate text-fg">{onDevice ? `${modelLabel(local.installed)} · on this computer` : m ? `${modelLabel(m)} · MOTH Cloud` : "No model available"}</span>


      <button aria-label="Model details" title="View active model details" className="flex shrink-0 cursor-pointer items-center gap-1 text-faint hover:text-fg" onClick={() => openIntelligence("overview")}>
        <Info className="size-3.5" />
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
