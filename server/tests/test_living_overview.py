from sqlalchemy import delete
from conftest import H
from moth_server import models as M
from moth_server.db import model_lineage
from test_serving_v053 import _two_releases


def test_snapshot_tracks_loaded_promotion_rollback_and_unavailable_engine(client, owner, tmp_path):
    ctx, stable, candidate = _two_releases(client, owner, tmp_path)
    def snapshot():
        response=client.get('/v1/intelligence/progress',headers=H(owner['token']))
        assert response.status_code == 200, response.text
        return response.json()
    first=snapshot()
    assert first['current']['version'] == stable
    assert first['serving']['loaded']
    assert client.put('/v1/admin/config/flags',headers=H(owner['token']),json={'cloud_inference_enabled':False}).status_code == 200
    disabled=snapshot()
    assert disabled['current']['version'] == stable and not disabled['serving']['accepting_requests']
    assert client.put('/v1/admin/config/flags',headers=H(owner['token']),json={'cloud_inference_enabled':True}).status_code == 200
    assert snapshot()['serving']['accepting_requests']
    M.deploy(ctx,candidate)
    assert snapshot()['current']['version'] == candidate
    M.deploy(ctx,stable)
    assert snapshot()['current']['version'] == stable
    # Registry rows alone cannot claim a model is serving after an engine failure/reset.
    ctx.extras.pop('inference_engine')
    unavailable=snapshot()
    assert unavailable['current'] is None and not unavailable['serving']['loaded']


def test_legacy_deployed_package_is_visible_without_lineage_row(client, owner, tmp_path):
    ctx, stable, _ = _two_releases(client,owner,tmp_path)
    with ctx.db.tx() as conn:
        conn.execute(delete(model_lineage).where(model_lineage.c.version == stable))
    body=client.get('/v1/intelligence/progress',headers=H(owner['token'])).json()
    assert body['current']['version'] == stable
    assert body['current']['model_id'] == ctx.extras['inference_engine'].model_id
    assert body['current']['tokenizer_fingerprint'] == M.release(ctx,stable)['info']['tokenizer_fingerprint']
