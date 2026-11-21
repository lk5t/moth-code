import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataMeter } from "@/features/home/HomeExtras";

describe("2.5 training data meter", () => {
  it("shows distinct tokens against what MOTH's size needs, and how often it has been read", () => {
    render(<DataMeter status={{ prepared_tokens: 40e6, needed_tokens: 117e6, params: 5.86e6, passes: 2.6, sources: 9, enough: false }} />);
    expect(screen.getByText("growing")).toBeTruthy();
    expect(screen.getByText(/need ~117\.0M/)).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("34");
    expect(screen.getByText(/read 2\.6× \(more data coming\)/)).toBeTruthy();
  });
  it("shows nothing before MOTH Cloud reports it", () => {
    const { container } = render(<DataMeter status={{}} />);
    expect(container.innerHTML).toBe("");
  });
});
