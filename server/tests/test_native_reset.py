"""Destructive reset tests use ONLY temporary deployment storage and fixture databases."""
import json
from pathlib import Path
import pytest
from sqlalchemy import select,func
from conftest import H,register_verified
from moth_server import models as M,db as D,training
from moth_server.evolution import native_reset as R,settings as S
from test_serving_v053 import _two_releases


def test_full_erasure_preserves_platform_and_requires_separate_backup_scope(client,owner,settings,tmp_path):
    ctx,old,candidate=_two_releases(client,owner,tmp_path)
    unrelated=ctx.settings.data_dir/'projects'/'keep.txt';unrelated.parent.mkdir();unrelated.write_text('user project')
    (ctx.settings.data_dir/'keys').mkdir(exist_ok=True);key=ctx.settings.data_dir/'keys'/'keep.key';key.write_text('security configuration')
    software=ctx.settings.storage_dir/'software'/'keep.zip';software.parent.mkdir(exist_ok=True);software.write_bytes(b'installed software')
    for relative in ('evolution/datasets/d1','lineage/custom-tokenizers/v1','library/builds/1','eval/datasets/one','coordinator/checkpoints'):
        root=ctx.settings.data_dir/relative;root.mkdir(parents=True,exist_ok=True);(root/'data.bin').write_bytes(b'native owned data')
    backup=ctx.settings.data_dir/'genesis'/'old'/'archive';backup.mkdir(parents=True);(backup/'old.pt').write_bytes(b'backup copy')
    worker_id,worker_token=training.enroll_worker(ctx,training.create_enrollment(ctx,owner['user'],'Reset worker',None),{},'0.6.0')
    with ctx.db.tx() as c:
        job=c.execute(D.training_jobs.insert().values(kind='train_round',status='leased',worker_id=worker_id,spec='{}',created_at=D.now(),updated_at=D.now())).inserted_primary_key[0]
        conversation=c.execute(D.conversations.insert().values(user_id=owner['user']['id'],title='Keep chat',created_at=D.now(),updated_at=D.now())).inserted_primary_key[0]
        c.execute(D.conversation_messages.insert().values(conversation_id=conversation,role='user',content='Keep message',created_at=D.now(),model_version=old))
    ctx.db.set_config('general-user-preference',{'keep':True})
    base='/v1/admin/evolution/native-reset';headers=H(owner['token'])
    plan=client.post(base+'/preview',headers=headers,json={}).json()
    assert plan['inventory']['records']['model_releases']>=2
    assert plan['inventory']['managed_backup_files']>0
    assert M.deployed(ctx)['version']==old
    denied=client.post(base+'/execute',headers=headers,json={'reset_id':plan['id'],'confirmation':'wrong'})
    assert denied.status_code==422 and M.deployed(ctx)['version']==old
    result=client.post(base+'/execute',headers=headers,json={'reset_id':plan['id'],'confirmation':R.CONFIRM})
    assert result.status_code==200,result.text
    state=result.json();assert state['status']=='completed' and worker_id in state['pending_worker_acknowledgements']
    assert state['retained_managed_backup_files'] and backup.exists()
    assert M.deployed(ctx) is None and ctx.extras.get('inference_engine') is None
    assert not M.list_releases(ctx) and S.get(ctx)['paused']
    assert unrelated.read_text()=='user project' and key.exists() and software.exists()
    assert ctx.db.get_config('general-user-preference')=={'keep':True}
    assert ctx.db.one(select(D.conversation_messages).where(D.conversation_messages.c.conversation_id==conversation))['content']=='Keep message'
    assert ctx.db.one(select(D.users).where(D.users.c.id==owner['user']['id']))
    worker=ctx.db.one(select(D.workers).where(D.workers.c.id==worker_id))
    assert worker and worker['token_hash'] and worker['paused'] is False
    beat=training.heartbeat(ctx,worker,None,job,0)
    assert beat['job_cancelled'] and beat['reset_generation']==state['generation']
    assert training.claim_job(ctx,worker,True) is None
    training.heartbeat(ctx,worker,None,None,None,reset_ack=state['generation'],reset_retained=1)
    assert R.status(ctx)['pending_worker_acknowledgements']==[]
    assert R.status(ctx)['reported_retained_worker_cache_files'][worker_id]==1
    repeated=client.post(base+'/execute',headers=headers,json={'reset_id':plan['id'],'confirmation':R.CONFIRM})
    assert repeated.status_code==200 and repeated.json()['generation']==state['generation']
    with ctx.db.tx() as c:assert R.next_job_values(ctx,c)['id']>job
    new_version=M.reserve(ctx,'new untrained baseline',{},owner['user']['id'])
    assert new_version>candidate
    # A separately previewed/confirmed backup scope is required, even after a normal reset.
    second=client.post(base+'/preview',headers=headers,json={'include_managed_backups':True}).json()
    assert client.post(base+'/execute',headers=headers,json={'reset_id':second['id'],'confirmation':R.CONFIRM}).status_code==422
    assert backup.exists()
    result=client.post(base+'/execute',headers=headers,json={'reset_id':second['id'],'confirmation':R.CONFIRM,'backup_confirmation':R.BACKUP_CONFIRM})
    assert result.status_code==200,result.text
    assert not backup.exists()


def test_partial_failure_stays_fenced_and_retryable(client,owner,monkeypatch):
    ctx=client.app.state.ctx;uid=owner['user']['id']
    root=ctx.settings.data_dir/'lineage';root.mkdir();(root/'weights.pt').write_bytes(b'fixture only')
    plan=R.preview(ctx,uid)
    original=R.shutil.rmtree
    def fail(path):
        if Path(path)==root:raise OSError('isolated injected storage failure')
        return original(path)
    monkeypatch.setattr(R.shutil,'rmtree',fail)
    with pytest.raises(ValueError,match='storage failure'):R.execute(ctx,plan['id'],R.CONFIRM,uid)
    assert R.fenced(ctx) and R.state(ctx)['status']=='failed'
    assert client.post('/v1/admin/evolution/run',headers=H(owner['token'])).status_code==503
    assert client.get('/v1/me',headers=H(owner['token'])).status_code==200
    monkeypatch.setattr(R.shutil,'rmtree',original)
    assert R.execute(ctx,plan['id'],R.CONFIRM,uid)['status']=='completed'
    assert not root.exists()


def test_reset_auth_and_symlink_ownership(client,owner,settings,tmp_path):
    base='/v1/admin/evolution/native-reset'
    assert client.post(base+'/preview',json={}).status_code==401
    token=register_verified(client,settings,'regular-reset-user')['token']
    assert client.post(base+'/preview',headers=H(token),json={}).status_code==403
    outside=tmp_path/'other-deployment';outside.mkdir();(outside/'preserve.pt').write_bytes(b'other')
    (settings.data_dir/'lineage').symlink_to(outside,target_is_directory=True)
    response=client.post(base+'/preview',headers=H(owner['token']),json={})
    assert response.status_code==422 and (outside/'preserve.pt').exists()


def test_running_native_work_is_fenced_before_deletion_and_requires_reauth(client,owner):
    import threading
    ctx=client.app.state.ctx;uid=owner['user']['id'];started=threading.Event();release=threading.Event()
    R.spawn(ctx,lambda:(started.set(),release.wait(5)),'isolated-native-test')
    assert started.wait(1)
    plan=R.preview(ctx,uid)
    try:
        with pytest.raises(ValueError,match='finishing'):R.execute(ctx,plan['id'],R.CONFIRM,uid)
        assert R.fenced(ctx)
    finally:release.set()
    for thread in list(ctx.extras.get('native_threads',())):thread.join(2)
    assert R.execute(ctx,plan['id'],R.CONFIRM,uid)['status']=='completed'
    with ctx.db.tx() as c:c.execute(D.sessions.update().values(reauth_at=0))
    assert client.post('/v1/admin/evolution/native-reset/preview',headers=H(owner['token']),json={}).status_code==428


def test_connected_worker_purges_only_proven_owned_cache_and_acknowledges(client,owner,tmp_path,monkeypatch):
    from moth_worker.runner import WorkerRunner
    from moth_worker.client import WorkerClient
    ctx=client.app.state.ctx
    wid,token=training.enroll_worker(ctx,training.create_enrollment(ctx,owner['user'],'Worker cleanup',None),{},'0.6.0')
    runner=WorkerRunner(WorkerClient('http://testserver',token,http=client),tmp_path/'worker',log=lambda _:None)
    monkeypatch.setattr(runner,'hardware',lambda:{})
    root=runner.state_dir/'jobs';(root/'1.pt').write_bytes(b'owned cache');(root/'1.pt.sha256').write_text('fixture')
    (root/'1.owner.json').write_text(json.dumps({'scope':runner.cache_scope()}))
    (root/'2.pt').write_bytes(b'other deployment');(root/'2.owner.json').write_text(json.dumps({'scope':'another-deployment'}))
    (root/'3.pt').write_bytes(b'unverified legacy cache')
    credential=runner.state_dir/'config.json';credential.write_text('preserve credentials')
    plan=R.preview(ctx,owner['user']['id']);R.execute(ctx,plan['id'],R.CONFIRM,owner['user']['id'])
    runner.current_job=1;runner.beat()
    assert runner.cancelled_job==1 and (root/'1.pt').exists()
    runner.current_job=None;runner.beat();runner.beat()
    assert not (root/'1.pt').exists() and not (root/'1.pt.sha256').exists()
    assert (root/'2.pt').exists() and (root/'3.pt').exists() and credential.exists()
    state=R.status(ctx);assert wid not in state['pending_worker_acknowledgements']
    assert state['reported_retained_worker_cache_files'][wid]==2


def test_new_explicit_model_can_train_after_reset_with_retained_backups(client,owner,tmp_path):
    import torch
    from moth_server.evolution.bootstrap import initialize
    from moth.model.registry import load_model
    ctx=client.app.state.ctx;uid=owner['user']['id']
    backup=ctx.settings.data_dir/'genesis'/'old';backup.mkdir(parents=True);(backup/'archive.pt').write_bytes(b'retained backup')
    plan=R.preview(ctx,uid);R.execute(ctx,plan['id'],R.CONFIRM,uid)
    assert M.list_releases(ctx)==[]
    fresh=initialize(ctx,uid)['model'];model,tok,_=load_model(Path(fresh['path']),device='cpu')
    original={key:value.clone() for key,value in model.state_dict().items()}
    optimizer=model.configure_optimizer(0.001,0,device_type='cpu')
    x=torch.arange(32).view(1,-1)%model.cfg.vocab_size
    for _ in range(2):
        _,loss=model(x,x.roll(-1,1));optimizer.zero_grad();loss.backward();optimizer.step()
    assert torch.isfinite(loss) and any(not torch.equal(original[key],value) for key,value in model.state_dict().items())
    assert backup.exists() and S.get(ctx)['paused']


def test_actual_local_training_stops_before_owned_checkpoint_erasure(client,owner,tmp_path,monkeypatch):
    from test_evolution_v053 import _world
    from moth_server.evolution import engine as EN,memory as MEM,backends as B
    import time
    ctx,_=_world(client,owner,tmp_path,monkeypatch)
    S.update(ctx,{'training':{'steps':10000,'checkpoint_interval':1},'max_experiments_per_cycle':1})
    deadline=time.time()+20
    exp=None
    while time.time()<deadline:
        EN.tick(ctx)
        exp=next((e for e in MEM.experiments(ctx) if e['status']=='running' and e['backend']=='local'),None)
        if exp:break
        time.sleep(0.05)
    assert exp,'isolated local training did not start'
    proc=(ctx.extras.get('evolution_procs') or {}).get(exp['id'])
    assert proc is not None and proc.poll() is None
    plan=R.preview(ctx,owner['user']['id'])
    result=R.execute(ctx,plan['id'],R.CONFIRM,owner['user']['id'])
    assert result['status']=='completed' and proc.poll() is not None
    assert not (ctx.settings.data_dir/'evolution').exists()
    assert client.get('/v1/intelligence/progress',headers=H(owner['token'])).json()['current'] is None
