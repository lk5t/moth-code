import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { modelLabel } from "@/lib/model-label";
import { MothEmblem } from "@/components/MothEmblem";
import { TrainingProgress } from "@/features/intelligence/TrainingProgress";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

afterEach(cleanup);

it("presents the existing checkpoint as MOTH 0.0.1 without changing model identity", () => {
  const checkpoint = { name: "moth-200k-v0.1-step500", params: 1160000 };
  expect(modelLabel(checkpoint)).toBe("MOTH 0.0.1");
  expect(checkpoint.name).toBe("moth-200k-v0.1-step500");
  expect(modelLabel({ name: "other-package", model_version: "0.02" })).toBe("MOTH 0.02");
  expect(modelLabel("External provider")).toBe("External provider");
});

it("keeps each animated emblem's SVG references independent", () => {
  const { container } = render(<><MothEmblem motion="idle" /><MothEmblem motion="working" /></>);
  const ids = [...container.querySelectorAll("[id]")].map((e) => e.id);
  expect(new Set(ids).size).toBe(ids.length);
  for (const svg of container.querySelectorAll("svg")) {
    const own = new Set([...svg.querySelectorAll("[id]")].map((e) => e.id));
    for (const use of svg.querySelectorAll("use")) expect(own.has(use.getAttribute("href")!.slice(1))).toBe(true);
  }
});

describe("visible training reports", () => {
  it("updates measured counts, loss and checkpoint from new reports", () => {
    const progress = { current: { name: "moth-200k-v0.1-step500" }, training: { enabled: true, paused: false,
      cycle: { status: "training" }, experiments: [{ id: 4, status: "running", backend: "local", device: "cpu",
        measurement: { step: 2, max_steps: 8, tokens_seen: 256, train_loss: 4.321, fraction: .25 } }] } };
    const { rerender } = render(<TrainingProgress progress={progress} resources={null} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByText("256")).toBeInTheDocument();
    expect(screen.getByText("4.321")).toBeInTheDocument();
    progress.training.experiments[0].measurement = { step: 8, max_steps: 8, tokens_seen: 1024, train_loss: 3.2,
      fraction: 1, checkpoint: { name: "step_00000008.pt", step: 8 } } as any;
    rerender(<TrainingProgress progress={progress} resources={null} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByText("Checkpoint").nextSibling).toHaveTextContent("step 8");
    expect(screen.getByText("Remaining").nextSibling).toHaveTextContent("Estimating");  // no start time reported: no invented estimate
    expect(screen.queryByText("256")).not.toBeInTheDocument();
  });
  it("shows waiting/paused states without inventing progress", () => {
    const { container } = render(<TrainingProgress resources={null} progress={{ training: { enabled: true,
      paused: true, experiments: [{ id: 1, status: "waiting", backend: null, measurement: {} }] } }} />);
    expect(screen.getByText(/· Paused/)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getAllByText("Not reported").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-motion="working"]')).toBeNull();
  });
  it("derives remaining time only from the measured step rate", () => {
    const started = Date.now() / 1000 - 100;  // 100 s for 50 of 200 steps → about 300 s left
    render(<TrainingProgress resources={{ local: { cpu_count: 4, cpu_percent: 37, memory: { used: 2 * 1024 ** 3, total: 8 * 1024 ** 3 }, gpus: [] } }}
      progress={{ network: { workers_online: 1, gpu_online: 0, cpu_online: 1 }, training: { enabled: true, paused: false, cycle: { status: "training" },
        experiments: [{ id: 7, status: "running", backend: "local", device: "cpu", started_at: started,
          data: { stage: "foundation", domains: { code: 0.6, language: 0.4 } }, plan: { steps: 200, lr: 0.0003, batch_size: 8 },
          measurement: { step: 50, max_steps: 200, tokens_seen: 51200, train_loss: 3.1 } }] } }} />);
    expect(screen.getByText("Remaining").nextSibling?.textContent).toMatch(/≈ (4|5) min/);
    expect(screen.getByText(/code 60%, language 40%/)).toBeInTheDocument();
    expect(screen.getByText("37% of 4 cores")).toBeInTheDocument();
    expect(screen.getByText("2.0 GB of 8.0 GB in use")).toBeInTheDocument();
    expect(screen.getByText("1 (0 GPU · 1 CPU)")).toBeInTheDocument();
  });
});

it("retains keyboard tab selection and accessible panels after the tab redesign", async () => {
  render(<Tabs defaultValue="one"><TabsList aria-label="Test sections"><TabsTrigger value="one">One</TabsTrigger>
    <TabsTrigger value="two">Two</TabsTrigger></TabsList><TabsContent value="one">First panel</TabsContent>
    <TabsContent value="two">Second panel</TabsContent></Tabs>);
  screen.getByRole("tab", { name: "One" }).focus();
  fireEvent.keyDown(screen.getByRole("tab", { name: "One" }), { key: "ArrowRight" });
  await waitFor(() => expect(screen.getByRole("tab", { name: "Two" })).toHaveAttribute("aria-selected", "true"));
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Second panel");
});
