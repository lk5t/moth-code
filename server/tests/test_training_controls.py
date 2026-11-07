import json

import pytest
from sqlalchemy import select

from conftest import H
from moth_server.db import workers, training_jobs
from moth_server.evolution import engine as EN, memory as MEM, settings as S
from test_evolution import drive
from test_evolution_v053 import _world
from test_training_network import enroll, runner


def test_worker_admission_respects_free_memory_and_owner_gpu_fraction():
    from moth_server.training import fits
    gpu = {'compute': 'gpu', 'gpus': [{'memory_gb': 12, 'memory_used_gb': 1}]}
    spec = {'requirements': {'memory_bytes': 2 * 1024**3}}
    assert fits(gpu, spec)
    assert not fits(gpu, spec, {'gpu_memory_fraction': .1})
    assert not fits({'compute': 'gpu', 'gpus': [{'memory_gb': 12, 'memory_used_gb': 11}]}, spec)
    assert not fits({'compute': 'cpu', 'ram_gb': 8, 'ram_available_gb': 1}, spec)


def test_quarantined_worker_progress_is_never_silently_reset(client, owner, training_world, tmp_path):
    _, w = enroll(client, owner['token'])
    job = client.post('/v1/worker/jobs/claim', headers=H(w['worker_token'])).json()
    r = runner(client, w['worker_token'], tmp_path, 'quarantined')
    corrupt = r.state_dir / 'jobs' / f"{job['id']}.pt.corrupt"
    corrupt.write_bytes(b'preserve quarantined progress')
    result = r.run_job(job)
    assert not result['accepted'] and 'refusing to reset' in result['error']
    assert corrupt.read_bytes() == b'preserve quarantined progress'
    assert not corrupt.with_suffix('').exists()


def test_selected_worker_start_pause_stop_and_recover_real_training(client, owner, tmp_path, monkeypatch):
    from moth_worker import runner as runner_module
    from moth_worker.runner import Stop
    ctx, _ = _world(client, owner, tmp_path, monkeypatch)
    S.update(ctx, {'training': {'steps': 4}, 'growth': {'enabled': False}})
    _, a = enroll(client, owner['token'])
    _, b = enroll(client, owner['token'])
    start = client.post('/v1/admin/evolution/training/start', headers=H(owner['token']), json={'worker_id': a['worker_id']})
    assert start.status_code == 200, start.text
    assert client.post('/v1/worker/jobs/claim', headers=H(b['worker_token'])).status_code == 204
    job = client.post('/v1/worker/jobs/claim', headers=H(a['worker_token'])).json()
    assert job['spec']['worker_ids'] == [a['worker_id']]
    assert client.post(f"/v1/training/workers/{a['worker_id']}/pause", headers=H(owner['token'])).status_code == 200
    beat = client.post('/v1/worker/heartbeat', headers=H(a['worker_token']), json={'job_id': job['id'], 'progress': .1})
    assert beat.json()['paused'] and not beat.json()['job_cancelled']
    assert ctx.db.one(select(training_jobs).where(training_jobs.c.id == job['id']))['status'] == 'leased'
    client.post(f"/v1/training/workers/{a['worker_id']}/resume", headers=H(owner['token']))
    r = runner(client, a['worker_token'], tmp_path, 'controls')
    r.hardware = lambda: {'compute': 'cpu', 'cpu_count': 2, 'ram_gb': 8, 'gpus': []}
    monkeypatch.setattr(runner_module, 'CHECKPOINT_EVERY', 1)
    progress = r.client.progress

    def stop_after_step(jid, fraction):
        progress(jid, fraction)
        r.beat()  # records measured loss, steps, tokens and checkpoint step
        metrics = client.get('/v1/admin/jobs', headers=H(owner['token'])).json()[0]['metrics']['progress']
        assert metrics['step'] == 1 and metrics['tokens'] > 0 and metrics['train_loss'] > 0
        client.post(f"/v1/training/workers/{a['worker_id']}/stop", headers=H(owner['token']))
        r.beat()

    r.client.progress = stop_after_step
    with pytest.raises(Stop):
        r.run_job(job)
    w = ctx.db.one(select(workers).where(workers.c.id == a['worker_id']))
    assert w['paused'] and not w['revoked_at']
    client.post(f"/v1/training/workers/{a['worker_id']}/resume", headers=H(owner['token']))
    again = client.post('/v1/worker/jobs/claim', headers=H(a['worker_token'])).json()
    assert again['id'] == job['id']
    r2 = runner(client, a['worker_token'], tmp_path, 'controls')
    assert r2.run_job(again)['accepted']
    done = ctx.db.one(select(training_jobs).where(training_jobs.c.id == job['id']))
    assert json.loads(done['result'])['training']['steps'] == 4
    assert json.loads(done['result'])['training']['train_loss'] > 0


def test_start_all_and_cpu_server_commands_use_existing_engine(client, owner, tmp_path, monkeypatch):
    ctx, _ = _world(client, owner, tmp_path, monkeypatch)
    _, a = enroll(client, owner['token'])
    _, b = enroll(client, owner['token'])
    headers = H(owner['token'])
    r = client.post('/v1/admin/evolution/training/start', headers=headers, json={})
    assert r.status_code == 200 and set(r.json()['worker_ids']) == {a['worker_id'], b['worker_id']}
    assert MEM.experiments(ctx, MEM.active_cycle(ctx)['id'])[0]['backend'] == 'distributed'
    EN.cancel_cycle(ctx)
    S.update(ctx, {'training': {'steps': 3}, 'growth': {'enabled': False}})
    r = client.post('/v1/admin/evolution/training/start', headers=headers, json={'server_cpu': True})
    assert r.status_code == 200, r.text
    cyc = drive(ctx, lambda c: c['status'] in MEM.TERMINAL_CYCLE)
    exp = MEM.experiments(ctx, cyc['id'])[0]
    assert exp['backend'] == 'local' and exp['status'] in ('passed', 'rejected')
    assert exp['metrics']['training']['step'] == 3
