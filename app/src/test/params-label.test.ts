import { describe, expect, it } from "vitest";
import { paramsLabel } from "@/lib/params";

describe("paramsLabel", () => {
  it("says a count was measured only when the server verified it from the weights", () => {
    expect(paramsLabel(5184768, true)).toBe("5,184,768 parameters · counted from the saved weights");
    expect(paramsLabel(5184768, false)).toBe("5,184,768 parameters · registered count, not yet counted from the weights");
    expect(paramsLabel(5184768)).toBe("5,184,768 parameters");
    expect(paramsLabel(null, true)).toBe("Parameters not recorded");
  });
});
