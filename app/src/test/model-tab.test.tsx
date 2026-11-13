import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
const mocks = vi.hoisted(() => ({ api: vi.fn(), role: "owner" }));
vi.mock("@/lib/account", () => ({ serverApi: mocks.api, useAccount: (fn: (s: any) => unknown) => fn({ token: "t", user: { role: mocks.role } }) }));
vi.mock("@/features/owner/ops", () => ({ secure: (fn: () => Promise<unknown>) => fn() }));
vi.mock("@/lib/cloud-progress", () => ({ refreshCloudProgress: vi.fn() }));
import { BenchmarkHistory, ModelTab, benchmarkChange, benchmarkValue, capabilityLabel, changeLabel } from "@/features/intelligence/ModelTab";

const v3 = { version: 52, model_version: "0.0.3", name: "moth-evolution-v52-e8", display_name: "MOTH 0.0.3", params: 99648, params_verified: true,
  config: { n_layers: 4, d_model: 128, n_heads: 4, vocab_size: 272 }, deployed: true, retained: true, model_id: "moth-evolution-v52-e8",
  tokenizer_fingerprint: "bpe-272-abc", revision: 3, deployed_at: 1794500000,
  benchmarks: { code: { value: 0.42, metric: "accuracy", higher_is_better: true }, math: { value: 0.3, metric: "accuracy", higher_is_better: true } } };
const v2 = { ...v3, version: 50, model_version: "0.0.2", display_name: "MOTH 0.0.2", deployed: false,
  benchmarks: { code: { value: 0.40, metric: "accuracy", higher_is_better: true }, math: { value: 0.35, metric: "accuracy", higher_is_better: true } } };
const v1 = { ...v3, version: 40, model_version: "0.0.1", display_name: "MOTH 0.0.1", deployed: false, retained: false, benchmarks: {} };
const progress = { current: v3, timeline: [v1, v2, v3], lifecycle: { active: 52, rollback: 50 },
  serving: { accepting_requests: true, reason: "Ready to answer" }, checkpoint: { available: true, step: 900 },
  improvement: { verified: true, primary_improvement: 0.031 }, training: { paused: false, cycle: null, experiments: [] } };
afterEach(() => { cleanup(); vi.clearAllMocks(); mocks.role = "owner"; });

describe("Model tab", () => {
  it("shows one active model with its measurements, capabilities and the single rollback model", () => {
    render(<ModelTab progress={progress} />);
    expect(screen.getByRole("heading", { name: "MOTH 0.0.3" })).toBeInTheDocument();
    expect(screen.queryByText(/^moth-evolution-v52-e8$/, { selector: "h2" })).toBeNull();  // never the public name
    expect(screen.getByText("99,648 parameters · counted from the saved weights")).toBeInTheDocument();
    expect(screen.getByText("4 layers · 128 dimensions")).toBeInTheDocument();
    expect(screen.getAllByText("Coding").length).toBe(2);  // capabilities card and benchmark history
    expect(screen.getAllByText("Arithmetic").length).toBe(2);
    expect(screen.getAllByText(/42.0%/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("MOTH 0.0.2").length).toBeGreaterThan(0);  // the rollback model
    expect(screen.getByText(/Verified improvement/)).toBeInTheDocument();
    expect(screen.getByText("Version history (3)")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").filter((li) => /measurements only/.test(li.textContent ?? "")).length).toBe(1);  // removed weights keep their history
  });
  it("lets only the Owner roll back, after confirming", async () => {
    mocks.api.mockResolvedValue({ deployed: 50 });
    render(<ModelTab progress={progress} />);
    fireEvent.click(screen.getByRole("button", { name: "Roll back" }));
    fireEvent.click(screen.getByRole("button", { name: "Make MOTH 0.0.2 active" }));
    await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("/v1/admin/evolution/rollback", { method: "POST", json: { version: 50 } }));
    cleanup(); mocks.role = "user";
    render(<ModelTab progress={progress} />);
    expect(screen.queryByRole("button", { name: "Roll back" })).toBeNull();
  });
  it("compares promoted versions in the benchmark history, conversation and coding first", () => {
    const tl = [
      { version: 50, model_version: "0.0.2", display_name: "MOTH 0.0.2", benchmarks: { math: { value: 0.3, higher_is_better: true, evaluated_at: 1794400000 },
        dialogue: { value: 0.2, higher_is_better: true, evaluated_at: 1794400000 } } },
      { version: 51, model_version: null, benchmarks: { dialogue: { value: 0.9, higher_is_better: true } } },  // a rejected candidate
      { version: 52, model_version: "0.0.3", display_name: "MOTH 0.0.3", benchmarks: { math: { value: 0.25, higher_is_better: true, evaluated_at: 1794500000 },
        dialogue: { value: 0.35, higher_is_better: true, evaluated_at: 1794500000 } } }];
    render(<BenchmarkHistory timeline={tl} />);
    const rows = screen.getAllByRole("row").slice(1).map((r) => r.textContent);
    expect(rows[0]).toContain("Conversation (multi-turn)");  // priority order
    expect(rows[0]).toContain("35.0%▲");
    expect(rows[1]).toContain("Arithmetic");
    expect(rows[1]).toContain("25.0%▼");
    expect(screen.queryByText("90.0%")).toBeNull();  // candidates that were not promoted are not listed
  });
  it("formats benchmarks honestly", () => {
    expect(benchmarkValue({ value: 0.5, metric: "accuracy" })).toBe("50.0%");
    expect(benchmarkValue({ value: 2.31, metric: "loss" })).toBe("2.310 loss");
    expect(benchmarkChange({ value: 2.0, higher_is_better: false }, { value: 2.5 })).toBeCloseTo(0.5);
    expect(capabilityLabel("holdout_python")).toBe("Held-out python");
    expect(changeLabel({ value: 3.3, metric: "loss" }, 0.327)).toBe("0.327");  // a loss change is not percentage points
    expect(changeLabel({ value: 0.42, metric: "accuracy" }, 0.02)).toBe("2.0 pts");
  });
});
