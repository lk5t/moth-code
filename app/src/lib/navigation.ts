import { appStore, type View } from "./app-state";

export const WORKSPACES: { view: View; label: string; description: string }[] = [
  { view: "overview", label: "Overview", description: "Active model, status and warnings" },
  { view: "chat", label: "Chat", description: "Conversations and answers" },
  { view: "workspace", label: "Code", description: "Projects, files, editor and coding agent" },
  { view: "intelligence", label: "Intelligence", description: "Training, evaluation and safe evolution" },
  { view: "data", label: "Data", description: "Datasets, tokenizer and preparation" },
  { view: "network", label: "Network", description: "Workers and personal contribution" },
  { view: "activity", label: "Activity", description: "History, events and model timeline" },
  { view: "settings", label: "Settings", description: "Account, privacy, updates and administration" },
];
export function workspaceOf(view: View): View {
  if (view === "owner") return "settings";
  if (["training", "models", "evolution"].includes(view)) return "intelligence";
  return view;
}
export function navigate(view: View) {
  const state = appStore.getState();
  appStore.setState({ view, ...(view === "intelligence" && !["training", "evolution"].includes(state.intelligenceTab)
    ? { intelligenceTab: "training" as const } : {}) });
}
