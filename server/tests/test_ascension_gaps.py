"""Focused integration coverage for growth, replay and promotion gaps."""
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import torch

from conftest import H
from moth_server import models as M, serving
from moth_server.db import library_builds, model_lineage, evolution_cycles, now
from moth_server.evolution import backends as B, engine as EN, memory as MEM, settings as S, v2
from test_evolution_v053 import _world
from test_serving_v053 import _two_releases, _served_version


def test_real_worker_expands_then_trains_without_touching_base(client, owner, tmp_path, monkeypatch):
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner
    from moth.model.registry import load_model

    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    cyc = EN.start_cycle(ctx)
    EN._planning(ctx, cyc, S.get(ctx))
    exp = MEM.experiments(ctx, cyc['id'])[0]
    base = M.release(ctx, base_v)
    before = Path(base['path'], 'model.pt').read_bytes()
    cfg = {**exp['config'], 'steps': 3, 'method': 'expansion',
           'grow': {'add_layers': 1, 'ffn_hidden': 256}}
    MEM.update_experiment(ctx, exp['id'], config=cfg, status='running', backend='worker')
    exp = MEM.experiment(ctx, exp['id'])
    jid = B.create_worker_job(ctx, exp)
    enrollment = client.post('/v1/training/enrollments', json={'name': 'growth-cpu'}, headers=H(owner['token'])).json()
    worker = client.post('/v1/worker/enroll', json={'token': enrollment['token'], 'version': '0.5.4',
        'hardware': {'compute': 'cpu', 'gpus': [], 'ram_gb': 16, 'cpu_count': 2}}).json()
    job = client.post('/v1/worker/jobs/claim', headers=H(worker['worker_token'])).json()
    assert job['id'] == jid and job['spec']['expanded']
    original = torch.load(B.job_files(ctx, job['spec'])[0], weights_only=True)
    from moth.community.validation import serialize_state, tensor_bytes_sha256

    bad = {k: torch.zeros_like(v) for k, v in original.items()}
    bad['layers.2.attn.wo.weight'].fill_(100)
    payload = serialize_state(bad)
    rejected = B.accept_worker_result(ctx, {'spec': json.dumps(job['spec'])},
        {'base_sha256': job['spec']['base_sha256'], 'delta_sha256': tensor_bytes_sha256(payload)}, payload)
    assert not rejected['accepted']
    runner = WorkerRunner(WorkerClient('http://testserver', worker['worker_token'], http=client), tmp_path/'worker',
                          heartbeat_seconds=3600, update_check_seconds=None, log=lambda _: None)
    outcome = runner.run_job(job)
    assert outcome['accepted'], outcome
    result = json.loads((B.run_dir(ctx, exp)/'result.json').read_text())
    model, _, manifest = load_model(result['package'], verify=True)
    assert model.cfg.n_layers == 3 and model.cfg.ffn_hidden == 256
    assert model.num_params() > base['info']['params']
    assert manifest['lineage']['method'] == 'expansion'
    assert any(not torch.equal(original[k], v.float()) for k,v in model.state_dict().items())
    assert Path(base['path'], 'model.pt').read_bytes() == before


def test_promotion_waits_for_traffic_and_successful_signature(client, owner, tmp_path, monkeypatch):
    ctx, stable, candidate = _two_releases(client, owner, tmp_path)
    serving.start_canary(ctx, candidate, 100)
    with ctx.db.tx() as c:
        cid = c.execute(evolution_cycles.insert().values(status='monitoring', trigger='manual', base_version=stable,
            candidate_version=candidate, created_at=now(), updated_at=now(),
            result=json.dumps({'staged': True, 'canary_percent': 100, 'previous_version': stable,
                               'deployed_at': now()-100}))).inserted_primary_key[0]
    settings = S.get(ctx)
    settings['monitoring'].update(minutes=0, min_requests=2)
    EN._monitoring(ctx, MEM.cycle(ctx,cid), settings)
    assert MEM.cycle(ctx,cid)['status'] == 'monitoring' and ctx.extras['deployed_version'] == stable
    for _ in range(2):
        assert _served_version(client, owner['token']) == candidate
    with monkeypatch.context() as m:
        def fail(*args):
            raise OSError('test signing failure')
        m.setattr(serving, 'sign_release', fail)
        EN._monitoring(ctx, MEM.cycle(ctx,cid), settings)
    assert ctx.extras['deployed_version'] == stable and MEM.cycle(ctx,cid)['status'] == 'monitoring'
    EN._monitoring(ctx, MEM.cycle(ctx,cid), settings)
    assert ctx.extras['deployed_version'] == candidate and MEM.cycle(ctx,cid)['status'] == 'completed'


def test_replay_retains_previous_build_and_masks_are_not_dropped(client, owner, tmp_path, monkeypatch):
    from moth_server.intelligence import library
    from moth_server.evolution import datasets as DS

    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    old = library.latest_ready(ctx)
    old_root = Path(old['path'])
    original = (old_root/'tokens/language/train.bin').read_bytes()
    with ctx.db.tx() as c:
        c.execute(model_lineage.update().where(model_lineage.c.version==base_v).values(datasets=json.dumps([old['content_sha256']])))
    new_root = tmp_path/'next-build'
    shutil.copytree(old_root,new_root)
    data = np.fromfile(new_root/'tokens/language/train.bin',dtype=np.uint16)
    data[0] = (int(data[0])+1) % 256
    data.tofile(new_root/'tokens/language/train.bin')
    sha = hashlib.sha256(data.tobytes()).hexdigest()
    mixture = json.loads((new_root/'tokens/mixture.json').read_text())
    mixture['build_sha256']=sha
    (new_root/'tokens/mixture.json').write_text(json.dumps(mixture))
    values={k:v for k,v in old.items() if k!='id'}
    values.update(path=str(new_root),content_sha256=sha)
    with ctx.db.tx() as c:
        bid=c.execute(library_builds.insert().values(**values)).inserted_primary_key[0]
    ds=DS.register_prepared(ctx,new_root/'tokens/language',f'Library: language (build {bid})',['language'],False,None)
    DS.approve(ctx,ds['id'],None)
    src=v2.mixture_source(ctx,M.release(ctx,base_v))
    assert set(src['build_shas'])=={old['content_sha256'],sha}
    combined=np.fromfile(Path(src['path'])/'language/train.bin',dtype=np.uint16)
    replay=np.frombuffer(original,dtype=np.uint16)[:65536]
    assert np.array_equal(combined[len(data):],replay)
    assert (old_root/'tokens/language/train.bin').read_bytes()==original
    mask=np.memmap(Path(src['path'])/'language/train.mask',dtype=np.uint8,mode='r+')
    mask[0]=0
    mask.flush()
    exp={'id':100,'dataset_id':ds['id'],'config':{'mixture':{'path':src['path'],'weights':{'language':1.0}}}}
    assert not B.worker_training_supported(ctx,exp)
    with pytest.raises(ValueError,match='assistant-masked'):
        B.create_worker_job(ctx,exp)
    cycle = EN.start_cycle(ctx)
    EN._planning(ctx, cycle, S.get(ctx))
    planned = MEM.experiments(ctx, cycle['id'])[0]
    old_id = next(i for i in src['dataset_ids'] if i != ds['id'])
    assert client.post(f'/v1/admin/evolution/datasets/{old_id}/revoke', headers=H(owner['token'])).status_code == 200
    assert MEM.experiment(ctx, planned['id'])['status'] == 'cancelled'
    remaining = v2.mixture_source(ctx, M.release(ctx,base_v))
    assert remaining['path'] == str(new_root/'tokens')
