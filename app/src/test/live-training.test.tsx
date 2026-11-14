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
