from pathlib import Path


def test_windows_worker_reports_available_ram_not_total(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'worker'))
    from moth_worker import hardware as H
    monkeypatch.setattr(H, '_nvidia_smi', lambda: ([], None))
    monkeypatch.setattr(H, '_windows_memory', lambda: (16 * 2**30, 2 * 2**30))
    def unsupported(*args):
        raise AttributeError('Windows has no sysconf')
    monkeypatch.setattr(H.os, 'sysconf', unsupported)
    import moth.training.resources as R
    monkeypatch.setattr(R, 'memory_budget', lambda total, available: (total, available))
    measured = H.detect()
    assert measured['ram_gb'] == 16
    assert measured['ram_available_gb'] == 2
    from moth_server.training import capacity_bytes
    assert capacity_bytes(measured) <= 2 * 2**30
