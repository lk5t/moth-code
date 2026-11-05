import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Markdown } from "@/features/chat/Markdown";
import { LossChart } from "@/components/LossChart";
import { ErrorBoundary } from "@/components/ErrorBoundary";

describe("Markdown", () => {
  it("renders code blocks and inline code", () => {
    const { container } = render(<Markdown text={"Use `add`:\n\n```python\ndef add(a, b):\n    return a + b\n```"} />);
    expect(container.querySelector("pre code")?.textContent).toBe("def add(a, b):\n    return a + b");
    expect(screen.getByText("add").tagName).toBe("CODE");
  });
  it("never injects HTML from model output", () => {
    const { container } = render(<Markdown text={'<img src=x onerror="alert(1)"><script>alert(1)</script>'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>");
  });
});

describe("LossChart", () => {
  it("shows an empty state without metrics", () => {
    render(<LossChart points={[]} />);
    expect(screen.getByText("No metrics logged yet")).toBeInTheDocument();
  });
  it("draws train and validation series", () => {
    const { container } = render(
      <LossChart points={[
        { step: 1, split: "train", loss: 8 }, { step: 50, split: "train", loss: 5 },
        { step: 50, split: "val", loss: 5.5 }, { step: 100, split: "val", loss: 4.5 },
      ]} />,
    );
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBe(2);
    expect(container.querySelectorAll("circle").length).toBe(2);
  });
});

describe("ErrorBoundary", () => {
  it("contains render crashes", () => {
    const Boom = () => {
      throw new Error("kaboom");
    };
    const spy = console.error;
    console.error = () => {};
    render(<ErrorBoundary label="Training"><Boom /></ErrorBoundary>);
    console.error = spy;
    expect(screen.getByText("Training hit an unexpected error")).toBeInTheDocument();
    expect(screen.getByText("kaboom")).toBeInTheDocument();
  });
});
