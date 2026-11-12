"""Owner-gated, reversible fresh-lineage reset. Never runs during installation or migration.

Preparation pauses the existing engine, waits for leased worker jobs and checkpoints local
trainers. It copies only model/training state, verifies every byte through a restoration
round trip, and stages fresh random weights. Activation is a separate, confirmed action.
Original releases and checkpoints are retained; accounts and projects are never migrated.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import uuid

from sqlalchemy import select

from moth_server.context import Ctx
from moth_server import models as M
from moth_server.db import now, training_jobs
from moth_server.evolution import engine as EN, memory as MEM, settings as S, backends as B

KEY = 'genesis_state'
CONFIRMATION = 'RESET MOTH TO 0.01'


def status(ctx: Ctx) -> dict:
    return ctx.db.get_config(KEY, {}) or {'status': 'not_prepared'}


def _directory(ctx: Ctx, reset_id: str) -> Path:
    if str(uuid.UUID(reset_id)) != reset_id:
        raise ValueError('Invalid reset plan')
    return Path(ctx.settings.data_dir) / 'genesis' / reset_id


def _save(ctx, plan):
    ctx.db.set_config(KEY, plan)
    return plan


def _sha(path):
    from moth.training.checkpoint import file_sha256
    return file_sha256(path)


def _verify_tree(archive: Path, index: dict, destination: Path | None = None):
    for name, entry in index.items():
        src = (archive / name).resolve()
        if archive.resolve() not in src.parents or src.is_symlink() or not src.is_file():
            raise ValueError('Invalid or missing archived model file')
        if src.stat().st_size != entry['size'] or _sha(src) != entry['sha256']:
            raise ValueError(f'Archive integrity failed: {name}')
        if destination is not None:
            dest = destination / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            if _sha(dest) != entry['sha256']:
                raise ValueError(f'Restoration verification failed: {name}')


def prepare(ctx: Ctx, actor_id: int) -> dict:
    """Prepare a concrete, verified reset plan without replacing the deployed model."""
    import torch
    from moth.model.config import preset
    from moth.model.tokenizer import Tokenizer
    from moth.model.transformer import MothModel
    from moth.model.registry import export_model
    from moth.training.checkpoint import atomic_torch_save, verify
    from moth_server import db as DB

    with EN._tick_lock:
        active = MEM.active_cycle(ctx)
        if active and active['status'] in ('deploying', 'monitoring'):
            raise ValueError('Finish or roll back the active model rollout before preparing a reset')
        plan = status(ctx)
        if plan.get('status') == 'prepared':
            verify_plan(ctx, plan)
            return plan
        if plan.get('status') == 'active':
            raise ValueError('GENESIS is already active; use the existing model rollback controls')
        previous = M.deployed(ctx)
        if plan.get('status') != 'preparing':
            plan = {'id': str(uuid.uuid4()), 'status': 'preparing', 'created_at': now(), 'actor_id': actor_id,
                    'previous_version': previous['version'] if previous else None,
                    'previous_name': previous['name'] if previous else None,
                    'previous_settings': copy.deepcopy(ctx.db.get_config(S.KEY, {}) or {}),
                    'previous_state': EN.state(ctx)}
            _save(ctx, plan)
        if (previous or {}).get('version') != plan['previous_version']:
            raise ValueError('The deployed model changed; abort this plan and prepare a new backup')
        S.update(ctx, {'paused': True})
        for exp in MEM.experiments(ctx, limit=10000):
            if exp['status'] == 'running' and exp['backend'] == 'local':
                if not B.pause_local(ctx, exp, wait_s=60):
                    raise ValueError('A local trainer has not checkpointed yet; retry preparation once it stops')
        leased = ctx.db.all(select(training_jobs.c.id).where(training_jobs.c.status == 'leased'))
        if leased:
            raise ValueError('Existing worker jobs must finish/checkpoint before backup. New leases are paused; retry preparation shortly')
        root = _directory(ctx, plan['id'])
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        archive = root / 'archive'
        if archive.exists():
            shutil.rmtree(archive)  # only this unfinished, unapproved backup; original state is untouched
        archive.mkdir()
        data = Path(ctx.settings.data_dir).resolve()
        from moth.model.package import inspect_package
        for release in M.list_releases(ctx):
            if release.get('path') and not inspect_package(release['path'], deep=True)['ok']:
                raise ValueError('A legacy model package failed integrity verification; no reset was prepared')
        roots = [M.releases_dir(ctx), data / 'lineage', data / 'evolution' / 'runs', data / 'coordinator']
        files = {}
        for source_root in roots:
            if not source_root.exists():
                continue
            for src in source_root.rglob('*'):
                if src.is_symlink():
                    raise ValueError('Model backups cannot follow symbolic links')
                if src.is_file():
                    files[str(src.resolve().relative_to(data))] = src
        required = sum(p.stat().st_size for p in files.values())
        if shutil.disk_usage(root).free < required * 2 + 256 * 1024**2:
            raise ValueError('Not enough free disk for a backup plus its restoration verification')
        index = {}
        for name, src in files.items():
            dst = archive / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            index[name] = {'sha256': _sha(src), 'size': src.stat().st_size}
        tables = [DB.model_releases, DB.model_lineage, DB.evaluation_reports, DB.evolution_cycles,
                  DB.evolution_experiments, DB.evolution_events, DB.training_jobs]
        history = {table.name: ctx.db.all(select(table)) for table in tables}
        (archive / 'training-history.json').write_text(json.dumps(history, default=str), encoding='utf-8')
        index['training-history.json'] = {'sha256': _sha(archive / 'training-history.json'),
                                           'size': (archive / 'training-history.json').stat().st_size}
        (root / 'archive-index.json').write_text(json.dumps(index, sort_keys=True), encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='restore-check-', dir=root) as tmp:
            _verify_tree(archive, index, Path(tmp))
        seed = root / 'fresh' / 'seed.pt'
        seed.parent.mkdir(exist_ok=True)
        tok = Tokenizer([])
        tok_path = seed.parent / 'tokenizer.json'
        tok.save(tok_path)
        cfg = preset('moth-tiny', vocab_size=tok.vocab_size, ffn_hidden=128)
        cfg.name = 'moth-0.01'
        if not seed.exists():
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(secrets.randbits(63))
                fresh = MothModel(cfg)
            atomic_torch_save({'model': fresh.state_dict(), 'model_config': cfg.to_dict(),
                              'tokenizer_path': str(tok_path), 'tokenizer_fingerprint': tok.fingerprint(),
                              'step': 0, 'tokens_seen': 0, 'train_config': {}}, seed)
        if not verify(seed):
            raise ValueError('Fresh seed integrity failed; refusing to replace it')
        package = seed.parent / 'packages' / 'moth-0.01'
        lineage_id = f"native-moth-genesis-{plan['id']}"
        if not package.exists():
            export_model(seed, package.parent, package.name, dtype='float32', extra={
                'model_version': '0.0.1', 'display_name': 'MOTH 0.0.1', 'family': 'MOTH',
                'lineage_id': lineage_id, 'initialization': 'random-untrained'})
        plan.update(status='prepared', archive_files=len(index), archive_bytes=sum(e['size'] for e in index.values()),
                    archive_index_sha256=_sha(root / 'archive-index.json'), restore_verified=True,
                    seed_sha256=_sha(seed), model_config=cfg.to_dict(), parameters=cfg.num_params(),
                    lineage_id=lineage_id, confirmation=CONFIRMATION, prepared_at=now())
        MEM.event(ctx, 'genesis.prepared', 'Legacy model backup and restoration verified; fresh untrained MOTH 0.01 staged. Owner activation is still required', actor=actor_id)
        return _save(ctx, plan)


def verify_plan(ctx, plan):
    root = _directory(ctx, plan['id'])
    index_path = root / 'archive-index.json'
    if _sha(index_path) != plan['archive_index_sha256']:
        raise ValueError('Archive index integrity failed')
    _verify_tree(root / 'archive', json.loads(index_path.read_text()))
    if _sha(root / 'fresh' / 'seed.pt') != plan['seed_sha256']:
        raise ValueError('Fresh checkpoint integrity failed')


def activate(ctx: Ctx, reset_id: str, confirmation: str, actor_id: int, start_training: bool = False) -> dict:
    """Explicit approval only, after backup verification; never an automatic upgrade step."""
    from moth_server import serving
    from moth_server import db as DB
    from moth_server.evolution import v2
    with EN._tick_lock:
        plan = status(ctx)
        if confirmation != CONFIRMATION or plan.get('id') != reset_id or plan.get('status') != 'prepared':
            raise ValueError('An explicitly confirmed, prepared reset plan is required')
        verify_plan(ctx, plan)
        current = M.deployed(ctx)
        if (current or {}).get('version') != plan['previous_version']:
            raise ValueError('The deployed model changed after backup; prepare a new plan')
        root = _directory(ctx, reset_id)
        if not plan.get('new_version'):
            rel = M._register(ctx, root / 'fresh/packages/moth-0.01', 'MOTH 0.01 (untrained)',
                              {'type': 'native-initialization', 'genesis_id': reset_id}, actor_id)
            plan['new_version'] = rel['version']
            _save(ctx, plan)
            info = {**rel['info'], 'initialization': 'random-untrained',
                    'lineage_totals': {'steps': 0, 'tokens': 0, 'cycles': 0},
                    'dev_checkpoint': v2.store_dev_checkpoint(ctx, rel['version'], str(root / 'fresh/seed.pt'), plan['seed_sha256'])}
            M._set(ctx, rel['version'], info=json.dumps(info))
        rel = M.evaluate(ctx, plan['new_version'], actor_id=actor_id)
        if rel['status'] == 'evaluated' and (rel.get('evaluation') or {}).get('reason') == 'regression':
            # This is an explicitly approved fresh baseline, not an automatic improvement.
            # Reuse the existing Owner override; every structural/finite/inference check must
            # still pass, and the measured regression remains recorded as a regression.
            rel = M.publish(ctx, rel['version'], actor_id, override_regression=True)
        if rel['status'] != 'published':
            raise ValueError(rel.get('error') or 'The untrained baseline failed evaluation; the previous model is retained')
        serving.sign_release(ctx, rel['version'])
        # Keep original checkpoint directories. cancel_cycle's cleanup is intentionally avoided.
        with ctx.db.tx() as c:
            c.execute(DB.evolution_cycles.update().where(DB.evolution_cycles.c.status.notin_(MEM.TERMINAL_CYCLE))
                      .values(status='cancelled', finished_at=now(), updated_at=now(), error='Archived by approved GENESIS reset'))
            c.execute(DB.evolution_experiments.update().where(DB.evolution_experiments.c.status.notin_(MEM.TERMINAL_EXPERIMENT))
                      .values(status='cancelled', finished_at=now(), error='Archived by approved GENESIS reset'))
            c.execute(training_jobs.update().where(training_jobs.c.status.in_(('queued', 'leased')))
                      .values(status='cancelled', updated_at=now(), error='Archived by approved GENESIS reset'))
        deployed = M.deploy(ctx, rel['version'], actor_id, expected_parent=plan['previous_version'])
        EN._set_state(ctx, stable_version=rel['version'], next_cycle_at=0, consecutive_failures=0, idle_reason=None)
        S.update(ctx, {'enabled': True, 'paused': not start_training})
        plan.update(status='active', activated_at=now(), activated_by=actor_id, retired_legacy_jobs=True)
        _save(ctx, plan)
        MEM.event(ctx, 'genesis.activated', 'Owner activated fresh untrained MOTH 0.01; no legacy parameters inherited', actor=actor_id)
    if start_training:
        EN.wake(ctx)
    return {'plan': plan, 'model': deployed}


def restore(ctx: Ctx, reset_id: str, actor_id: int) -> dict:
    """Roll back the serving model to the retained, verified legacy release. Training stays paused."""
    with EN._tick_lock:
        plan = status(ctx)
        if plan.get('id') != reset_id or plan.get('status') not in ('preparing', 'prepared', 'active'):
            raise ValueError('No matching reset plan is available')
        if plan.get('restore_verified'):
            verify_plan(ctx, plan)
            root = _directory(ctx, reset_id)
            data = Path(ctx.settings.data_dir).resolve()
            for name, entry in json.loads((root / 'archive-index.json').read_text()).items():
                if name == 'training-history.json':
                    continue
                dest = (data / name).resolve()
                if data not in dest.parents:
                    raise ValueError('Invalid restoration destination')
                if dest.exists() and _sha(dest) != entry['sha256']:
                    raise ValueError('A retained file has changed; refusing to overwrite newer training progress')
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(root / 'archive' / name, dest)
        if plan.get('status') == 'active' and plan.get('previous_version'):
            M.deploy(ctx, plan['previous_version'], actor_id)
        ctx.db.set_config(S.KEY, {**plan['previous_settings'], 'paused': True})
        EN._set_state(ctx, **{k: v for k, v in plan['previous_state'].items() if k != 'last_tick'})
        plan.update(status='restored', restored_at=now(), retired_legacy_jobs=True)
        MEM.event(ctx, 'genesis.restored', 'Owner restored the archived lineage; training remains paused', actor=actor_id)
        return _save(ctx, plan)
