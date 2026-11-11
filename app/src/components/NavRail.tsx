import { ActivityNotices } from "./ActivityNotices";
import { useEffect } from "react";
import { Brain, FolderGit2, MessageSquare, Network, Settings, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import { appStore, useApp } from "@/lib/app-state";
import { WORKSPACES, navigate, workspaceOf } from "@/lib/navigation";
import { Tip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { LivingMoth } from "./LivingMoth";
import { AccountMenu } from "@/features/account/AccountMenu";
import { SidebarCollections, requestChat } from "./SidebarCollections";
import { FeatureSearch } from "./FeatureSearch";

const icons = [MessageSquare, FolderGit2, Brain, Network, Settings];
export function NavRail() {
  const view = useApp((s) => s.view);
  const collapsed=useApp(s=>s.sidebarCollapsed),busy=useApp(s=>s.chatSession.busy);
  useEffect(() => {
    const shortcut = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || !e.altKey) return;
      const target = ({w: "workspace", i: "intelligence", s: "settings"} as const)[e.key.toLowerCase() as "w" | "i" | "s"];
      if(target) {e.preventDefault(); navigate(target === "workspace" && appStore.getState().workspaceMode === "chat" ? "chat" : target);}
    };
    window.addEventListener("keydown", shortcut);return () => window.removeEventListener("keydown", shortcut);
  }, []);
  return <nav aria-label="Main workspaces" className={cn("flex min-h-0 shrink-0 flex-col gap-2 border-r border-border bg-bg p-2 transition-[width] motion-reduce:transition-none",collapsed?"w-14":"w-14 md:w-56")}>
    <div className="flex h-9 shrink-0 items-center justify-between gap-1">
      {!collapsed&&<div className="hidden min-w-0 items-center gap-2 md:flex"><LivingMoth className="size-6"/><span className="text-xs font-medium tracking-widest">MOTH</span></div>}
      <button aria-label={collapsed?"Expand sidebar":"Collapse sidebar"} aria-expanded={!collapsed} onClick={()=>appStore.setState({sidebarCollapsed:!collapsed})} className="ml-auto rounded p-2 text-muted hover:bg-surface-2 hover:text-fg focus-visible:outline focus-visible:outline-accent">{collapsed?<PanelLeftOpen className="size-4"/>:<PanelLeftClose className="size-4"/>}</button>
    </div>
    <button aria-label="New Chat" disabled={busy} onClick={()=>requestChat(null)} className="flex h-9 shrink-0 items-center justify-center gap-2 rounded-md border border-border bg-surface-2 px-2 text-xs text-fg disabled:opacity-50"><Plus className="size-4"/>{!collapsed&&<span className="hidden md:inline">New Chat</span>}</button>
    <div className="grid shrink-0 gap-0.5">
    {WORKSPACES.map((item,index)=>{const Icon=icons[index],selected=workspaceOf(view)===item.view;
      return <Tip key={item.view} label={item.description}><button aria-label={item.label} aria-current={selected?"page":undefined} onClick={()=>navigate(item.view)} className={cn("relative flex h-8 min-w-0 items-center justify-center gap-2.5 rounded-md px-2 text-xs text-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:outline focus-visible:outline-accent",!collapsed&&"md:justify-start",selected&&"bg-surface-2 text-fg before:absolute before:left-0 before:top-1.5 before:h-5 before:w-0.5 before:rounded-full before:bg-accent before:shadow-[0_0_10px_var(--color-accent)]")}><Icon className="size-4 shrink-0"/>{!collapsed&&<span className="hidden truncate md:inline">{item.label}</span>}</button></Tip>;
    })}
    </div>
    <div hidden={collapsed} className={cn("min-h-0 flex-1 flex-col pt-1",collapsed?"hidden":"hidden md:flex")}><SidebarCollections/></div>
    {collapsed&&<div className="flex-1"/>}
    <div className="shrink-0 border-t border-border pt-1"><FeatureSearch compact={collapsed}/><div className="flex items-center justify-center gap-2"><AccountMenu/>{!collapsed&&<span className="hidden md:inline"><ActivityNotices/></span>}</div></div>
  </nav>;
}
