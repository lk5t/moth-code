/**
 * 2.3 sidebar body: Projects as folders with their chats inside, then standalone Chats (with search).
 * Compact layout in the style of a desktop coding assistant: small type, tight rows, nothing decorative.
 */
import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Folder, FolderOpen, MessageSquare, Plus } from "lucide-react";
import { ConversationList } from "./ConversationList";
import { appStore, useApp, type Project } from "@/lib/app-state";
import { useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { useEvent } from "@/lib/events";
import { openProjectPath, pickProject } from "@/features/workspace/project-actions";
import { cn } from "@/lib/utils";

export function requestChat(conversationId: number | null, title?: string) {
  if (appStore.getState().chatSession.busy) return;
  appStore.setState((s) => ({ view: "chat", chatRequest: { sequence: (s.chatRequest?.sequence ?? 0) + 1, conversationId, title, projectId: null } }));
}

/** 2.3: open a project's chat (or a new one in it) in that project's panel. */
export async function requestProjectChat(project: Project, conversationId: number | null, title?: string) {
  if (appStore.getState().chatSession.busy) return;
  await openProjectPath(project.path);
  appStore.setState((s) => ({ view: "workspace",
    chatRequest: { sequence: (s.chatRequest?.sequence ?? 0) + 1, conversationId, title, projectId: project.id } }));
}

const sectionTitle = "flex h-7 w-full items-center gap-1 px-2 text-[0.6875rem] font-medium text-muted hover:text-fg";

export function SidebarCollections({ search = "" }: { search?: string }) {
  const projects = useApp((s) => s.projects);
  const token = useAccount((s) => s.token), server = useAccount((s) => s.serverUrl);
  const [showProjects, setShowProjects] = useState(true), [showChats, setShowChats] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { data: chats, error: loadError, reload } = useResource<{ id: number; title: string }[]>(
    `/api/conversations?scope=general&q=${encodeURIComponent(search)}`, [], undefined, server + "\0" + token);
  useEvent("chat", (e) => { if (e.kind === "done" || e.kind === "error") void reload(); });
  useEvent("conversations", () => void reload());
  const recent = [...projects].sort((a, b) => b.last_opened - a.last_opened).slice(0, 8);
  const add = async () => { setError(null); try { await pickProject(); } catch (e) { setError((e as Error).message); } };

  return <div className="flex min-h-0 flex-1 flex-col text-xs">
    <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-0.5">
      {!search && <section aria-label="Projects">
        <div className="flex items-center">
          <button className={sectionTitle} aria-label="Show or hide projects" aria-expanded={showProjects} onClick={() => setShowProjects((v) => !v)}>
            Projects {showProjects ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}</button>
          <button aria-label="Open project" title="Open a project folder" onClick={() => void add()} className="ml-auto mr-1 rounded p-1 text-muted hover:bg-surface-2 hover:text-fg"><Plus className="size-3.5" /></button>
        </div>
        {showProjects && <ul className="space-y-px">
          {recent.map((p) => <ProjectItem key={p.id} project={p} />)}
          {!recent.length && <li className="px-2 py-1 text-faint">Open a folder to code with MOTH.</li>}
        </ul>}
        {error && <p role="alert" className="px-2 text-danger">{error}</p>}
      </section>}
      <section aria-label="Chats">
        {!search && <button className={sectionTitle} aria-label="Show or hide chats" aria-expanded={showChats} onClick={() => setShowChats((v) => !v)}>
          Chats {showChats ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}</button>}
        {(showChats || search) && <>
          <ConversationList chats={chats ?? []} searching={!!search} reload={() => void reload()} />
          {!chats?.length && !loadError && <p className="px-2 py-1 text-faint">{search ? "No matching chats." : "Start a new chat with MOTH."}</p>}
          {loadError && <p role="alert" className="px-2 text-danger">Chat history unavailable. <button onClick={() => void reload()} className="underline">Retry</button></p>}
        </>}
      </section>
    </div>
  </div>;
}

function ProjectItem({ project }: { project: Project }) {
  const current = useApp((s) => s.project?.id === project.id && s.view === "workspace");
  const session = useApp((s) => s.chatSession);
  const [open, setOpen] = useState(current);
  useEffect(() => { if (current) setOpen(true); }, [current]);
  const { data: chats } = useResource<{ id: number; title: string }[]>(open ? `/api/conversations?project_id=${project.id}` : null, ["conversations"], []);
  return <li>
    <div className={cn("group flex h-7 items-center rounded hover:bg-surface-2", current && "bg-surface-2")}>
      <button aria-label={`${open ? "Collapse" : "Expand"} ${project.name}`} aria-expanded={open} onClick={() => setOpen((v) => !v)} className="flex h-7 w-5 shrink-0 items-center justify-center text-faint hover:text-fg">
        {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}</button>
      <button title={project.path} onClick={() => void openProjectPath(project.path)} className="flex min-w-0 flex-1 items-center gap-1.5 pr-1 text-left text-muted hover:text-fg">
        {open ? <FolderOpen className="size-3.5 shrink-0" /> : <Folder className="size-3.5 shrink-0" />}<span className="truncate">{project.name}</span></button>
      <button aria-label={`New chat in ${project.name}`} title="New chat in this project" onClick={() => void requestProjectChat(project, null)} className="mr-1 rounded p-0.5 text-faint opacity-0 hover:text-fg focus-visible:opacity-100 group-hover:opacity-100"><Plus className="size-3" /></button>
    </div>
    {open && <ul className="ml-5 space-y-px border-l border-border pl-1">
      {(chats ?? []).slice(0, 12).map((c) => <li key={c.id}>
        <button title={c.title} disabled={session.busy} aria-current={session.conversationId === c.id ? "true" : undefined}
          onClick={() => void requestProjectChat(project, c.id, c.title)}
          className="flex h-6 w-full min-w-0 items-center gap-1.5 rounded px-1.5 text-left text-[0.6875rem] text-muted hover:bg-surface-2 hover:text-fg aria-[current=true]:text-fg disabled:opacity-50">
          <MessageSquare className="size-3 shrink-0" /><span className="truncate">{c.title}</span></button></li>)}
      {chats && !chats.length && <li className="px-1.5 py-0.5 text-[0.6875rem] text-faint">No chats yet</li>}
    </ul>}
  </li>;
}
