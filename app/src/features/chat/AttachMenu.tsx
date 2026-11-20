/** 2.4: what can go into a message — files, a whole folder, screenshots and photos, or a GitHub link. */
import { useRef, useState } from "react";
import { FileText, FolderOpen, GitBranch, Image as ImageIcon, Loader2, Paperclip } from "lucide-react";
import { IMAGE_EXT, readFiles, readImagePaths, readImages, readLink, readPaths, type Attachment, type Skipped } from "@/lib/attachments";
import { isTauri } from "@/lib/backend";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export type Added = { files: Attachment[]; skipped: Skipped[] };

/** Files from a browser drop, paste or picker: images get their text read, other files are read as text. */
export async function ingestFiles(list: FileList | File[]): Promise<Added> {
  const all = Array.from(list);
  const images = all.filter((f) => f.type.startsWith("image/") || IMAGE_EXT.test(f.name));
  const rest = all.filter((f) => !images.includes(f));
  const text = rest.length ? await readFiles(rest) : { files: [], skipped: [] };
  return { files: [...(images.length ? await readImages(images) : []), ...text.files], skipped: text.skipped };
}

/** Paths dropped onto the desktop window. */
export async function ingestPaths(paths: string[]): Promise<Added> {
  const images = paths.filter((p) => IMAGE_EXT.test(p)), rest = paths.filter((p) => !IMAGE_EXT.test(p));
  const [a, b] = await Promise.all([images.length ? readImagePaths(images) : { files: [], skipped: [] }, rest.length ? readPaths(rest) : { files: [], skipped: [] }]);
  return { files: [...a.files, ...b.files], skipped: [...a.skipped, ...b.skipped] };
}

async function githubTokenOrNull(): Promise<string | null> {
  if (!isTauri()) return null;
  try { return await (await import("@/lib/github")).githubToken(); } catch { return null; }
}

export function AttachMenu({ disabled, onAdd, onError }: { disabled?: boolean; onAdd: (r: Added) => void; onError: (m: string) => void }) {
  const files = useRef<HTMLInputElement>(null), folder = useRef<HTMLInputElement>(null), images = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false), [link, setLink] = useState(""), [busy, setBusy] = useState<string | null>(null);
  const run = async (label: string, job: () => Promise<Added>) => {
    setBusy(label);
    try { onAdd(await job()); setOpen(false); setLink(""); } catch (e) { onError((e as Error).message); } finally { setBusy(null); }
  };
  const pickFolder = async () => {
    if (!isTauri()) { folder.current?.click(); return; }
    const { open: dialog } = await import("@tauri-apps/plugin-dialog");
    const dir = await dialog({ directory: true, multiple: false, title: "Attach a folder" });
    if (typeof dir === "string") await run("folder", () => readPaths([dir]));
  };
  const item = "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50";
  return <>
    <input ref={files} type="file" multiple hidden onChange={(e) => { const f = e.target.files; if (f?.length) void run("files", () => ingestFiles(f)); e.target.value = ""; }} />
    <input ref={images} type="file" accept="image/*" multiple hidden onChange={(e) => { const f = e.target.files; if (f?.length) void run("image", () => ingestFiles(f)); e.target.value = ""; }} />
    {/* browsers: a folder picker (the desktop app uses the system folder dialog) */}
    <input ref={folder} type="file" multiple hidden {...{ webkitdirectory: "", directory: "" }}
      onChange={(e) => { const f = e.target.files; if (f?.length) void run("folder", () => readFiles(f)); e.target.value = ""; }} />
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="icon-sm" variant="ghost" title="Attach files, a folder, an image or a GitHub link" aria-label="Attach" disabled={disabled}>
          {busy ? <Loader2 className="animate-spin" /> : <Paperclip />}</Button>
      </PopoverTrigger>
      <PopoverContent align="start" side="top" className="w-72">
        <button className={item} onClick={() => files.current?.click()}><FileText className="size-3.5 text-accent" />Files</button>
        <button className={item} onClick={() => void pickFolder()}><FolderOpen className="size-3.5 text-accent" />Folder</button>
        <button className={item} onClick={() => images.current?.click()}><ImageIcon className="size-3.5 text-accent" />Screenshot or photo
          <span className="ml-auto text-[0.625rem] text-faint">or paste it</span></button>
        <form className="mt-1 border-t border-border px-1 pt-1.5" onSubmit={(e) => { e.preventDefault(); if (link.trim()) void run("link", async () => readLink(link.trim(), await githubTokenOrNull())); }}>
          <label className="mb-1 flex items-center gap-2 px-1 text-xs text-muted"><GitBranch className="size-3.5 text-accent" />GitHub link</label>
          <div className="flex gap-1">
            <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://github.com/owner/repo" aria-label="GitHub link"
              className="h-7 min-w-0 flex-1 rounded-md border border-border bg-bg px-2 text-xs outline-none focus:border-accent/60" />
            <Button size="sm" type="submit" disabled={!link.trim() || busy === "link"}>{busy === "link" ? <Loader2 className="animate-spin" /> : "Add"}</Button>
          </div>
          <p className="mt-1 px-1 text-[0.625rem] text-faint">A repository, folder or file. Text files only, never secrets.</p>
        </form>
        <p className="mt-1.5 border-t border-border px-2 pt-1.5 text-[0.625rem] text-faint">MOTH reads text, not pictures: for an image it gets the text in it.</p>
      </PopoverContent>
    </Popover>
  </>;
}
