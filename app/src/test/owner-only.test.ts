import { describe, expect, it } from "vitest";
import { isOwnerView, WORKSPACES } from "@/lib/navigation";
import { resetIn } from "@/components/UsageRing";

describe("1.0.12 owner-only views and usage ring", () => {
  it("keeps MOTH's training, data, models and administration for the Owner", () => {
    for (const v of ["intelligence", "evolution", "data", "models", "training", "owner"] as const) expect(isOwnerView(v)).toBe(true);
    for (const v of ["home", "chat", "workspace", "network", "settings"] as const) expect(isOwnerView(v)).toBe(false);
    expect(WORKSPACES.find((w) => w.view === "intelligence")?.ownerOnly).toBe(true);
  });
  it("says when usage frees up", () => {
    expect(resetIn(null)).toBe("not in use");
    expect(resetIn(1000 + 30 * 60, 1000)).toBe("frees up in 30 min");
    expect(resetIn(1000 + 2 * 86400 + 3600, 1000)).toBe("frees up in 2 d 1 h");
  });
});
