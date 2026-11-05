/** Single reconnecting WebSocket to /ws/events with topic subscriptions. */
import { useEffect, useRef } from "react";
import { backend } from "./backend";

export interface MothEvent {
  topic: string;
  ts: number;
  [key: string]: any;
}

type Listener = (e: MothEvent) => void;

const listeners = new Map<string, Set<Listener>>();
let socket: WebSocket | null = null;
let retry = 0;
let started = false;

function connect() {
  const b = backend();
  const url = b.url.replace(/^http/, "ws") + `/ws/events?token=${encodeURIComponent(b.token)}`;
  socket = new WebSocket(url);
  socket.onopen = () => {
    retry = 0;
    dispatch({ topic: "connection", ts: Date.now() / 1000, connected: true });
  };
  socket.onmessage = (msg) => {
    try {
      dispatch(JSON.parse(msg.data));
    } catch {
      /* ignore malformed */
    }
  };
  socket.onclose = () => {
    dispatch({ topic: "connection", ts: Date.now() / 1000, connected: false });
    const delay = Math.min(5000, 250 * 2 ** retry++);
    setTimeout(connect, delay);
  };
}

function dispatch(e: MothEvent) {
  listeners.get(e.topic)?.forEach((fn) => fn(e));
  listeners.get("*")?.forEach((fn) => fn(e));
}

export function startEvents() {
  if (started) return;
  started = true;
  connect();
}

export function subscribe(topic: string, fn: Listener): () => void {
  if (!listeners.has(topic)) listeners.set(topic, new Set());
  listeners.get(topic)!.add(fn);
  return () => listeners.get(topic)?.delete(fn);
}

/** React hook: the latest callback is always used without resubscribing. */
export function useEvent(topic: string, fn: Listener) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => subscribe(topic, (e) => ref.current(e)), [topic]);
}

export const _testing = { dispatch, listeners };
