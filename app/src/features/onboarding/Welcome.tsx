/**
 * First launch: Sign in or create an account → open a workspace → start coding.
 * No server addresses, ports or Python: MOTH Cloud is built in.
 */
import { useState } from "react";
import { FolderOpen, LogIn, UserPlus } from "lucide-react";
import { useAccount } from "@/lib/account";
import { useApp } from "@/lib/app-state";
import { useConnection } from "@/lib/connection";
import { openAccountDialog } from "@/features/account/AccountDialog";
import { pickProject } from "@/features/workspace/project-actions";
import { MothEmblem } from "@/components/MothEmblem";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { createStore } from "@/lib/store";

const SKIP_KEY = "moth.welcome.done";

function readDone(): boolean {
  try {
    return localStorage.getItem(SKIP_KEY) === "1";
  } catch {
    return false;
  }
}

const welcomeStore = createStore({ done: readDone() });

/** Shown on first launch until the user has signed in and opened a workspace (or skipped). */
export function useWelcomeVisible(): boolean {
  const ready = useAccount((s) => s.ready);
  const user = useAccount((s) => s.user);
  const hasSaved = useAccount((s) => s.accounts.length > 0);
  const project = useApp((s) => s.project);
  const isDone = welcomeStore.useStore((s) => s.done);
  if (!ready || isDone) return false;
  return !user ? !hasSaved : !project;
}

function finish() {
  try {
    localStorage.setItem(SKIP_KEY, "1");
  } catch {
    /* storage unavailable */
  }
  welcomeStore.setState({ done: true });
}

function StepDot({ n, active, complete }: { n: number; active: boolean; complete: boolean }) {
  return (
    <span className={cn("flex size-6 items-center justify-center rounded-full border text-[11px] font-medium",
      complete ? "border-accent bg-accent text-white" : active ? "border-accent text-fg" : "border-border text-faint")}>
      {complete ? "✓" : n}
    </span>
  );
}

export function Welcome() {
  const user = useAccount((s) => s.user);
  const connection = useConnection((s) => s.status);
  const [busy, setBusy] = useState(false);
  const step = user ? 2 : 1;

  return (
    <div className="absolute inset-0 z-40 flex items-center justify-center bg-bg/95 backdrop-blur-sm animate-fade-in">
      <div className="flex w-[440px] flex-col items-center gap-6 text-center">
        <MothEmblem className="size-16 drop-shadow-[0_0_18px_rgba(193,18,31,0.45)]" />
        <div>
          <h1 className="text-xl font-semibold">Welcome to MOTH Code</h1>
          <p className="mt-1 text-sm text-muted">An AI coding agent powered by MOTH, its own neural network.</p>
        </div>
        <div className="flex w-full items-center justify-center gap-3 text-xs text-muted">
          <StepDot n={1} active={step === 1} complete={step > 1} /> Sign in
          <span className="h-px w-8 bg-border" />
          <StepDot n={2} active={step === 2} complete={false} /> Open a workspace
          <span className="h-px w-8 bg-border" />
          <StepDot n={3} active={false} complete={false} /> Code
        </div>
        {step === 1 ? (
          <div className="flex w-full flex-col gap-2">
            <Button size="lg" onClick={() => openAccountDialog("login")}><LogIn /> Sign in</Button>
            <Button size="lg" variant="secondary" onClick={() => openAccountDialog("register")}><UserPlus /> Create a free account</Button>
            {connection === "offline" && (
              <p className="text-xs text-warning">MOTH Cloud can't be reached right now — MOTH Code keeps trying in the background.</p>
            )}
          </div>
        ) : (
          <div className="flex w-full flex-col gap-2">
            <p className="text-sm">Signed in as <span className="text-fg">{user?.display_name || user?.username}</span>. Now open the folder you want to work in.</p>
            <Button size="lg" disabled={busy} onClick={async () => {
              setBusy(true);
              try {
                await pickProject();
                finish();
              } finally {
                setBusy(false);
              }
            }}><FolderOpen /> Open a workspace</Button>
          </div>
        )}
        <button className="cursor-pointer text-xs text-faint hover:text-fg" onClick={finish}>
          {step === 1 ? "Continue without signing in (editor, terminal and Git work offline)" : "Skip for now"}
        </button>
      </div>
    </div>
  );
}
