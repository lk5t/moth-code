import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(digits) + "B";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(digits) + "M";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(digits) + "K";
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
}

export function timeAgo(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function languageFromPath(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript", mjs: "javascript", cjs: "javascript",
    py: "python", rs: "rust", go: "go", java: "java", kt: "kotlin", c: "c", h: "c", cpp: "cpp", cc: "cpp",
    hpp: "cpp", cs: "csharp", rb: "ruby", php: "php", swift: "swift", html: "html", css: "css", scss: "scss",
    json: "json", md: "markdown", yaml: "yaml", yml: "yaml", toml: "ini", ini: "ini", sh: "shell", bash: "shell",
    ps1: "powershell", sql: "sql", xml: "xml", lua: "lua", dart: "dart", dockerfile: "dockerfile",
  };
  return map[ext] ?? "plaintext";
}
