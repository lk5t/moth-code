import json
from sqlalchemy import select
from conftest import H,register_verified
from moth_server import db as D
from moth_server.audit import audit
from moth_server.evolution import memory as MEM,native_reset as R
from moth_server.intelligence.activity import feed


def test_activity_permissions_pagination_filter_and_reset(client,owner,settings):
    ctx=client.app.state.ctx;uid=owner['user']['id']
    user=register_verified(client,settings,'activity-reader');other=user['user']['id']
    audit(ctx.db,'models.deployed',uid,'release:1',{'secret':'DO_NOT_EXPOSE'})
    audit(ctx.db,'worker.enrolled',other,'worker:7',{'secret':'DO_NOT_EXPOSE'})
    MEM.event(ctx,'experiment.rejected','private dataset path /owner/private',level='warning')
    owner_events=feed(ctx,uid,True)['events'];assert any('private dataset' in e['message'] for e in owner_events)
    regular=client.get('/v1/intelligence/activity',headers=H(user['token'])).json()
    assert 'DO_NOT_EXPOSE' not in json.dumps(regular) and '/owner/private' not in json.dumps(regular)
    assert any(e['action']=='worker.enrolled' for e in regular['events'])
    assert not any(e['action']=='models.deployed' for e in regular['events'])
    first=feed(ctx,uid,True,limit=1);second=feed(ctx,uid,True,cursor=first['next_cursor'],limit=1)
    assert first['events'][0]['id']!=second['events'][0]['id']
    assert all(e['category']=='deployment' for e in feed(ctx,uid,True,category='deployment')['events'])
    assert client.get('/v1/intelligence/activity?category=invalid',headers=H(owner['token'])).status_code==422
    assert client.get('/v1/intelligence/activity?cursor=garbage',headers=H(owner['token'])).status_code==422
    plan=R.preview(ctx,uid);R.execute(ctx,plan['id'],R.CONFIRM,uid)
    after=feed(ctx,uid,True)
    assert not any(e['action'] in ('models.deployed','experiment.rejected') for e in after['events'])
    assert any(e['action']=='native_reset.completed' for e in after['events'])
    assert '/owner/private' not in json.dumps(after)
    assert after['generation']==1
