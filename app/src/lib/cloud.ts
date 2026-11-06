/** MOTH Cloud status (via the local backend, which talks to the signed-in account's server). */
import { useEffect, useState } from "react";
import { get } from "./backend";
import { useEvent } from "./events";

export interface CloudStatus {
  signed_in: boolean;
  reachable: boolean | null;
  available: boolean;
  model?: { name: string; params?: number; context_length?: number };
  error?: string;
  /** why it isn't available: unreachable | not_moth | no_model_deployed | inference_disabled */
  reason?: string;
}

export function useCloudStatus(pollMs = 60000) {
  const [status, setStatus] = useState<CloudStatus | null>(null);
  const load = () => get<CloudStatus>("/api/cloud/status").then(setStatus).catch(() => setStatus(null));
  useEffect(() => {
    load();
    const t = setInterval(load, pollMs);
    return () => clearInterval(t);
  }, []);
  useEvent("account", () => load());
  return { status, reload: load };
}
