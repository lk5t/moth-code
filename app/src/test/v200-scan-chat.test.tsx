import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/backend", () => ({ get: mocks.get, post: mocks.post, isTauri: () => false }));
vi.mock("@/lib/cloud", () => ({ useCloudStatus: () => ({ status: { signed_in: true, available: true, model: { name: "MOTH" } }, reload: vi.fn() }) }));
vi.mock("@/lib/cloud-progress", () => ({ useCloudProgress: () => ({ data: { current: { name: "MOTH" }, serving: { accepting_requests: true } } }) }));
vi.mock("@/lib/hooks", () => ({ useResource: () => ({ data: null, reload: vi.fn() }) }));
vi.mock("@/features/agent/TaskCard", () => ({ TaskCard: () => null }));
vi.mock("@/features/account/AccountDialog", () => ({ openAccountDialog: vi.fn() }));
import { ChatPanel } from "@/features/chat/ChatPanel";
import { appStore } from "@/lib/app-state";
import { _testing } from "@/lib/events";

const plan = { target: "10.0.0.5", hosts: 1, ports: [8080], port_count: 1, default_ports: false, describe: "10.0.0.5 port 8080" };
const scan = { id: "s1", target: "10.0.0.5", hosts: ["10.0.0.5"], ports: [8080], confirmed_at: 1, status: "running", phase: "Scanning ports", progress: 0.3,
  started_at: 1, finished_at: null, open_ports: [], findings: [], stronger: [], error: null, counts: { critical: 0, high: 0, medium: 0, low: 0, info: 0 } };

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

it("asks for a Yes before scanning and never sends the request to the cloud", async () => {
  mocks.post.mockImplementation(async (path: string) => path === "/api/scans/parse" ? { plan, refused: null } : path === "/api/scans" ? scan : {});
  mocks.get.mockResolvedValue(scan);
  render(<ChatPanel general />);
  type("find vulnerabilities on 10.0.0.5 port 8080");
  expect(await screen.findByText("10.0.0.5 port 8080")).toBeInTheDocument();
  expect(mocks.post).not.toHaveBeenCalledWith("/api/chat", expect.anything());
  expect(mocks.post).not.toHaveBeenCalledWith("/api/scans", expect.anything());  // nothing runs before the Yes
  fireEvent.click(screen.getByRole("button", { name: /Yes, scan it/ }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/scans", { message: "find vulnerabilities on 10.0.0.5 port 8080", confirmed: true }));
  expect(await screen.findByRole("button", { name: /Stop/ })).toBeInTheDocument();
  act(() => _testing.dispatch({ topic: "scan", ts: 1, kind: "finding", scan: { ...scan, findings: [{ severity: "high", title: "Redis answers without a password", port: 6379, evidence: "PING", fix: "Set a password", host: "10.0.0.5", ref: "" }] } }));
  expect(await screen.findByText("Redis answers without a password")).toBeInTheDocument();
});

it("No cancels, and refusals are explained", async () => {
  mocks.post.mockImplementation(async (path: string, body: any) => path === "/api/scans/parse"
    ? (body.message.includes("8.8.8.0") ? { plan: null, refused: "address ranges can only be scanned on private networks" } : { plan, refused: null }) : {});
  render(<ChatPanel general />);
  type("scan 10.0.0.5 port 8080");
  fireEvent.click(await screen.findByRole("button", { name: "No" }));
  expect(await screen.findByText("Okay, nothing was scanned.")).toBeInTheDocument();
  type("scan 8.8.8.0/24");
  expect(await screen.findByText(/I won't scan that: address ranges/)).toBeInTheDocument();
  expect(mocks.post).not.toHaveBeenCalledWith("/api/scans", expect.anything());
});

it("2.1: code audits run from chat, show findings and offer Ask MOTH", async () => {
  const report = { kind: "Code audit", note: "Checked 3 files", total: 1, counts: { critical: 0, high: 1, medium: 0, low: 0, info: 0 },
    findings: [{ severity: "high", title: "eval/exec on dynamic input", where: "a.py:1", evidence: "x = eval(user)", fix: "Parse the data instead.", ref: "CWE-95" }] };
  mocks.post.mockImplementation(async (path: string) => path === "/api/security/parse" ? { tool: "code_audit" } : path === "/api/security/audit" ? { report, conversation_id: 7 } : {});
  mocks.get.mockResolvedValue([{ id: 1, role: "user", content: "audit my code for security" }, { id: 2, role: "assistant", content: "**Code audit**", meta: { report } }]);
  render(<ChatPanel general />);
  type("audit my code for security");
  expect(await screen.findByText("eval/exec on dynamic input")).toBeInTheDocument();
  expect(mocks.post).toHaveBeenCalledWith("/api/security/audit", expect.objectContaining({ message: "audit my code for security" }));
  expect(mocks.post).not.toHaveBeenCalledWith("/api/chat", expect.anything());
  fireEvent.click(screen.getByRole("button", { name: /Ask MOTH/ }));
  await waitFor(() => expect((screen.getByRole("textbox", { name: "Message MOTH" }) as HTMLTextAreaElement).value).toContain("eval/exec on dynamic input"));
});
