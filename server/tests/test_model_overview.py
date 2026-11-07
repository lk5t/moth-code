from pathlib import Path

from conftest import H
from moth_server.evolution.bootstrap import initialize


def test_overview_uses_verified_weights_and_does_not_fabricate_measurements(client, owner):
    ctx = client.app.state.ctx
    rel = initialize(ctx)['model']
    r = client.get('/v1/admin/model-overview', headers=H(owner['token']))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['model']['params'] == 99648
    assert data['model']['model_version'] == '0.01'
    assert data['model']['totals'] == {'steps': 0, 'tokens': 0, 'cycles': 0}
    assert data['model']['training']['train_loss'] is None
    assert data['evaluation'] is None and not data['accepted_versions']
    assert data['checkpoint']['valid'] and data['checkpoint']['bytes'] > 0
    # Real corruption invalidates the dev checkpoint; the verified serving package remains available.
    Path(rel['info']['dev_checkpoint']['path']).write_bytes(b'corrupt')
    data = client.get('/v1/admin/model-overview', headers=H(owner['token'])).json()
    assert not data['development_checkpoint']['valid']
    assert data['checkpoint']['kind'] == 'serving-package'
