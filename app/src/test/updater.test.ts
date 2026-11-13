import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ invoke: vi.fn(), relaunch: vi.fn(), onClose: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("@tauri-apps/plugin-process", () => ({ relaunch: mocks.relaunch }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => ({ onCloseRequested: mocks.onClose }) }));
vi.mock("@/lib/backend", () => ({ isTauri: () => true }));
vi.mock("@/lib/endpoint", () => ({ APP_VERSION: "0.5.1", CLIENT_HEADER: "desktop/0.5.1" }));
vi.mock("@/lib/account", async () => {
  const { createStore } = await import("@/lib/store");
  return { accountStore: createStore({ serverUrl: "https://moth.test", updateRequired: null }), normalizeServerUrl: (s: string) => s };
});
import { accountStore } from "@/lib/account";
import { checkForUpdates, describeUpdateError, installNow, reportPreviousUpdate, startUpdater, updaterStore } from "@/lib/updater";

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  accountStore.setState({ serverUrl: "https://moth.test" });
  updaterStore.setState({ phase: "idle", version: null, notes: null, progress: 0, error: null, lastCheck: null, dismissed: false });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  mocks.invoke.mockImplementation(async (cmd: string) => cmd === "update_check" ? { version: "0.5.4", current_version: "0.5.1", notes: "signed update" } : undefined);
  mocks.onClose.mockResolvedValue(() => {});
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("desktop update lifecycle", () => {
  it("detects 0.5.1 → 0.5.4, downloads through the verifying command, and waits for restart", async () => {
    localStorage.setItem("moth.user-settings", "keep");
    await checkForUpdates({ manual: true });
    expect(mocks.invoke).toHaveBeenCalledWith("update_check", expect.objectContaining({ server: "https://moth.test", channel: "stable" }));
    expect(mocks.invoke).toHaveBeenCalledWith("update_download");
    expect(updaterStore.getState()).toMatchObject({ phase: "ready", version: "0.5.4", progress: 100 });
    expect(mocks.invoke).not.toHaveBeenCalledWith("update_install");
    expect(JSON.parse(localStorage.getItem("moth.update.pending")!)).toMatchObject({ from: "0.5.1", to: "0.5.4" });
    await installNow();
    expect(mocks.invoke).toHaveBeenCalledWith("update_install");
    expect(mocks.relaunch).toHaveBeenCalledOnce();
    expect(localStorage.getItem("moth.user-settings")).toBe("keep");
  });
  it("installs a verified download on the real window close callback", async () => {
    vi.useFakeTimers(); startUpdater(); await vi.advanceTimersByTimeAsync(0);
    await checkForUpdates();
    const ev = { preventDefault: vi.fn() };
    await mocks.onClose.mock.calls[0][0](ev);
    expect(ev.preventDefault).toHaveBeenCalledOnce();
    expect(mocks.invoke).toHaveBeenCalledWith("update_install");
  });
  it("labels only a successful no-update response as current", async () => {
    mocks.invoke.mockImplementation(async (cmd: string) => cmd === "update_check" ? null : undefined);
    await checkForUpdates({ manual: true });
    expect(updaterStore.getState().phase).toBe("up-to-date");
    expect(mocks.invoke).not.toHaveBeenCalledWith("update_download");
  });
  it.each([
    "Update check failed (HTTP 503): Windows installer is not yet available",
    "error sending request: DNS connection failed",
    "Invalid desktop update metadata: malformed JSON",
  ])("shows a failed check: %s", async (error) => {
    mocks.invoke.mockImplementation(async (cmd: string) => { if (cmd === "update_check") throw new Error(error); });
    await expect(checkForUpdates({ manual: true })).rejects.toThrow();
    expect(updaterStore.getState().phase).toBe("error");
    expect(updaterStore.getState().error).toBeTruthy();
    expect(mocks.invoke).not.toHaveBeenCalledWith("update_install");
  });
  it("treats a staged rollout that has not reached this install as a wait, not an error", async () => {
    mocks.invoke.mockImplementation(async (cmd: string) => { if (cmd === "update_check") throw new Error("Update check failed (HTTP 409): Desktop 0.7.1 is rolling out to 10% of installations. This installation will retry automatically when its rollout group is eligible."); });
    await checkForUpdates({ manual: true });
    expect(updaterStore.getState()).toMatchObject({ phase: "waiting", error: null });
    expect(mocks.invoke).not.toHaveBeenCalledWith("update_download");
  });
  it("never retries or installs a signature verification failure", async () => {
    mocks.invoke.mockImplementation(async (cmd: string) => {
      if (cmd === "update_check") return { version: "0.5.4", current_version: "0.5.1" };
      if (cmd === "update_download") throw new Error("signature verification failed");
    });
    await checkForUpdates();
    expect(updaterStore.getState().phase).toBe("error");
    expect(mocks.invoke.mock.calls.filter(([cmd]) => cmd === "update_download")).toHaveLength(1);
    await installNow();
    expect(mocks.invoke).not.toHaveBeenCalledWith("update_install");
    expect(localStorage.getItem("moth.update.pending")).toBeNull();
  });
  it("does not misreport a failed install after restart", async () => {
    await checkForUpdates();
    mocks.invoke.mockImplementation(async (cmd: string) => { if (cmd === "update_install") throw new Error("installer could not start"); });
    await installNow();
    expect(updaterStore.getState().phase).toBe("error");
    expect(localStorage.getItem("moth.update.pending")).toBeNull();
    expect(mocks.relaunch).not.toHaveBeenCalled();
  });
  it("survives damaged pending metadata and explains an unconfigured server", async () => {
    localStorage.setItem("moth.update.pending", "bad JSON");
    expect(() => reportPreviousUpdate()).not.toThrow();
    accountStore.setState({ serverUrl: "" }); await checkForUpdates();
    expect(updaterStore.getState()).toMatchObject({ phase: "error", error: expect.stringContaining("Connection") });
    expect(describeUpdateError("Update check failed (HTTP 503): missing updater signature")).toContain("HTTP 503");
  });
});
