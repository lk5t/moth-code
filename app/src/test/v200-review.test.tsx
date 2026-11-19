import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { diffLines, diffStats, folded, sideBySide } from "@/lib/diff";
import { codeTarget, highlight } from "@/lib/highlight";
import { Markdown } from "@/features/chat/Markdown";
import { DiffView } from "@/features/workspace/DiffView";

describe("2.0 diff", () => {
  it("finds added and removed lines", () => {
    const rows = diffLines("a\nb\nc\nd", "a\nB\nc\nd\ne");
    expect(diffStats(rows)).toEqual({ added: 2, removed: 1 });
    expect(rows.filter((r) => r.t === "same").map((r) => r.text)).toEqual(["a", "c", "d"]);
    const pairs = sideBySide(rows);
    expect(pairs.find((p) => p.left?.t === "del")?.right?.text).toBe("B");  // replaced line sits next to its replacement
  });
  it("new files are all additions and long unchanged runs fold", () => {
    expect(diffStats(diffLines("", "x\ny"))).toEqual({ added: 2, removed: 0 });
    const before = Array.from({ length: 50 }, (_, i) => `l${i}`).join("\n");
    const after = before.replace("l25", "changed");
    const f = folded(sideBySide(diffLines(before, after)));
    expect(f.filter((x) => "skip" in x).length).toBe(2);
  });
  it("renders a before/after table", () => {
    render(<DiffView path="src/a.py" before={"x = 1\n"} after={"x = 2\n"} />);
    expect(screen.getByText("src/a.py")).toBeTruthy();
    expect(screen.getByText("+1")).toBeTruthy();
    expect(screen.getByText("−1")).toBeTruthy();
  });
});

describe("2.0 messages", () => {
  it("highlights keywords, strings and comments", () => {
    const t = highlight("def f(x):\n    return 'hi'  # done", "python");
    expect(t.find((x) => x.k === "kw")?.v).toBe("def");
    expect(t.find((x) => x.k === "str")?.v).toBe("'hi'");
    expect(t.find((x) => x.k === "com")?.v).toBe("# done");
    expect(highlight("whatever", "unknownlang")).toEqual([{ k: "plain", v: "whatever" }]);
  });
  it("finds the file a code block is for, and refuses paths outside the project", () => {
    expect(codeTarget("python src/app.py", "x")).toBe("src/app.py");
    expect(codeTarget("js", "// file: web/main.js\nx")).toBe("web/main.js");
    expect(codeTarget("python", "print(1)")).toBeNull();
    expect(codeTarget("python ../../etc/passwd", "x")).toBeNull();
  });
  it("renders lists, headings, bold and keeps HTML inert", () => {
    const { container } = render(<Markdown text={"## Steps\n- **one**\n- two\n\n1. first\n2. second\n\n<b>raw</b>"} />);
    expect(container.querySelectorAll("ul li").length).toBe(2);
    expect(container.querySelectorAll("ol li").length).toBe(2);
    expect(container.querySelector("strong")?.textContent).toBe("one");
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByRole("heading").textContent).toBe("Steps");
  });
});
