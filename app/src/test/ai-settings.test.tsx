import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
const m = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/account", () => ({ serverApi: m.api, useAccount: (fn: (s: any) => unknown) => fn({ token: "t", serverUrl: "s", user: { role: "owner" } }) }));
vi.mock("@/features/owner/ops", () => ({ secure: (fn: () => Promise<unknown>) => fn(), formatBytes: (n: number) => `${n} B` }));
import { AiSettings } from "@/features/intelligence/AiSettings";
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const settings = { automatic: true, autopilot: true, cloud_workers: true, auto_deploy: true, budget: { max_compute_hours_per_day: 6, max_cycle_hours: 12 }, limits: { min_free_memory_gb: 1 }, rollout: { canary_percent: 20 } };
const storage = { disk: { free: 100, total: 1000 }, removable_bytes: 50, categories: [
  { id: "models", label: "Model versions", explanation: "", bytes: 80, removable_bytes: 50, items: [
    { id: "model:5", label: "v5 deployed", bytes: 30, protected: true, reason: "Deployed — serving MOTH" },
    { id: "model:7", label: "v7 evaluated", bytes: 50, protected: false, reason: null }] }] };
m.api.mockImplementation(async (path: string) => path.endsWith("/status") ? { settings } : path.endsWith("/discovery")
  ? { policy: { approved_sources: ["python-stdlib"] }, discovered: [{ id: "python-stdlib", name: "Python standard library", license: "PSF-2.0", license_verified: true }, { id: "mbpp", name: "MBPP", license: "CC-BY-4.0", license_verified: true }] }
  : path.endsWith("/storage") ? storage : { removed: ["model:7"], skipped: [], freed_bytes: 50 });

it("writes plain choices to the existing settings", async () => {
  render(<AiSettings />);
  fireEvent.click(await screen.findByRole("switch", { name: "Plan training automatically" }));
  await waitFor(() => expect(m.api).toHaveBeenCalledWith("/v1/admin/evolution/settings", { method: "PUT", json: { changes: { autopilot: false } } }));
  fireEvent.click(screen.getByRole("radio", { name: "Light" }));
  await waitFor(() => expect(m.api).toHaveBeenCalledWith("/v1/admin/evolution/settings", { method: "PUT", json: { changes: { budget: { max_compute_hours_per_day: 2, max_cycle_hours: 12 } } } }));
  fireEvent.click(await screen.findByRole("checkbox", { name: /MBPP/ }));
  await waitFor(() => expect(m.api).toHaveBeenCalledWith("/v1/admin/library/discovery", { method: "PUT", json: { changes: { approved_sources: ["python-stdlib", "mbpp"] } } }));
});

it("cleans up only removable storage and shows why the rest is kept", async () => {
  render(<AiSettings />);
  expect(await screen.findByText("Kept: Deployed — serving MOTH")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Remove v5 deployed" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Clean up 50 B" }));
  await waitFor(() => expect(m.api).toHaveBeenCalledWith("/v1/admin/evolution/storage/cleanup", { method: "POST", json: { items: ["model:7"] } }));
  expect(await screen.findByText("Freed 50 B.")).toBeInTheDocument();
});
