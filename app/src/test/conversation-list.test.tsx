import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
const mock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/backend", () => ({ api: mock.api }));
import { ConversationList } from "@/components/ConversationList";
import { appStore } from "@/lib/app-state";
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const chats = [{ id: 1, title: "Parser bug" }, { id: 2, title: "Refactor" }, { id: 3, title: "Docs" }];

it("renames a conversation", async () => {
  const reload = vi.fn(); mock.api.mockResolvedValue({ id: 1, title: "Lexer bug" });
  render(<ConversationList chats={chats} searching={false} reload={reload} />);
  fireEvent.click(screen.getByRole("button", { name: "Options for Parser bug" }));
  fireEvent.click(await screen.findByRole("button", { name: "Rename" }));
  const field = screen.getByRole("textbox", { name: "Conversation name" });
  fireEvent.change(field, { target: { value: "Lexer bug" } }); fireEvent.submit(field.closest("form")!);
  await waitFor(() => expect(mock.api).toHaveBeenCalledWith("/api/conversations/1", { method: "PATCH", json: { title: "Lexer bug" } }));
  expect(reload).toHaveBeenCalled();
});

it("deletes one after confirmation and several selected at once", async () => {
  mock.api.mockResolvedValue({ deleted: [2], missing: [], failed: [] });
  render(<ConversationList chats={chats} searching={false} reload={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Options for Refactor" }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
  expect(mock.api).not.toHaveBeenCalled();  // nothing happens before the confirmation
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(mock.api).toHaveBeenCalledWith("/api/conversations/delete", { method: "POST", json: { ids: [2] } }));
  mock.api.mockResolvedValue({ deleted: [1, 3], missing: [], failed: [] });
  fireEvent.click(screen.getByRole("button", { name: "Manage chats" }));
  fireEvent.click(await screen.findByRole("button", { name: "Select chats" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Parser bug" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Docs" }));
  fireEvent.click(screen.getByRole("button", { name: /Delete 2/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
  await waitFor(() => expect(mock.api).toHaveBeenLastCalledWith("/api/conversations/delete", { method: "POST", json: { ids: [1, 3] } }));
});

it("clears all only with the typed phrase and reports partial failures", async () => {
  mock.api.mockResolvedValue({ deleted: [1, 2], missing: [], failed: [{ id: 3, error: "database is locked" }] });
  render(<ConversationList chats={chats} searching={false} reload={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Manage chats" }));
  fireEvent.click(await screen.findByRole("button", { name: "Clear all chats…" }));
  const button = screen.getByRole("button", { name: "Delete all chats" });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "Clear all confirmation" }), { target: { value: "DELETE ALL" } });
  fireEvent.click(button);
  await waitFor(() => expect(mock.api).toHaveBeenCalledWith("/api/conversations/delete", { method: "POST", json: { all: true, confirm: "DELETE ALL" } }));
  expect(await screen.findByRole("alert")).toHaveTextContent("1 could not be deleted (database is locked)");
});

it("refuses to delete the open chat while MOTH is still answering", async () => {
  appStore.setState({ chatSession: { conversationId: 2, title: "Refactor", busy: true } });
  render(<ConversationList chats={chats} searching={false} reload={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Options for Refactor" }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("still answering");
  expect(mock.api).not.toHaveBeenCalled();
  appStore.setState({ chatSession: { conversationId: null, title: "New conversation", busy: false } });
});
