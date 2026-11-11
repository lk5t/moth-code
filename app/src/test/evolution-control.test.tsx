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
  m.api.mockImplementation(async (path: string, init?: any) => {
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
