import { describe, expect, it } from "vitest";
import { withTab } from "@/features/chat/ChatTabs";
import { partState } from "@/features/intelligence/SharedTraining";

describe("2.4 chat tabs", () => {
  it("adds a chat at the end, renames it in place and keeps at most 8", () => {
    let tabs = withTab([], 1, "One");
    tabs = withTab(tabs, 2, "Two");
    expect(withTab(tabs, 1, "One")).toBe(tabs);  // unchanged: same array
    expect(withTab(tabs, 1, "Renamed").map((t) => t.title)).toEqual(["Renamed", "Two"]);
    for (let i = 3; i <= 10; i++) tabs = withTab(tabs, i, `#${i}`);
    expect(tabs.map((t) => t.id)).toEqual([3, 4, 5, 6, 7, 8, 9, 10]);
  });
});

describe("2.3.2 shared training in plain words", () => {
  it("describes each part", () => {
    expect(partState({ status: "completed" }).label).toBe("done");
    expect(partState({ status: "leased", progress: 0.4 }).label).toBe("training · 40%");
    expect(partState({ status: "queued", progress: 0.9 }).label).toContain("the last one stopped at 90%");
    expect(partState({ status: "cancelled" }).tone).toBe("off");
  });
});
