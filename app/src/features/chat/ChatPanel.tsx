import { navigate } from "@/lib/navigation";
import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { MothEvent } from "@/lib/events";
import { ArrowUp, Bug, Code2, HelpCircle, Radar, ShieldCheck, Cloud, FileText, LogIn, MessageSquarePlus, Paperclip, RefreshCw, Square, Upload, X } from "lucide-react";
import { formatAttachments, formatBytes, onDesktopDrop, readFiles, readPaths, splitAttachments, type Attachment } from "@/lib/attachments";
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
import { AnswerContext, Markdown, CopyText } from "./Markdown";
import { ErrorNotice } from "@/components/ErrorNotice";
import { AgentPanel } from "@/features/agent/AgentPanel";
import { sounds } from "@/lib/sounds";
import { AnswerFooter, type AnswerMeta } from "@/features/intelligence/AnswerFooter";
import { useCloudProgress } from "@/lib/cloud-progress";
import { modelLabel } from "@/lib/model-label";
import { UsageRing } from "@/components/UsageRing";
import { parseScan, parseSecurity, runAudit, scanToChat, startScan, type AuditReport, type ScanPlan } from "@/lib/scans";
import { ConfirmScan, ReportCard, ScanCard } from "@/features/security/ScanCard";

interface ChatMessage {
  id: number | string;
  role: "user" | "assistant" | "error" | "scan";
  scan?: { stage: "confirm" | "starting" | "running" | "cancelled" | "refused"; text: string; plan?: ScanPlan; refused?: string; id?: string };
  content: string;
  meta?: ({ report?: AuditReport; scan_id?: string; code_checks?: { language: string; ok: boolean; problem: string | null }[]; via?: string; prompt?: string; model?: string; tokens?: number; tokens_per_sec?: number; stop_reason?: string; compacted?: boolean } & AnswerMeta) | null;
  streaming?: boolean;
}

/** 2.0 starter prompts: what MOTH can do, one click away. */
const STARTERS = [
  { label: "Fix a bug in my code", text: "Fix this bug: ", icon: Bug },
  { label: "Explain an error", text: "Explain this error and how to fix it: ", icon: HelpCircle },
  { label: "Write a function", text: "Write a Python function that ", icon: Code2 },
  { label: "Scan my server", text: "Check 192.168.1.10 for vulnerabilities", icon: Radar },
  { label: "Learn a security topic", text: "Explain how SQL injection works and how to prevent it", icon: ShieldCheck },
];
const PROJECT_STARTERS = [
  { label: "Explain this project", text: "Explain how this project is organised", icon: HelpCircle },
  { label: "Help debug a problem", text: "Help me debug: ", icon: Bug },
  { label: "Write tests", text: "Write tests for ", icon: Code2 },
  { label: "Audit my code", text: "Audit my code for security problems", icon: ShieldCheck },
  { label: "Check dependencies", text: "Check my dependencies for vulnerabilities", icon: Radar },
];

interface Conversation {
  id: number;
  title: string;
}


/** ``general``: the full-page Chat (everyday questions, writing, explanations) — not tied to a project. */
export function ChatPanel({ general = false, contextProjectId = null }: { general?: boolean; contextProjectId?: number | null } = {}) {
  const workspaceProject = useApp((s) => s.project);
  const project = general ? null : workspaceProject;
  const [mode, setMode] = useState<"chat" | "agent">("chat");
  const [remembered, setRemembered] = useState<string | null>(null);
  useEffect(() => { if (!remembered) return; const t = setTimeout(() => setRemembered(null), 6000); return () => clearTimeout(t); }, [remembered]);
  useEffect(() => {  // 2.1: "Ask MOTH" on a security finding puts the question in the chat box
    const ask = (e: Event) => { setMode("chat"); setInput((e as CustomEvent<string>).detail); setTimeout(() => composer.current?.focus(), 0); };
    window.addEventListener("moth:ask", ask);
    return () => window.removeEventListener("moth:ask", ask);
  }, []);
  useEffect(() => {  // 1.0: "Fix this" and the error watcher open the agent with the new task
    const open = () => setMode("agent");
    window.addEventListener("moth:open-agent", open);
    return () => window.removeEventListener("moth:open-agent", open);
  }, []);
  // 2.0: files and folders dropped into chat
  const [attached, setAttached] = useState<Attachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const [dropNote, setDropNote] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const addAttachments = (r: { files: Attachment[]; skipped: { path: string; reason: string }[] }) => {
    setAttached((cur) => [...cur.filter((c) => !r.files.some((f) => f.path === c.path)), ...r.files].slice(0, 30));
    setDropNote(r.skipped.length ? `Skipped ${r.skipped.length}: ${r.skipped.slice(0, 3).map((x) => `${x.path} (${x.reason})`).join(", ")}${r.skipped.length > 3 ? "…" : ""}` : null);
  };
  useEffect(() => {
    let off = () => {};
    let alive = true;
    onDesktopDrop({ over: setDragging, drop: (paths) => { readPaths(paths).then(addAttachments).catch((e) => setDropNote(String(e.message ?? e))); } })
      .then((u) => { if (alive) off = u; else u(); }).catch(() => {});
    return () => { alive = false; off(); };
  }, []);
  useEffect(() => { if (!dropNote) return; const t = setTimeout(() => setDropNote(null), 8000); return () => clearTimeout(t); }, [dropNote]);
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
  // A deleted conversation (sidebar, bulk delete, clear all or the retention setting) never stays open.
  useEvent("conversations", (e) => {
    void reloadConversations();
    if (Array.isArray(e.deleted) && cidRef.current !== null && e.deleted.includes(cidRef.current)) {
      setCid(null); setMessages([]); setHasOlder(false);
    }
  });
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
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;

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
    if(e.kind === "done") { reloadConversations(); sounds.chime(); }
  };

  useEvent("chat", (e) => {
    if (cidRef.current === null && sendingNew.current) {
      early.current.push(e);
      return;
    }
    if (e.conversation_id === cidRef.current) apply(e);
  });

  const setScan = (key: ChatMessage["id"], patch: Partial<NonNullable<ChatMessage["scan"]>>) =>
    setMessages((cur) => cur.map((m) => m.id === key && m.scan ? { ...m, scan: { ...m.scan, ...patch } } : m));
  const confirmScan = async (m: ChatMessage) => {
    if (!m.scan) return;
    setScan(m.id, { stage: "starting" });
    try { const s = await startScan(m.scan.text); setScan(m.id, { stage: "running", id: s.id }); sounds.click(); }
    catch (e) { setScan(m.id, { stage: "refused", refused: (e as Error).message }); }
  };
  // when a chat scan finishes, its summary is saved into the conversation, so follow-up questions have it as context
  const savedScans = useRef(new Set<string>());
  useEvent("scan", (e) => {
    if (e.kind !== "finished" || savedScans.current.has(e.scan.id)) return;
    const local = messagesRef.current.find((m) => m.scan?.id === e.scan.id);
    if (!local?.scan) return;
    savedScans.current.add(e.scan.id);
    scanToChat(e.scan.id, cidRef.current, local.scan.text).then(async (r) => {
      sounds.chime(); reloadConversations();
      const history = await get<ChatMessage[]>(`/api/conversations/${r.conversation_id}/messages?limit=100`);
      skipFetch.current = r.conversation_id; cidRef.current = r.conversation_id; setCid(r.conversation_id); setMessages(history);
    }).catch(() => {});
  });

  const send = async (regenerate = false) => {
    const typed = input.trim() || (attached.length ? "Take a look at these files." : "");
    const text = regenerate ? [...messages].reverse().find((m)=>m.role === "user")?.content ?? "" : formatAttachments(typed, attached);
    if (!text || busy) return;
    if (!regenerate) {  // 2.1: "audit my code" / "check my dependencies" / "is this nginx config secure?" run here, on your files
      const sec = await parseSecurity(typed).catch(() => null);
      if (sec?.tool) {
        setInput(""); setAttached([]); followTail.current = true; sounds.click(); setBusy(true);
        setMessages((m) => [...m, { id: `u${Date.now()}`, role: "user", content: text }, { id: `a${Date.now()}`, role: "assistant", content: "", streaming: true }]);
        try {
          const r = await runAudit({ message: typed, project_id: project?.id ?? contextProjectId ?? null, files: attached.map((f) => ({ path: f.path, content: f.content })), conversation_id: cid });
          const history = await get<ChatMessage[]>(`/api/conversations/${r.conversation_id}/messages?limit=100`);
          skipFetch.current = r.conversation_id; cidRef.current = r.conversation_id; setCid(r.conversation_id); setMessages(history);
          reloadConversations(); sounds.chime();
        } catch (e) {
          setMessages((m) => [...m.filter((x) => !x.streaming), { id: `e${Date.now()}`, role: "error", content: String((e as Error).message ?? e) }]);
        } finally { setBusy(false); }
        return;
      }
    }
    if (!regenerate && !attached.length) {  // 2.0: "scan 10.0.0.5 port 8080" asks for a Yes and runs here, not in the cloud
      const asked = await parseScan(typed).catch(() => null);
      if (asked?.plan || asked?.refused) {
        setInput(""); followTail.current = true; sounds.click();
        setMessages((m) => [...m, { id: `u${Date.now()}`, role: "user", content: typed },
          { id: `s${Date.now()}`, role: "scan", content: "", scan: asked.plan ? { stage: "confirm", text: typed, plan: asked.plan } : { stage: "refused", text: typed, refused: asked.refused! } }]);
        return;
      }
    }
    if(!regenerate) {setInput("");setAttached([]);setMessages((m) => [...m, { id: `u${Date.now()}`, role: "user", content: text }]);}
    sounds.click();
    followTail.current=true;setBusy(true);
    const isNew = cid === null;
    if (isNew) {
      sendingNew.current = true;
      early.current = [];
    }
    try {
      const r = await post<{ conversation_id: number; remembered?: string | null }>("/api/chat", {
        message: text, regenerate,
        conversation_id: cid,
        project_id: project?.id ?? null,
        context_project_id: contextProjectId,
      });
      if (r.remembered) setRemembered(r.remembered);  // 1.0: shown under the input for a few seconds
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
      if(!regenerate) setInput(splitAttachments(text).body);
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
                  "cursor-pointer rounded px-2.5 py-0.5 text-[0.6875rem] font-medium capitalize text-muted transition-colors",
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
        {!general && <span className="flex min-w-0 items-center gap-1 text-[0.6875rem] text-faint" title={cloud?.model?.name}>
          <Cloud className="size-3" />
          <span className="truncate">{currentLabel}</span>
        </span>}
      </div>}

      {mode === "agent" ? (
        <AgentPanel />
      ) : (
        <div className="relative flex min-h-0 flex-1 flex-col"
          onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }}
          onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
          onDrop={(e) => { if (!e.dataTransfer.files.length) return; e.preventDefault(); setDragging(false); readFiles(e.dataTransfer.files).then(addAttachments).catch(() => {}); }}>
          {dragging && <div className="pointer-events-none absolute inset-2 z-20 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-accent/70 bg-bg/80 text-sm text-fg backdrop-blur-sm animate-fade-in">
            <Upload className="size-6 animate-bounce text-accent" />Drop files or folders to share them with MOTH
            <span className="text-[0.6875rem] text-muted">Text files only · keys and .env files are never read</span></div>}
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
                    <div className="mt-3 flex justify-center gap-2"><Button size="sm" variant="secondary" onClick={() => reloadCloud()}><RefreshCw /> Retry</Button>
                      {(cloud?.reason === "no_model_deployed" || cloud?.reason === "training_first_model") && <Button size="sm" variant="ghost" onClick={() => navigate("overview")}>Open AI</Button>}</div>
                  </div>
                ) : (
                  <div className="max-w-sm text-xs text-muted">
                    {currentLabel}{liveModel?.current?.initialization === "random-untrained" && !usingLocal ? " · untrained baseline; capabilities have not been established." : ". Measured model details are available in Overview."}
                  </div>
                )}
                {!noModel && <div className="flex flex-wrap gap-1.5">
                  {(general ? STARTERS : PROJECT_STARTERS).map((st, i) =>
                    <button key={st.label} style={{ animationDelay: `${i * 50}ms` }} className="lift flex cursor-pointer items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-muted animate-slide-up hover:border-accent/50 hover:text-fg"
                      onClick={() => { setInput(st.text); composer.current?.focus(); }}><st.icon className="size-3.5 text-accent" />{st.label}</button>)}
                </div>}
              </div>
            ) : (
              <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
                {messages.map((m,index) => {
                  const content = <div key={m.id} className={cn("flex animate-message-in", !m.streaming && "chat-row", m.role === "user" && "justify-end")}>
                    {m.role === "scan" && m.scan ? (
                      <div className="flex w-full gap-2.5"><MothEmblem motion={m.scan.stage === "running" ? "generating" : "none"} className="mt-0.5 size-5 shrink-0" />
                        {m.scan.stage === "confirm" || m.scan.stage === "starting"
                          ? <ConfirmScan plan={m.scan.plan!} busy={m.scan.stage === "starting"} onYes={() => void confirmScan(m)} onNo={() => setScan(m.id, { stage: "cancelled" })} />
                          : m.scan.stage === "running" && m.scan.id ? <ScanCard id={m.scan.id} />
                          : m.scan.stage === "cancelled" ? <div className="text-[0.8125rem] text-muted">Okay, nothing was scanned.</div>
                          : <div className="max-w-xl rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-[0.8125rem] text-warning">I won't scan that: {m.scan.refused}</div>}
                      </div>
                    ) : m.role === "assistant" && m.meta?.report ? (
                      <div className="flex w-full gap-2.5"><MothEmblem motion="none" className="mt-0.5 size-5 shrink-0" />
                        <div className="min-w-0 flex-1 space-y-1.5"><ReportCard report={m.meta.report} />
                          <details className="text-[0.6875rem] text-muted"><summary className="cursor-pointer hover:text-fg">Full write-up</summary><div className="mt-1 text-[0.8125rem] text-fg"><Markdown text={m.content} /></div></details></div>
                      </div>
                    ) : m.role === "assistant" && m.meta?.scan_id ? (
                      <div className="flex w-full gap-2.5"><MothEmblem motion="none" className="mt-0.5 size-5 shrink-0" />
                        <div className="min-w-0 flex-1 space-y-1.5"><ScanCard id={m.meta.scan_id} />
                          <details className="text-[0.6875rem] text-muted"><summary className="cursor-pointer hover:text-fg">Full write-up</summary><div className="mt-1 text-[0.8125rem] text-fg"><Markdown text={m.content} /></div></details></div>
                      </div>
                    ) : m.role === "user" ? (
                      <UserBubble text={m.content} />
                    ) : m.role === "error" ? (
                      <ErrorNotice error={m.content} />
                    ) : (
                      <div className="flex max-w-[95%] gap-2.5">
                        <MothEmblem motion={m.streaming ? "generating" : "none"} className="mt-0.5 size-5 shrink-0" />
                        <div className="min-w-0 text-[0.8125rem] leading-relaxed">
                          {m.content ? <AnswerContext.Provider value={{ prompt: m.meta?.prompt, answer: m.content, model: m.meta?.model, via: m.meta?.via }}><Markdown text={m.content} streaming={m.streaming} /></AnswerContext.Provider> : <span className="shimmer-text font-medium">Thinking…</span>}
                          {m.streaming && <span className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-accent" />}
                          {!m.streaming && looksBroken(m.content, m.meta?.stop_reason) && (
                            <div role="note" className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning/10 px-2 py-1 text-[0.6875rem] text-warning">
                              This reply looks garbled — MOTH is still learning to write.
                              {index === lastAssistant && cid !== null && <button className="cursor-pointer underline" disabled={busy} onClick={() => send(true)}>Try again</button>}
                            </div>
                          )}
                          {!!m.meta?.code_checks?.length && <div className="mt-1.5 flex flex-wrap gap-1.5 animate-fade-in">{m.meta.code_checks.map((c, ci) =>
                            <span key={ci} title={c.problem ?? "The code parses; it was not run."} className={cn("inline-flex items-center gap-1 rounded border px-1.5 py-px text-[0.625rem]", c.ok ? "border-success/30 text-success" : "border-warning/40 bg-warning/10 text-warning")}>
                              {c.ok ? "✓" : "!"} {c.language} {c.ok ? "code checked" : `has a problem: ${c.problem}`}</span>)}</div>}
                          {m.meta?.compacted && <div className="mt-1 text-[0.65625rem] text-faint">Earlier messages were summarised so this long chat fits.</div>}
                          {m.meta && (
                            <div className="mt-1 text-[0.65625rem] text-faint">
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
            {remembered && <p role="status" className="animate-pop mb-1 text-[0.6875rem] text-success">MOTH will remember: “{remembered}” (Settings → Memory)</p>}
            {dropNote && <p role="status" className="mb-1 text-[0.6875rem] text-warning animate-fade-in">{dropNote}</p>}
            {attached.length > 0 && <div className="stagger mb-1.5 flex flex-wrap gap-1.5" aria-label="Attached files">
              {attached.map((f) => <span key={f.path} className="flex max-w-60 items-center gap-1.5 rounded-md border border-border bg-surface-2 py-0.5 pl-2 pr-1 text-[0.6875rem] animate-pop" title={f.path}>
                <FileText className="size-3 shrink-0 text-accent" /><span className="truncate">{f.path}</span><span className="shrink-0 text-faint">{formatBytes(f.size)}{f.truncated ? " · cut" : ""}</span>
                <button aria-label={`Remove ${f.name}`} className="rounded p-0.5 text-muted hover:bg-surface-3 hover:text-fg" onClick={() => setAttached((cur) => cur.filter((c) => c.path !== f.path))}><X className="size-3" /></button></span>)}
            </div>}
            <div className="flex w-full items-end gap-2 rounded-lg border border-border bg-surface p-1.5 transition-shadow focus-within:border-accent/50 focus-within:shadow-glow">
              <input ref={picker} type="file" multiple hidden onChange={(e) => { if (e.target.files?.length) readFiles(e.target.files).then(addAttachments).catch(() => {}); e.target.value = ""; }} />
              <Button size="icon" variant="ghost" title="Attach files" aria-label="Attach files" disabled={!!noModel} onClick={() => picker.current?.click()}><Paperclip /></Button>
              <Textarea
                ref={composer}
                rows={1}
                value={input}
                aria-label="Message MOTH"
                placeholder={signedOut ? "Sign in to chat with MOTH" : noModel ? (cloud?.reachable === false ? "MOTH Cloud can't be reached" : "MOTH can't answer yet") : "Message MOTH"}
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
              <UsageRing refreshKey={busy} />
              {busy ? (
                <Button size="icon" variant="secondary" title="Stop" onClick={() => cid !== null && post(`/api/chat/${cid}/cancel`)}>
                  <Square className="text-accent" />
                </Button>
              ) : (
                <Button size="icon" disabled={(!input.trim() && !attached.length) || !!noModel} onClick={() => send()} title="Send">
                  <ArrowUp />
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


/** 1.0 honest answers: a finished reply that is clearly not language (looping, symbol soup, letter salad). */
export function looksBroken(text: string, stop?: string | null): boolean {
  const t = (text || "").trim();
  if (!t) return stop !== "cancelled";
  if (stop === "repetition") return true;
  if (t.length < 12) return false;
  const letters = (t.match(/[A-Za-z]/g) || []).length / t.length;
  const words = t.split(/\s+/).filter(Boolean);
  const real = words.filter((w) => /^[A-Za-z][a-z']{0,14}[.,!?;:]?$/.test(w)).length / Math.max(1, words.length);
  const longest = Math.max(...words.map((w) => w.length));
  const pairs = new Set(words.slice(1).map((w, i) => words[i] + " " + w)).size / Math.max(1, words.length - 1);
  if (/```/.test(t)) return false;  // code is judged by running it, not by this
  return letters < 0.45 || real < 0.45 || longest > 30 || (words.length > 12 && pairs < 0.4);
}

/** 2.0: a user message, with attached files shown as chips you can open. */
const UserBubble = memo(function UserBubble({ text }: { text: string }) {
  const { body, files } = splitAttachments(text);
  return <div className="flex max-w-[85%] flex-col items-end gap-1">
    {body && <div className="selectable whitespace-pre-wrap rounded-xl rounded-br-sm border border-border bg-surface-2 px-3.5 py-2 text-[0.8125rem]">{body}</div>}
    {files.length > 0 && <div className="flex flex-wrap justify-end gap-1">
      {files.map((f, i) => <details key={i} className="group max-w-full rounded-md border border-border bg-surface text-[0.6875rem]">
        <summary className="flex cursor-pointer items-center gap-1.5 px-2 py-0.5 text-muted hover:text-fg"><FileText className="size-3 text-accent" /><span className="truncate">{f.path}</span></summary>
        <pre className="selectable max-h-60 max-w-[36rem] overflow-auto border-t border-border p-2 font-mono text-[0.6875rem] text-fg">{f.content}</pre>
      </details>)}
    </div>}
  </div>;
});
