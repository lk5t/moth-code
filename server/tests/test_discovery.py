from conftest import H
from moth_server.evolution import datasets as DS
from moth_server.evolution.bootstrap import initialize
from moth_server.intelligence import discovery, library


def test_real_stdlib_discovery_preparation_and_revocation(client, owner):
    ctx = client.app.state.ctx
    seed = initialize(ctx)['model']
    discovery.update(ctx, {'max_source_chars': 100000})
    result = discovery.ensure_data(ctx, wait=True)
    build = library.latest_ready(ctx)
    assert build and build['id'] == result['build']
    rows = DS.approved(ctx, seed['info']['tokenizer_fingerprint'])
    assert rows and rows[0]['tokens_train'] > 1000 and rows[0]['license'] == 'PSF-2.0'
    st = library.status(ctx)['builds'][0]
    assert st['token_counts']['code']['train'] > 1000
    assert st['progress']['message'] == 'Prepared and approved'
    assert discovery.ensure_data(ctx)['build'] == result['build']
    DS.revoke(ctx, rows[0]['id'], owner['user']['id'])
    discovery.update(ctx, {'max_source_chars': 110000})
    assert discovery.ensure_data(ctx)['status'] == 'awaiting_source_approval'
    assert not DS.approved(ctx)


def test_discovery_requires_trusted_license_owner_and_budget(client, owner, monkeypatch):
    headers = H(owner['token'])
    assert client.get('/v1/admin/library/discovery').status_code == 401
    assert client.put('/v1/admin/library/discovery', headers=headers,
                      json={'changes': {'approved_sources': ['https://arbitrary.example/data']}}).status_code == 422
    ctx = client.app.state.ctx
    discovery.update(ctx, {'approved_sources': ['gsm8k'], 'max_download_bytes': 0})
    assert discovery.ensure_data(ctx)['status'] == 'storage_budget'
    assert not library.latest_ready(ctx)
    from moth.datafactory import catalog
    assert discovery.update(ctx, {'approved_sources': [s['id'] for s in catalog.SOURCES]})['approved_sources']
    monkeypatch.setitem(catalog.source('gsm8k'), 'license', 'unknown')
    import pytest
    with pytest.raises(ValueError, match='license'):
        discovery.update(ctx, {'approved_sources': ['gsm8k']})
    discovery.update(ctx, {'approved_sources': []})
    assert discovery.ensure_data(ctx)['status'] == 'awaiting_source_approval'
