import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
vi.mock("@/features/workspace/WorkspaceView", () => ({ WorkspaceView: () => <input aria-label="Unsaved code" defaultValue="original code" /> }));
vi.mock("@/features/chat/ChatView", () => ({ ChatView: () => <textarea aria-label="Chat draft" defaultValue="" />,ModelBar:()=> <span>Active model</span> }));
import { WorkspaceShell } from "@/features/workspace/WorkspaceShell";
import { appStore } from "@/lib/app-state";

beforeEach(() => { localStorage.clear(); appStore.setState({ view: "workspace", workspaceMode: "code", openFiles: [{ path: "main.py", content: "unsaved", saved: "original", language: "python" }] }); });
describe("unified Code/Chat workspace", () => {
  it("preserves both mode drafts and unsaved files while switching", () => {
    render(<WorkspaceShell />);
    fireEvent.change(screen.getByLabelText("Unsaved code"), { target: { value: "edited code" } });
    fireEvent.click(screen.getByRole("button", { name: "Switch to Chat" }));
    fireEvent.change(screen.getByLabelText("Chat draft"), { target: { value: "unfinished question" } });
    expect(screen.getByLabelText("Unsaved code")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Switch to Code" }));
    expect(screen.getByLabelText("Unsaved code")).toHaveValue("edited code");
    expect(screen.getByLabelText("Chat draft")).toHaveValue("unfinished question");
    expect(appStore.getState().openFiles[0].content).toBe("unsaved");
    expect(JSON.parse(localStorage.getItem("moth.navigation")!).workspaceMode).toBe("code");
  });
  it("supports the same mode switch from the keyboard", () => {
    render(<WorkspaceShell />);
    fireEvent.keyDown(window, { key: "M", ctrlKey: true, shiftKey: true });
    expect(appStore.getState().view).toBe("chat");
    expect(screen.getByRole("button", { name: "Switch to Code" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "M", metaKey: true, shiftKey: true });
    expect(appStore.getState().view).toBe("workspace");
  });
});
