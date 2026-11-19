import { appStore, aiTab, type View } from "./app-state";

/** The main sections. Everything else lives inside one of them. */
export const WORKSPACES: { view: View; label: string; description: string; ownerOnly?: boolean }[] = [
  { view: "home", label: "Home", description: "What MOTH is doing, your recent work and today's progress" },
  { view: "chat", label: "Chat", description: "Conversations with MOTH" },
  { view: "workspace", label: "Projects", description: "Coding projects, files, editor and autonomous tasks" },
  { view: "intelligence", label: "AI", description: "Evolution, live training, data and model history", ownerOnly: true },
  { view: "scans", label: "Security", description: "Scans you confirmed in chat: findings, fixes and logs" },
  { view: "network", label: "Network", description: "Workers, servers and your computer's contribution" },
  { view: "settings", label: "Settings", description: "Account, preferences, updates and administration" },
];
/** 1.0.12 security: views only the Owner account may open (MOTH's training, data, models, administration). */
const OWNER_VIEWS = new Set<string>(["intelligence", "overview", "data", "activity", "training", "models", "evolution", "owner"]);
export function isOwnerView(view: View): boolean {
  return OWNER_VIEWS.has(view);
}
/** Which main section a view belongs to (older views open inside AI or Settings). */
export function workspaceOf(view: View): View {
  if (view === "owner") return "settings";
  if (["overview", "data", "activity", "training", "models", "evolution"].includes(view)) return "intelligence";
  return view;
}
export function navigate(view: View) {
  const legacy: Partial<Record<View, string>> = { overview: "evolution", training: "evolution", data: "data", activity: "history", evolution: "history", models: "model" };
  if (legacy[view]) { appStore.setState({ view: "intelligence", intelligenceTab: aiTab(legacy[view]) }); return; }
  appStore.setState({ view });
}
