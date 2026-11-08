import Editor from "@monaco-editor/react";
import { Code2, X } from "lucide-react";
import "./monaco-setup";
import { useApp, appStore } from "@/lib/app-state";
import { EmptyState } from "@/components/ui/empty";
import { cn } from "@/lib/utils";
import { closeFile, saveFile, updateFile } from "./workspace-actions";

export function EditorPanel() {
  const files = useApp((s) => s.openFiles);
  const active = useApp((s) => s.activeFile);
  const file = files.find((f) => f.path === active);

  if (!files.length) {
    return (
      <EmptyState icon={<Code2 />} title="No file open">
        Select a file in the explorer, or ask MOTH to work on your project.
      </EmptyState>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div role="tablist" aria-label="Open files" className="flex h-9 shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-bg px-1">
        {files.map((f, index) => {
          const dirty = f.content !== f.saved;
          return (
            <div
              key={f.path}
              role="tab"
              aria-selected={f.path === active}
              tabIndex={f.path === active ? 0 : -1}
              onClick={() => appStore.setState({ activeFile: f.path })}
              onKeyDown={(event) => {
                const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
                if (!delta) return;
                event.preventDefault();
                const next = (index + delta + files.length) % files.length;
                appStore.setState({ activeFile: files[next].path });
                (event.currentTarget.parentElement?.querySelectorAll<HTMLElement>('[role="tab"]')[next])?.focus();
              }}
              className={cn(
                "group flex h-7 shrink-0 cursor-pointer items-center gap-2 rounded-md px-2.5 text-xs text-muted hover:bg-surface-2 hover:text-fg",
                f.path === active && "bg-surface-3 text-fg shadow-[inset_0_-2px_0_#C1121F]",
              )}
              title={f.path}
            >
              <span className="max-w-40 truncate">{f.path.split("/").pop()}</span>
              <button
                aria-label={`Close ${f.path.split("/").pop()}`}
                className="flex size-4 items-center justify-center rounded hover:bg-surface-3 cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation();
                  if (dirty && !window.confirm(`Discard unsaved changes to ${f.path}?`)) return;
                  closeFile(f.path);
                }}
              >
                {dirty ? <span className="size-2 rounded-full bg-accent group-hover:hidden" /> : null}
                <X className={cn("size-3", dirty && "hidden group-hover:block")} />
              </button>
            </div>
          );
        })}
      </div>
      {file && (
        <div className="min-h-0 flex-1">
          <Editor
            key={file.path}
            path={file.path}
            theme="moth"
            language={file.language}
            value={file.content}
            onChange={(v) => updateFile(file.path, v ?? "")}
            onMount={(editor, monaco) => {
              editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => saveFile(file.path));
            }}
            options={{
              fontFamily: "'Cascadia Code', 'Cascadia Mono', Consolas, monospace",
              fontSize: 13,
              fontLigatures: true,
              minimap: { enabled: false },
              smoothScrolling: true,
              cursorSmoothCaretAnimation: "on",
              scrollBeyondLastLine: false,
              renderLineHighlight: "line",
              padding: { top: 8 },
              automaticLayout: true,
            }}
          />
        </div>
      )}
    </div>
  );
}
