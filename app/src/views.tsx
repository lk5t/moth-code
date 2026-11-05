import type { View } from "@/lib/app-state";
import { EmptyState } from "@/components/ui/empty";
import { TrainingView } from "@/features/training/TrainingView";
import { ModelsView } from "@/features/models/ModelsView";

function Pending({ name }: { name: string }) {
  return <EmptyState title={name}>This subsystem is not implemented yet.</EmptyState>;
}

/** Top-level views other than workspace/settings. */
export const views: Partial<Record<View, React.ComponentType>> = {
  training: TrainingView,
  models: ModelsView,
  community: () => <Pending name="Community learning" />,
};
