"""Thread-safe publish/subscribe bus used to stream events to the UI.

Subsystems (terminal, agent, training, community) run in worker threads and
publish dictionaries; WebSocket handlers subscribe with an asyncio queue.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._async_subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._sync_subs: list[Callable[[dict[str, Any]], None]] = []

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        event = {"topic": topic, "ts": time.time(), **payload}
        with self._lock:
            async_subs = list(self._async_subs)
            sync_subs = list(self._sync_subs)
        for loop, queue in async_subs:
            try:
                loop.call_soon_threadsafe(_put_nowait, queue, event)
            except RuntimeError:  # loop closed
                self.unsubscribe_async(queue)
        for fn in sync_subs:
            try:
                fn(event)
            except Exception:  # never let a subscriber break a publisher
                pass

    def subscribe_async(self, maxsize: int = 10000) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._async_subs.append((loop, queue))
        return queue

    def unsubscribe_async(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._async_subs = [(l, q) for l, q in self._async_subs if q is not queue]

    def subscribe(self, fn: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        with self._lock:
            self._sync_subs.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._sync_subs:
                    self._sync_subs.remove(fn)

        return unsubscribe


def _put_nowait(queue: asyncio.Queue, event: dict[str, Any]) -> None:
    if queue.full():  # drop oldest rather than block publishers
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(event)
