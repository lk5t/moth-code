"""0.7.1: the minimum monitored requests is 0 and zero user traffic never blocks a promotion."""
import json

from moth_server import serving
from moth_server.db import evolution_cycles, now
from moth_server.evolution import engine as EN, memory as MEM, settings as S
from moth_server.routes import evolution as RE
from test_serving_v053 import _two_releases


def test_default_threshold_is_zero(client):
    assert S.DEFAULTS['monitoring']['min_requests'] == 0
    assert S.get(client.app.state.ctx)['monitoring']['min_requests'] == 0


def test_stored_threshold_migrates_to_zero_once_and_owner_value_then_persists(client):
    ctx = client.app.state.ctx
    ctx.db.set_config(S.MIGRATION_V071, None)
    ctx.db.set_config(S.KEY, {'monitoring': {'min_requests': 5, 'minutes': 12.0}, 'max_experiments_per_cycle': 3})
    RE.setup(ctx)  # what every start (and every update, which restarts the server) runs
    s = S.get(ctx)
    assert s['monitoring']['min_requests'] == 0
    assert s['monitoring']['minutes'] == 12.0 and s['max_experiments_per_cycle'] == 3  # nothing else changed
    S.update(ctx, {'monitoring': {'min_requests': 4}})  # an Owner choice made after the migration
    RE.setup(ctx)
    RE.setup(ctx)
    assert S.get(ctx)['monitoring']['min_requests'] == 4


def _monitoring_cycle(ctx, stable, candidate):
    serving.start_canary(ctx, candidate, 100)
    with ctx.db.tx() as c:
        return c.execute(evolution_cycles.insert().values(status='monitoring', trigger='manual', base_version=stable,
            candidate_version=candidate, created_at=now(), updated_at=now(),
            result=json.dumps({'staged': True, 'canary_percent': 100, 'previous_version': stable,
                               'deployed_at': now() - 100}))).inserted_primary_key[0]


def test_zero_requests_with_cloud_answering_on_promotes_after_health_checks(client, owner, tmp_path, monkeypatch):
    from moth_server.routes import admin as A

    ctx, stable, candidate = _two_releases(client, owner, tmp_path)
    monkeypatch.setattr(A, 'flags', lambda c: {'cloud_inference_enabled': True})
    cid = _monitoring_cycle(ctx, stable, candidate)
    settings = S.get(ctx)
    settings['monitoring'].update(minutes=0)
    assert settings['monitoring']['min_requests'] == 0
    for _ in range(EN.HEALTH_CHECKS_WITHOUT_TRAFFIC - 1):
        EN._monitoring(ctx, MEM.cycle(ctx, cid), settings)
        cyc = MEM.cycle(ctx, cid)
        assert cyc['status'] == 'monitoring'
        assert cyc['result']['waiting_reason'] == 'running health checks on the new version'  # never "minimum requests"
    EN._monitoring(ctx, MEM.cycle(ctx, cid), settings)
    cyc = MEM.cycle(ctx, cid)
    assert cyc['status'] == 'completed' and ctx.extras['deployed_version'] == candidate
    assert cyc['result']['verified_by'] == 'health_checks'
    assert any('No user requests arrived' in e['message'] for e in MEM.events(ctx, 20) if e['kind'] == 'deploy.verified')


def test_zero_threshold_keeps_rolling_back_failed_health_checks(client, owner, tmp_path, monkeypatch):
    from moth_server.routes import admin as A

    ctx, stable, candidate = _two_releases(client, owner, tmp_path)
    monkeypatch.setattr(A, 'flags', lambda c: {'cloud_inference_enabled': True})
    cid = _monitoring_cycle(ctx, stable, candidate)
    settings = S.get(ctx)
    settings['monitoring'].update(minutes=0)
    monkeypatch.setattr(EN, '_probe', lambda c, v=None: 'the model produced no tokens')
    EN._monitoring(ctx, MEM.cycle(ctx, cid), settings)
    assert MEM.cycle(ctx, cid)['status'] == 'rolled_back' and ctx.extras['deployed_version'] == stable


def test_owner_minimum_above_zero_still_waits_for_traffic(client, owner, tmp_path, monkeypatch):
    from moth_server.routes import admin as A

    ctx, stable, candidate = _two_releases(client, owner, tmp_path)
    monkeypatch.setattr(A, 'flags', lambda c: {'cloud_inference_enabled': True})
    cid = _monitoring_cycle(ctx, stable, candidate)
    settings = S.get(ctx)
    settings['monitoring'].update(minutes=0, min_requests=2)
    EN._monitoring(ctx, MEM.cycle(ctx, cid), settings)
    cyc = MEM.cycle(ctx, cid)
    assert cyc['status'] == 'monitoring' and 'minimum monitored requests' in cyc['result']['waiting_reason']
