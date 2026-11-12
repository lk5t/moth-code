"""Read-only explanation of the capability-based growth decision; never creates experiments or data."""
import json
from pathlib import Path
from sqlalchemy import select
from moth_server import models as M
from moth_server.db import library_builds
from moth_server.evolution import compute as C, datasets as DS, memory as MEM, settings as S, v2


def inspect(ctx):
    settings=S.get(ctx);base=M.deployed(ctx)
    result={'enabled':settings['growth']['enabled'],'automatic':settings.get('automatic',True),
            'paused':settings['paused'],'budget':settings['growth'],
            'explanation':'Learning updates weights; parameter count increases only after a larger candidate passes evaluation and is promoted.',
            'history_limit':100,'attempts':[],'blockers':[]}
    if not base:
        return result|{'blockers':['No deployed native model is available.'],'decision':None}
    from moth.model.config import MothConfig
    from moth_server.evolution import capacity as CAP
    cfg=MothConfig.from_dict(json.loads((Path(base['path'])/'config.json').read_text()))
    evidence=v2.growth_evidence(ctx,base)|{'plateau_threshold':settings['growth']['plateau_threshold']}
    decision=CAP.assess(ctx,base,settings)  # the same capability-based decision the planner makes
    versions={base['version']}|{a['version'] for a in MEM.ancestors(ctx,base['version'])}
    attempts=[e for e in MEM.experiments(ctx,limit=100) if e['base_version'] in versions and (e['config'] or {}).get('method')=='expansion']
    result.update(deployed_version=base['version'],registered_params=base['info'].get('params'),architecture_params=cfg.num_params(),
                  params_verified=M.params_verified(base['info']),
                  tokenizer=base['info'].get('tokenizer_fingerprint'),evidence=evidence,decision=decision,
                  attempts=[{'id':e['id'],'status':e['status'],'candidate':e.get('candidate_version'),'growth':(e['config'] or {}).get('grow'),'error':e.get('error')} for e in attempts])
    approved=DS.approved(ctx,base['info'].get('tokenizer_fingerprint'))
    ready=ctx.db.all(select(library_builds).where(library_builds.c.status=='ready'))
    compatible=any(b['tokenizer_fingerprint']==base['info'].get('tokenizer_fingerprint') and b['path'] and
                   (Path(b['path'])/'tokens/mixture.json').is_file() and
                   any(f"(build {b['id']})" in d['name'] for d in approved) for b in ready)
    if not result['enabled']:result['blockers'].append('Architecture growth is disabled by the Owner.')
    if not settings.get('use_curriculum',True):result['blockers'].append('Curriculum planning is disabled; the existing growth planner is not invoked.')
    if not compatible:result['blockers'].append('No ready, approved curriculum build matches the deployed tokenizer.')
    if not decision['grow']:result['blockers'].append(decision['reason'])
    if settings['paused'] or not settings['enabled']:result['blockers'].append('Training is paused or disabled.')
    target=decision.get('params_after',cfg.num_params());tr=settings['training']
    need=C.estimate_training_memory(target,tr['batch_size'],tr['seq_len'],cfg.d_model,cfg.n_layers+decision.get('add_layers',0))
    backend,reasons=C.choose_backend(ctx,settings,need)
    result.update(estimated_training_bytes=need,available_backend=backend,compute_blockers=reasons)
    if backend is None:result['blockers'].extend(reasons)
    from moth.model.growth import growth_options
    limit=int(settings['growth'].get('max_params',0)) or None
    result['options']=[o for o in growth_options(cfg,2.0) if not limit or o['params']<=limit][:12]
    result['request']=ctx.db.get_config('growth_request',None)
    result['compatibility']='Expansion preserves vocabulary, tokenizer and existing weights; optimizer state is migrated. Held-out gates and rollback still apply.'
    result['scope']='Current deployed lineage; at most the latest 100 recorded experiments. Missing history is not proof that growth never ran.'
    return result
