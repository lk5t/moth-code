import { describe, expect, it } from "vitest";
import { honestCapability } from "@/features/home/HomeView";

describe("honest capability text", () => {
  it("says a small model cannot yet do real tasks", () => {
    expect(honestCapability(5_857_920)).toMatch(/5\.9 million.*cannot yet reliably/);
    expect(honestCapability(null)).toBeNull();
  });
  it("is less cautious as MOTH grows", () => {
    expect(honestCapability(120e6)).toMatch(/120 million.*often need checking/);
    expect(honestCapability(3e9)).toMatch(/3\.0 billion/);
  });
});
