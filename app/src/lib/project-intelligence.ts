import { api } from "./backend";
import { accountStore } from "./account";

/** Bind local requests to the session that initiated them, without sending Cloud credentials. */
export async function projectApi<T>(path: string, method = "GET", json?: unknown): Promise<T> {
  const {serverUrl, token} = accountStore.getState();
  const profile = token && serverUrl
    ? Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(serverUrl.replace(/\/+$/, "") + "\0" + token))), b => b.toString(16).padStart(2, "0")).join("")
    : "device-local";
  const current = accountStore.getState();
  if (current.token !== token || current.serverUrl !== serverUrl) throw new Error("Account changed. Retry in the current account.");
  return api<T>(path, {method, json, headers: {"X-Moth-Profile": profile}});
}
