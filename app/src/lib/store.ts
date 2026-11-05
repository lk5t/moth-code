/** Minimal global store (no external dependency) built on useSyncExternalStore. */
import { useSyncExternalStore } from "react";

export function createStore<T extends object>(initial: T) {
  let state = initial;
  const subs = new Set<() => void>();
  const getState = () => state;
  const setState = (patch: Partial<T> | ((s: T) => Partial<T>)) => {
    const next = typeof patch === "function" ? patch(state) : patch;
    state = { ...state, ...next };
    subs.forEach((fn) => fn());
  };
  const subscribe = (fn: () => void) => {
    subs.add(fn);
    return () => subs.delete(fn);
  };
  function useStore<U>(selector: (s: T) => U): U {
    return useSyncExternalStore(subscribe, () => selector(state), () => selector(state));
  }
  return { getState, setState, subscribe, useStore };
}
