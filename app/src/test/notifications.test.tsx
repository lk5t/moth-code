import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
const mocks = vi.hoisted(() => ({ api: vi.fn(), role: "owner" }));
vi.mock("@/lib/account", () => ({ serverApi: mocks.api, useAccount: (fn: (s: any) => unknown) => fn({ token: "t", serverUrl: "https://cloud", user: { role: mocks.role } }) }));
import { ActivityNotices } from "@/components/ActivityNotices";

afterEach(() => { cleanup(); vi.clearAllMocks(); mocks.role = "owner"; });

describe("Owner notifications", () => {
  it("shows the Owner's unread count from the owner-only endpoint", async () => {
    mocks.api.mockResolvedValue({ unread: 2, items: [
      { id: 9, ts: 1794500000, title: "Deployment rolled back", message: "v8 was rolled back", level: "error", category: "rollback", unread: true },
      { id: 7, ts: 1794400000, title: "New MOTH version promoted", message: "MOTH 0.0.3", level: "info", category: "promotion", unread: true }] });
    render(<ActivityNotices />);
    expect(await screen.findByRole("button", { name: "2 unread notifications" })).toBeInTheDocument();
    expect(mocks.api).toHaveBeenCalledWith("/v1/admin/notifications?limit=30");
  });
  it("is absent for every other account and never requests notifications", async () => {
    mocks.role = "user";
    render(<ActivityNotices />);
    await waitFor(() => expect(mocks.api).not.toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /notifications/i })).toBeNull();
  });
});
