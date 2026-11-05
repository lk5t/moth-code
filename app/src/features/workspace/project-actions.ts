import { open } from "@tauri-apps/plugin-dialog";
import { get, isTauri, post } from "@/lib/backend";
import { appStore, type Project } from "@/lib/app-state";

export async function loadProjects() {
  const projects = await get<Project[]>("/api/projects");
  appStore.setState({ projects });
  return projects;
}

export async function openProjectPath(path: string) {
  const project = await post<Project>("/api/projects", { path });
  appStore.setState({ project, openFiles: [], activeFile: null, view: "workspace", explorerOpen: true });
  try {
    localStorage.setItem("moth.lastProject", String(project.id));
  } catch {
    /* storage unavailable */
  }
  await loadProjects();
}

/** Ask the user for a folder. Opening it authorises it as a MOTH workspace. */
export async function pickProject() {
  let path: string | null = null;
  if (isTauri()) {
    const res = await open({ directory: true, multiple: false, title: "Open workspace folder" });
    path = typeof res === "string" ? res : null;
  } else {
    path = window.prompt("Workspace folder path");
  }
  if (path) await openProjectPath(path);
}
