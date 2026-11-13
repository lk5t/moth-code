import { cn } from "@/lib/utils";

export function Progress({ value, className }: { value: number; className?: string }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <div className={cn("h-1 w-full overflow-hidden rounded-full bg-surface-3", className)}>
      <div className={cn("h-full rounded-full bg-accent shadow-[0_0_10px_rgb(193_18_31/0.7)] transition-[width] duration-700 ease-out", v > 0 && v < 100 && "progress-live")} style={{ width: `${v}%` }} />
    </div>
  );
}
