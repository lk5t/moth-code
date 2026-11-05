/**
 * Backend discovery and HTTP client.
 *
 * Inside the desktop app the Rust shell launches the Python backend and
 * exposes its port and per-launch API token via the `backend_info` command.
 * In a plain browser (`npm run dev` without Tauri) we fall back to
 * VITE_MOTH_BACKEND (default http://127.0.0.1:8765) with no token, which
 * matches `python -m moth.server --port 8765`.
 */
import { invoke } from "@tauri-apps/api/core";

export type BackendStatus = "starting" | "ready" | "failed";

export interface BackendInfo {
  status: BackendStatus;
  url: string;
  token: string;
  error?: string | null;
  logs?: string[];
}

export const isTauri = (): boolean => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let cached: BackendInfo | null = null;

export async function fetchBackendInfo(): Promise<BackendInfo> {
  if (isTauri()) {
    const info = await invoke<BackendInfo>("backend_info");
    if (info.status === "ready") cached = info;
    return info;
  }
  const url = (import.meta.env.VITE_MOTH_BACKEND as string | undefined) ?? "http://127.0.0.1:8765";
  try {
    const r = await fetch(`${url}/api/health`);
    if (!r.ok) throw new Error(`health check returned ${r.status}`);
    cached = { status: "ready", url, token: (import.meta.env.VITE_MOTH_TOKEN as string | undefined) ?? "" };
    return cached;
  } catch (e) {
    return { status: "starting", url, token: "", error: `Backend not reachable at ${url}: ${String(e)}` };
  }
}

export async function restartBackend(): Promise<void> {
  cached = null;
  if (isTauri()) await invoke("restart_backend");
}

export function backend(): BackendInfo {
  if (!cached) throw new Error("backend not ready");
  return cached;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const b = backend();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (b.token) headers.Authorization = `Bearer ${b.token}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const res = await fetch(b.url + path, { ...init, headers, body });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T,>(path: string) => api<T>(path);
export const post = <T,>(path: string, json?: unknown) => api<T>(path, { method: "POST", json: json ?? {} });
export const put = <T,>(path: string, json: unknown) => api<T>(path, { method: "PUT", json });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });
