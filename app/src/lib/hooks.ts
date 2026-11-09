import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";
import { get } from "./backend";
import { useEvent } from "./events";

/** Coalesced event refresh with account/path isolation and late-response protection. */
export function useResource<T>(path: string | null, topics: string[] = [], initial?: T, scope = "", loader: (path: string) => Promise<T> = get) {
  const key = JSON.stringify([path, scope]);
  const current = useRef(key); current.current = key;
  const mounted = useRef(false), sequence = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [result, setResult] = useState<{key: string; data: T | undefined; error: string | null}>({key, data: initial, error: null});
  const reload = useCallback(async () => {
    if (!path) return;
    const request = ++sequence.current;
    try {
      const data = await loader(path);
      if (mounted.current && current.current === key && request === sequence.current) setResult({key, data, error: null});
    } catch (e) {
      if (mounted.current && current.current === key && request === sequence.current)
        setResult(previous => ({key, data: previous.key === key ? previous.data : initial, error: String((e as Error).message ?? e)}));
    }
  }, [path, key, loader]);
  useEffect(() => {
    mounted.current = true; void reload();
    return () => { mounted.current = false; ++sequence.current; if (timer.current) clearTimeout(timer.current); timer.current = null; };
  }, [reload]);
  useEvent("*", (e) => {
    if (!topics.includes(e.topic) || timer.current) return;
    timer.current = setTimeout(() => { timer.current = null; void reload(); }, 300);
  });
  const setData = useCallback((value: SetStateAction<T | undefined>) => {
    setResult(previous => ({key, error: null, data: typeof value === "function" ? (value as (v: T | undefined) => T | undefined)(previous.key === key ? previous.data : initial) : value}));
  }, [key]);
  return {data: result.key === key ? result.data : initial, error: result.key === key ? result.error : null, reload, setData};
}
