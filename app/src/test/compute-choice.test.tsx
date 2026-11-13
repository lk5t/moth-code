import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
const mocks = vi.hoisted(() => ({ api: vi.fn(), get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/account", () => ({ serverApi: mocks.api, useAccount: (fn: (s: any) => unknown) => fn({ token: "t", serverUrl: "s", user: { role: "owner" } }) }));
vi.mock("@/lib/backend", () => ({ get: mocks.get, put: mocks.put }));
vi.mock("@/features/owner/ops", () => ({ secure: (fn: () => Promise<unknown>) => fn(), formatBytes: (n: number) => `${n} B` }));
import { AiSettings } from "@/features/intelligence/AiSettings";

const settings = { automatic: true, autopilot: true, auto_deploy: true, cloud_workers: true, budget: { max_compute_hours_per_day: 6 },
  limits: { min_free_memory_gb: 1 }, backends: { local_cpu: true, local_gpu: true, workers: true }, rollout: { canary_percent: 20 } };
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("What trains MOTH", () => {
  it("offers the cloud server, workers and this computer, each writing its real setting", async () => {
    mocks.api.mockImplementation(async (path: string) => path.includes("evolution/status") ? { settings } : path.includes("storage") ? { categories: [] } : { discovered: [], policy: {} });
    mocks.get.mockResolvedValue({ available: true, enabled: false });
    mocks.put.mockResolvedValue({});
    render(<AiSettings />);
    const cloud = await screen.findByRole("switch", { name: "Train with MOTH Cloud server" });
    expect(cloud).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("switch", { name: "Train with Workers" }));
    await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/v1/admin/evolution/settings", { method: "PUT",
      json: { changes: { cloud_workers: false, backends: { local_cpu: true, local_gpu: true, workers: false } } } }));
    const pc = await screen.findByRole("switch", { name: "Train with This computer" });
    await waitFor(() => expect(pc).not.toBeDisabled());
    fireEvent.click(pc);
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/api/participant", { enabled: true }));
  });
});
