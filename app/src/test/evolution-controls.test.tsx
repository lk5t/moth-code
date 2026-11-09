import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { EvolutionControls } from "@/features/training/EvolutionControls";
afterEach(cleanup);
it("sends only the selected policy and never resumes paused training implicitly", () => {
  const change = vi.fn();
  render(<EvolutionControls settings={{ enabled: false, paused: true, auto_deploy: false }} onChange={change} />);
  expect(screen.getAllByRole("switch")).toHaveLength(3);
  expect(screen.getAllByRole("combobox")).toHaveLength(2);
  fireEvent.change(screen.getByRole("combobox", { name: "Training Mode" }), { target: { value: "eco" } });
  expect(change).toHaveBeenLastCalledWith({ training_mode: "eco" });
  fireEvent.click(screen.getByRole("switch", { name: "Automatic Evolution" }));
  expect(change).toHaveBeenLastCalledWith({ enabled: true });
  fireEvent.click(screen.getByRole("switch", { name: "Use cloud workers" }));
  expect(change).toHaveBeenLastCalledWith({ cloud_workers: false });
});
