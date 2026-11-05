import { useEffect, useRef, useState } from "react";
import { ArrowUp, Brain, Cpu, MessageSquarePlus, Square } from "lucide-react";
import { get, post } from "@/lib/backend";
import { useEvent } from "@/lib/events";
import { appStore, useApp } from "@/lib/app-state";
import { useResource } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { MothEmblem } from "@/components/MothEmblem";
import { cn } from "@/lib/utils";
import { Markdown } from "./Markdown";
import { agentMode } from "./agent-slot";

interface ChatMessage {
  id: number | string;
  role: "user" | "assistant" | "error";
  content: string;
  meta?: { model?: string; tokens?: number; tokens_per_sec?: number; stop_reason?: string } | null;
  streaming?: boolean;
}

interface Conversation {
  id: number;
  title: string;
}

interface ModelStatus {
  loaded: boolean;
  name?: string;
  device?: string;
}

export function ChatPanel() {
  const project = useApp((s) => s.project);
  const [mode, setMode] = useState<"chat" | "agent">("chat");
  const { data: status } = useResource<ModelStatus>("/api/model/status", ["model"]);
  const { data: conversations, reload: reloadConversations } = useResource<Conversation[]>(
    `/api/conversations${project ? `?project_id=${project.id}` : ""}`,
    [],
    [],
  );
  const [cid, setCid] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const AgentView = agentMode.component;

  useEffect(() => {
    setCid(null);
    setMessages([]);
  }, [project?.id]);

  useEffect(() => {
    if (cid === null) return;
    get<ChatMessage[]>(`/api/conversations/${cid}/messages`).then((m) => setMessages((cur) => (cur.some((x) => x.streaming) ? cur : m)));
  }, [cid]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEvent("chat", (e) => {
    if (e.conversation_id !== cid) return;
    setMessages((cur) => {
      const last = cur[cur.length - 1];
      const streaming = last?.streaming ? last : null;
      if (e.kind === "start") {
        return streaming ? cur : [...cur, { id: e.message_key, role: "assistant", content: "", streaming: true }];
      }
      if (!streaming) return cur;
      const rest = cur.slice(0, -1);
      if (e.kind === "token") return [...rest, { ...streaming, content: streaming.content + e.text }];
      if (e.kind === "replace") return [...rest, { ...streaming, content: e.text }];
      if (e.kind === "done") return [...rest, { ...streaming, content: e.text, meta: e.meta, streaming: false }];
      if (e.kind === "error") return [...rest, { id: streaming.id, role: "error", content: e.error }];
      return cur;
    });
    if (e.kind === "done" || e.kind === "error") setBusy(false);
  });

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [...m, { id: `u${Date.now()}`, role: "user", content: text }]);
    try {
      const r = await post<{ conversation_id: number }>("/api/chat", {
        message: text,
        conversation_id: cid,
        project_id: project?.id ?? null,
      });
      if (cid === null) {
        setCid(r.conversation_id);
        reloadConversations();
      }
    } catch (e) {
      setBusy(false);
      setMessages((m) => [...m, { id: `e${Date.now()}`, role: "error", content: String((e as Error).message ?? e) }]);
    }
  };

  const noModel = status && !status.loaded;

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border px-3">
        {agentMode.component && (
          <div className="flex rounded-md border border-border p-0.5">
            {(["chat", "agent"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={cn(
                  "cursor-pointer rounded px-2.5 py-0.5 text-[11px] font-medium capitalize text-muted transition-colors",
                  mode === m && "bg-accent text-white shadow-glow",
                )}
              >
                {m}
              </button>
            ))}
          </div>
        )}
        {mode === "chat" && (
          <Select
            className="h-7 min-w-0 max-w-56 flex-1 text-xs"
            value={cid ?? ""}
            onChange={(e) => {
              setMessages([]);
              setCid(e.target.value ? Number(e.target.value) : null);
            }}
          >
            <option value="">New conversation</option>
            {conversations?.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </Select>
        )}
        <div className="flex-1" />
        {mode === "chat" && (
          <Button variant="ghost" size="icon-sm" title="New conversation" onClick={() => { setCid(null); setMessages([]); }}>
            <MessageSquarePlus />
          </Button>
        )}
        <span className="flex items-center gap-1 text-[11px] text-faint">
          <Cpu className="size-3" />
          {status?.loaded ? `${status.name} · ${status.device}` : "no model"}
        </span>
      </div>

      {mode === "agent" && AgentView ? (
        <AgentView />
      ) : (
        <>
          <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-center animate-fade-in">
                <MothEmblem className="size-14" />
                <div className="text-sm font-medium">What should MOTH work on?</div>
                {noModel ? (
                  <div className="max-w-sm text-xs leading-relaxed text-muted">
                    No MOTH model is loaded. MOTH answers only with its own neural network, so a model must be
                    trained (or an exported one loaded) first.
                    <div className="mt-3 flex justify-center gap-2">
                      <Button size="sm" variant="outline" onClick={() => appStore.setState({ view: "training" })}><Brain /> Train a model</Button>
                      <Button size="sm" variant="secondary" onClick={() => appStore.setState({ view: "models" })}><Cpu /> Load a model</Button>
                    </div>
                  </div>
                ) : (
                  <div className="max-w-sm text-xs text-muted">
                    Responses come from {status?.name}. Early MOTH models are small and experimental — expect limited answers.
                  </div>
                )}
              </div>
            ) : (
              <div className="mx-auto flex max-w-3xl flex-col gap-4">
                {messages.map((m) => (
                  <div key={m.id} className={cn("flex animate-rise", m.role === "user" && "justify-end")}>
                    {m.role === "user" ? (
                      <div className="selectable max-w-[85%] whitespace-pre-wrap rounded-xl rounded-br-sm border border-border bg-surface-2 px-3.5 py-2 text-[13px]">{m.content}</div>
                    ) : m.role === "error" ? (
                      <div className="max-w-[90%] rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{m.content}</div>
                    ) : (
                      <div className="flex max-w-[95%] gap-2.5">
                        <MothEmblem className="mt-0.5 size-5 shrink-0" />
                        <div className="min-w-0 text-[13px] leading-relaxed">
                          {m.content ? <Markdown text={m.content} /> : <span className="text-muted">…</span>}
                          {m.streaming && <span className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-accent" />}
                          {m.meta && (
                            <div className="mt-1 text-[10.5px] text-faint">
                              {m.meta.model} · {m.meta.tokens} tokens · {m.meta.tokens_per_sec} tok/s
                              {m.meta.stop_reason === "max_tokens" && " · stopped at token limit"}
                              {m.meta.stop_reason === "cancelled" && " · cancelled"}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="shrink-0 p-3">
            <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-border bg-surface p-2 transition-shadow focus-within:border-accent/50 focus-within:shadow-glow">
              <Textarea
                rows={2}
                value={input}
                placeholder={noModel ? "Load a MOTH model to start chatting" : "Message MOTH  (Enter to send, Shift+Enter for a new line)"}
                disabled={!!noModel}
                className="max-h-48 min-h-10 border-0 bg-transparent focus:shadow-none"
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              {busy ? (
                <Button size="icon" variant="secondary" title="Stop" onClick={() => cid !== null && post(`/api/chat/${cid}/cancel`)}>
                  <Square className="text-accent" />
                </Button>
              ) : (
                <Button size="icon" disabled={!input.trim() || !!noModel} onClick={send} title="Send">
                  <ArrowUp />
                </Button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
