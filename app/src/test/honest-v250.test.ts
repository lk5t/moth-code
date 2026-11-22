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

import { shapeText } from "@/features/intelligence/ModelTab";

describe("2.5.2 model shape in plain words", () => {
  it("describes layers, width, context and tokenizer", () => {
    expect(shapeText({ n_layers: 3, d_model: 384, vocab_size: 512, max_seq_len: 2048 }))
      .toBe("Shape: 3 layers × 384 wide, sees 2,048 tokens at once; reads text one byte at a time.");
    expect(shapeText({ n_layers: 16, d_model: 384, vocab_size: 8192 })).toContain("8,192 word pieces");
    expect(shapeText({})).toBeNull();
  });
});
