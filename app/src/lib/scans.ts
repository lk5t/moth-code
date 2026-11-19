/** 2.0 chat pentesting: scans run by the local backend, from this computer, after a Yes. */
import { useEffect, useState } from "react";
import { get, post } from "./backend";
import { useEvent } from "./events";

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];
export interface ScanPlan { target: string; hosts: number; ports: number[]; port_count: number; default_ports: boolean; describe: string }
export interface Finding { severity: Severity; title: string; port: number | null; evidence: string; fix: string; host: string; ref: string }
export interface StrongerStep { id: string; check: string; host: string; port: number; status: "offered" | "done"; title: string; what: string; result?: string }
export interface Scan {
  id: string; target: string; hosts: string[]; ports: number[]; confirmed_at: number; status: "running" | "done" | "stopped" | "error";
  phase: string; progress: number; started_at: number; finished_at: number | null;
  open_ports: { host: string; port: number; service: string; banner: string }[];
  findings: Finding[]; stronger: StrongerStep[]; error: string | null; counts: Record<Severity, number>;
  log?: { at: number; action: string; [k: string]: unknown }[]; log_count?: number;
}

export const parseScan = (message: string) => post<{ plan: ScanPlan | null; refused: string | null }>("/api/scans/parse", { message });
export const startScan = (message: string) => post<Scan>("/api/scans", { message, confirmed: true });
export const stopScan = (id: string) => post(`/api/scans/${id}/stop`);
export const stopAllScans = () => post("/api/scans/stop-all");
export const runStronger = (id: string, step_id: string) => post<Scan>(`/api/scans/${id}/stronger`, { step_id, confirmed: true });
export const scanToChat = (id: string, conversation_id: number | null, question: string) =>
  post<{ conversation_id: number; message_id: number }>(`/api/scans/${id}/to-chat`, { conversation_id, question });

/** A scan kept up to date by live events. */
export function useScan(id: string | null) {
  const [scan, setScan] = useState<Scan | null>(null);
  useEffect(() => { if (id) get<Scan>(`/api/scans/${id}`).then(setScan).catch(() => {}); else setScan(null); }, [id]);
  useEvent("scan", (e) => { if (id && e.scan?.id === id) setScan((cur) => ({ ...(cur ?? {}), ...e.scan, log: cur?.log })); });
  return [scan, setScan] as const;
}

export const SEV_STYLE: Record<Severity, string> = {
  critical: "bg-[#ff2d3d]/18 text-[#ff6b75] border-[#ff2d3d]/45",
  high: "bg-danger/12 text-danger border-danger/30",
  medium: "bg-warning/12 text-warning border-warning/30",
  low: "bg-[#7aa2f7]/12 text-[#9db8ff] border-[#7aa2f7]/30",
  info: "bg-surface-3 text-muted border-border",
};
