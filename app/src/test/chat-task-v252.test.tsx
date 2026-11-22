import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/backend", () => ({ get: mocks.get, post: mocks.post, put: vi.fn(), isTauri: () => false }));
vi.mock("@/lib/cloud", () => ({ useCloudStatus: () => ({ status: { signed_in: true, available: true, model: { name: "MOTH" } }, reload: vi.fn() }) }));
vi.mock("@/lib/cloud-progress", () => ({ useCloudProgress: () => ({ data: { current: { name: "MOTH" }, serving: { accepting_requests: true } } }) }));
vi.mock("@/lib/hooks", () => ({ useResource: () => ({ data: null, reload: vi.fn() }) }));
vi.mock("@/features/agent/TaskCard", () => ({ TaskCard: ({ taskId }: { taskId: string }) => <div>task card {taskId}</div> }));
vi.mock("@/features/account/AccountDialog", () => ({ openAccountDialog: vi.fn() }));
import { ChatPanel } from "@/features/chat/ChatPanel";
import { appStore } from "@/lib/app-state";

beforeEach(() => {
  appStore.setState({ chatRequest: null, chatSession: { conversationId: null, title: "New conversation", busy: false } });
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} unobserve() {} });
  HTMLElement.prototype.scrollTo = vi.fn();
  mocks.get.mockReset(); mocks.post.mockReset();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function type(text: string) {
  const box = screen.getByRole("textbox", { name: "Message MOTH" });
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
}

it("2.5.2: one chat — no tabs; a request to act runs as a task card in the conversation", async () => {
  mocks.post.mockImplementation(async (path: string) =>
    path === "/api/chat/task" ? { conversation_id: 7, task: { id: "t1" } } : path === "/api/scans/parse" ? { plan: null, refused: null }
      : path === "/api/security/parse" ? { tool: null } : {});
  mocks.get.mockImplementation(async (path: string) => path.startsWith("/api/conversations/7/messages")
    ? [{ id: 1, role: "user", content: "open my downloads folder" }, { id: 2, role: "assistant", content: "Working on it", meta: { task_id: "t1" } }] : []);
  render(<ChatPanel general />);
  expect(screen.queryByRole("tab", { name: /Do it on my PC/ })).toBeNull();
  type("open my downloads folder");
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/chat/task", { goal: "open my downloads folder", conversation_id: null, project_id: null }));
  expect(await screen.findByText("task card t1")).toBeInTheDocument();
  expect(mocks.post).not.toHaveBeenCalledWith("/api/chat", expect.anything());
});

it("2.5.2: questions are answered, not turned into tasks", async () => {
  mocks.post.mockImplementation(async (path: string) => path === "/api/chat" ? { conversation_id: 8 } : path === "/api/scans/parse" ? { plan: null, refused: null } : { tool: null });
  mocks.get.mockResolvedValue([]);
  render(<ChatPanel general />);
  type("how do I run the tests?");
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/chat", expect.objectContaining({ message: "how do I run the tests?" })));
  expect(mocks.post).not.toHaveBeenCalledWith("/api/chat/task", expect.anything());
});
