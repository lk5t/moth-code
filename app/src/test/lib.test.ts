import { describe, expect, it, vi, beforeEach } from "vitest";
import { createStore } from "@/lib/store";
import { cn, formatNumber, languageFromPath } from "@/lib/utils";
import { _testing, subscribe } from "@/lib/events";

describe("utils", () => {
  it("formats numbers", () => {
    expect(formatNumber(49_295_872, 1)).toBe("49.3M");
    expect(formatNumber(1500, 1)).toBe("1.5K");
    expect(formatNumber(12)).toBe("12");
    expect(formatNumber(null)).toBe("—");
  });
  it("maps file extensions to Monaco languages", () => {
    expect(languageFromPath("src/app.tsx")).toBe("typescript");
    expect(languageFromPath("main.py")).toBe("python");
    expect(languageFromPath("LICENSE")).toBe("plaintext");
  });
  it("merges tailwind classes", () => {
    expect(cn("px-2", "px-4", false && "hidden")).toBe("px-4");
  });
});

describe("store", () => {
  it("notifies subscribers and merges state", () => {
    const s = createStore({ a: 1, b: "x" });
    const fn = vi.fn();
    s.subscribe(fn);
    s.setState({ a: 2 });
    s.setState((st) => ({ b: st.b + "y" }));
    expect(s.getState()).toEqual({ a: 2, b: "xy" });
    expect(fn).toHaveBeenCalledTimes(2);
  });
});

describe("event bus", () => {
  beforeEach(() => _testing.listeners.clear());
  it("routes events by topic and wildcard, and unsubscribes", () => {
    const chat = vi.fn();
    const all = vi.fn();
    const off = subscribe("chat", chat);
    subscribe("*", all);
    _testing.dispatch({ topic: "chat", ts: 0, text: "hi" });
    _testing.dispatch({ topic: "job", ts: 0 });
    expect(chat).toHaveBeenCalledTimes(1);
    expect(all).toHaveBeenCalledTimes(2);
    off();
    _testing.dispatch({ topic: "chat", ts: 0 });
    expect(chat).toHaveBeenCalledTimes(1);
  });
});
