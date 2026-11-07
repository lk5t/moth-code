/** Chat: a clean, full-page conversation with MOTH (everyday questions, explanations, writing, code). */
import { useEffect, useState } from "react";
import { Info } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { get } from "@/lib/backend";
import { Badge } from "@/components/ui/badge";
import { appStore } from "@/lib/app-state";
import { ChatPanel } from "./ChatPanel";

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
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-4 py-2 text-xs">
      <span className="text-fg">{onDevice ? `${local.installed.display_name ?? "MOTH"} · on this computer` : m ? `${m.name} · MOTH Cloud` : "No model available"}</span>
      {m?.params && <span className="text-muted">{(m.params / 1e6).toFixed(1)}M parameters</span>}
      {caps.slice(0, 4).map(([k, v]) => <Badge key={k} title="measured on held-out benchmarks">{k} {pct(v)}</Badge>)}
      <div className="flex-1" />
      <button className="flex cursor-pointer items-center gap-1 text-faint hover:text-fg" onClick={() => appStore.setState({ view: "intelligence" })}>
        <Info className="size-3.5" />What MOTH can do
      </button>
    </div>
  );
}

export function ChatView() {
  return (
    <div className="flex h-full flex-col">
      <ModelBar />
      <div className="min-h-0 flex-1"><ChatPanel general /></div>
    </div>
  );
}
