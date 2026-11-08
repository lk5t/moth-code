import { useEffect } from "react";
import { ArrowLeftRight, Code2, MessageSquare } from "lucide-react";
import { appStore, useApp } from "@/lib/app-state";
import { cn } from "@/lib/utils";
import { ChatView } from "@/features/chat/ChatView";
import { WorkspaceView } from "./WorkspaceView";

/** Both existing workspaces stay mounted: drafts, streams, files and terminals survive a switch. */
export function WorkspaceShell() {
  const view = useApp((s) => s.view);
  const code = view === "workspace";
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
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-bg px-3 sm:px-5">
        <div className="flex items-center gap-1 rounded-lg border border-border bg-surface p-1" aria-label="Workspace mode">
          <button aria-pressed={code} onClick={() => appStore.setState({ view: "workspace" })}
            className={cn("flex cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-xs transition-colors", code ? "bg-surface-2 text-fg" : "text-muted hover:text-fg")}>
            <Code2 className="size-3.5" />Code
          </button>
          <ArrowLeftRight aria-hidden className={cn("size-3.5 text-faint transition-transform duration-200 motion-reduce:transition-none", !code && "rotate-180")} />
          <button aria-pressed={!code} onClick={() => appStore.setState({ view: "chat" })}
            className={cn("flex cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-xs transition-colors", !code ? "bg-surface-2 text-fg" : "text-muted hover:text-fg")}>
            <MessageSquare className="size-3.5" />Chat
          </button>
        </div>
        <span className="hidden text-xs text-faint sm:block">{code ? "Projects, agent, editor and terminal" : "Conversations, ideas and research"}</span>
        <span className="ml-auto hidden text-[11px] text-faint lg:block">Ctrl/⌘ Shift M</span>
      </header>
      <div hidden={!code} className={cn("min-h-0 flex-1", !code && "hidden")}><WorkspaceView /></div>
      <div hidden={code} className={cn("min-h-0 flex-1", code && "hidden")}><ChatView /></div>
    </div>
  );
}
