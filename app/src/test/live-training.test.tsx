import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { stageOf, StageMeter, WritingNow } from "@/features/intelligence/live/Learning";
import { LossChart } from "@/features/intelligence/live/LossChart";
import { alertPrefs, setAlertPrefs } from "@/lib/alerts";

describe("0.10.0 live training", () => {
  it("names the learning stage from the measured loss", () => {
    expect(stageOf(4.0)?.index).toBe(0);           // babbling
    expect(stageOf(2.0)?.index).toBe(2);           // words
    expect(stageOf(1.0)?.index).toBe(4);           // sentences
    expect(stageOf(3.6, "token")?.index).toBe(4);  // 1.0 per byte with a BPE tokenizer
    expect(stageOf(null)).toBeNull();
    render(<StageMeter loss={2.0} per="byte" />);
    expect(screen.getByLabelText("Learning stage: Words")).toBeInTheDocument();
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
