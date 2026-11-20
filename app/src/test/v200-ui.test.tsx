import { describe, expect, it, beforeEach } from "vitest";
import { formatAttachments, splitAttachments } from "@/lib/attachments";
import { score } from "@/components/FeatureSearch";
import { ROOT_PX, setUiSize, stepUiSize, uiSizeStore } from "@/lib/ui-size";
import { setMotion } from "@/lib/motion";

describe("2.0 app size", () => {
  beforeEach(() => setUiSize("compact"));
  it("defaults to compact and scales the root font", () => {
    expect(uiSizeStore.getState().size).toBe("compact");
    expect(document.documentElement.style.fontSize).toBe(`${ROOT_PX.compact}px`);
  });
  it("steps within compact..large and remembers it", () => {
    stepUiSize(-1); expect(uiSizeStore.getState().size).toBe("compact");
    stepUiSize(1); stepUiSize(1); stepUiSize(1); expect(uiSizeStore.getState().size).toBe("large");
    expect(localStorage.getItem("moth.uiSize")).toBe("large");
    expect(document.documentElement.dataset.uiSize).toBe("large");
  });
  it("Ctrl + and Ctrl - change the size", async () => {
    const { startUiSizeShortcuts } = await import("@/lib/ui-size");
    const stop = startUiSizeShortcuts();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "=", ctrlKey: true }));
    expect(uiSizeStore.getState().size).toBe("normal");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "0", ctrlKey: true }));
    expect(uiSizeStore.getState().size).toBe("compact");
    stop();
  });
  it("animations can be switched off", () => {
    setMotion(false); expect(document.documentElement.dataset.motion).toBe("off");
    setMotion(true); expect(document.documentElement.dataset.motion).toBe("on");
  });
});

describe("2.0 command bar", () => {
  it("needs every word and ranks label starts first", () => {
    expect(score({ label: "New chat", group: "Actions" }, "zzz")).toBe(0);
    expect(score({ label: "New chat", group: "Actions" }, "new")).toBeGreaterThan(score({ label: "Renew things", group: "Actions" }, "new"));
    expect(score({ label: "App size: Large", description: "Make the whole app smaller or bigger", group: "Actions" }, "size large")).toBeGreaterThan(0);
  });
});

describe("2.0 dropped files", () => {
  it("round-trips files through a message, including code fences", () => {
    const files = [{ path: "src/a.py", name: "a.py", size: 10, content: "print(1)", truncated: false },
      { path: "README.md", name: "README.md", size: 20, content: "```js\nx\n```", truncated: false }];
    const text = formatAttachments("look at these", files);
    const out = splitAttachments(text);
    expect(out.body).toBe("look at these");
    expect(out.files).toEqual([{ path: "src/a.py", content: "print(1)", kind: "file" }, { path: "README.md", content: "```js\nx\n```", kind: "file" }]);
  });
  it("2.4: an image travels as the text read from it, with its id for the preview", () => {
    const img = { kind: "image" as const, image_id: "ab".repeat(16) + ".png", path: "shot.png", name: "shot.png", size: 5, content: "KeyError: 'value'", truncated: false };
    const out = splitAttachments(formatAttachments("why this error?", [img, { ...img, image_id: "cd".repeat(16) + ".png", name: "blank.png", path: "blank.png", content: "", note: "no engine" }]));
    expect(out.body).toBe("why this error?");
    expect(out.files[0]).toEqual({ path: "shot.png", content: "KeyError: 'value'", kind: "image", image_id: "ab".repeat(16) + ".png" });
    expect(out.files[1].content).toContain("no text could be read from it: no engine");
  });
  it("leaves ordinary messages alone", () => {
    expect(splitAttachments("hello ```code```")).toEqual({ body: "hello ```code```", files: [] });
  });
});
