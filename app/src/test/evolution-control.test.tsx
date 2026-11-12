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
  expect(screen.getByText("MOTH 0.01 is evolving")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Evolution/ })).toBeNull();
  expect(m.api).not.toHaveBeenCalled();
});


it("shows workers with their tasks, versions and the bottleneck from the server", async () => {
  m.api.mockResolvedValue({ stage: "training", running: true, doing: "Training (cycle #3).", objective: "weakness-tilted curriculum (stage foundation)",
    parallel: 2, queued_jobs: 1, versions: { active: 7, previous: 6, active_name: "MOTH 0.0.7", previous_name: "MOTH 0.0.6" }, bottleneck: "1 job(s) wait for a MOTH worker, but none is online.",
    workers: [{ id: 1, name: "Lab GPU", online: true, paused: false, state: "working", compute: "GPU", gflops: 812.4, task: { kind: "evolve_train", progress: 0.4 } },
              { id: 2, name: "Laptop", online: false, paused: false, compute: "CPU", task: null }] });
  render(<EvolutionControl progress={{ current: { name: "MOTH 0.02" }, training: {} }} />);
  expect(await screen.findByText(/Active MOTH 0.0.7 · previous MOTH 0.0.6 kept for rollback/)).toBeInTheDocument();
  expect(screen.getByText("2 running · 1 waiting for a worker")).toBeInTheDocument();
  expect(screen.getByText("1 of 2 online · 1 busy")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Computing network" })).toHaveTextContent("Worker #1 · Lab GPU · working · GPU");
  expect(screen.getByRole("region", { name: "Computing network" })).toHaveTextContent("training · 40%");
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
      causes: [{ cause: "insufficient_training", found: false, detail: "41 tokens per parameter" }],
      coherence: { explanation: "Replies are readable text that ends on its own.", samples: [{ prompt: "What is 2 + 3?", reply: "5" }] } },
    growth_attempts: [{ experiment: 31, status: "rejected", params_before: 5184768, params_after: 6221568, measured: true }] } });
  render(<EvolutionControl progress={{ current: { name: "MOTH 0.12" }, training: {} }} />);
  expect(await screen.findByText("Current architecture may be limiting progress. Testing a larger candidate.")).toBeInTheDocument();
  expect(screen.getByText("Arithmetic remains limited. Evaluating possible causes.")).toBeInTheDocument();
  expect(screen.getByText("Replies: Replies are readable text that ends on its own.")).toBeInTheDocument();
  expect(screen.getByText("Model v12: 5,184,768 parameters · counted from the saved weights")).toBeInTheDocument();
  expect(screen.getByText(/2\.0% \/ target 20\.0% · not improving/)).toBeInTheDocument();
  expect(screen.getByText(/loss 2\.123 · improving/)).toBeInTheDocument();
  expect(screen.getByText(/fits this server · fits 1 MOTH worker\(s\) · training time not measured yet/)).toBeInTheDocument();
  expect(screen.getByText(/Experiment #31: 5,184,768 → 6,221,568 parameters \(counted from weights\) · Larger model did not improve performance enough\. Kept the current version\./)).toBeInTheDocument();
});


it("resumes a paused Evolution without choosing new data, and shows MOTH Cloud and workers as one network", async () => {
  m.api.mockImplementation(async (path: string) => path === "/v1/admin/evolution/resume" ? { paused: false } : {
    stage: "paused", running: false, doing: "Evolution is paused.",
    server: { id: "cloud", name: "MOTH Cloud (this server)", online: true, compute: "CPU", utilization: { cpu: 0.42, memory: 0.31 },
      task: { kind: "evolve_train", experiment: 12, progress: 0.5 }, contribution: { runs: 3, tokens: 1_200_000 } },
    workers: [{ id: 8, name: "linux-box", online: true, paused: false, state: "working", throughput: 23603.4, compute: "CPU", speed: { ratio: 1.3, basis: "measured" },
      utilization: { cpu: 0.9, memory: null }, task: { kind: "evolve_train", experiment: 13, progress: 0.25 }, contribution: { runs: 2, tokens: 800_000 } },
      { id: 9, name: "laptop", online: false, paused: false, state: "unavailable", compute: "CPU", contribution: { runs: 0, tokens: 0 } },
      { id: 10, name: "old-pc", online: false, paused: false, state: "unavailable", compute: "CPU", last_error: "worker stopped reporting; job requeued", contribution: { runs: 0, tokens: 0 } }] });
  render(<EvolutionControl progress={{ current: { name: "MOTH 0.03" }, training: {} }} />);
  const net = await screen.findByRole("region", { name: "Computing network" });
  expect(net).toHaveTextContent("Computing network · 1 worker(s) offline");
  expect(net).toHaveTextContent("MOTH Cloud (this server)");
  expect(net).toHaveTextContent("training experiment #12 · 50%");
  expect(net).toHaveTextContent("CPU 42% · memory 31%");
  expect(net).toHaveTextContent("3 run(s) · 1.2M tokens trained");
  expect(net).toHaveTextContent("Worker #8 · linux-box");
  expect(net).toHaveTextContent("1.3× this server's speed (measured)");
  expect(net).toHaveTextContent("training experiment #13 · 25%");
  expect(net).toHaveTextContent("CPU 90% · memory —");
  expect(net).not.toHaveTextContent("laptop");
  expect(net).toHaveTextContent("Worker #8 · linux-box · working");
  expect(net).toHaveTextContent("23,603 tokens/s measured");
  expect(net).toHaveTextContent("Worker #10 · old-pc · unavailable");
  expect(net).toHaveTextContent("Last problem: worker stopped reporting; job requeued");
  fireEvent.click(screen.getByRole("button", { name: "Resume Evolution" }));
  await waitFor(() => expect(m.api).toHaveBeenCalledWith("/v1/admin/evolution/resume", { method: "POST", timeoutMs: 600000 }));
  expect(m.api).not.toHaveBeenCalledWith("/v1/admin/evolution/autopilot/start", expect.anything());
});
