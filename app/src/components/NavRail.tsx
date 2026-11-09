import { useEffect } from "react";
import { Activity, Brain, Code2, Database, Home, MessageSquare, Network, Settings } from "lucide-react";
import { appStore, useApp } from "@/lib/app-state";
import { WORKSPACES, navigate, workspaceOf } from "@/lib/navigation";
import { Tip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { LivingMoth, IntelligencePulse } from "./LivingMoth";
import { AccountMenu } from "@/features/account/AccountMenu";
import { FeatureSearch } from "./FeatureSearch";

const icons = [Home, MessageSquare, Code2, Brain, Database, Network, Activity, Settings];
export function NavRail() {
  const view = useApp((s) => s.view);
  useEffect(() => {
    const shortcut = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || !e.altKey) return;
      const target = ({w: "workspace", i: "intelligence", s: "settings"} as const)[e.key.toLowerCase() as "w" | "i" | "s"];
      if(target) {e.preventDefault(); navigate(target === "workspace" && appStore.getState().workspaceMode === "chat" ? "chat" : target);}
    };
    window.addEventListener("keydown", shortcut);return () => window.removeEventListener("keydown", shortcut);
  }, []);
  return <nav aria-label="Main workspaces" className="flex w-[52px] shrink-0 flex-col items-stretch gap-1 border-r border-border bg-bg p-2 md:w-[148px]">
    <div className="mb-2 flex h-9 items-center justify-center gap-2"><LivingMoth className="size-7" /><span className="hidden text-sm font-medium tracking-widest md:inline">MOTH</span></div>
    <div className="mb-1 hidden md:block"><IntelligencePulse /></div>
    {WORKSPACES.map((item, index) => {const Icon=icons[index], selected=workspaceOf(view) === item.view;
      return <Tip key={item.view} label={item.description}><button aria-label={item.label} aria-current={selected ? "page" : undefined} onClick={() => navigate(item.view)}
        className={cn("flex h-9 w-full shrink-0 items-center justify-center gap-2 rounded-lg px-2 text-xs text-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:outline focus-visible:outline-accent md:justify-start", selected && "bg-surface-2 text-fg ring-1 ring-inset ring-accent/40")}>
        <Icon className="size-4 shrink-0"/><span className="hidden md:inline">{item.label}</span>
      </button></Tip>;
    })}
    <div className="flex-1"/><FeatureSearch /><div className="mt-1 flex justify-center"><AccountMenu /></div>
  </nav>;
}
