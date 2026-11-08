"""GENESIS reset with real weights, optimizer state, verified archive, activation and restoration.

All models/data here are isolated fixtures, never the deployed production installation.
"""
import json
from pathlib import Path

import pytest
import torch
from sqlalchemy import select

from conftest import H, register_verified
from moth_server import models as M, db as DB, training
from moth_server.evolution import genesis as G, settings as S, v2
from moth.model.config import MothConfig
from moth.model.transformer import MothModel
from moth.training.checkpoint import atomic_torch_save, file_sha256
from test_serving_v053 import _two_releases


@pytest.fixture
def legacy(client, owner, tmp_path):
    ctx, version, candidate = _two_releases(client, owner, tmp_path)
    old = M.release(ctx, version)
    model = MothModel(MothConfig.from_dict(json.loads(Path(old['path'], 'config.json').read_text())))
    model.load_state_dict(torch.load(Path(old['path']) / 'model.pt', weights_only=True))
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    x = torch.arange(32).view(1, -1) % model.cfg.vocab_size
    _, loss = model(x, x.roll(-1, 1))
    loss.backward()
    optimizer.step()
    checkpoint = ctx.settings.data_dir / 'lineage' / 'dev' / f'v{version:05d}.pt'
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    atomic_torch_save({'model': model.state_dict(), 'optimizer': optimizer.state_dict(),
                      'model_config': model.cfg.to_dict(), 'step': 1, 'tokens_seen': 32}, checkpoint)
    M._set(ctx, version, name='moth-200k-v0.1-step500', info=json.dumps({**old['info'],
        'model_version': '0.25', 'dev_checkpoint': {'path': str(checkpoint), 'sha256': file_sha256(checkpoint)}}))
    return ctx, version, candidate, checkpoint


def test_verified_fresh_reset_requires_approval_and_restores_legacy(client, settings, owner, legacy):
    ctx, old, candidate, checkpoint = legacy
    before = checkpoint.read_bytes()
    before_package = Path(M.release(ctx, old)['path'], 'model.pt').read_bytes()
    token = register_verified(client, settings, 'not-reset-owner')['token']
    assert client.post('/v1/admin/evolution/genesis/prepare', headers=H(token)).status_code == 403
    prepared = client.post('/v1/admin/evolution/genesis/prepare', headers=H(owner['token']))
    assert prepared.status_code == 200, prepared.text
    plan = prepared.json()
    assert plan['status'] == 'prepared' and plan['restore_verified'] and plan['archive_files'] > 1
    assert plan['parameters'] == 99648 and plan['previous_name'] == 'moth-200k-v0.1-step500'
    assert M.deployed(ctx)['version'] == old
    assert S.get(ctx)['paused'] is True
    root = ctx.settings.data_dir / 'genesis' / plan['id']
    archived = root / 'archive' / checkpoint.relative_to(ctx.settings.data_dir)
    assert archived.read_bytes() == before
    assert torch.load(archived, weights_only=True)['optimizer']['state']
    fresh = torch.load(root / 'fresh/seed.pt', weights_only=True)
    assert fresh['step'] == fresh['tokens_seen'] == 0 and not fresh.get('optimizer')
    assert client.post('/v1/admin/evolution/genesis/activate', headers=H(owner['token']), json={
        'reset_id': plan['id'], 'confirmation': 'not approved'}).status_code == 409
    assert M.deployed(ctx)['version'] == old
    activated = client.post('/v1/admin/evolution/genesis/activate', headers=H(owner['token']), json={
        'reset_id': plan['id'], 'confirmation': G.CONFIRMATION, 'start_training': False})
    assert activated.status_code == 200, activated.text
    new = M.deployed(ctx)
    assert new['info']['model_version'] == '0.01'
    assert new['info']['lineage_id'] == plan['lineage_id']
    assert new['info']['lineage_totals'] == {'steps': 0, 'tokens': 0, 'cycles': 0}
    assert Path(new['path'], 'model.pt').read_bytes() != before_package
    assert checkpoint.read_bytes() == before
    # An accepted version in the old lineage must not make GENESIS skip to 0.26.
    cand = M.release(ctx, candidate)
    M._set(ctx, candidate, info=json.dumps({**cand['info'], 'lineage_id': plan['lineage_id']}))
    assert v2.assign_model_version(ctx, candidate) == '0.02'
    assert training.coordinator(ctx) is None  # retired rounds cannot auto-restart
    checkpoint.unlink()  # exercise restoration from the verified archive, not only a pointer switch
    restored = client.post(f"/v1/admin/evolution/genesis/{plan['id']}/restore", headers=H(owner['token']))
    assert restored.status_code == 200, restored.text
    assert M.deployed(ctx)['version'] == old and S.get(ctx)['paused']
    assert checkpoint.read_bytes() == before
    assert ctx.db.one(select(DB.users).where(DB.users.c.username == 'not-reset-owner'))


def test_tampered_backup_blocks_activation_without_touching_active_model(client, owner, legacy):
    ctx, old, _, _ = legacy
    plan = G.prepare(ctx, owner['user']['id'])
    root = ctx.settings.data_dir / 'genesis' / plan['id']
    index = json.loads((root / 'archive-index.json').read_text())
    entry = next(name for name in index if name.endswith('model.pt'))
    (root / 'archive' / entry).write_bytes(b'corrupt backup')
    with pytest.raises(ValueError, match='Archive integrity'):
        G.activate(ctx, plan['id'], G.CONFIRMATION, owner['user']['id'])
    assert M.deployed(ctx)['version'] == old


def test_existing_worker_jobs_must_quiesce_before_backup(client, owner, legacy):
    ctx, old, _, _ = legacy
    with ctx.db.tx() as c:
        jid = c.execute(DB.training_jobs.insert().values(kind='train_round', status='leased', spec='{}',
            attempts=1, max_attempts=3, created_at=DB.now(), updated_at=DB.now())).inserted_primary_key[0]
    with pytest.raises(ValueError, match='Existing worker jobs'):
        G.prepare(ctx, owner['user']['id'])
    assert G.status(ctx)['status'] == 'preparing' and M.deployed(ctx)['version'] == old
    assert training.claim_job(ctx, {'paused': False}, True) is None
    with ctx.db.tx() as c:
        c.execute(DB.training_jobs.update().where(DB.training_jobs.c.id == jid).values(status='completed'))
    assert G.prepare(ctx, owner['user']['id'])['restore_verified']
