import { useEffect } from "react";
import { ArrowLeftRight, Code2, MessageSquare } from "lucide-react";
import { appStore, useApp } from "@/lib/app-state";
import { cn } from "@/lib/utils";
import { ChatView, ModelBar } from "@/features/chat/ChatView";
import { WorkspaceView } from "./WorkspaceView";
import { MothEmblem } from "@/components/MothEmblem";

/** Both existing workspaces stay mounted: drafts, streams, files and terminals survive a switch. */
export function WorkspaceShell() {
  const view = useApp((s) => s.view);
  const code = view === "workspace";
  const session=useApp(s=>s.chatSession),project=useApp(s=>s.project);
  useEffect(() => {
    const keyboard = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "m") {
        e.preventDefault();
        appStore.setState({ view: appStore.getState().workspaceMode === "code" ? "chat" : "workspace" });
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, []);
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-bg px-2 sm:px-3">
        <MothEmblem motion="idle" className="size-6 shrink-0" />
        <span className="flex min-w-0 flex-1 items-center gap-2 text-xs font-medium">{code ? <Code2 className="size-3.5" /> : <MessageSquare className="size-3.5" />}<span className="truncate">{code ? project?.name??"Code" : session.title}</span></span>
        {!code && <ModelBar />}
        <button className="ml-auto flex shrink-0 items-center gap-2 rounded px-2 py-1 text-xs text-muted hover:text-fg focus-visible:outline focus-visible:outline-accent"
          onClick={() => appStore.setState({view: code ? "chat" : "workspace"})} title="Switch workspace · Ctrl/⌘ Shift M" aria-label={code ? "Switch to Chat" : "Switch to Code"}>
          <ArrowLeftRight className="size-3.5" />
        </button>
      </header>
      <div hidden={!code} className={cn("min-h-0 flex-1", !code && "hidden")}><WorkspaceView /></div>
      <div hidden={code} className={cn("min-h-0 flex-1", code && "hidden")}><ChatView /></div>
    </div>
  );
}
