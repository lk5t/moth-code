/**
 * Settings → Intelligence: privacy choices for MOTH Cloud and the user's own knowledge.
 *
 * Every switch is off unless the user turns it on, except keeping cloud history and using knowledge.
 * Private knowledge is visible only to its owner; shared knowledge is added by the Owner.
 */
import { useEffect, useRef, useState } from "react";
import { BookOpen, Brain, FileUp, Search, Trash2 } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { timeAgo } from "@/lib/utils";

type Any = Record<string, any>;

function Row({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-6 border-b border-border py-3 last:border-0">
      <div><div className="text-[13px] text-fg">{title}</div>{desc && <div className="mt-0.5 text-xs text-muted">{desc}</div>}</div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}
export interface Consent { training_consent: boolean; external_ai: boolean; keep_history: boolean; use_knowledge: boolean }

export function IntelligenceSection() {
  const signedIn = useAccount((s) => !!s.token);
  const [status, setStatus] = useState<Any | null>(null);
  const [docs, setDocs] = useState<Any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const load = () => {
    serverApi<Any>("/v1/intelligence/status").then(setStatus).catch((e) => setErr(e.message));
    serverApi<Any>("/v1/knowledge").then((d) => setDocs(d.documents)).catch(() => {});
  };
  useEffect(() => { if (signedIn) load(); }, [signedIn]);
  if (!signedIn) return null;
  if (!status) {
    return err ? (
      <Card><CardContent className="text-xs text-muted">Intelligence settings need MOTH Cloud 0.5.1 or newer ({err}).</CardContent></Card>
    ) : null;
  }
  const c: Consent = status.consent;
  const set = async (k: keyof Consent, v: boolean) => {
    if (k === "keep_history" && !v && !confirm("Turning history off also deletes the conversations stored on MOTH Cloud. Continue?")) return;
    const r = await serverApi<Any>("/v1/me/consent", { method: "PUT", json: { [k]: v } });
    setStatus({ ...status, consent: r.consent });
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Brain className="size-4 text-accent" />Intelligence & privacy</CardTitle>
        <CardDescription>How MOTH Cloud may use your conversations. You can change these at any time.</CardDescription>
      </CardHeader>
      <CardContent>
        <Row title="Help improve MOTH" desc="Rated answers you send (and their prompts) may be used to train MOTH after the Owner reviews them. Off by default.">
          <Switch checked={c.training_consent} onCheckedChange={(v) => set("training_consent", v)} />
        </Row>
        <Row title="Use knowledge in answers" desc="MOTH searches shared knowledge and your documents and cites its sources.">
          <Switch checked={c.use_knowledge} onCheckedChange={(v) => set("use_knowledge", v)} />
        </Row>
        <Row title="Keep conversation history on MOTH Cloud" desc="Conversations in MOTH Code are always kept on this computer.">
          <Switch checked={c.keep_history} onCheckedChange={(v) => set("keep_history", v)} />
        </Row>
        {status.external_ai_enabled && (
          <Row title="Allow external AI models" desc="When the Owner has connected one, a request may be answered by an external provider. Your message is then sent to it.">
            <Switch checked={c.external_ai} onCheckedChange={(v) => set("external_ai", v)} />
          </Row>
        )}
        <ModelsList models={status.models} />
        <Knowledge docs={docs} reload={load} enabled={status.knowledge_enabled} />
      </CardContent>
    </Card>
  );
}

function ModelsList({ models }: { models: Any[] }) {
  return (
    <div className="border-b border-border py-3">
      <div className="mb-2 text-[13px] text-fg">Models MOTH Cloud can use</div>
      <div className="flex flex-col gap-1.5">
        {models.map((m) => (
          <div key={m.id} className="flex flex-wrap items-center gap-2 text-xs">
            <Badge variant={m.available ? "success" : "default"}>{m.available ? "available" : "unavailable"}</Badge>
            <span className="text-fg">{m.name}</span>
            {m.params && <span className="text-muted">{(m.params / 1e6).toFixed(1)}M parameters</span>}
            {m.latency_ms != null && <span className="text-muted">· {Math.round(m.latency_ms)} ms per answer</span>}
            {!m.available && <span className="text-muted">— {m.reason}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function Knowledge({ docs, reload, enabled }: { docs: Any[]; reload: () => void; enabled: boolean }) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Any[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const add = async (t: string, body: string, source = "") => {
    setMsg(null);
    try {
      const r = await serverApi<Any>("/v1/knowledge", { method: "POST", json: { title: t, text: body, source } });
      setMsg(r.duplicate ? "Already in your knowledge — nothing was added twice." :
        r.replaced_version ? `Updated to version ${r.document.version}.` : "Added.");
      setTitle(""); setText(""); reload();
    } catch (e) { setMsg((e as Error).message); }
  };
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    if (f.size > 2_000_000) return setMsg("That file is larger than 2 MB.");
    add(f.name, await f.text(), f.name);
  };
  const search = async () => setHits((await serverApi<Any>(`/v1/knowledge/search?q=${encodeURIComponent(q)}`)).results);
  return (
    <div className="flex flex-col gap-3 py-3">
      <div className="flex items-center gap-2 text-[13px] text-fg"><BookOpen className="size-4 text-accent" />My knowledge
        {!enabled && <Badge>turned off by the Owner</Badge>}</div>
      <div className="text-xs text-muted">Notes and documents MOTH may use to answer you. Only you can see them.</div>
      <div className="flex flex-col gap-2">
        <Input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Textarea placeholder="Paste text…" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="flex gap-2">
          <Button size="sm" disabled={!title.trim() || !text.trim()} onClick={() => add(title, text)}>Add</Button>
          <Button size="sm" variant="secondary" onClick={() => file.current?.click()}><FileUp />Add a text file</Button>
          <input ref={file} type="file" accept=".txt,.md,.csv,.json,.py,.ts,.js,.html" hidden onChange={(e) => onFile(e.target.files?.[0])} />
        </div>
        {msg && <div className="text-xs text-muted">{msg}</div>}
      </div>
      {docs.length > 0 && (
        <div className="flex flex-col gap-1">
          {docs.map((d) => (
            <div key={d.id} className="flex items-center justify-between gap-2 text-xs">
              <span className="truncate text-fg">{d.title} <span className="text-muted">v{d.version} · {timeAgo(d.updated_at)}</span>
                {d.shared && <Badge className="ml-2">shared</Badge>}</span>
              {!d.shared && (
                <Button size="sm" variant="ghost" aria-label={`Delete ${d.title}`}
                  onClick={() => serverApi(`/v1/knowledge/${d.id}`, { method: "DELETE" }).then(reload)}><Trash2 /></Button>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input placeholder="Try a search…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && q && search()} />
        <Button size="sm" variant="secondary" disabled={!q} onClick={search}><Search />Search</Button>
      </div>
      {hits && (hits.length ? hits.map((h) => (
        <div key={h.chunk_id} className="rounded-md bg-surface-2 p-2 text-xs"><div className="text-fg">{h.title}</div>
          <div className="line-clamp-3 text-muted">{h.text}</div></div>
      )) : <div className="text-xs text-muted">Nothing found.</div>)}
    </div>
  );
}
