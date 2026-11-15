import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NetworkTraining } from "@/features/training/NetworkTraining";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/account", () => ({ serverApi: api }));
vi.mock("@/lib/backend", () => ({ get: () => Promise.resolve({ available: true, enabled: false }), put: vi.fn() }));
vi.mock("@/features/owner/ops", () => ({ secure: (fn: () => Promise<unknown>) => fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it("has no switch that leaves cloud computers out of training (1.0.14)", async () => {
  api.mockImplementation((path: string) => Promise.resolve(path.endsWith("/status") ? {
    settings: { backends: { workers: true }, distributed: { enabled: true } }, cycle: null,
  } : {}));
  render(<NetworkTraining />);
  await screen.findByRole("switch", { name: "Contribute this computer" });
  expect(screen.queryByRole("switch", { name: "Use cloud workers" })).toBeNull();
});
