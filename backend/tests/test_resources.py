from pathlib import Path

from moth.training.resources import cpu_count, memory_budget


def test_container_limits_bound_reported_training_capacity(monkeypatch):
    import os
    monkeypatch.setattr(os, 'cpu_count', lambda: 64)
    monkeypatch.setattr(os, 'sched_getaffinity', lambda _: set(range(16)))
    values = {'cpu.max': '400000 100000', 'memory.max': '1000', 'memory.current': '750'}
    monkeypatch.setattr(Path, 'read_text', lambda p, **kwargs: values[p.name])
    assert cpu_count() == 4
    assert memory_budget(8000, 6000) == (1000, 250)
