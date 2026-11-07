import json
from pathlib import Path

import torch

from conftest import H
from moth.model.registry import load_model, sha256_file
from moth_server import models as M
from moth_server.evolution import memory as MEM
from moth_server.evolution import v2
from moth_server.evolution.bootstrap import initialize


def test_initialization_is_real_near_100k_and_idempotent(client, owner):
    response = client.post('/v1/admin/evolution/initialize', headers=H(owner['token']))
    assert response.status_code == 200, response.text
    rel = response.json()['model']
    model, tok, manifest = load_model(rel['path'])
    assert sum(p.numel() for p in model.parameters()) == rel['info']['params'] == 99648
    assert manifest['model_version'] == '0.01' and tok.vocab_size == 272
    assert MEM.ancestors(client.app.state.ctx, rel['version'])[0]['method'] == 'initialization'
    assert rel['status'] == 'uploaded' and not M.deployed(client.app.state.ctx)
    digest = sha256_file(Path(rel['path']) / 'model.pt')
    again = initialize(client.app.state.ctx)
    assert not again['created'] and again['model']['version'] == rel['version']
    assert sha256_file(Path(rel['path']) / 'model.pt') == digest


def test_existing_larger_checkpoint_preserved_and_version_migrates(client, tiny_model_dir):
    ctx = client.app.state.ctx
    rel = M._register(ctx, tiny_model_dir, 'Existing trained lineage', {'type': 'upload'}, None)
    before = sha256_file(Path(rel['path']) / 'model.pt')
    assert not initialize(ctx)['created']
    assert v2.assign_model_version(ctx, rel['version']) == '0.01'
    assert rel['info']['params'] > 100000
    assert sha256_file(Path(rel['path']) / 'model.pt') == before
    # A historical label is retained; new accepted descendants use padded increments.
    M._set(ctx, rel['version'], info=json.dumps({**M.release(ctx, rel['version'])['info'], 'model_version': '0.1'}))
    next_v = M.reserve(ctx, 'candidate', {'type': 'evolution'}, None)
    MEM.record_lineage(ctx, next_v, rel['version'], 'continue')
    assert v2.assign_model_version(ctx, next_v) == '0.02'
    assert M.release(ctx, rel['version'])['info']['model_version'] == '0.1'


def test_unregistered_weights_prevent_random_reset(client, tmp_path):
    ctx = client.app.state.ctx
    existing = Path(ctx.settings.data_dir) / 'unfinished.pt'
    torch.save({'progress': 'preserve'}, existing)
    import pytest

    with pytest.raises(ValueError, match='unregistered'):
        initialize(ctx)
    assert torch.load(existing, weights_only=True)['progress'] == 'preserve'


def test_initialization_recovers_interrupted_registration_without_new_weights(client, monkeypatch):
    import pytest
    from moth.training.checkpoint import file_sha256
    ctx = client.app.state.ctx
    with monkeypatch.context() as patch:
        def interrupted(*args, **kwargs):
            raise RuntimeError('interrupted registration')
        patch.setattr(M, 'finalize', interrupted)
        with pytest.raises(RuntimeError, match='interrupted'):
            initialize(ctx)
    version = M.list_releases(ctx)[0]['version']
    seed = Path(ctx.settings.data_dir) / 'lineage' / 'initial' / 'seed.pt'
    digest = file_sha256(seed)
    recovered = initialize(ctx)
    assert recovered['recovered'] and recovered['model']['version'] == version
    assert file_sha256(seed) == digest and len(M.list_releases(ctx)) == 1
