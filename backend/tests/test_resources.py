from pathlib import Path

from moth.training.resources import cpu_count, memory_budget


def test_container_limits_bound_reported_training_capacity(monkeypatch):
    import os
    monkeypatch.setattr(os, 'cpu_count', lambda: 64)
    monkeypatch.setattr(os, 'sched_getaffinity', lambda _: set(range(16)), raising=False)
    values = {'cpu.max': '400000 100000', 'memory.max': '1000', 'memory.current': '750'}
    monkeypatch.setattr(Path, 'read_text', lambda p, **kwargs: values[p.name])
    assert cpu_count() == 4
    assert memory_budget(8000, 6000) == (1000, 250)


def test_native_host_without_linux_resource_interfaces(monkeypatch):
    import os

    monkeypatch.setattr(os, 'cpu_count', lambda: 8)
    monkeypatch.delattr(os, 'sched_getaffinity', raising=False)

    def absent_cgroup(*args, **kwargs):
        raise FileNotFoundError('no Linux cgroups on this host')

    monkeypatch.setattr(Path, 'read_text', absent_cgroup)
    assert cpu_count() == 8
    assert memory_budget(8000, 6000) == (8000, 6000)
