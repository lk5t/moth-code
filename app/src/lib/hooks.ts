import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./backend";
import { useEvent } from "./events";

/** Fetch a JSON resource and refetch whenever an event on one of `topics` arrives. */
export function useResource<T>(path: string | null, topics: string[] = [], initial?: T) {
  const [data, setData] = useState<T | undefined>(initial);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reload = useCallback(async () => {
    if (!path) return;
    try {
      setData(await get<T>(path));
      setError(null);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }, [path]);
  useEffect(() => {
    reload();
  }, [reload]);
  useEvent("*", (e) => {
    if (!topics.includes(e.topic)) return;
    // coalesce bursts of events (e.g. training metrics) into one refetch
    if (timer.current) return;
    timer.current = setTimeout(() => {
      timer.current = null;
      reload();
    }, 300);
  });
  return { data, error, reload, setData };
}
