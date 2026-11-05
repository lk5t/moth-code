import { appStore, useApp, type View } from "@/lib/app-state";
import { cn } from "@/lib/utils";
import { useAccount } from "@/lib/account";
import { EmptyState } from "@/components/ui/empty";
import { TrainingView } from "@/features/training/TrainingView";
import { ModelsView } from "@/features/models/ModelsView";
import { NetworkView } from "@/features/network/NetworkView";
import { OwnerDashboard } from "@/features/owner/OwnerDashboard";

const OWNER_TABS: [View, string][] = [["owner", "Dashboard"], ["training", "Model training"], ["models", "Model packages"]];

function OwnerSwitcher() {
  const view = useApp((s) => s.view);
  return (
    <div className="flex shrink-0 gap-1 border-b border-border bg-bg px-6 pt-3">
      {OWNER_TABS.map(([v, label]) => (
        <button key={v} onClick={() => appStore.setState({ view: v })}
          className={cn("cursor-pointer rounded-t-md px-3 py-1.5 text-xs transition-colors",
            view === v ? "bg-surface-2 text-fg" : "text-faint hover:text-fg")}>{label}</button>
      ))}
    </div>
  );
}

/** Owner-only tools, grouped under one Owner entry: dashboard, local training, model packaging. */
function ownerOnly(C: React.ComponentType): React.ComponentType {
  return function OwnerOnly() {
    const role = useAccount((s) => s.user?.role);
    if (role !== "owner") return <EmptyState title="Owner tools">These tools are available to the MOTH Owner account only.</EmptyState>;
    return (
      <div className="flex h-full flex-col">
        <OwnerSwitcher />
        <div className="min-h-0 flex-1"><C /></div>
      </div>
    );
  };
}

/** Top-level views other than workspace/settings. */
export const views: Partial<Record<View, React.ComponentType>> = {
  network: NetworkView,
  owner: ownerOnly(OwnerDashboard),
  training: ownerOnly(TrainingView),
  models: ownerOnly(ModelsView),
};
