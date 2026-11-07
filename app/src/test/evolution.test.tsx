import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvolutionView } from "@/features/evolution/EvolutionView";
import { IntelligenceView } from "@/features/intelligence/IntelligenceView";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/account", () => ({
  serverApi: api,
  useAccount: (select: (s: unknown) => unknown) => select({ token: "test", user: { role: "owner" } }),
}));
vi.mock("@/features/owner/ops", () => ({ secure: (fn: () => Promise<unknown>) => fn() }));
vi.mock("@/features/training/NetworkTraining", () => ({ NetworkTraining: () => null, ParticipantSwitch: () => null }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Evolution", () => {
  it("charts recorded parameter counts without inventing missing validation measurements", async () => {
    api.mockResolvedValue({ current: null, stable: null, development: null,
      training: { enabled: false }, network: { workers_online: 0, gpu_online: 0, cpu_online: 0, verified_tokens: 0 },
      timeline: [{ version: 1, params: 49295872, name: "MOTH", benchmarks: {}, training: {}, method: "foundation" }],
    });
    render(<IntelligenceView />);
    fireEvent.click(await screen.findByRole("button", { name: "Parameter count" }));
    expect(screen.getByRole("img", { name: "Parameter count across model versions" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Validation loss" })).not.toBeInTheDocument();
  });

  it("sends the settings API contract and displays measured experiment data", async () => {
    api.mockImplementation((path: string) => Promise.resolve(path.endsWith("/progress") ? {
      current: null, training: { enabled: true, paused: false, cycle: null, experiments: [{
        id: 7, status: "planned", backend: "local", candidate_version: 3, requires_approval: true,
        growth: { params_before: 100, params_after: 120 },
        metrics: { training: { batch_tuning: { batch_size: 2, grad_accum: 4, effective_batch_size: 8 } } },
      }] },
    } : {}));
    render(<EvolutionView />);
    expect(await screen.findByText("Experiment #7")).toBeInTheDocument();
    expect(screen.getByText(/Measured batch: 2 × 4/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve expansion" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/v1/admin/evolution/experiments/7/approve", { method: "POST" }));
    fireEvent.click(screen.getByRole("switch", { name: "Improve MOTH automatically" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/v1/admin/evolution/settings", {
      method: "PUT", json: { changes: { paused: true } },
    }));
  });
});
