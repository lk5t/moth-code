import { useState } from "react";

/** Persist navigation preferences only, never unsaved form data or credentials. */
export function useSavedSection<T extends string>(key: string, allowed: readonly T[], fallback: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try { const saved = localStorage.getItem(`moth.section.${key}`) as T; return allowed.includes(saved) ? saved : fallback; }
    catch { return fallback; }
  });
  return [value, (next: T) => { if (!allowed.includes(next)) return; setValue(next);
    try { localStorage.setItem(`moth.section.${key}`, next); } catch { /* navigation still works */ }
  }];
}
