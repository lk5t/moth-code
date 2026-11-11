/** Conversation management on this computer: rename, delete selected, clear all (0.6.2). */
import { api } from "./backend";

export type DeleteResult = { deleted: number[]; missing: number[]; failed: { id: number; error: string }[] };

export const renameConversation = (id: number, title: string) =>
  api<{ id: number; title: string }>(`/api/conversations/${id}`, { method: "PATCH", json: { title } });

export const deleteConversations = (ids: number[]) =>
  api<DeleteResult>("/api/conversations/delete", { method: "POST", json: { ids } });

export const clearConversations = (confirm: string) =>
  api<DeleteResult>("/api/conversations/delete", { method: "POST", json: { all: true, confirm } });

/** A plain sentence for what happened, including partial failures. */
export function describeDelete(r: DeleteResult): string | null {
  if (!r.failed.length) return null;
  return `${r.deleted.length} deleted; ${r.failed.length} could not be deleted (${r.failed[0].error}). Try again.`;
}
