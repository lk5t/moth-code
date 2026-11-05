"""User-controlled participation settings: opt-in, GPU limits, schedule, pause."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ParticipationSettings:
    enabled: bool = False  # strictly opt-in
    paused: bool = False
    coordinator_url: str = ""  # none by default: no public coordinator is operated yet
    gpu_memory_fraction: float = 0.5
    duty_cycle: float = 0.5  # fraction of time spent computing while contributing
    device: str = "auto"
    schedule_enabled: bool = False
    schedule_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])  # Monday=0
    schedule_start_hour: int = 22
    schedule_end_hour: int = 7
    max_rounds_per_day: int = 10

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "ParticipationSettings":
        d = d or {}
        s = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        s.gpu_memory_fraction = min(max(float(s.gpu_memory_fraction), 0.05), 0.95)
        s.duty_cycle = min(max(float(s.duty_cycle), 0.05), 1.0)
        s.schedule_start_hour %= 24
        s.schedule_end_hour %= 24
        return s

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def in_schedule(s: ParticipationSettings, now: dt.datetime) -> bool:
    if not s.schedule_enabled:
        return True
    start, end, h = s.schedule_start_hour, s.schedule_end_hour, now.hour
    if start == end:
        within = True
    elif start < end:
        within = start <= h < end
    else:  # window wraps midnight, e.g. 22 → 7
        within = h >= start or h < end
    # For wrapped windows the early-morning hours belong to the previous day's schedule.
    day = (now - dt.timedelta(days=1)).weekday() if (start > end and h < end) else now.weekday()
    return within and day in s.schedule_days


def may_contribute(s: ParticipationSettings, now: dt.datetime, rounds_today: int) -> tuple[bool, str]:
    if not s.enabled:
        return False, "community training is off (opt-in)"
    if s.paused:
        return False, "paused by you"
    if not s.coordinator_url:
        return False, "no coordinator configured (no public MOTH coordinator is running yet)"
    if not in_schedule(s, now):
        return False, "outside your scheduled hours"
    if rounds_today >= s.max_rounds_per_day:
        return False, "daily contribution limit reached"
    return True, "ok"
