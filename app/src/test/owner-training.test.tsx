import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WorkersPanel } from "@/features/owner/ops";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/account", () => ({ serverApi: api, withReauth: (fn: () => Promise<unknown>) => fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("keeps the owner's worker controls; Evolution assigns the work itself", async () => {
  api.mockImplementation((path: string) => Promise.resolve(path === "/v1/admin/workers" ? [{
    id: 7, name: "CPU", owner: "lk5t", status: "online", paused: false, hardware: { cpu_count: 2, gpus: [] },
  }] : []));
  render(<WorkersPanel />);
  fireEvent.click(await screen.findByRole("button", { name: "Pause" }));
  expect(screen.queryByRole("button", { name: /Start (All Compatible Workers|Training|Server CPU Training)/ })).toBeNull();
  expect(screen.queryByText("Training jobs")).toBeNull();  // the manual job list is retired
  expect(screen.getByText(/Evolution assigns work to these computers automatically/)).toBeInTheDocument();
  await waitFor(() => expect(api).toHaveBeenCalledWith("/v1/training/workers/7/pause", { method: "POST", json: undefined }));
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/v1/training/workers/7/stop", { method: "POST", json: undefined }));
});
