/** 2.0: files and folders dropped into chat travel inside the message as marked, fenced blocks, so the
 * conversation history (and MOTH) sees them, while the chat shows them as small file chips. */
import { isTauri, post } from "./backend";

export interface Attachment { path: string; name: string; size: number; content: string; truncated: boolean }
export interface Skipped { path: string; reason: string }

const MAX_FILE = 120_000, MAX_TOTAL = 300_000;

function fence(text: string): string {
  let f = "```";
  while (text.includes(f)) f += "`";
  return f;
}

export function formatAttachments(message: string, files: Attachment[]): string {
  if (!files.length) return message;
  return message + files.map((f) => { const ff = fence(f.content); return `\n\n[file: ${f.path}]\n${ff}\n${f.content}${f.truncated ? "\n… (cut off here)" : ""}\n${ff}`; }).join("");
}

/** The message text without its attached files, plus the attached files. */
export function splitAttachments(text: string): { body: string; files: { path: string; content: string }[] } {
  const files: { path: string; content: string }[] = [];
  const re = /\n*\[file: ([^\]\n]+)\]\n(`{3,})[^\n]*\n([\s\S]*?)\n\2(?=\n|$)/g;
  const body = text.replace(re, (_m, path: string, _f: string, content: string) => { files.push({ path, content }); return ""; });
  return { body: body.trim(), files };
}

/** Paths from the desktop app (Tauri drag and drop): read by the local backend. */
export async function readPaths(paths: string[]): Promise<{ files: Attachment[]; skipped: Skipped[] }> {
  return post("/api/attachments/read", { paths });
}

/** Files from a browser drop or file picker. */
export async function readFiles(list: FileList | File[]): Promise<{ files: Attachment[]; skipped: Skipped[] }> {
  const files: Attachment[] = [], skipped: Skipped[] = [];
  let total = 0;
  for (const f of Array.from(list).slice(0, 30)) {
    if (/(^\.env|\.pem$|\.key$|^id_(rsa|ed25519|ecdsa)|credentials)/i.test(f.name)) { skipped.push({ path: f.name, reason: "looks like a secret (key, .env or credentials)" }); continue; }
    if (total >= MAX_TOTAL) { skipped.push({ path: f.name, reason: "limit reached" }); continue; }
    const limit = Math.min(MAX_FILE, MAX_TOTAL - total);
    const text = await f.slice(0, limit + 1).text();
    if (text.includes("\u0000")) { skipped.push({ path: f.name, reason: "not a text file" }); continue; }
    const content = text.slice(0, limit);
    total += content.length;
    files.push({ path: (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name, name: f.name, size: f.size, content, truncated: text.length > limit });
  }
  return { files, skipped };
}

/** Listen for files dragged onto the desktop window. Returns an unsubscribe function. */
export async function onDesktopDrop(handlers: { over: (on: boolean) => void; drop: (paths: string[]) => void }): Promise<() => void> {
  if (!isTauri()) return () => {};
  const { getCurrentWebview } = await import("@tauri-apps/api/webview");
  return getCurrentWebview().onDragDropEvent((e) => {
    const p = e.payload as { type: string; paths?: string[] };
    if (p.type === "enter" || p.type === "over") handlers.over(true);
    else if (p.type === "leave") handlers.over(false);
    else if (p.type === "drop") { handlers.over(false); if (p.paths?.length) handlers.drop(p.paths); }
  });
}

export function formatBytes(n: number): string {
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
}
