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
    expect(screen.getByText(/step_00000008.pt/)).toBeInTheDocument();
    expect(screen.queryByText("256")).not.toBeInTheDocument();
  });
  it("shows waiting/paused states without inventing progress", () => {
    const { container } = render(<TrainingProgress resources={null} progress={{ training: { enabled: true,
      paused: true, experiments: [{ id: 1, status: "waiting", backend: null, measurement: {} }] } }} />);
    expect(screen.getByText(/Paused by the Owner/)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getAllByText("Not reported").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-motion="working"]')).toBeNull();
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
