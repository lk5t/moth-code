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
      <div className="flex h-8 shrink-0 items-stretch overflow-x-auto border-b border-border bg-bg">
        {files.map((f) => {
          const dirty = f.content !== f.saved;
          return (
            <div
              key={f.path}
              onClick={() => appStore.setState({ activeFile: f.path })}
              className={cn(
                "group flex cursor-pointer items-center gap-2 border-r border-border px-3 text-xs text-muted hover:text-fg",
                f.path === active && "bg-surface text-fg shadow-[inset_0_1px_0_#C1121F]",
              )}
              title={f.path}
            >
              <span className="max-w-40 truncate">{f.path.split("/").pop()}</span>
              <button
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
