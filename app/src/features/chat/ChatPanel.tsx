import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { MothEvent } from "@/lib/events";
import { ArrowUp, Cloud, LogIn, MessageSquarePlus, RefreshCw, Square } from "lucide-react";
import { useCloudStatus } from "@/lib/cloud";
import { openAccountDialog } from "@/features/account/AccountDialog";
import { get, post } from "@/lib/backend";
import { useEvent } from "@/lib/events";
import { appStore, useApp } from "@/lib/app-state";
import { useResource } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { MothEmblem } from "@/components/MothEmblem";
import { cn } from "@/lib/utils";
import { Markdown, CopyText } from "./Markdown";
import { ErrorNotice } from "@/components/ErrorNotice";
import { AgentPanel } from "@/features/agent/AgentPanel";
import { AnswerFooter, type AnswerMeta } from "@/features/intelligence/AnswerFooter";
import { useCloudProgress } from "@/lib/cloud-progress";
import { modelLabel } from "@/lib/model-label";

interface ChatMessage {
  id: number | string;
  role: "user" | "assistant" | "error";
  content: string;
  meta?: ({ model?: string; tokens?: number; tokens_per_sec?: number; stop_reason?: string } & AnswerMeta) | null;
  streaming?: boolean;
}

interface Conversation {
  id: number;
  title: string;
}


/** ``general``: the full-page Chat (everyday questions, writing, explanations) — not tied to a project. */
export function ChatPanel({ general = false, contextProjectId = null }: { general?: boolean; contextProjectId?: number | null } = {}) {
  const workspaceProject = useApp((s) => s.project);
  const project = general ? null : workspaceProject;
  const [mode, setMode] = useState<"chat" | "agent">("chat");
  const { status: cloud, reload: reloadCloud } = useCloudStatus();
  const {data: liveModel} = useCloudProgress();
  const [search, setSearch] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  useEffect(()=>{const timer=setTimeout(()=>setSearchQuery(search),200);return()=>clearTimeout(timer);},[search]);
  const { data: conversations, reload: reloadConversations } = useResource<Conversation[]>(
    `/api/conversations${project ? `?project_id=${project.id}` : "?scope=general"}&q=${encodeURIComponent(searchQuery)}`,
    [],
    [],
  );
  const [cid, setCid] = useState<number | null>(null);
  const chatRequest=useApp(s=>s.chatRequest);
  const [hasOlder, setHasOlder] = useState(false);
  const followTail = useRef(true);
  const conversationLoad = useRef(0);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  useEffect(()=>{
    if(!general)return;
    const title=conversations?.find(c=>c.id===cid)?.title??(chatRequest?.conversationId===cid&&chatRequest.title?chatRequest.title:cid===null?'New conversation':'Current conversation');
    appStore.setState({chatSession:{conversationId:cid,title,busy}});
  },[general,cid,busy,conversations,chatRequest?.title]);
  useEffect(()=>{
    if(!general||!chatRequest||busy)return;
    if(chatRequest.conversationId===cid && cid!==null)return;
    if(input.trim()&&!confirm('Change conversation and discard the unsent message? Cancel to keep your draft.'))return;
    setCid(chatRequest.conversationId);setMessages([]);setInput('');
  },[general,chatRequest?.sequence]);
  useLayoutEffect(() => {
    const field = composer.current;
    if (!field) return;
    const resize = () => {
      field.style.height = "auto";
      field.style.height = `${Math.min(field.scrollHeight, 160)}px`;
    };
    resize();
    // Both workspaces stay mounted; resize when this one becomes visible or its panel changes width.
    let width = field.clientWidth;
    const observer = new ResizeObserver(() => {
      if (field.clientWidth !== width) { width = field.clientWidth; resize(); }
    });
    observer.observe(field);
    return () => observer.disconnect();
  }, [input, mode]);

  useEffect(() => {
    if (cidRef.current !== null) void post(`/api/chat/${cidRef.current}/cancel`).catch(() => {});
    setCid(null);
    setBusy(false);
    setHasOlder(false);
    setMessages([]);
  }, [project?.id]);

  useEffect(() => {
    const load=++conversationLoad.current;
    if (cid === null || skipFetch.current === cid) return;
    setHasOlder(false);followTail.current=true;
    get<ChatMessage[]>(`/api/conversations/${cid}/messages?limit=100`).then((history) => {
      if(load !== conversationLoad.current) return;
      setMessages((current) => current.some((x)=>x.streaming) ? current : history);setHasOlder(history.length === 100);
    }).catch((error) => {if(load === conversationLoad.current) setMessages([{id:"history-error",role:"error",content:error.message}]);});
    return () => {conversationLoad.current++;};
  }, [cid]);

  useEffect(() => {
    if(followTail.current) scroller.current?.scrollTo({top:scroller.current.scrollHeight,behavior:"auto"});
  }, [messages]);
  const loadOlder = async () => {
    const first=messages.find((message)=>typeof message.id === "number");
    const node=scroller.current, conversation=cid;
    if(!first || !node || cid === null) return;
    const oldHeight=node.scrollHeight;
    try {
      const older=await get<ChatMessage[]>(`/api/conversations/${cid}/messages?limit=100&before_id=${first.id}`);
      if(cidRef.current !== conversation) return;
      followTail.current=false;setMessages((current)=>[...older,...current]);setHasOlder(older.length === 100);
      requestAnimationFrame(()=>{node.scrollTop+=node.scrollHeight-oldHeight;});
    } catch(error) {setMessages((current)=>[...current,{id:`older-${Date.now()}`,role:"error",content:(error as Error).message}]);}
  };

  // Refs avoid a race: for a new conversation, streaming events can arrive
  // before POST /api/chat returns the conversation id.
  const cidRef = useRef<number | null>(null);
  const sendingNew = useRef(false);
  const early = useRef<MothEvent[]>([]);
  const skipFetch = useRef<number | null>(null);
  cidRef.current = cid;

  const apply = (e: MothEvent) => {
    setMessages((cur) => {
      const last = cur[cur.length - 1];
      const streaming = last?.streaming ? last : null;
      if (e.kind === "start") {
        return streaming ? cur : [...cur, { id: e.message_key, role: "assistant", content: "", streaming: true }];
      }
      if (e.kind === "done" && !streaming) {
        return [...cur, { id: e.message_key, role: "assistant", content: e.text, meta: e.meta }];
      }
      if (e.kind === "error" && !streaming) return [...cur, { id: e.message_key, role: "error", content: e.error }];
      if (!streaming) return cur;
      const rest = cur.slice(0, -1);
      if (e.kind === "token") return [...rest, { ...streaming, content: streaming.content + e.text }];
      if (e.kind === "replace") return [...rest, { ...streaming, content: e.text }];
      if (e.kind === "done") return [...rest, { ...streaming, id:e.message_id ?? streaming.id, content: e.text, meta: e.meta, streaming: false }];
      if (e.kind === "error") return [...rest, { id: streaming.id, role: "error", content: e.error }];
      return cur;
    });
    if (e.kind === "done" || e.kind === "error") setBusy(false);
    if(e.kind === "done") reloadConversations();
  };

  useEvent("chat", (e) => {
    if (cidRef.current === null && sendingNew.current) {
      early.current.push(e);
      return;
    }
    if (e.conversation_id === cidRef.current) apply(e);
  });

  const send = async (regenerate = false) => {
    const text = regenerate ? [...messages].reverse().find((m)=>m.role === "user")?.content ?? "" : input.trim();
    if (!text || busy) return;
    if(!regenerate) {setInput("");setMessages((m) => [...m, { id: `u${Date.now()}`, role: "user", content: text }]);}
    followTail.current=true;setBusy(true);
    const isNew = cid === null;
    if (isNew) {
      sendingNew.current = true;
      early.current = [];
    }
    try {
      const r = await post<{ conversation_id: number }>("/api/chat", {
        message: text, regenerate,
        conversation_id: cid,
        project_id: project?.id ?? null,
        context_project_id: contextProjectId,
      });
      if (isNew) {
        skipFetch.current = r.conversation_id;
        cidRef.current = r.conversation_id;
        setCid(r.conversation_id);
        sendingNew.current = false;
        early.current.filter((e) => e.conversation_id === r.conversation_id).forEach(apply);
        early.current = [];
        reloadConversations();
      }
    } catch (e) {
      sendingNew.current = false;
      setBusy(false);
      if(!regenerate) setInput(text);
      setMessages((m) => [...m, { id: `e${Date.now()}`, role: "error", content: String((e as Error).message ?? e) }]);
    }
  };

  const { data: onDevice } = useResource<{ installed: Record<string,any> | null; answer_on_device: boolean } | null>("/api/ondevice", ["ondevice"], null);
  const previousAnswers = useMemo(() => {
    const previous=new Set<ChatMessage['id']>();let newer=false;
    for(let i=messages.length-1;i>=0;i--) {const message=messages[i];if(message.role === "user") newer=false;
      else if(message.role === "assistant") {if(newer) previous.add(message.id);newer=true;}}
    return previous;
  },[messages]);
  const lastAssistant = messages.reduce((index,message,i)=>message.role === "assistant" ? i : index,-1);
  const local = !!onDevice?.installed;
  const signedOut = cloud && !local ? !cloud.signed_in : false;
  const noModel = !local && (typeof liveModel?.serving?.accepting_requests === "boolean" && !cloud?.available
    ? !liveModel.serving.accepting_requests : !!cloud && (!cloud.signed_in || !cloud.available));
  const usingLocal = local && (onDevice?.answer_on_device || !cloud?.available);
  const currentLabel = usingLocal ? `${modelLabel(onDevice?.installed)} · this computer`
    : liveModel ? liveModel.current ? `${modelLabel(liveModel.current)} · Cloud` : "No native model deployed"
    : cloud?.available ? modelLabel(cloud.model) : cloud?.signed_in ? "Cloud unavailable" : "signed out";

  return (
    <div className="flex h-full flex-col">
      {!general && <div className="flex h-8 shrink-0 items-center gap-2 border-b border-border px-2">
        {!general && (
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
            aria-label="Conversation" disabled={busy} title={busy ? "Stop or wait for the current reply before changing conversations" : "Conversation history"}
            value={cid ?? ""}
            onChange={(e) => {
              setMessages([]);
              setCid(e.target.value ? Number(e.target.value) : null);
            }}
          >
            <option value="">New conversation</option>
            {cid !== null && !conversations?.some((item)=>item.id === cid) && <option value={cid}>Current conversation</option>}
            {conversations?.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </Select>
        )}
        {mode === "chat" && <input aria-label="Search conversations" placeholder="Search history" value={search} onChange={(event)=>setSearch(event.target.value)} className="h-7 w-28 min-w-0 rounded border border-border bg-bg px-2 text-xs sm:w-40" />}
        <div className="flex-1" />
        {mode === "chat" && (
          <Button variant="ghost" size="icon-sm" title={busy ? "Stop or wait for the current reply" : "New conversation"} disabled={busy} aria-label="New conversation" onClick={() => { setCid(null); setMessages([]); }}>
            <MessageSquarePlus />
          </Button>
        )}
        {!general && <span className="flex min-w-0 items-center gap-1 text-[11px] text-faint" title={cloud?.model?.name}>
          <Cloud className="size-3" />
          <span className="truncate">{currentLabel}</span>
        </span>}
      </div>}

      {mode === "agent" ? (
        <AgentPanel />
      ) : (
        <>
          <div ref={scroller} onScroll={(event)=>{const node=event.currentTarget;followTail.current=node.scrollHeight-node.scrollTop-node.clientHeight < 80;}} className="min-h-0 flex-1 overflow-y-auto px-3 py-3 sm:px-4">
            {hasOlder && <Button size="sm" variant="ghost" onClick={loadOlder}>Load older messages</Button>}
            {messages.length === 0 ? (
              <div className="mx-auto flex w-full max-w-4xl flex-col gap-3 pt-5 text-left animate-fade-in sm:pt-8">
                <div className="flex items-center gap-2"><MothEmblem motion="idle" className="size-10 shrink-0" />
                  <div className="text-sm font-medium">{general ? "What would you like to explore?" : "What should MOTH work on?"}</div></div>
                {signedOut ? (
                  <div className="max-w-sm text-xs leading-relaxed text-muted">
                    MOTH runs in MOTH Cloud. Sign in to chat with the official MOTH model and use the coding agent.
                    <div className="mt-3 flex justify-center"><Button size="sm" onClick={() => openAccountDialog("login")}><LogIn /> Sign in</Button></div>
                  </div>
                ) : noModel ? (
                  <div className="max-w-sm text-xs leading-relaxed text-muted">
                    {cloud?.reachable === false
                      ? "Can't reach MOTH Cloud right now. Your editor, terminal and Git keep working; MOTH will be back when the connection returns."
                      : cloud?.error ?? "MOTH Cloud inference is not available yet."}
                    <div className="mt-3 flex justify-center"><Button size="sm" variant="secondary" onClick={() => reloadCloud()}><RefreshCw /> Retry</Button></div>
                  </div>
                ) : (
                  <div className="max-w-sm text-xs text-muted">
                    {currentLabel}{liveModel?.current?.initialization === "random-untrained" && !usingLocal ? " · untrained baseline; capabilities have not been established." : ". Measured model details are available in Overview."}
                  </div>
                )}
                {!noModel && <div className="flex flex-wrap gap-1.5">
                  {(general ? ["Explain a concept", "Help me plan", "Write something"] : ["Explain this project", "Help debug a problem", "Review a change"]).map((prompt) =>
                    <button key={prompt} className="cursor-pointer rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-muted transition-colors hover:border-accent/50 hover:text-fg"
                      onClick={() => { setInput(prompt + ": "); composer.current?.focus(); }}>{prompt}</button>)}
                </div>}
              </div>
            ) : (
              <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
                {messages.map((m,index) => {
                  const content = <div key={m.id} className={cn("flex animate-rise", m.role === "user" && "justify-end")}>
                    {m.role === "user" ? (
                      <div className="selectable max-w-[85%] whitespace-pre-wrap rounded-xl rounded-br-sm border border-border bg-surface-2 px-3.5 py-2 text-[13px]">{m.content}</div>
                    ) : m.role === "error" ? (
                      <ErrorNotice error={m.content} />
                    ) : (
                      <div className="flex max-w-[95%] gap-2.5">
                        <MothEmblem motion={m.streaming ? "generating" : "none"} className="mt-0.5 size-5 shrink-0" />
                        <div className="min-w-0 text-[13px] leading-relaxed">
                          {m.content ? <Markdown text={m.content} /> : <span className="text-muted">…</span>}
                          {m.streaming && <span className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-accent" />}
                          {m.meta && (
                            <div className="mt-1 text-[10.5px] text-faint">
                              {modelLabel(m.meta.model)} · {m.meta.tokens} tokens · {m.meta.tokens_per_sec} tok/s
                              {m.meta.stop_reason === "max_tokens" && " · stopped at token limit"}
                              {m.meta.stop_reason === "cancelled" && " · cancelled"}
                            </div>
                          )}
                          {!m.streaming && <div className="mt-2 flex flex-wrap gap-2"><CopyText text={m.content} label="Copy answer" />
                            {index === lastAssistant && !messages.slice(index+1).some((message)=>message.role === "user") && cid !== null &&
                              <Button size="sm" variant="ghost" disabled={busy} onClick={()=>send(true)}>Regenerate</Button>}
                          </div>}
                          {m.meta && !m.streaming && <AnswerFooter meta={m.meta} answer={m.content} />}
                        </div>
                      </div>
                    )}
                  </div>;
                  return previousAnswers.has(m.id) ? <details key={m.id} className="rounded border border-border p-2 text-xs text-muted"><summary className="cursor-pointer">Previous answer · retained in history</summary>{content}</details> : content;
                })}
              </div>
            )}
          </div>
          <div className="mx-auto w-full max-w-4xl shrink-0 px-3 pb-3 pt-1 sm:px-4">
            <div className="flex w-full items-end gap-2 rounded-lg border border-border bg-surface p-1.5 transition-shadow focus-within:border-accent/50 focus-within:shadow-glow">
              <Textarea
                ref={composer}
                rows={1}
                value={input}
                aria-label="Message MOTH"
                placeholder={signedOut ? "Sign in to chat with MOTH" : noModel ? "MOTH Cloud is unavailable" : "Message MOTH"}
                title="Enter to send · Shift+Enter for a new line"
                disabled={!!noModel}
                className="max-h-40 min-h-8 border-0 bg-transparent px-2 py-1.5 focus:shadow-none"
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
                <Button size="icon" disabled={!input.trim() || !!noModel} onClick={() => send()} title="Send">
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
