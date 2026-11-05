import { Button } from "@/components/ui/button";
import { MothEmblem, Wordmark } from "./MothEmblem";

export function Splash({ status, error, onRetry }: { status: string; error?: string | null; onRetry?: () => void }) {
  return (
    <div className="relative flex h-full flex-col items-center justify-center overflow-hidden bg-bg">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_42%,rgba(193,18,31,0.13),transparent_55%)]" />
      <MothEmblem className="h-36 w-36 animate-rise" glow />
      <Wordmark className="mt-6 text-lg animate-rise" />
      <div className="mt-8 h-5 text-xs text-muted animate-fade-in">
        {error ? <span className="text-danger">{status}</span> : status}
      </div>
      {!error && (
        <div className="mt-3 h-px w-40 overflow-hidden bg-surface-3">
          <div className="h-full w-1/3 animate-[splash_1.2s_ease-in-out_infinite] bg-accent shadow-[0_0_10px_#C1121F]" />
        </div>
      )}
      {error && (
        <div className="mt-4 flex max-w-lg flex-col items-center gap-3 animate-fade-in">
          <pre className="selectable max-h-48 w-full overflow-auto rounded-md border border-border bg-surface p-3 text-[11px] text-muted whitespace-pre-wrap">
            {error}
          </pre>
          {onRetry && <Button onClick={onRetry}>Retry</Button>}
        </div>
      )}
      <style>{`@keyframes splash { 0% { transform: translateX(-100%) } 100% { transform: translateX(300%) } }`}</style>
    </div>
  );
}
