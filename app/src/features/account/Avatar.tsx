import { cn } from "@/lib/utils";

export function Avatar({ name, url, size = 28, className }: { name: string; url?: string | null; size?: number; className?: string }) {
  const initials = name.slice(0, 2).toUpperCase();
  return url ? (
    <img src={url} alt="" width={size} height={size} className={cn("rounded-full border border-border object-cover", className)} style={{ width: size, height: size }} />
  ) : (
    <span
      className={cn("inline-flex items-center justify-center rounded-full border border-accent/50 bg-accent-soft font-semibold text-[#ff6b75]", className)}
      style={{ width: size, height: size, fontSize: size * 0.38 }}
    >
      {initials}
    </span>
  );
}
