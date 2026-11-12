import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
const m = vi.hoisted(() => ({ api: vi.fn(), role: "owner" }));
vi.mock("@/lib/account", () => ({ serverApi: m.api, useAccount: (fn: (s: any) => unknown) => fn({ token: "t", serverUrl: "s", user: { role: m.role } }) }));
vi.mock("@/features/owner/ops", () => ({ secure: (fn: () => Promise<unknown>) => fn() }));
vi.mock("@/components/LivingMoth", () => ({ LivingMoth: () => <span /> }));
import { EvolutionControl } from "@/features/intelligence/EvolutionControl";
afterEach(() => { cleanup(); vi.clearAllMocks(); m.role = "owner"; });

it("starts from Genesis with one click and reports what it did", async () => {
  let started = false;
  m.api.mockImplementation(async (path: string) => {
    if (path.endsWith("/autopilot/start")) { started = true; return { steps: ["Created the first MOTH model (seed size, byte-level tokenizer)."], status: {} }; }
    return started ? { stage: "preparing_data", running: true, doing: "Preparing training data." } : { stage: "genesis", running: false, doing: "There is no model yet." };
  });
  render(<EvolutionControl progress={{ current: null, training: {} }} />);
  expect(await screen.findByText("Start MOTH from zero")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Start Evolution" }));
  await waitFor(() => expect(m.api).toHaveBeenCalledWith("/v1/admin/evolution/autopilot/start", { method: "POST", timeoutMs: 600000 }));
  expect(await screen.findByText(/Created the first MOTH model/)).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Pause Evolution" })).toBeInTheDocument();
});

it("shows the reasons for plan changes and never offers controls to other users", async () => {
  m.role = "user";
  render(<EvolutionControl progress={{ current: { name: "MOTH 0.01" }, training: { enabled: true, paused: false, cycle: { status: "training" } } }} />);
  expect(screen.getByText("MOTH is evolving")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Evolution/ })).toBeNull();
  expect(m.api).not.toHaveBeenCalled();
});


it("shows workers with their tasks, versions and the bottleneck from the server", async () => {
  m.api.mockResolvedValue({ stage: "training", running: true, doing: "Training (cycle #3).", objective: "weakness-tilted curriculum (stage foundation)",
    parallel: 2, queued_jobs: 1, versions: { active: 7, previous: 6 }, bottleneck: "1 job(s) wait for a MOTH worker, but none is online.",
    workers: [{ id: 1, name: "Lab GPU", online: true, paused: false, compute: "GPU", gflops: 812.4, task: { kind: "evolve_train", progress: 0.4 } },
              { id: 2, name: "Laptop", online: false, paused: false, compute: "CPU", task: null }] });
  render(<EvolutionControl progress={{ current: { name: "MOTH 0.02" }, training: {} }} />);
  expect(await screen.findByText(/Active v7 · previous v6 kept for rollback/)).toBeInTheDocument();
  expect(screen.getByText("2 running · 1 waiting for a worker")).toBeInTheDocument();
  expect(screen.getByText("1 of 2 online · 1 busy")).toBeInTheDocument();
  expect(screen.getByText("training an experiment · 40%")).toBeInTheDocument();
  expect(screen.getByText(/Holding back progress: 1 job\(s\) wait/)).toBeInTheDocument();
  expect(screen.getByText(/weakness-tilted curriculum/)).toBeInTheDocument();
});

it("reports the intelligence check, real size and growth outcomes exactly as the server measured them", async () => {
  m.api.mockResolvedValue({ stage: "training", running: true, doing: "Training (cycle #9).", intelligence: {
    version: 12, params: 5184768, params_verified: true,
    assessment: { action: "grow", investigating: "Arithmetic remains limited. Evaluating possible causes.",
      headline: "Current architecture may be limiting progress. Testing a larger candidate.",
      reason: "arithmetic did not improve over the last 3 measured versions despite 41 tokens per parameter: grow 20% (5,184,768 → 6,221,568 parameters)",
      estimate: { memory_bytes: 2 * 2 ** 30, fits_server: true, workers_that_fit: 1, training_seconds: null },
      capabilities: [{ capability: "math", name: "Arithmetic", value: 0.02, target: 0.2, limited: true, stalled: true, higher_is_better: true, change: 0 },
                     { capability: "holdout_language", name: "Language understanding", value: 2.1234, target: null, limited: null, stalled: false, higher_is_better: false, change: 0.04 }],
      causes: [{ cause: "insufficient_training", found: false, detail: "41 tokens per parameter" }] },
    growth_attempts: [{ experiment: 31, status: "rejected", params_before: 5184768, params_after: 6221568, measured: true }] } });
  render(<EvolutionControl progress={{ current: { name: "MOTH 0.12" }, training: {} }} />);
  expect(await screen.findByText("Current architecture may be limiting progress. Testing a larger candidate.")).toBeInTheDocument();
  expect(screen.getByText("Arithmetic remains limited. Evaluating possible causes.")).toBeInTheDocument();
  expect(screen.getByText("Model v12: 5,184,768 parameters · counted from the saved weights")).toBeInTheDocument();
  expect(screen.getByText(/2\.0% \/ target 20\.0% · not improving/)).toBeInTheDocument();
  expect(screen.getByText(/loss 2\.123 · improving/)).toBeInTheDocument();
  expect(screen.getByText(/fits this server · fits 1 MOTH worker\(s\) · training time not measured yet/)).toBeInTheDocument();
  expect(screen.getByText(/Experiment #31: 5,184,768 → 6,221,568 parameters \(counted from weights\) · Larger model did not improve performance enough\. Kept the current version\./)).toBeInTheDocument();
});
