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

export type View = "chat" | "workspace" | "intelligence" | "evolution" | "network" | "owner" | "training" | "models" | "settings";

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
});

export const useApp = appStore.useStore;
