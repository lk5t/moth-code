import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { OwnerDashboard } from "@/features/owner/OwnerDashboard";
import { appStore } from "@/lib/app-state";
import { ModelOverview } from "@/features/owner/ModelOverview";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/account", () => ({ serverApi: api, withReauth: (fn: () => Promise<unknown>) => fn(),
  useAccount: (fn: (s: unknown) => unknown) => fn({ user: { role: "owner" } }) }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("keeps administration in Owner tools and routes native AI into Intelligence", async () => {
  api.mockResolvedValue(null);
  render(<OwnerDashboard />);
  const primary = screen.getByRole("tablist", { name: "Owner sections" });
  expect(within(primary).getAllByRole("tab").map(t => t.textContent)).toEqual(["Overview", "Servers", "Community", "Settings"]);
  fireEvent.click(screen.getByRole("button", { name: "View active model" }));
  expect(appStore.getState()).toMatchObject({ view: "intelligence", intelligenceTab: "evolution" });
  fireEvent.mouseDown(within(primary).getByRole("tab", { name: "Settings" }), { button: 0 });
  await screen.findByRole("tab", { name: "Updates" });
  expect(screen.getByRole("tab", { name: "Audit log" })).toBeInTheDocument();
});

it("shows exact parameters and marks missing measurements unavailable", async () => {
  api.mockResolvedValue({ model: { release: 1, name: "MOTH 0.01", model_version: "0.01", params: 99648,
    training: {}, status: "uploaded" }, training: {}, workers: {}, accepted_versions: [] });
  render(<ModelOverview />);
  await waitFor(() => expect(screen.getByText("Exact parameters").parentElement).toHaveTextContent("99,648"));
  expect(screen.getByText("Total training steps").parentElement).toHaveTextContent("Unavailable");
  expect(screen.getByText("Training loss").parentElement).toHaveTextContent("Unavailable");
  expect(screen.getByText("Checkpoint size").parentElement).toHaveTextContent("Unavailable");
});
