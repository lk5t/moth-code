import json
import os
from pathlib import Path

import torch
from sqlalchemy import select

from conftest import H
from moth_server import models as M, serving
from moth_server.db import evolution_cycles, library_builds, now
from moth_server.evolution import engine as EN, memory as MEM, settings as S
from moth_server.intelligence import discovery, library
from test_evolution import FAST, drive
from test_serving_v053 import _served_version, _two_releases


def test_empty_install_to_two_real_cpu_upgrades_and_rollback(client, owner):
    """Real PSF corpus, real training/evaluation/traffic/signatures; no trained quality claim."""
    ctx = client.app.state.ctx
    headers = H(owner['token'])
    torch.manual_seed(0)
    S.update(ctx, {**FAST, 'paused': True, 'training': {**FAST['training'], 'steps': 20}, 'growth': {'enabled': False},
                   'rollout': {'canary_percent': 100}, 'monitoring': {'minutes': 0.0, 'min_requests': 1}})
    discovery.update(ctx, {'max_source_chars': 100000})
    initialized = client.post('/v1/admin/evolution/initialize', headers=headers).json()['model']
    seed_bytes = Path(initialized['path'], 'model.pt').read_bytes()
    activated = client.post('/v1/admin/evolution/initialize/activate', headers=headers)
    assert activated.status_code == 200, activated.text
    assert activated.json()['evaluation']['passed']
    assert client.put('/v1/admin/config/flags', headers=headers,
                      json={'cloud_inference_enabled': True}).status_code == 200
    # Start finds no approved data and requests real automatic PSF preparation.
    start = client.post('/v1/admin/evolution/training/start', headers=headers, json={'server_cpu': True})
    assert start.status_code == 200, start.text
    versions = []
    for expected in ('0.02', '0.03'):
        cyc = drive(ctx, lambda c: c['status'] in ('monitoring', *MEM.TERMINAL_CYCLE), timeout=240)
        assert cyc['status'] == 'monitoring', [(e['status'], e.get('error'), e.get('metrics')) for e in MEM.experiments(ctx, cyc['id'])]
        candidate = cyc['candidate_version']
        # A health probe alone must not count as monitored user traffic.
        assert M.deployed(ctx)['version'] != candidate
        assert _served_version(client, owner['token']) == candidate
        cyc = drive(ctx, lambda c: c['status'] in MEM.TERMINAL_CYCLE)
        assert cyc['status'] == 'completed', cyc
        rel = M.deployed(ctx)
        assert rel['info']['model_version'] == expected
        assert rel['info']['params'] == 99648  # versions do not imply a size milestone
        assert MEM.ancestors(ctx, rel['version'])[1]['version'] == (versions[-1]['release'] if versions else initialized['version'])
        exp = next(e for e in MEM.experiments(ctx, cyc['id']) if e['candidate_version'] == candidate)
        assert all(g['passed'] for g in exp['metrics']['gates'])
        assert any(g.get('detail', '').startswith('retention:') and g.get('candidate') is not None
                   and g.get('baseline') is not None for g in exp['metrics']['gates'])
        assert rel['info']['dev_checkpoint']['sha256'] and rel['info']['training']['train_loss'] > 0
        assert Path(rel['path'], 'model-manifest.json.sig').exists()
        versions.append({'release': rel['version'], 'model_version': expected, 'params': rel['info']['params'],
                         'totals': rel['info']['lineage_totals'], 'gates': exp['metrics']['gates']})
        if expected == '0.02':
            S.update(ctx, {'training': {'steps': 12}})
            EN.wake(ctx)
    assert versions[-1]['totals']['steps'] == 32
    assert versions[-1]['totals']['tokens'] == 32 * 8 * 64
    b = library.latest_ready(ctx)
    assert b and 'PSF-2.0' in b['manifest']
    overview = client.get('/v1/admin/model-overview', headers=headers).json()
    assert [r['model_version'] for r in overview['accepted_versions']] == ['0.01', '0.02', '0.03']
    assert overview['checkpoint']['valid']
    assert EN.rollback_to(ctx, initialized['version'], owner['user']['id'])['version'] == initialized['version']
    assert Path(initialized['path'], 'model.pt').read_bytes() == seed_bytes
    after_rollback = client.get('/v1/admin/model-overview', headers=headers).json()
    assert len(after_rollback['accepted_versions']) == 3  # rollback does not erase accepted descendants
    target = os.environ.get('MOTH_LIFECYCLE_EVIDENCE')
    if target:
        Path(target).write_text(json.dumps({'trained_foundation': False, 'test_data_dir': str(ctx.settings.data_dir), 'corpus': 'PSF-2.0 Python standard library',
                                          'versions': versions, 'rollback': 'verified original seed bytes'}, indent=2))


def test_stable_parent_change_blocks_automatic_promotion(client, owner, tmp_path):
    ctx, base, candidate = _two_releases(client, owner, tmp_path)
    with ctx.db.tx() as c:
        cid = c.execute(evolution_cycles.insert().values(status='deploying', trigger='manual', base_version=base,
            base_sha256=M.release(ctx, base)['sha256'], candidate_version=candidate, created_at=now(), updated_at=now())).inserted_primary_key[0]
    M.deploy(ctx, candidate)  # an explicit owner selection while this cycle was in progress
    import pytest
    with pytest.raises(M.ReleaseError, match='stable parent changed'):
        M.deploy(ctx, base, engine=ctx.extras['inference_engine'], expected_parent=base)
    with pytest.raises(M.ReleaseError, match='stable parent changed'):
        M.deploy(ctx, base, expected_parent=base)
    EN._deploying(ctx, MEM.cycle(ctx, cid), S.get(ctx))
    assert MEM.cycle(ctx, cid)['status'] == 'cancelled'
    assert M.deployed(ctx)['version'] == candidate


def test_interrupted_preparation_keeps_verified_downloads(client):
    ctx = client.app.state.ctx
    cached = library.root(ctx) / 'cache' / 'verified-test-file'
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b'keep downloaded progress')
    with ctx.db.tx() as c:
        bid = c.execute(library_builds.insert().values(status='running', created_at=now())).inserted_primary_key[0]
    library.recover(ctx)
    b = ctx.db.one(select(library_builds).where(library_builds.c.id == bid))
    assert b['status'] == 'failed' and 'restart' in b['error']
    assert cached.read_bytes() == b'keep downloaded progress'
