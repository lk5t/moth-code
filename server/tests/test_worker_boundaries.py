import json
from sqlalchemy import select
from conftest import H, register_verified
from moth_server.db import workers
from moth_server import training as T


def test_cloud_enrollment_and_toggle_do_not_authorize_personal_devices(client, settings, owner):
    token = register_verified(client, settings, 'boundary')['token']
    assert client.post('/v1/training/enrollments', json={'kind': 'cloud'}, headers=H(token)).status_code == 403
    enrolled = []
    for kind, account in [('cloud', owner['token']), ('personal', token)]:
        e = client.post('/v1/training/enrollments', json={'kind': kind}, headers=H(account))
        assert e.status_code == 200, e.text
        w = client.post('/v1/worker/enroll', json={'token': e.json()['token'], 'hardware': {'cpu_count': 4, 'ram_gb': 8}, 'version': '0.5.9'}).json()
        enrolled.append(w)
    ctx = client.app.state.ctx
    ctx.db.set_config('evolution_settings', {'cloud_workers': False})
    for kind, w in zip(('cloud', 'personal'), enrolled):
        reply = client.post('/v1/worker/heartbeat', json={'hardware': {'worker_kind': 'personal'}}, headers=H(w['worker_token']))
        assert reply.status_code == 200
        row = ctx.db.one(select(workers).where(workers.c.id == w['worker_id']))
        assert json.loads(row['hardware'])['worker_kind'] == kind
        assert T.worker_allowed(ctx, row) == (kind == 'personal')
    wid = enrolled[1]['worker_id']
    assert client.put(f'/v1/training/workers/{wid}/limits', json={'cpu_threads': 8}, headers=H(owner['token'])).status_code == 403
    assert client.post(f'/v1/training/workers/{wid}/resume', headers=H(owner['token'])).status_code == 403


def test_revocation_between_authentication_and_claim_blocks_assignment(client, owner, training_world):
    from test_training_network import enroll
    _, w = enroll(client, owner['token'])
    ctx = client.app.state.ctx
    stale = ctx.db.one(select(workers).where(workers.c.id == w['worker_id']))
    assert client.post(f"/v1/training/workers/{w['worker_id']}/revoke", headers=H(owner['token'])).status_code == 200
    assert T.claim_job(ctx, stale, True) is None
