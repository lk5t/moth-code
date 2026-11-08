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

import { normalizeServerUrl } from "@/lib/account";

describe("normalizeServerUrl", () => {
  it("adds https:// to a bare domain and http:// to local addresses", () => {
    expect(normalizeServerUrl("moth.example.com")).toBe("https://moth.example.com");
    expect(normalizeServerUrl(" moth.example.com/ ")).toBe("https://moth.example.com");
    expect(normalizeServerUrl("127.0.0.1:8900")).toBe("http://127.0.0.1:8900");
    expect(normalizeServerUrl("localhost:8900")).toBe("http://localhost:8900");
  });
  it("drops API paths users paste by mistake but keeps a real prefix", () => {
    expect(normalizeServerUrl("https://moth.example.com/v1/auth/login")).toBe("https://moth.example.com");
    expect(normalizeServerUrl("https://moth.example.com/cloud")).toBe("https://moth.example.com");
    expect(normalizeServerUrl("https://example.com/moth/")).toBe("https://example.com/moth");
  });
  it("rejects invalid addresses and other schemes", () => {
    expect(() => normalizeServerUrl("ftp://moth.example.com")).toThrow();
    expect(() => normalizeServerUrl("http://")).toThrow();
    expect(normalizeServerUrl("")).toBe("");
  });
});

import { backoffMs, versionLess } from "@/lib/connection";
import { MOTH_ENV, resolveServer, setUserServer, userServer } from "@/lib/endpoint";

describe("connection", () => {
  it("backs off exponentially up to a minute", () => {
    expect([1, 2, 3, 4, 5, 6, 10].map(backoffMs)).toEqual([2000, 4000, 8000, 16000, 32000, 60000, 60000]);
  });
  it("compares versions numerically", () => {
    expect(versionLess("0.2.1", "0.3.0")).toBe(true);
    expect(versionLess("0.10.0", "0.9.9")).toBe(false);
    expect(versionLess("0.3.0", "0.3.0")).toBe(false);
  });
});

describe("endpoint", () => {
  it("uses the built-in endpoint unless the user chose another address", () => {
    expect(MOTH_ENV).toBe("development"); // vitest runs in dev mode
    expect(resolveServer()).toBe("http://127.0.0.1:8900");
    setUserServer("https://proceed-presently.trycloudflare.com");
    expect(userServer()).toBe("https://proceed-presently.trycloudflare.com");
    expect(resolveServer()).toBe("https://proceed-presently.trycloudflare.com");
    setUserServer(null);
    expect(resolveServer()).toBe("http://127.0.0.1:8900");
  });
});

import { requestError } from "@/lib/errors";
describe("API validation messages", () => {
  it("renders the reported query.body failure as a readable message", () => {
    expect(requestError([{ type: "missing", loc: ["query", "body"], msg: "Field required", input: null }], "Bad request")).toBe("Field required");
    expect(requestError([{ loc: ["body", "enabled"], msg: "Input should be a valid boolean" }], "Bad request")).toBe("enabled: Input should be a valid boolean");
  });
});
