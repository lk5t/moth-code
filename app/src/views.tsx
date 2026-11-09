import { type View } from "@/lib/app-state";
import { useAccount } from "@/lib/account";
import { EmptyState } from "@/components/ui/empty";
import { OwnerDashboard } from "@/features/owner/OwnerDashboard";
import { ActivityWorkspace } from "@/features/activity/ActivityWorkspace";
import { IntelligenceHub } from "@/features/intelligence/IntelligenceHub";

/** Owner-only tools, grouped under one Owner entry: dashboard, local training, model packaging. */
function ownerOnly(C: React.ComponentType): React.ComponentType {
  return function OwnerOnly() {
    const role = useAccount((s) => s.user?.role);
    if (role !== "owner") return <EmptyState title="Owner tools">These tools are available to the MOTH Owner account only.</EmptyState>;
    return (
      <div className="flex h-full flex-col">
        <div className="min-h-0 flex-1"><C /></div>
      </div>
    );
  };
}

/** Top-level views other than workspace/settings. */
export const views: Partial<Record<View, React.ComponentType>> = {
  overview: IntelligenceHub,
  data: IntelligenceHub,
  activity: ActivityWorkspace,
  intelligence: IntelligenceHub,
  evolution: IntelligenceHub,
  network: IntelligenceHub,
  owner: ownerOnly(OwnerDashboard),
  training: IntelligenceHub,
  models: IntelligenceHub,
};
