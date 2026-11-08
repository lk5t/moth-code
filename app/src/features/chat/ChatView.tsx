/** Chat: a clean, full-page conversation with MOTH (everyday questions, explanations, writing, code). */
import { useEffect, useState } from "react";
import { Info, FolderOpen } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { get, put } from "@/lib/backend";
import { Badge } from "@/components/ui/badge";
import { appStore, useApp } from "@/lib/app-state";
import { Switch } from "@/components/ui/switch";
import { ChatPanel } from "./ChatPanel";
import { modelLabel } from "@/lib/model-label";

type Any = Record<string, any>;
const pct = (x: number) => `${Math.round(x * 100)}%`;

/** The active model, where it runs and what it was measured to do well — so expectations are honest. */
function ModelBar() {
  const signedIn = useAccount((s) => !!s.token);
  const [cloud, setCloud] = useState<Any | null>(null);
  const [local, setLocal] = useState<Any | null>(null);
  useEffect(() => {
    if (signedIn) serverApi<Any>("/v1/intelligence/status").then(setCloud).catch(() => setCloud(null));
    get<Any>("/api/ondevice").then(setLocal).catch(() => setLocal(null));
  }, [signedIn]);
  const onDevice = local?.installed && local?.answer_on_device;
  const m = (cloud?.models ?? []).find((x: Any) => x.available);
  const caps = Object.entries((m?.capabilities ?? {}) as Record<string, number>).sort((a, b) => b[1] - a[1]);
  return (
    <div className="flex min-h-8 shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-1 text-xs">
      <span className="min-w-0 truncate text-fg">{onDevice ? `${modelLabel(local.installed)} · on this computer` : m ? `${modelLabel(m)} · MOTH Cloud` : "No model available"}</span>
      {m?.params && <span className="text-muted">{(m.params / 1e6).toFixed(1)}M parameters</span>}
      {caps.slice(0, 2).map(([k, v]) => <Badge className="hidden lg:inline-flex" key={k} title="measured on held-out benchmarks">{k} {pct(v)}</Badge>)}
      <div className="flex-1" />
      <button className="flex cursor-pointer items-center gap-1 text-faint hover:text-fg" onClick={() => appStore.setState({ view: "intelligence" })}>
        <Info className="size-3.5" />What MOTH can do
      </button>
    </div>
  );
}

export function ChatView() {
  const project = useApp((s) => s.project);
  const [shareProjectId, setShareProjectId] = useState<number | null>(null);
  const share = !!project && shareProjectId === project.id;
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setShareProjectId(null); setError(null); }, [project?.id]);
  const attach = async (enabled: boolean) => {
    if (!project || !enabled) { setShareProjectId(null); return; }
    setError(null);
    try {
      const consent = await get<{ granted: boolean }>(`/api/projects/${project.id}/cloud-consent`);
      if (!consent.granted) {
        if (!confirm(`Allow relevant excerpts from ${project.name} to be sent to MOTH Cloud for chat? They are not added to training data. Conversation history stays on this computer.`)) return;
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
