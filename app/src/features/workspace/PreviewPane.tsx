/**
 * 1.0 live preview: when a command in the terminal starts a local web server, its page opens here and
 * reloads by itself whenever a file in the workspace changes (including MOTH's edits).
 */
import { useEffect, useRef, useState } from "react";
import { ExternalLink, Globe, RotateCw, X } from "lucide-react";
import { createStore } from "@/lib/store";
import { useEvent } from "@/lib/events";
import { openExternal } from "@/lib/external";
import { Button } from "@/components/ui/button";

export const previewStore = createStore<{ url: string | null; open: boolean }>({ url: null, open: false });
export const usePreview = previewStore.useStore;

const URL_RX = /(https?:\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::\d{2,5})(?:\/[^\s'"<>]*)?)/;

/** The local address a dev server printed, normalised for the preview (null when none). */
export function spotPreviewUrl(text: string): string | null {
  const m = text.match(URL_RX);
  return m ? m[1].replace("0.0.0.0", "localhost").replace("[::1]", "localhost").replace(/[.,)]+$/, "") : null;
}

export function PreviewPane() {
  const { url, open } = usePreview((s) => s);
  const frame = useRef<HTMLIFrameElement>(null);
  const [stamp, setStamp] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEvent("files", () => {  // live: reload shortly after files change
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setStamp((n) => n + 1), 700);
  });
  useEffect(() => () => clearTimeout(timer.current), []);
  if (!url || !open) return null;
  return <section aria-label="Live preview" className="animate-pop fixed bottom-10 right-4 z-40 flex h-[55vh] w-[min(560px,calc(100vw-32px))] flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-2xl">
    <div className="flex h-8 shrink-0 items-center gap-1.5 border-b border-border px-2 text-xs">
      <Globe className="size-3.5 text-accent" /><span className="live-dot" />
      <span className="min-w-0 flex-1 truncate text-muted">{url}</span>
      <Button size="icon-sm" variant="ghost" title="Reload" onClick={() => setStamp((n) => n + 1)}><RotateCw /></Button>
      <Button size="icon-sm" variant="ghost" title="Open in your browser" onClick={() => void openExternal(url)}><ExternalLink /></Button>
      <Button size="icon-sm" variant="ghost" title="Close preview" onClick={() => previewStore.setState({ open: false })}><X /></Button>
    </div>
    <iframe ref={frame} key={stamp} title="Live preview" src={url} className="min-h-0 flex-1 bg-white" sandbox="allow-scripts allow-forms allow-same-origin allow-popups" />
  </section>;
}
