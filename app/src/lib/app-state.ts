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

export type View = "workspace" | "training" | "models" | "community" | "settings";

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
}

export const appStore = createStore<AppState>({
  view: "workspace",
  project: null,
  projects: [],
  openFiles: [],
  activeFile: null,
  explorerOpen: true,
  toolsOpen: false,
  terminalOpen: false,
  rightTab: "editor",
  treeVersion: 0,
});

export const useApp = appStore.useStore;
