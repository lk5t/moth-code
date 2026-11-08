import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
const mocks = vi.hoisted(() => ({ api: vi.fn(), get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/account", () => ({ serverApi: mocks.api, useAccount: (fn: (s: any) => unknown) => fn({ token: "test-session", user: { role: "owner" } }) }));
vi.mock("@/lib/backend", () => ({ get: mocks.get, put: mocks.put }));
vi.mock("@/features/owner/ops", () => ({ secure: (fn: () => Promise<unknown>) => fn(), formatBytes: (n: number) => `${n} bytes`,
  ModelsPanel: () => <p>Cloud registry controls</p>, WorkersPanel: () => <p>Worker resource controls</p> }));
vi.mock("@/features/owner/evolution", () => ({ EvolutionPanel: () => <p>Growth approval and rollback controls</p> }));
vi.mock("@/features/owner/intelligence", () => ({ IntelligencePanel: () => <p>Approved dataset controls</p> }));
vi.mock("@/features/owner/ModelOverview", () => ({ ModelOverview: () => <p>Baseline and selected workers</p> }));
vi.mock("@/features/training/TrainingView", () => ({ TrainingView: () => <p>Local training controls</p> }));
vi.mock("@/features/models/ModelsView", () => ({ ModelsView: () => <p>Local package controls</p> }));
vi.mock("@/features/evolution/EvolutionView", () => ({ EvolutionView: () => <p>Existing evolution cycle controls</p> }));
vi.mock("@/features/network/NetworkView", () => ({ NetworkView: () => <p>Existing worker enrollment controls</p> }));
import { IntelligenceHub, ModelActivity } from "@/features/intelligence/IntelligenceHub";
import { appStore } from "@/lib/app-state";

const progress = { current: { version: 1, model_version: "0.01", name: "MOTH 0.01", params: 99648,
  config: { n_layers: 2, d_model: 64, n_heads: 4 }, initialization: "random-untrained", benchmarks: {} },
  training: { enabled: true, paused: false, cycle: null }, timeline: [], stable: null, development: null,
  network: { workers_online: 0, gpu_online: 0, cpu_online: 0, verified_tokens: 0 },
  datasets: { sources: [{ id: "psf", name: "Python standard library", license: "PSF-2.0", records: 60 }] } };
beforeEach(() => {
  appStore.setState({ view: "intelligence", intelligenceTab: "overview" });
  mocks.get.mockResolvedValue({ available: true, enabled: false, completed_jobs: 0 });
  mocks.api.mockImplementation(async (path: string) => {
    if (path.endsWith("/progress")) return progress;
    if (path.endsWith("/status")) return { settings: { backends: { local_cpu: true, workers: true }, distributed: { enabled: true } }, cycle: null };
    if (path.endsWith("/resources")) return { training: { running: [] }, local: { cpu_count: 4, cpu_percent: 2, memory: { available: 4 * 1024 ** 3 } } };
    if (path.endsWith("/genesis")) return { status: "not_prepared" };
    return {};
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Intelligence consolidation", () => {
  it("provides the five functional tabs and retains existing controls in their new home", async () => {
    render(<IntelligenceHub />);
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Overview", "Training", "Evolution", "Network", "Data"]);
    await screen.findByRole("button", { name: "Inspect layer 2" });
    fireEvent.click(screen.getByRole("button", { name: "Inspect layer 2" }));
    expect(screen.getByRole("button", { name: "Inspect layer 2" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Training" }), { button: 0 });
    await screen.findByRole("button", { name: "Train MOTH now" });
    expect(screen.getByRole("switch", { name: "Contribute this computer" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Training Mode" })).toHaveValue("automatic");
    expect(screen.getByRole("button", { name: "Prepare and verify backup" })).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Data" }), { button: 0 });
    await screen.findByText("Approved dataset controls");
    expect(screen.getByText("PSF-2.0 · 60 retained samples")).toBeInTheDocument();
    expect(appStore.getState().intelligenceTab).toBe("data");
  });
  it("never animates a training claim without reported progress", async () => {
    const props = { progress: { ...progress, training: { cycle: { status: "training" } } }, resources: { training: { running: [{ progress: { step: 0 } }] } } };
    const { rerender } = render(<ModelActivity {...props} />);
    expect(screen.queryByText("Training progress received")).not.toBeInTheDocument();
    rerender(<ModelActivity {...props} resources={{ training: { running: [{ progress: { step: 1 } }] } }} />);
    await waitFor(() => expect(screen.getByText("Training progress received")).toBeInTheDocument());
    expect(screen.getByText(/Fresh, untrained baseline/)).toBeInTheDocument();
  });
});


it("clears model activity after a failed refresh instead of showing stale state as current", async () => {
  vi.useFakeTimers();
  try {
    await act(async () => { render(<IntelligenceHub />); });
    expect(screen.getByRole("button", { name: "Inspect layer 2" })).toBeInTheDocument();
    mocks.api.mockRejectedValue(new Error("connection lost"));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.queryByRole("button", { name: "Inspect layer 2" })).not.toBeInTheDocument();
    expect(screen.getAllByText(/Live status unavailable/).length).toBeGreaterThan(0);
  } finally { vi.useRealTimers(); }
});
