"""Explicit deployment-owned native AI erasure. Never called by upgrades or maintenance.

Known owned roots only; account, billing, chat, consent, security keys and software are excluded.
Failures remain fenced and resumable. Offline copies/backups are disclosed, never claimed erased.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time
import uuid
from sqlalchemy import select, func, delete
from moth_server import db as D

KEY='native_reset'
CONFIRM='DELETE ALL NATIVE AI DATA'
BACKUP_CONFIRM='DELETE MANAGED AI BACKUPS'
ROOTS=('storage/models','storage/uploads','lineage','evolution','coordinator','library','eval')
TABLES=('training_jobs','evolution_experiments','evolution_cycles','evaluation_reports','model_lineage','evolution_events','training_datasets','library_builds','uploads','model_releases')
CONFIGS=('deployed_release','evolution_state','curriculum','library_pins','library_updates','eval_dataset_pinned','genesis_state','library_discovery_state','library_discovery_scan_at')
NATIVE_AUDIT=('models.','evolution.','library.','training.')


def state(ctx):return ctx.db.get_config(KEY,{}) or {'status':'idle','generation':0}
def fenced(ctx):return state(ctx).get('status') in ('fencing','deleting','failed')
def empty(ctx):return state(ctx).get('status')=='completed' and not ctx.db.one(select(D.model_releases.c.id).limit(1))


def lock(ctx):return ctx.extras.setdefault('native_operation_lock',threading.RLock())


def spawn(ctx,target,name):
    """Track native background work so erasure cannot race an unobserved writer."""
    with lock(ctx):
        if fenced(ctx):raise ValueError('Native AI reset is in progress; finish recovery first')
        def run():
            try:target()
            finally:
                with lock(ctx):ctx.extras.setdefault('native_threads',set()).discard(threading.current_thread())
        thread=threading.Thread(target=run,name=name,daemon=True)
        ctx.extras.setdefault('native_threads',set()).add(thread);thread.start();return thread


def owned(ctx,relative):
    if relative not in (*ROOTS,'genesis'):raise ValueError('Unrecognized native storage category')
    base=Path(ctx.settings.data_dir).resolve();path=base/relative
    # Reject links in root ancestors as well as descendants; never traverse another deployment.
    candidate=path
    while candidate!=base:
        if candidate.is_symlink():raise ValueError('Native storage contains a symbolic link; resolve ownership before reset')
        candidate=candidate.parent
    if path.exists():
        for entry in path.rglob('*'):
            if entry.is_symlink():raise ValueError('Native storage contains a symbolic link; resolve ownership before reset')
    return path


def inventory(ctx,backups=False):
    roots=[]
    for relative in (*ROOTS,*(('genesis',) if backups else ())):
        path=owned(ctx,relative);files=[p for p in path.rglob('*') if p.is_file()] if path.is_dir() else ([path] if path.is_file() else [])
        roots.append({'category':relative,'files':len(files),'bytes':sum(p.stat().st_size for p in files)})
    counts={name:int(ctx.db.one(select(func.count().label('n')).select_from(getattr(D,name)))['n']) for name in TABLES}
    backup=owned(ctx,'genesis');copies=sum(1 for p in backup.rglob('*') if p.is_file()) if backup.exists() else 0
    external=[];base=Path(ctx.settings.data_dir).resolve()
    for table,column in ((D.model_releases,'path'),(D.training_datasets,'path'),(D.library_builds,'path')):
        for row in ctx.db.all(select(table.c[column])):
            if row[column] and base not in Path(row[column]).resolve().parents:external.append(str(row[column]))
    return {'roots':roots,'records':counts,'managed_backup_files':copies,'backups_included':backups,'external_references':external,
        'disclosure':'Only deployment-owned roots are erased. Managed GENESIS backups are retained unless separately confirmed. Infrastructure snapshots, exported packages, external paths and offline Desktop/Worker copies cannot be certified erased here. Accounts, credentials, billing, chat, projects, settings, consent, security keys and software binaries are preserved.'}


def preview(ctx,actor_id,backups=False):
    with lock(ctx):
        previous=state(ctx)
        if fenced(ctx):raise ValueError('A reset requires recovery. Retry its existing reset ID rather than replacing it.')
        plan={'id':uuid.uuid4().hex,'status':'preview','actor_id':actor_id,'created_at':time.time(),
              'generation':int(previous.get('generation',0)),'inventory':inventory(ctx,backups),'backups':backups}
        ctx.db.set_config(KEY,plan);return plan


def next_job_values(ctx,conn):
    """Monotonic even on SQLite after DELETE; stale workers can never hit a reused job ID."""
    row=conn.execute(select(D.server_config).where(D.server_config.c.key=='native_job_floor').with_for_update()).mappings().first()
    if not row:return {}
    floor=json.loads(row['value']) or 0
    maximum=conn.execute(select(func.max(D.training_jobs.c.id))).scalar() or 0
    value=max(int(maximum)+1,int(floor))
    ctx.db.set_config('native_job_floor',value+1,conn=conn)
    return {"id":value}


def pending_workers(ctx):
    generation=state(ctx).get('generation',0)
    if not generation:return []
    return [w['id'] for w in ctx.db.all(select(D.workers.c.id).where(D.workers.c.revoked_at.is_(None))) if int(ctx.db.get_config('native_reset_ack:'+str(w['id']),0) or 0)<generation]


def status(ctx):
    out=state(ctx).copy();out['pending_worker_acknowledgements']=pending_workers(ctx)
    out['reported_retained_worker_cache_files']={w['id']:ctx.db.get_config('native_reset_retained:'+str(w['id']),0) for w in ctx.db.all(select(D.workers.c.id)) if ctx.db.get_config('native_reset_retained:'+str(w['id']),0)}
    return out


def execute(ctx,reset_id,confirmation,actor_id,backup_confirmation=''):
    from moth.training.checkpoint import RunLock,CheckpointError
    try:
        with RunLock(Path(ctx.settings.data_dir)/'.native-reset-control','Owner native AI reset'):
            return _execute(ctx,reset_id,confirmation,actor_id,backup_confirmation)
    except CheckpointError as error:raise ValueError('Another reset operation is running; wait for it to finish') from error


def _execute(ctx,reset_id,confirmation,actor_id,backup_confirmation=''):
    from moth_server.evolution import engine as EN, settings as S, memory as MEM, backends as B
    from moth_server import serving
    from moth_server.evolution.compute import activity
    from moth_server.audit import audit
    with lock(ctx):
        plan=state(ctx)
        if plan.get('id')!=reset_id or plan.get('actor_id')!=actor_id:raise ValueError('Reset preview does not belong to this Owner session')
        if confirmation!=CONFIRM:raise ValueError('Type the exact native AI deletion confirmation')
        if plan.get('backups') and backup_confirmation!=BACKUP_CONFIRM:raise ValueError('Managed backup deletion requires its separate exact confirmation')
        if plan['status']=='completed':return status(ctx)
        if plan['status']=='preview' and time.time()-plan['created_at']>600:raise ValueError('Reset preview expired; inspect a fresh inventory')
        if plan['status'] not in ('preview','failed','fencing','deleting'):raise ValueError('Invalid reset state')
        first=plan['status']=='preview'
        if first:plan.update(generation=plan.get('generation',0)+1,started_at=time.time())
        plan.update(status='fencing',error=None);ctx.db.set_config(KEY,plan)
        S.update(ctx,{'paused':True})
        # Cancel leases before waiting, so connected workers stop and late uploads are rejected.
        with ctx.db.tx() as c:
            maximum=c.execute(select(func.max(D.training_jobs.c.id))).scalar() or 0
            row=c.execute(select(D.server_config.c.value).where(D.server_config.c.key=='native_job_floor')).scalar()
            old=json.loads(row) if row else 0
            ctx.db.set_config('native_job_floor',max(int(old),int(maximum)+1),conn=c)
            versions=c.execute(select(func.max(D.model_releases.c.version))).scalar() or 0
            row=c.execute(select(D.server_config.c.value).where(D.server_config.c.key=='native_version_floor')).scalar()
            old=json.loads(row) if row else 1
            ctx.db.set_config('native_version_floor',max(int(old),int(versions)+1),conn=c)
            c.execute(D.training_jobs.update().where(D.training_jobs.c.status.in_(('queued','leased'))).values(status='cancelled',lease_expires_at=None,error='Native AI reset',updated_at=time.time()))
        try:
            if not EN._tick_lock.acquire(blocking=False):raise ValueError('Evolution is finishing an operation. Native work is fenced; retry this reset shortly.')
            try:
                if ctx.extras.get('native_http_active',0):raise ValueError('Native requests are finishing. Retry this reset shortly.')
                if any(t.is_alive() for t in ctx.extras.get('native_threads',set())):raise ValueError('Native preparation/evaluation is finishing. Retry this reset after it stops.')
                for exp in MEM.experiments(ctx,limit=10000):
                    if exp['backend']=='local' and exp['status'] in ('running','paused'):
                        if not B.pause_local(ctx,exp,wait_s=20):raise ValueError('A trainer has not stopped yet. Native work remains fenced; retry recovery.')
                if activity(ctx).active:raise ValueError('A native response is finishing. Retry after it closes.')
                serving.end_canary(ctx,'Native AI reset')
                engine=ctx.extras.pop('inference_engine',None)
                if engine is not None:engine.unload()
                ctx.extras.pop('deployed_version',None);ctx.extras.pop('coordinator',None)
                # Revalidate ownership immediately before deletion. External originals are preserved/disclosed.
                current=inventory(ctx,plan['backups'])
                plan.update(status='deleting');ctx.db.set_config(KEY,plan)
                for relative in (*ROOTS,*(('genesis',) if plan['backups'] else ())):
                    path=owned(ctx,relative)
                    if path.is_dir():shutil.rmtree(path)
                    elif path.exists():path.unlink()
                with ctx.db.tx() as c:
                    for name in TABLES:c.execute(delete(getattr(D,name)))
                    c.execute(D.conversation_messages.update().where(D.conversation_messages.c.model_version.is_not(None)).values(model_version=None,model=None))
                    c.execute(delete(D.feedback).where(D.feedback.c.model_version.is_not(None)))
                    for key in CONFIGS:c.execute(delete(D.server_config).where(D.server_config.c.key==key))
                    c.execute(delete(D.server_config).where(D.server_config.c.key.like('library_progress_%')))
                    for prefix in NATIVE_AUDIT:c.execute(delete(D.audit_log).where(D.audit_log.c.action.like(prefix+'%')))
                    for prefix in ('moth_server.models','moth_server.evolution','moth_server.intelligence.library','moth.training'):
                        c.execute(delete(D.error_log).where(D.error_log.c.source.like(prefix+'%')))
                    ctx.db.set_config('deployed_release',None,conn=c)
                    ctx.db.set_config('genesis_state',{'status':'erased_by_full_reset','retired_legacy_jobs':True},conn=c)
                    for user in c.execute(select(D.users.c.id,D.users.c.settings)).mappings().all():
                        settings=json.loads(user['settings'] or '{}')
                        if 'pinned_model_version' in settings:
                            settings.pop('pinned_model_version');c.execute(D.users.update().where(D.users.c.id==user['id']).values(settings=json.dumps(settings)))
                    c.execute(D.workers.update().values(verified_jobs=0,failed_jobs=0,trained_tokens=0))
                for name in ('inference_activity','evolution_procs','evolution_recovered','intelligence_cache'):
                    ctx.extras.pop(name,None)
                verification=inventory(ctx,plan['backups'])
                if any(verification['records'].values()) or any(r['files'] for r in verification['roots']):raise ValueError('Reset verification found remaining native data; retry recovery')
                # Keep only minimal security/recovery metadata; no deleted model names, hashes or paths.
                complete={'id':reset_id,'status':'completed','generation':plan['generation'],'actor_id':actor_id,'completed_at':time.time(),
                          'backups_included':plan['backups'],'retained_managed_backup_files':0 if plan['backups'] else current['managed_backup_files'],
                          'retained_external_copies':len(current['external_references']),'disclosure':current['disclosure']}
                ctx.db.set_config(KEY,complete)
                audit(ctx.db,'native_reset.completed',actor_id,None,{'id':reset_id,'generation':plan['generation'],'backups_included':plan['backups']})
                return status(ctx)
            finally:EN._tick_lock.release()
        except Exception as error:
            plan.update(status='failed',error=str(error)[:300]);ctx.db.set_config(KEY,plan)
            raise ValueError(str(error)) from None
