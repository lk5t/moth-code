import { Brain, Cpu, Settings, SquareTerminal, Users } from "lucide-react";
import { appStore, useApp, type View } from "@/lib/app-state";
import { Tip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { MothEmblem } from "./MothEmblem";

const items: { view: View; label: string; icon: React.ReactNode }[] = [
  { view: "workspace", label: "Workspace", icon: <SquareTerminal /> },
  { view: "training", label: "Training", icon: <Brain /> },
  { view: "models", label: "Models & inference", icon: <Cpu /> },
  { view: "community", label: "Community learning", icon: <Users /> },
];

export function NavRail() {
  const view = useApp((s) => s.view);
  const button = (v: View, label: string, icon: React.ReactNode) => (
    <Tip key={v} label={label}>
      <button
        onClick={() => appStore.setState({ view: v })}
        className={cn(
          "relative flex size-9 cursor-pointer items-center justify-center rounded-lg text-faint transition-all hover:bg-surface-2 hover:text-fg [&_svg]:size-[18px]",
          view === v && "text-fg bg-surface-2 before:absolute before:-left-[9px] before:h-5 before:w-0.5 before:rounded-full before:bg-accent before:shadow-[0_0_8px_#C1121F]",
        )}
        aria-label={label}
      >
        {icon}
      </button>
    </Tip>
  );
  return (
    <nav className="flex w-[52px] shrink-0 flex-col items-center gap-1 border-r border-border bg-bg py-3">
      <MothEmblem className="mb-3 size-8 transition-[filter] hover:drop-shadow-[0_0_10px_rgba(193,18,31,0.6)]" />
      {items.map((i) => button(i.view, i.label, i.icon))}
      <div className="flex-1" />
      {button("settings", "Settings", <Settings />)}
    </nav>
  );
}
