/** Settings → Privacy & AI: how long conversations on this computer are kept (off by default). */
import { useEffect, useState } from "react";
import { get, put } from "@/lib/backend";
import { Card, CardContent } from "@/components/ui/card";

const OPTIONS: [number, string][] = [[0, "Keep until I delete them"], [30, "30 days"], [90, "90 days"], [365, "1 year"]];

export function ChatRetention() {
  const [days, setDays] = useState<number | null>(null), [error, setError] = useState<string | null>(null);
  useEffect(() => { get<Record<string, any>>("/api/settings").then((s) => setDays(typeof s.chat_retention_days === "number" ? s.chat_retention_days : 0)).catch((e) => setError(e.message)); }, []);
  const choose = async (value: number) => {
    setError(null);
    try { await put("/api/settings", { chat_retention_days: value }); setDays(value); } catch (e) { setError((e as Error).message); }
  };
  return <Card><CardContent className="flex flex-wrap items-start justify-between gap-3 p-4">
    <div className="max-w-xl"><p className="text-sm">Conversation history</p>
      <p className="mt-0.5 text-xs text-muted">Chats are stored on this computer only. With a time limit, conversations with no new message for that long are deleted automatically once a day. You can always delete chats yourself from the sidebar.</p>
      {error && <p role="alert" className="mt-1 text-xs text-danger">{error}</p>}</div>
    <select aria-label="Keep conversations" disabled={days === null} value={days ?? 0} onChange={(e) => void choose(Number(e.target.value))}
      className="rounded-md border border-border bg-bg px-2 py-1 text-xs text-fg">
      {OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
    </select>
  </CardContent></Card>;
}
