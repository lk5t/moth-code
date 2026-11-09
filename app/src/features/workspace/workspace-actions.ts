import { get, put } from "@/lib/backend";
import { appStore, type OpenFile } from "@/lib/app-state";
import { projectApi } from "@/lib/project-intelligence";
import { languageFromPath } from "@/lib/utils";

export async function openFile(path: string) {
  const s = appStore.getState();
  if (!s.project) return;
  if (!s.openFiles.some((f) => f.path === path)) {
    const res = await get<{ content: string }>(`/api/projects/${s.project.id}/file?path=${encodeURIComponent(path)}`);
    if (appStore.getState().project?.id !== s.project.id) return;
    const file: OpenFile = { path, content: res.content, saved: res.content, language: languageFromPath(path) };
    appStore.setState((st) => ({ openFiles: [...st.openFiles, file] }));
  }
  if (appStore.getState().project?.id !== s.project.id) return;
  void projectApi(`/api/projects/${s.project.id}/intelligence/inspected`, "POST", {path}).catch(() => {});
  appStore.setState({ activeFile: path, toolsOpen: true, rightTab: "editor" });
}

export function updateFile(path: string, content: string) {
  appStore.setState((st) => ({ openFiles: st.openFiles.map((f) => (f.path === path ? { ...f, content } : f)) }));
}

export async function saveFile(path: string) {
  const s = appStore.getState();
  const f = s.openFiles.find((x) => x.path === path);
  if (!s.project || !f) return;
  await put(`/api/projects/${s.project.id}/file`, { path, content: f.content });
  if(appStore.getState().project?.id!==s.project.id)return;
  appStore.setState((st) => ({ openFiles: st.openFiles.map((x) => (x.path === path ? { ...x, saved: f.content } : x)) }));
}

export function closeFile(path: string) {
  appStore.setState((st) => {
    const openFiles = st.openFiles.filter((f) => f.path !== path);
    const activeFile = st.activeFile === path ? (openFiles[openFiles.length - 1]?.path ?? null) : st.activeFile;
    return { openFiles, activeFile };
  });
}

/** Reload open, unmodified files after something else (e.g. the agent) changed them on disk. */
export async function refreshOpenFile(path: string) {
  const s = appStore.getState();
  const f = s.openFiles.find((x) => x.path === path);
  if (!s.project || !f || f.content !== f.saved) return;
  try {
    const res = await get<{ content: string }>(`/api/projects/${s.project.id}/file?path=${encodeURIComponent(path)}`);
    if(appStore.getState().project?.id!==s.project.id)return;
    appStore.setState((st) => ({
      openFiles: st.openFiles.map((x) => (x.path === path && x.content === x.saved ? { ...x, content: res.content, saved: res.content } : x)),
    }));
  } catch {
    if(appStore.getState().project?.id===s.project.id && appStore.getState().openFiles.find(x=>x.path===path)?.content===f.content) closeFile(path); // deleted; keep newer edits
  }
}
