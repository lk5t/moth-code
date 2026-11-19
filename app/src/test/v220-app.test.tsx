import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TimelineChart } from "@/features/intelligence/IntelligenceView";

const v = (version: number, value: number, extra: Record<string, unknown> = {}) =>
  ({ version, name: `moth-evolution-v${version}`, benchmarks: { holdout_language: { value, higher_is_better: false } }, ...extra });

describe("2.2 MOTH timeline", () => {
  const versions = [v(150, 5.62, { deployed: true, deployed_at: 1 }), ...Array.from({ length: 36 }, (_, i) => v(151 + i, 1.5 + (i % 5) * 0.03))];

  it("labels at most ~8 versions so the axis stays readable", () => {
    const { container } = render(<TimelineChart versions={versions} metric="holdout_language" />);
    const labels = [...container.querySelectorAll("text")].map((t) => t.textContent).filter((t) => /^v\d+$/.test(t ?? ""));
    expect(labels.length).toBeGreaterThan(3);
    expect(labels.length).toBeLessThanOrEqual(9);
    expect(labels).toContain("v186");
  });

  it("does not flatten the chart for one far-off point, and marks it off scale with its value", () => {
    const { container } = render(<TimelineChart versions={versions} metric="holdout_language" />);
    expect(screen.getByText("↑ off scale")).toBeInTheDocument();
    expect([...container.querySelectorAll("text")].some((t) => t.textContent === "5.620")).toBe(true);
  });

  it("sets promoted versions apart from candidates and shows a readout on hover", () => {
    render(<TimelineChart versions={versions} metric="holdout_language" />);
    expect(screen.getByText("candidate, not promoted")).toBeInTheDocument();
    fireEvent.focus(screen.getByRole("button", { name: /v151\): 1\.500, not promoted/ }));
    expect(screen.getByText("candidate · not promoted")).toBeInTheDocument();
    fireEvent.focus(screen.getByRole("button", { name: /v150\): 5\.620$/ }));
    expect(screen.getAllByText("serving now")).toHaveLength(2); // legend + readout
  });
});

describe("2.2 Home activity", () => {
  it("collapses repeated lines into one with a count", async () => {
    const { collapseRepeats } = await import("@/features/home/HomeView");
    const out = collapseRepeats([{ message: "Opened demo" }, { message: "Opened demo" }, { message: "Saved" }, { message: "Opened demo" }]);
    expect(out.map((x) => [x.message, x.times])).toEqual([["Opened demo", 2], ["Saved", 1], ["Opened demo", 1]]);
  });
});
