import type { View } from "@/lib/app-state";
import { TrainingView } from "@/features/training/TrainingView";
import { ModelsView } from "@/features/models/ModelsView";
import { CommunityView } from "@/features/community/CommunityView";

/** Top-level views other than workspace/settings. */
export const views: Partial<Record<View, React.ComponentType>> = {
  training: TrainingView,
  models: ModelsView,
  community: CommunityView,
};
