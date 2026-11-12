"""Focused scheduler and read-only growth diagnostics regressions."""
from conftest import H
from moth_server.evolution import engine as EN, settings as S, memory as MEM


def test_manual_schedule_never_creates_an_automatic_cycle(client,owner,monkeypatch):
    ctx=client.app.state.ctx
    response=client.put('/v1/admin/evolution/settings',headers=H(owner['token']),json={'changes':{'automatic':False}})
    assert response.status_code==200
    def unexpected(*args,**kwargs):raise AssertionError('Manual idle must not plan data or create a cycle')
    monkeypatch.setattr(EN,'start_cycle',unexpected)
    assert EN._maybe_start(ctx,S.get(ctx),woken=True)['state']=='manual'
    assert not MEM.cycles(ctx)
    assert client.put('/v1/admin/evolution/settings',headers=H(owner['token']),json={'changes':{'automatic':'false'}}).status_code==422


def test_growth_diagnostics_is_owner_only_and_never_initializes(client,owner):
    ctx=client.app.state.ctx
    assert client.get('/v1/admin/evolution/growth-diagnostics').status_code==401
    response=client.get('/v1/admin/evolution/growth-diagnostics',headers=H(owner['token']))
    assert response.status_code==200 and response.json()['decision'] is None
    assert 'No deployed' in response.json()['blockers'][0]
    assert not MEM.cycles(ctx)


def test_growth_diagnostics_reads_real_registered_architecture(client,owner,tmp_path):
    from test_serving_v053 import _two_releases
    from moth.model.config import MothConfig
    from moth_server import models as M
    import json
    from pathlib import Path
    ctx,version,_=_two_releases(client,owner,tmp_path)
    before=list(Path(ctx.settings.data_dir).rglob('*'))
    release=M.release(ctx,version);config=MothConfig.from_dict(json.loads((Path(release['path'])/'config.json').read_text()))
    response=client.get('/v1/admin/evolution/growth-diagnostics',headers=H(owner['token']))
    assert response.status_code==200,response.text
    report=response.json();assert report['architecture_params']==config.num_params()==release['info']['params']
    assert report['decision']['grow'] is False and report['decision']['action']=='continue_training'
    assert report['decision']['reason']=='no capability benchmark or held-out result has been recorded for this model yet'
    assert report['params_verified'] is True
    assert report['attempts']==[] and not MEM.cycles(ctx)
    assert set(before)==set(Path(ctx.settings.data_dir).rglob('*'))

from test_evolution import world, add_dataset, drive


def test_requested_manual_cycle_trains_real_weights_then_stays_idle(client,settings,world):
    ctx=world['ctx'];headers=world['o']
    S.update(ctx,{'automatic':False})
    dataset=add_dataset(client,headers)
    assert client.post(f"/v1/admin/evolution/datasets/{dataset['id']}/approve",headers=headers,json={}).status_code==200
    assert EN.tick(ctx)['state']=='manual' and not MEM.cycles(ctx)
    response=client.post('/v1/admin/evolution/run',headers=headers,json={})
    assert response.status_code==200,response.text
    cycle=drive(ctx,lambda c:c['status'] in MEM.TERMINAL_CYCLE)
    assert cycle['status']=='completed'
    experiment=MEM.experiments(ctx,cycle['id'])[0]
    assert experiment['metrics']['training']['step']==60 and experiment['candidate_version']!=world['base']
    from moth_server import models as M
    from moth.training.checkpoint import file_sha256
    from pathlib import Path
    assert file_sha256(Path(M.release(ctx,experiment['candidate_version'])['path'])/'model.pt') != file_sha256(Path(M.release(ctx,world['base'])['path'])/'model.pt')
    before=len(MEM.cycles(ctx));assert EN._maybe_start(ctx,S.get(ctx),woken=True)['state']=='manual'
    assert len(MEM.cycles(ctx))==before and S.get(ctx)['automatic'] is False
