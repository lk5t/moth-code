import pytest
from moth_server.evolution import settings as S


def test_modes_preserve_policy_and_explicit_pause(client, monkeypatch):
    ctx = client.app.state.ctx
    monkeypatch.setattr(S, 'cpu_count', lambda: 16)
    S.update(ctx, {'paused': True, 'limits': {'cpu_threads': 6, 'duty_cycle': .6}})
    assert S.runtime(ctx)['limits']['cpu_threads'] == 6  # existing policy untouched
    S.update(ctx, {'training_mode': 'eco'})
    assert S.runtime(ctx)['limits']['cpu_threads'] == 4
    assert S.runtime(ctx)['limits']['duty_cycle'] == .25
    S.update(ctx, {'training_mode': 'maximum', 'enabled': True, 'training_priority': 'training_first'})
    effective = S.runtime(ctx)
    assert effective['paused'] is True
    assert effective['limits']['cpu_threads'] == 6
    assert effective['limits']['duty_cycle'] == .6
    assert S.get(ctx)['limits']['cpu_threads'] == 6


@pytest.mark.parametrize('changes', [{'training_mode': 'turbo'}, {'training_priority': 'ignore_limits'}])
def test_reject_invalid_policy(client, changes):
    ctx = client.app.state.ctx
    before = S.get(ctx)
    with pytest.raises(S.SettingsError):
        S.update(ctx, changes)
    assert S.get(ctx) == before


def test_regular_account_cannot_change_evolution_policy(client, settings):
    from conftest import H, register_verified
    user = register_verified(client, settings, 'controls-user')
    response = client.put('/v1/admin/evolution/settings', headers=H(user['token']),
                          json={'changes': {'training_mode': 'maximum', 'backends': {'workers': True}}})
    assert response.status_code == 403


def test_priority_keeps_cpu_inference_and_owner_budget_protected(client, monkeypatch):
    from moth_server.evolution import compute as C
    ctx = client.app.state.ctx
    monkeypatch.setattr(C, 'local', lambda ctx: {'memory': {'available': 100 * C.GB}, 'disk': {'free': 100 * C.GB}})
    C.activity(ctx).start()
    S.update(ctx, {'training_priority': 'balanced'})
    assert C.local_blockers(ctx, S.runtime(ctx), 'cuda')
    S.update(ctx, {'training_priority': 'training_first'})
    assert not C.local_blockers(ctx, S.runtime(ctx), 'cuda')
    assert C.local_blockers(ctx, S.runtime(ctx), 'cpu')
    S.update(ctx, {'budget': {'max_compute_hours_per_day': 0}})
    assert any('budget' in reason for reason in C.local_blockers(ctx, S.runtime(ctx), 'cuda'))
