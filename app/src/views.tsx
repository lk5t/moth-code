import type { View } from "@/lib/app-state";
import { EmptyState } from "@/components/ui/empty";

function Pending({ name }: { name: string }) {
  return <EmptyState title={name}>This subsystem is not implemented yet.</EmptyState>;
}

/** Top-level views other than workspace/settings. */
export const views: Partial<Record<View, React.ComponentType>> = {
  training: () => <Pending name="Training" />,
  models: () => <Pending name="Models" />,
  community: () => <Pending name="Community learning" />,
};
