import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { EvolutionControls } from "@/features/training/EvolutionControls";
afterEach(cleanup);
it("sends only the selected policy and never resumes paused training implicitly", () => {
  const change = vi.fn();
  render(<EvolutionControls settings={{ enabled: false, paused: true, auto_deploy: false }} onChange={change} />);
  // on/off is Pause/Resume plus the schedule; the old "Automatic Evolution" switch no longer exists
  expect(screen.getAllByRole("switch")).toHaveLength(2);
  expect(screen.getAllByRole("combobox")).toHaveLength(3);
  fireEvent.change(screen.getByRole("combobox", { name: "Training Mode" }), { target: { value: "eco" } });
  expect(change).toHaveBeenLastCalledWith({ training_mode: "eco" });
  fireEvent.change(screen.getByRole("combobox", { name: "Training schedule" }), { target: { value: "automatic" } });
  expect(change).toHaveBeenLastCalledWith({ automatic: true });
  expect(change).not.toHaveBeenCalledWith(expect.objectContaining({ paused: false }));
  fireEvent.click(screen.getByRole("switch", { name: "Use cloud workers" }));
  expect(change).toHaveBeenLastCalledWith({ cloud_workers: false });
});
