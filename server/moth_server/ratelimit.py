"""Database-backed sliding-window rate limiting (works across restarts and multiple processes)."""

from __future__ import annotations

from sqlalchemy import delete, func, select

from moth_server.db import Database, now, rate_events


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__("too many requests")
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self, db: Database):
        self.db = db

    def hit(self, key: str, limit: int, window: float, consume: bool = True) -> None:
        """Raise RateLimited if ``key`` already has ``limit`` events in the last ``window`` seconds."""
        t = now()
        with self.db.tx() as c:
            c.execute(delete(rate_events).where(rate_events.c.key == key, rate_events.c.ts < t - window))
            count, oldest = c.execute(select(func.count(), func.min(rate_events.c.ts))
                                      .where(rate_events.c.key == key)).one()
            if count >= limit:
                raise RateLimited(max(1, int(oldest + window - t)))
            if consume:
                c.execute(rate_events.insert().values(key=key, ts=t))

    def clear(self, key: str) -> None:
        with self.db.tx() as c:
            c.execute(delete(rate_events).where(rate_events.c.key == key))
