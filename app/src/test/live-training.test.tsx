import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveVitals, recentTrend, WritingNow } from "@/features/intelligence/live/Learning";
import { LossChart } from "@/features/intelligence/live/LossChart";
import { alertPrefs, setAlertPrefs } from "@/lib/alerts";

describe("0.10.0 live training", () => {
  it("2.5: shows measured speed, held-out trend and each training computer's real load", () => {
    const history = [3.0, 2.9, 2.8, 2.7, 2.6, 2.5].map((loss, i) => ({ step: i * 10, loss, split: "val" }));
    expect(recentTrend(history)).toBeCloseTo((2.5 - 3.0) / 3.0);
    expect(recentTrend([])).toBeNull();
    render(<LiveVitals report={{ tokens_per_sec: 9400, val_loss: 2.5, history, round: 21, rounds: 29 }} passes={2.4}
      compute={[{ name: "gpu-box", kind: "gpu", gpu: 0.93, gpu_temp_c: 71, part_progress: 0.4, seen_seconds_ago: 12 }]} />);
    expect(screen.getByLabelText("Live measurements")).toBeInTheDocument();
    expect(screen.getByText("22 / 29")).toBeInTheDocument();
    expect(screen.getByText("2.4×")).toBeInTheDocument();
    expect(screen.getByText("93%")).toBeInTheDocument();
    expect(screen.getByText(/71°C/)).toBeInTheDocument();
    expect(screen.getByText("40% of part")).toBeInTheDocument();
  });

  it("draws the loss curve and marks the drop since the start", () => {
    const pts = [1, 2, 3, 4].map((s) => ({ step: s * 10, loss: 4 - s * 0.5, split: "train" }));
    render(<LossChart points={[...pts, { step: 40, loss: 2.2, split: "val" }]} live />);
    expect(screen.getByRole("img", { name: /Loss from step 10 to 40/ })).toBeInTheDocument();
    expect(screen.getByText(/lower than at the start/)).toBeInTheDocument();
  });

  it("shows what MOTH writes now and earlier", () => {
    render(<WritingNow prompt="Hi" samples={[{ step: 10, text: "aaa" }, { step: 20, text: "hello there" }]} />);
    expect(screen.getByText(/step 10: aaa/)).toBeInTheDocument();
    expect(screen.getByText(/step 20/)).toBeInTheDocument();
  });

  it("remembers the alert preferences on this computer", () => {
    setAlertPrefs({ keepInTray: false });
    expect(alertPrefs().keepInTray).toBe(false);
    expect(alertPrefs().notifications).toBe(true);
  });
});

describe("1.0 error watcher", () => {
  it("spots errors in terminal output", async () => {
    const { spotError, stripAnsi } = await import("@/features/workspace/TerminalPanel");
    expect(spotError("$ python a.py\nTraceback (most recent call last):\n  File \"a.py\", line 1\nNameError: name 'x' is not defined\n"))
      .toBe("NameError: name 'x' is not defined");
    expect(spotError("\nnpm ERR! missing script: start\n")).toBe("npm ERR! missing script: start");
    expect(spotError("all good\n3 passed\n")).toBeNull();
    expect(stripAnsi("\x1b[31mred\x1b[0m")).toBe("red");
  });
});

describe("1.0 honest answers", () => {
  it("flags garbled replies but not normal ones", async () => {
    const { looksBroken } = await import("@/features/chat/ChatPanel");
    expect(looksBroken("Hel the the ar yoou xqzt vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv")).toBe(true);
    expect(looksBroken("#$%^ &*() ### !!! ~~~ ^^^")).toBe(true);
    expect(looksBroken("Hello! I am doing well today. How can I help you?")).toBe(false);
    expect(looksBroken("```py\nx = 1\n```")).toBe(false);
    expect(looksBroken("anything", "repetition")).toBe(true);
  });
});

describe("1.0 live preview", () => {
  it("finds the local address a dev server prints", async () => {
    const { spotPreviewUrl } = await import("@/features/workspace/PreviewPane");
    expect(spotPreviewUrl("  ➜  Local:   http://localhost:5173/\n")).toBe("http://localhost:5173/");
    expect(spotPreviewUrl("Running on http://0.0.0.0:8000.")).toBe("http://localhost:8000");
    expect(spotPreviewUrl("see https://example.com")).toBeNull();
  });
});

describe("1.0 home", () => {
  it("greets by the time of day", async () => {
    const { greeting } = await import("@/features/home/HomeView");
    expect(greeting(8)).toBe("Good morning");
    expect(greeting(14)).toBe("Good afternoon");
    expect(greeting(20)).toBe("Good evening");
    expect(greeting(2)).toBe("Good night");
  });
});
