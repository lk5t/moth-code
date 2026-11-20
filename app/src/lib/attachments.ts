/** 2.0: files and folders dropped into chat travel inside the message as marked, fenced blocks, so the
 * conversation history (and MOTH) sees them, while the chat shows them as small file chips. */
import { isTauri, post } from "./backend";

export interface Attachment { path: string; name: string; size: number; content: string; truncated: boolean;
  /** 2.4: an image — kept on this computer (``image_id``); ``content`` is the text read from it */
  kind?: "file" | "image"; image_id?: string; note?: string | null }
export interface Skipped { path: string; reason: string }

const MAX_FILE = 120_000, MAX_TOTAL = 300_000;

function fence(text: string): string {
  let f = "```";
  while (text.includes(f)) f += "`";
  return f;
}

export function formatAttachments(message: string, files: Attachment[]): string {
  if (!files.length) return message;
  return message + files.map((f) => {
    if (f.kind === "image") {  // MOTH reads text, not pictures: it gets the text found in the image
      const text = f.content.trim() || `(an image; no text could be read from it${f.note ? `: ${f.note}` : ""})`;
      const ff = fence(text);
      return `\n\n[image: ${f.name.replace(/[\]|]/g, "_")} | ${f.image_id}]\n${ff}text\n${text}\n${ff}`;
    }
    const ff = fence(f.content); return `\n\n[file: ${f.path}]\n${ff}\n${f.content}${f.truncated ? "\n… (cut off here)" : ""}\n${ff}`;
  }).join("");
}

/** The message text without its attached files, plus the attached files. */
export function splitAttachments(text: string): { body: string; files: { path: string; content: string; kind: "file" | "image"; image_id?: string }[] } {
  const files: { path: string; content: string; kind: "file" | "image"; image_id?: string }[] = [];
  const re = /\n*\[(file|image): ([^\]\n]+)\]\n(`{3,})[^\n]*\n([\s\S]*?)\n\3(?=\n|$)/g;
  const body = text.replace(re, (_m, kind: string, ref: string, _f: string, content: string) => {
    if (kind === "image") { const [name, id] = ref.split(" | "); files.push({ path: name, content, kind: "image", image_id: id?.trim() }); }
    else files.push({ path: ref, content, kind: "file" });
    return "";
  });
  return { body: body.trim(), files };
}

export const IMAGE_EXT = /\.(png|jpe?g|gif|bmp|webp)$/i;
const toImage = (i: { id: string; name: string; size: number; text: string; note?: string | null }): Attachment =>
  ({ kind: "image", image_id: i.id, path: i.name, name: i.name, size: i.size, content: i.text, truncated: false, note: i.note });

/** 2.4: screenshots and photos (pasted, dropped or picked): kept on this computer, their text read. */
export async function readImages(list: File[]): Promise<Attachment[]> {
  const out: Attachment[] = [];
  for (const f of list.slice(0, 10)) {
    const data = await new Promise<string>((ok, bad) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = () => bad(r.error); r.readAsDataURL(f); });
    out.push(toImage(await post("/api/attachments/image", { name: f.name || "screenshot.png", data_base64: data })));
  }
  return out;
}

export async function readImagePaths(paths: string[]): Promise<{ files: Attachment[]; skipped: Skipped[] }> {
  const r = await post<{ images: Parameters<typeof toImage>[0][]; skipped: Skipped[] }>("/api/attachments/image-path", { paths });
  return { files: r.images.map(toImage), skipped: r.skipped };
}

/** 2.4: a GitHub repository, folder or file link. */
export async function readLink(url: string, githubToken?: string | null): Promise<{ files: Attachment[]; skipped: Skipped[] }> {
  return post("/api/attachments/link", { url }, githubToken ? { "X-GitHub-Token": githubToken } : undefined);
}

/** An image kept by the local backend, as a URL an <img> can show (the backend needs the token header). */
export async function imageUrl(id: string): Promise<string> {
  const { api } = await import("./backend");
  const blob = await api<Blob>(`/api/attachments/image/${encodeURIComponent(id)}`, { raw: true });
  return URL.createObjectURL(blob);
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
