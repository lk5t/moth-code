import { Crown, Network, Settings, SquareTerminal } from "lucide-react";
import { useAccount } from "@/lib/account";
import { appStore, useApp, type View } from "@/lib/app-state";
import { Tip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { MothEmblem } from "./MothEmblem";
import { AccountMenu } from "@/features/account/AccountMenu";

const items: { view: View; label: string; icon: React.ReactNode; owner?: boolean }[] = [
  { view: "workspace", label: "Workspace", icon: <SquareTerminal /> },
  { view: "network", label: "Training & Referrals", icon: <Network /> },
  { view: "owner", label: "Owner", icon: <Crown />, owner: true },
];
const OWNER_VIEWS: View[] = ["owner", "training", "models"];

export function NavRail() {
  const view = useApp((s) => s.view);
  const isOwner = useAccount((s) => s.user?.role === "owner");
  const button = (v: View, label: string, icon: React.ReactNode) => (
    <Tip key={v} label={label}>
      <button
        onClick={() => appStore.setState({ view: v })}
        className={cn(
          "relative flex size-9 cursor-pointer items-center justify-center rounded-lg text-faint transition-all hover:bg-surface-2 hover:text-fg [&_svg]:size-[18px]",
          (view === v || (v === "owner" && OWNER_VIEWS.includes(view))) && "text-fg bg-surface-2 before:absolute before:-left-[9px] before:h-5 before:w-0.5 before:rounded-full before:bg-accent before:shadow-[0_0_8px_#C1121F]",
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
      {items.filter((i) => !i.owner || isOwner).map((i) => button(i.view, i.label, i.icon))}
      <div className="flex-1" />
      {button("settings", "Settings", <Settings />)}
      <div className="mt-2"><AccountMenu /></div>
    </nav>
  );
}
