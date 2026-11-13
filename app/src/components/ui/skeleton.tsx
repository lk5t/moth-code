import { cn } from "@/lib/utils";

/** A quiet placeholder while real data loads (0.7.2). Announced once to screen readers via `label`. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("shimmer rounded-md bg-surface-2", className)} />;
}

export function LoadingBlock({ label, lines = 3, className }: { label: string; lines?: number; className?: string }) {
  return <div role="status" aria-label={label} className={cn("flex flex-col gap-2 animate-fade-in", className)}>
    <span className="sr-only">{label}</span>
    <Skeleton className="h-5 w-1/3" />
    {Array.from({ length: lines }, (_, i) => <Skeleton key={i} className={cn("h-3", i % 2 ? "w-2/3" : "w-full")} />)}
  </div>;
}
