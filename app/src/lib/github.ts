/** 1.0 GitHub connection: the token lives in the OS credential vault (desktop shell) and is sent to the
 * local backend only with each GitHub request. */
import { api } from "./backend";
import { isTauri } from "./backend";

async function vault<T>(cmd: string, args: Record<string, unknown>): Promise<T> {
  if (!isTauri()) throw new Error("GitHub connections need the MOTH Code desktop app.");
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

export const githubToken = () => vault<string | null>("connection_get", { name: "github" });
export const saveGithubToken = (token: string) => vault<void>("connection_set", { name: "github", token });
export const forgetGithub = () => vault<void>("connection_delete", { name: "github" });

export async function gh<T>(path: string, json?: unknown, token?: string): Promise<T> {
  const t = token ?? (await githubToken());
  if (!t) throw new Error("Connect GitHub first (Settings → Connections).");
  return api<T>(path, { method: json === undefined ? "GET" : "POST", headers: { "X-GitHub-Token": t },
    ...(json === undefined ? {} : { json }) });
}

export const TOKEN_PAGE = "https://github.com/settings/personal-access-tokens/new";
