import { expect, it } from "vitest";
import { modelLabel } from "@/lib/model-label";

it("shows one public MOTH identity and never internal package names", () => {
  expect(modelLabel({ display_name: "MOTH 0.0.7", name: "moth-evolution-v50-e8" })).toBe("MOTH 0.0.7");
  expect(modelLabel({ model_version: "0.0.3", name: "moth-evolution-e12" })).toBe("MOTH 0.0.3");
  expect(modelLabel({ name: "moth-evolution-v50-e8" })).toBe("MOTH");
  expect(modelLabel("moth-network-v00003")).toBe("MOTH");
  expect(modelLabel(null)).toBe("MOTH");
});
