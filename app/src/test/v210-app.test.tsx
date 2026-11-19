import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
vi.mock("@/lib/account", () => ({ serverApi: vi.fn(), accountStore: { getState: () => ({ token: null }), subscribe: () => () => {} }, useAccount: (fn: (s: any) => unknown) => fn({ user: { id: 1 } }) }));
import { STEPS, Tour, reopenTour } from "@/features/onboarding/Tour";
import { applyPrefs, current } from "@/lib/prefs-sync";
import { uiSizeStore, setUiSize } from "@/lib/ui-size";
import { motionStore, setMotion } from "@/lib/motion";
import { alertPrefs } from "@/lib/alerts";

afterEach(cleanup);

describe("2.1 guided tour", () => {
  it("walks through every step once and remembers it", () => {
    localStorage.removeItem("moth.tour.done");
    reopenTour();
    render(<Tour />);
    for (let i = 0; i < STEPS.length - 1; i++) {
      expect(screen.getByText(STEPS[i].title)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
    }
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(localStorage.getItem("moth.tour.done")).toBe("1");
    expect(screen.queryByText(STEPS[0].title)).toBeNull();
  });
});

describe("2.1 settings sync", () => {
  it("applies preferences from the account", () => {
    setUiSize("compact"); setMotion(true);
    applyPrefs({ ui_size: "large", motion: false, quiet_alerts: false, sounds: true });
    expect(uiSizeStore.getState().size).toBe("large");
    expect(motionStore.getState().on).toBe(false);
    expect(alertPrefs().quiet).toBe(false);
    expect(current()).toEqual({ ui_size: "large", motion: false, quiet_alerts: false, sounds: true });
    applyPrefs({ ui_size: "nonsense" as never });
    expect(uiSizeStore.getState().size).toBe("large");  // unknown values are ignored
  });
});
