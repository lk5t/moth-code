from pathlib import Path


def test_profile_uses_measurements_and_caches_stable_hardware(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'worker'))
    from moth_worker import hardware as H
    import torch
    before = torch.get_num_threads()
    calls = []
    def bench(device, seconds):
        calls.append(device)
        return {'device': device, 'gflops': 200 if device == 'cuda' else 100,
                'threads': torch.get_num_threads(), 'measured_at': 1}
    monkeypatch.setattr(H, 'benchmark', bench)
    hw = {'cpu_count': 2, 'torch_cuda': True, 'gpus': [{'memory_gb': 12, 'name': 'simulated GPU', 'utilization': 0}]}
    assert H.measured_device(tmp_path, hw)[0] == 'cuda'
    assert torch.get_num_threads() == before
    count = len(calls)
    hw['gpus'][0]['utilization'] = 80
    assert H.measured_device(tmp_path, hw)[0] == 'cuda'
    assert len(calls) == count


def test_failed_gpu_measurement_falls_back_to_measured_cpu(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'worker'))
    from moth_worker import hardware as H
    def bench(device, seconds):
        if device == 'cuda':
            raise RuntimeError('CUDA unavailable')
        return {'device': 'cpu', 'gflops': 20, 'threads': 1}
    monkeypatch.setattr(H, 'benchmark', bench)
    assert H.measured_device(tmp_path, {'torch_cuda': True, 'gpus': [{'memory_gb': 16}]})[0] == 'cpu'
