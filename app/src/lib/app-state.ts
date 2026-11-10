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
export type IntelligenceTab = "overview" | "training" | "evolution" | "improvements" | "history" | "advanced" | "network" | "data";

function navigation(): Partial<AppState> {
  try {
    const n = JSON.parse(localStorage.getItem("moth.navigation") ?? "{}");
    return {
      view: ["overview", "data", "activity", "chat", "workspace", "intelligence", "evolution", "network", "training", "models", "owner", "settings"].includes(n.view) ? n.view : "overview",
      workspaceMode: n.workspaceMode === "code" ? "code" : "chat",
      intelligenceTab: ["overview", "training", "evolution", "improvements", "history", "advanced", "network", "data"].includes(n.intelligenceTab) ? n.intelligenceTab : "overview",
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
  workspaceLayout?: Record<string, number>;
}

export const appStore = createStore<AppState>({
  view: "overview",
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
  intelligenceTab: "overview",
  ...navigation(),
});

let savedNavigation = "";
appStore.subscribe(() => {
  const s = appStore.getState();
  const mode = s.view === "workspace" ? "code" : s.view === "chat" ? "chat" : s.workspaceMode;
  if (mode !== s.workspaceMode) { appStore.setState({ workspaceMode: mode }); return; }
  try {
    const value = JSON.stringify({ view: s.view, workspaceMode: mode,
      intelligenceTab: s.intelligenceTab, explorerOpen: s.explorerOpen, toolsOpen: s.toolsOpen,
      terminalOpen: s.terminalOpen, workspaceLayout: s.workspaceLayout });
    if (value !== savedNavigation) { localStorage.setItem("moth.navigation", value); savedNavigation = value; }
  } catch { /* storage unavailable */ }
});

export function openIntelligence(tab: IntelligenceTab = "overview") {
  appStore.setState({ view: tab === "overview" ? "overview" : tab === "data" ? "data" : tab === "network" ? "network" : "intelligence", intelligenceTab: tab });
}

export const useApp = appStore.useStore;
