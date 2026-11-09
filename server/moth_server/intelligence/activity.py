"""Bounded, authorization-filtered activity projection. Never returns audit secrets or contents."""
from __future__ import annotations
import base64
import json
from sqlalchemy import select, union_all, literal, cast, String, case, or_, and_
from moth_server import db as D

CATEGORIES=('all','training','data','network','deployment','update','error','administration')


def feed(ctx,uid,owner,category='all',cursor=None,limit=50):
    if category not in CATEGORIES:raise ValueError('Unknown activity category')
    limit=max(1,min(100,limit))
    e=D.evolution_events;a=D.audit_log
    native_category=case((e.c.kind.like('data.%'),'data'),(e.c.kind.like('model.%'),'deployment'),
                         (e.c.kind.like('deployment.%'),'deployment'),else_='training')
    native_message=e.c.message if owner else literal('Recorded native evolution event')
    native=select((literal('e:')+cast(e.c.id,String)).label('id'),e.c.ts.label('ts'),native_category.label('category'),
                  native_message.label('message'),e.c.level.label('level'),e.c.kind.label('action'))
    audit_category=case((a.c.action.like('models.%'),'deployment'),(a.c.action.like('evolution.%'),'training'),
        (a.c.action.like('training.%'),'network'),(a.c.action.like('worker.%'),'network'),(a.c.action.like('library.%'),'data'),
        (a.c.action.like('software.%'),'update'),(a.c.action.like('updates.%'),'update'),else_='administration')
    labels={'models.deployed':'Native model promoted','models.rollback':'Native model rolled back',
        'evolution.rollback':'Evolution rolled back','native_reset.completed':'Owner reset deployment-owned native AI data',
        'library.build':'Dataset preparation started'}
    audit=select((literal('a:')+cast(a.c.id,String)).label('id'),a.c.ts.label('ts'),audit_category.label('category'),
        case(*[(a.c.action==action,label) for action,label in labels.items()],else_=a.c.action).label('message'),
        literal('info').label('level'),a.c.action.label('action')).where(or_(*(a.c.action.like(prefix+'%') for prefix in
            ('models.','evolution.','training.','worker.','library.','software.','updates.','native_reset.'))))
    if not owner:audit=audit.where(a.c.actor_id==uid)
    queries=[native,audit]
    if owner:
        error=D.error_log
        queries.append(select((literal('x:')+cast(error.c.id,String)).label('id'),error.c.ts.label('ts'),literal('error').label('category'),
            literal('Server recorded an error; inspect Owner diagnostics for details.').label('message'),literal('error').label('level'),literal('server.error').label('action')))
    events=union_all(*queries).subquery();query=select(events)
    if category!='all':query=query.where(events.c.category==category)
    if cursor:
        try:
            ts,key=json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if type(ts) not in (int,float) or not isinstance(key,str):raise ValueError()
        except Exception:raise ValueError('Invalid activity cursor') from None
        query=query.where(or_(events.c.ts<ts,and_(events.c.ts==ts,events.c.id<key)))
    rows=ctx.db.all(query.order_by(events.c.ts.desc(),events.c.id.desc()).limit(limit+1))
    more=len(rows)>limit;rows=rows[:limit]
    next_cursor=base64.urlsafe_b64encode(json.dumps([rows[-1]['ts'],rows[-1]['id']]).encode()).decode() if more and rows else None
    from moth_server.evolution.native_reset import state
    return {'events':rows,'next_cursor':next_cursor,'generation':state(ctx).get('generation',0)}
