"""GENESIS compute defaults respect Owner intent and real scheduling constraints."""
import copy
import json
import time

from moth.training.resources import cpu_count
from moth_server.evolution import settings as S, compute as C, distributed as D


def test_cpu_is_automatic_only_without_an_explicit_owner_disable(client):
    ctx = client.app.state.ctx
    assert S.get(ctx)['backends']['local_cpu'] is True
    assert 1 <= S.get(ctx)['limits']['cpu_threads'] <= cpu_count()
    S.update(ctx, {'backends': {'local_cpu': False}, 'paused': True})
    S.update(ctx, {'training': {'steps': 5}})
    assert S.get(ctx)['backends']['local_cpu'] is False
    assert S.get(ctx)['paused'] is True


def test_gpu_priority_and_cpu_fallback(client, monkeypatch):
    ctx = client.app.state.ctx
    settings = copy.deepcopy(S.get(ctx))
    hw = {'gpus': [{'memory_free': 8 * C.GB}], 'memory': {'available': 8 * C.GB}}
    cap = {'usable_gpu': 1, 'usable': 1, 'total': 1, 'online': 1}
    monkeypatch.setattr(C, 'local', lambda ctx: hw)
    monkeypatch.setattr(C, 'worker_capacity', lambda *a: cap)
    assert C.choose_backend(ctx, settings, C.GB)[0]['device'] == 'cuda'
    hw['gpus'] = []
    assert C.choose_backend(ctx, settings, C.GB)[0]['backend'] == 'worker'
    cap['usable_gpu'] = cap['usable'] = 0
    assert C.choose_backend(ctx, settings, C.GB)[0]['device'] == 'cpu'
    settings['backends']['local_cpu'] = False
    assert C.choose_backend(ctx, settings, C.GB)[0] is None


def test_stale_workers_are_not_available_compute(client, monkeypatch):
    ctx = client.app.state.ctx
    rows = [{'id': 1, 'status': 'online', 'paused': False, 'last_heartbeat_at': time.time() - 600,
             'hardware': json.dumps({'compute': 'gpu', 'gpus': [{'memory_total': 8 * C.GB}]}), 'limits': '{}'}]
    monkeypatch.setattr(ctx.db, 'all', lambda query: rows)
    cap = C.worker_capacity(ctx, C.GB)
    assert cap['online'] == cap['usable'] == cap['usable_gpu'] == 0
    assert not D.participants(ctx, C.GB)


def test_selects_the_gpu_that_actually_fits(client, monkeypatch):
    ctx = client.app.state.ctx
    settings = copy.deepcopy(S.get(ctx))
    monkeypatch.setattr(C, 'local', lambda ctx: {'gpus': [{'memory_free': 0.1 * C.GB}, {'memory_free': 8 * C.GB}]})
    assert C.choose_backend(ctx, settings, C.GB)[0]['device'] == 'cuda:1'
