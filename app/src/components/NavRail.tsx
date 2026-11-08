import { useEffect } from "react";
import { Brain, Crown, Settings, SquareTerminal } from "lucide-react";
import { useAccount } from "@/lib/account";
import { appStore, useApp, type View } from "@/lib/app-state";
import { Tip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { MothEmblem } from "./MothEmblem";
import { AccountMenu } from "@/features/account/AccountMenu";

// Code/Chat share one workspace; all native AI tools live in Intelligence.
const items: { view: View; label: string; icon: React.ReactNode; owner?: boolean }[] = [
  { view: "workspace", label: "Workspace · Code / Chat", icon: <SquareTerminal /> },
  { view: "intelligence", label: "Intelligence", icon: <Brain /> },
  { view: "owner", label: "Owner tools", icon: <Crown />, owner: true },
];
const INTELLIGENCE_VIEWS: View[] = ["intelligence", "evolution", "network", "training", "models"];

export function NavRail() {
  const view = useApp((s) => s.view);
  const isOwner = useAccount((s) => s.user?.role === "owner");
  useEffect(() => {
    const shortcut = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || !e.altKey) return;
      const target = ({ w: "workspace", i: "intelligence", s: "settings" } as const)[e.key.toLowerCase() as "w" | "i" | "s"];
      if (target) { e.preventDefault(); appStore.setState({ view: target === "workspace" && appStore.getState().workspaceMode === "chat" ? "chat" : target }); }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  const button = (v: View, label: string, icon: React.ReactNode) => (
    <Tip key={v} label={label}>
      <button
        onClick={() => appStore.setState({ view: v === "workspace" && appStore.getState().workspaceMode === "chat" ? "chat" : v })}
        className={cn(
          "relative flex size-9 cursor-pointer items-center justify-center rounded-lg text-faint transition-all hover:bg-surface-2 hover:text-fg [&_svg]:size-[18px]",
          (view === v || (v === "workspace" && view === "chat") || (v === "intelligence" && INTELLIGENCE_VIEWS.includes(view))) && "text-fg bg-surface-2 before:absolute before:-left-[9px] before:h-5 before:w-0.5 before:rounded-full before:bg-accent",
        )}
        aria-label={label}
        aria-current={(view === v || (v === "workspace" && view === "chat") || (v === "intelligence" && INTELLIGENCE_VIEWS.includes(view))) ? "page" : undefined}
      >
        {icon}
      </button>
    </Tip>
  );
  return (
    <nav className="flex w-[52px] shrink-0 flex-col items-center gap-1 border-r border-border bg-bg py-3">
      <MothEmblem motion="idle" className="mb-2 size-8 transition-[filter] hover:drop-shadow-[0_0_10px_rgba(193,18,31,0.6)]" />
      {items.filter((i) => !i.owner || isOwner).map((i) => button(i.view, i.label, i.icon))}
      <div className="flex-1" />
      {button("settings", "Settings", <Settings />)}
      <div className="mt-2"><AccountMenu /></div>
    </nav>
  );
}
