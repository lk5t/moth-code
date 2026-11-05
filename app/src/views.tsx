import type { View } from "@/lib/app-state";
import { useAccount } from "@/lib/account";
import { EmptyState } from "@/components/ui/empty";
import { TrainingView } from "@/features/training/TrainingView";
import { ModelsView } from "@/features/models/ModelsView";
import { NetworkView } from "@/features/network/NetworkView";
import { OwnerDashboard } from "@/features/owner/OwnerDashboard";

/** Owner-only tools: local training and model packaging for publishing candidates to MOTH Cloud. */
function ownerOnly(C: React.ComponentType): React.ComponentType {
  return function OwnerOnly() {
    const role = useAccount((s) => s.user?.role);
    if (role !== "owner") return <EmptyState title="Owner tools">These tools are available to the MOTH Owner account only.</EmptyState>;
    return <C />;
  };
}

/** Top-level views other than workspace/settings. */
export const views: Partial<Record<View, React.ComponentType>> = {
  network: NetworkView,
  owner: OwnerDashboard,
  training: ownerOnly(TrainingView),
  models: ownerOnly(ModelsView),
};
