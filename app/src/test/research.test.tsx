import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/account", () => ({ serverApi: mocks.api, useAccount: (fn: (s: any) => unknown) => fn({ token: "t" }) }));
import { DocRow, Research } from "@/features/intelligence/IntelligenceSection";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Knowledge 2.0 and Research", () => {
  it("shows a document's category, project, review state and lets its owner verify it", async () => {
    mocks.api.mockResolvedValue({});
    const reload = vi.fn();
    render(<DocRow d={{ id: 4, title: "Deploy notes", version: 2, updated_at: 1794500000, shared: false,
      meta: { category: "project", project: "moth-site", confidence: 0.6, verified: false, stale: true, near_duplicate_of: 3 } }} reload={reload} />);
    expect(screen.getByText("project: moth-site")).toBeInTheDocument();
    expect(screen.getByText("review: may be outdated")).toBeInTheDocument();
    expect(screen.getByText("similar to another document")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark Deploy notes verified" }));
    expect(mocks.api).toHaveBeenCalledWith("/v1/knowledge/4", { method: "PATCH", json: { verified: true } });
  });
  it("renders a cited report with conflicts and gaps, never as verified fact", async () => {
    mocks.api.mockResolvedValue({ summary: { sources: 2, corroborated: 1, single_source: 1, conflicts: 1 },
      findings: [{ text: "The worker uses port 8900.", cite: 1, status: "corroborated" }],
      conflicts: [{ a: { cite: 1 }, b: { cite: 2 }, why: "different numbers: 8900 vs 8901" }], gaps: ["kubernet"],
      sources: [{ n: 1, title: "Release guide", verified: false }, { n: 2, title: "Ops notes", verified: true }] });
    render(<Research />);
    fireEvent.change(screen.getByPlaceholderText("Ask a research question…"), { target: { value: "worker port?" } });
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(await screen.findByText(/different numbers: 8900 vs 8901/)).toBeInTheDocument();
    expect(screen.getByText(/Not covered by any source: kubernet/)).toBeInTheDocument();
    expect(screen.getByText(/\[2\] Ops notes \(verified\)/)).toBeInTheDocument();
  });
});
