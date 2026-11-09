import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NetworkTraining } from "@/features/training/NetworkTraining";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/account", () => ({ serverApi: api }));
vi.mock("@/lib/backend", () => ({ get: () => Promise.resolve({ available: true, enabled: false }), put: vi.fn() }));
vi.mock("@/features/owner/ops", () => ({ secure: (fn: () => Promise<unknown>) => fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it("controls cloud infrastructure independently of personal contribution", async () => {
  api.mockImplementation((path: string) => Promise.resolve(path.endsWith("/status") ? {
    settings: { backends: { workers: true }, distributed: { enabled: true } }, cycle: null,
  } : {}));
  render(<NetworkTraining />);
  fireEvent.click(await screen.findByRole("switch", { name: "Use cloud workers" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/v1/admin/evolution/settings", {
    method: "PUT", json: { changes: { cloud_workers: false } },
  }));
});
