from moth_server.evolution.milestones import compare

SUITES = [{'id': 'coding', 'sha': 'code-a', 'capability': 'code'},
          {'id': 'reasoning', 'sha': 'reason-b', 'capability': 'reasoning'}]

def scores(value):
    return {s['id']: {'ok': True, 'value': value, 'higher_is_better': True} for s in SUITES}


def test_checkpoints_minor_gains_and_missing_scores_do_not_earn_milestones():
    assert compare(SUITES, {}, {})
    assert compare(SUITES, scores(.4), scores(.41))
    assert compare([SUITES[0], {**SUITES[1], 'sha': 'code-a'}], scores(.4), scores(.6))
    assert not compare(SUITES, scores(.4), scores(.6))


def test_regressions_block_otherwise_significant_gains():
    candidate = scores(.6)
    candidate['reasoning']['value'] = .3
    assert any('regression' in r for r in compare(SUITES, scores(.4), candidate))


def test_milestone_requires_fresh_repeatable_results(monkeypatch):
    from moth_server.evolution import milestones as M
    monkeypatch.setattr(M.EV, 'build_suites', lambda *args: SUITES)
    monkeypatch.setattr(M.MEM, 'report', lambda ctx, version, sha: scores(.4 if version == 1 else .6)['coding'])
    def report(value):
        return {'ok': True, 'suites': scores(value), 'performance': {'peak_memory_bytes': 100, 'tokens_per_second': 100}}
    reports = iter([report(.4), report(.6), report(.4), report(.41)])
    monkeypatch.setattr(M.EV, '_run', lambda *args: next(reports))
    result = M.assess(None, {'version': 2, 'path': '/candidate'}, {'version': 1, 'path': '/baseline'})
    assert not result['eligible'] and len(result['confirmations']) == 2
    reports = iter([report(.4), report(.6), report(.4), report(.6)])
    monkeypatch.setattr(M.EV, '_run', lambda *args: next(reports))
    result = M.assess(None, {'version': 2, 'path': '/candidate'}, {'version': 1, 'path': '/baseline'})
    assert result['eligible'] and not result['reasons']


def test_failed_deployment_transaction_keeps_live_engine(client, monkeypatch):
    import pytest
    from contextlib import contextmanager
    from moth_server import models as M
    ctx = client.app.state.ctx
    version = M.reserve(ctx, 'transaction-fixture', {'type': 'evolution'}, None)
    old_engine = object()
    ctx.extras['inference_engine'] = old_engine
    ctx.extras['deployed_version'] = 999
    @contextmanager
    def broken_transaction():
        raise RuntimeError('simulated database failure')
        yield
    monkeypatch.setattr(ctx.db, 'tx', broken_transaction)
    with pytest.raises(RuntimeError, match='database failure'):
        M._swap_in(ctx, version, M.release(ctx, version), object(), None, {})
    assert ctx.extras['inference_engine'] is old_engine
    assert ctx.extras['deployed_version'] == 999
