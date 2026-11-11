import { createStore } from "./store";

export interface Project {
  id: number;
  path: string;
  name: string;
  last_opened: number;
}

export interface OpenFile {
  path: string;
  content: string;
  saved: string;
  language: string;
}

export type View = "overview" | "data" | "activity" | "chat" | "workspace" | "intelligence" | "evolution" | "network" | "owner" | "training" | "models" | "settings";
/** AI workspace sections. Older names (overview, training, improvements, advanced) remain accepted and map onto them. */
export type AiTab = "evolution" | "data" | "history" | "settings";
export type IntelligenceTab = AiTab | "overview" | "training" | "improvements" | "advanced" | "network";
export function aiTab(tab: IntelligenceTab | string | undefined): AiTab {
  if (tab === "data" || tab === "history" || tab === "settings") return tab;
  if (tab === "improvements") return "history";
  if (tab === "advanced") return "settings";
  return "evolution";
}

function navigation(): Partial<AppState> {
  try {
    const n = JSON.parse(localStorage.getItem("moth.navigation") ?? "{}");
    return {
      view: ["overview", "data", "activity", "chat", "workspace", "intelligence", "evolution", "network", "training", "models", "owner", "settings"].includes(n.view) ? n.view : "chat",
      workspaceMode: n.workspaceMode === "code" ? "code" : "chat",
      intelligenceTab: aiTab(n.intelligenceTab),
      ...(typeof n.sidebarCollapsed === "boolean" ? {sidebarCollapsed:n.sidebarCollapsed} : {}),
      ...(typeof n.explorerOpen === "boolean" ? { explorerOpen: n.explorerOpen } : {}),
      ...(typeof n.toolsOpen === "boolean" ? { toolsOpen: n.toolsOpen } : {}),
      ...(typeof n.terminalOpen === "boolean" ? { terminalOpen: n.terminalOpen } : {}),
      ...(n.workspaceLayout && typeof n.workspaceLayout === "object" && Object.values(n.workspaceLayout).every((v) => typeof v === "number" && v >= 0 && v <= 100) ? { workspaceLayout: n.workspaceLayout } : {}),
    };
  } catch { return {}; }
}

export interface AppState {
  view: View;
  project: Project | null;
  projects: Project[];
  openFiles: OpenFile[];
  activeFile: string | null;
  explorerOpen: boolean;
  toolsOpen: boolean;
  terminalOpen: boolean;
  rightTab: string;
  treeVersion: number;
  updateVersion: string | null;
  workspaceMode: "code" | "chat";
  intelligenceTab: IntelligenceTab;
  sidebarCollapsed: boolean;
  chatRequest: {sequence:number; conversationId:number|null;title?:string}|null;
  chatSession: {conversationId:number|null; title:string; busy:boolean};
  workspaceLayout?: Record<string, number>;
}

export const appStore = createStore<AppState>({
  view: "chat",
  project: null,
  projects: [],
  openFiles: [],
  activeFile: null,
  explorerOpen: true,
  toolsOpen: false,
  terminalOpen: false,
  rightTab: "editor",
  treeVersion: 0,
  updateVersion: null,
  workspaceMode: "chat",
  intelligenceTab: "evolution",
  sidebarCollapsed: false,
  chatRequest: null,
  chatSession: {conversationId:null,title:"New conversation",busy:false},
  ...navigation(),
});

let savedNavigation = "";
appStore.subscribe(() => {
  const s = appStore.getState();
  const mode = s.view === "workspace" ? "code" : s.view === "chat" ? "chat" : s.workspaceMode;
  if (mode !== s.workspaceMode) { appStore.setState({ workspaceMode: mode }); return; }
  try {
    const value = JSON.stringify({ view: s.view, workspaceMode: mode,
      intelligenceTab: s.intelligenceTab, sidebarCollapsed:s.sidebarCollapsed, explorerOpen: s.explorerOpen, toolsOpen: s.toolsOpen,
      terminalOpen: s.terminalOpen, workspaceLayout: s.workspaceLayout });
    if (value !== savedNavigation) { localStorage.setItem("moth.navigation", value); savedNavigation = value; }
  } catch { /* storage unavailable */ }
});

export function openIntelligence(tab: IntelligenceTab = "evolution") {
  if (tab === "network") { appStore.setState({ view: "network" }); return; }
  appStore.setState({ view: "intelligence", intelligenceTab: aiTab(tab) });
}

export const useApp = appStore.useStore;
