"""Conservative earned milestones using existing held-out evaluators, never training counters."""
from pathlib import Path
import math
from moth_server.evolution import evaluation as EV, memory as MEM


def compare(suites, baseline, candidate):
    reasons, improved = [], []
    for suite in suites:
        b, c = baseline.get(suite['id']), candidate.get(suite['id'])
        if not b or not c or not b.get('ok') or not c.get('ok'):
            reasons.append(f"{suite['id']}: verified measurements unavailable")
            continue
        if 'value' not in b or 'value' not in c:
            reasons.append(f"{suite['id']}: comparable score unavailable")
            continue
        if not all(type(x) in (int, float) and math.isfinite(x) for x in (b['value'], c['value'])):
            reasons.append(f"{suite['id']}: non-finite measurement")
            continue
        if b.get('higher_is_better') != c.get('higher_is_better'):
            reasons.append(f"{suite['id']}: metric direction mismatch")
            continue
        higher = bool(c.get('higher_is_better'))
        gain = EV._better(c['value'], b['value'], higher)
        if gain < -.02 or (suite.get('capability') == 'safety' and gain < 0):
            reasons.append(f"{suite['id']}: retention regression")
        # Accuracy gains must also be material in absolute terms; loss alone cannot earn a milestone.
        if (higher and c['value'] - b['value'] >= .05 and gain >= .1
                and suite.get('capability') in ('code', 'reasoning', 'math', 'coding')):
            improved.append(suite)
    independent = {s['sha'] for s in improved}
    capabilities = {s.get('capability') for s in improved}
    if len(independent) < 2 or len(capabilities) < 2:
        reasons.append('Requires substantial gains on two independent practical capability benchmarks')
    return reasons


def assess(ctx, candidate, baseline):
    suites = EV.build_suites(ctx, candidate)
    old = {s['id']: MEM.report(ctx, baseline['version'], s['sha']) for s in suites}
    new = {s['id']: MEM.report(ctx, candidate['version'], s['sha']) for s in suites}
    reasons = compare(suites, old, new)
    result = {'eligible': False, 'baseline': baseline['version'], 'baseline_sha256': baseline.get('sha256'),
              'candidate_sha256': candidate.get('sha256'), 'reasons': reasons, 'confirmations': []}
    if reasons:
        return result
    # Re-run, bypassing the per-version cache. Keep every result tied to exact package checksums.
    for repeat in range(2):
        b = EV._run(Path(baseline['path']), suites)
        c = EV._run(Path(candidate['path']), suites)
        if not b.get('ok') or not c.get('ok'):
            result['reasons'].append('Repeated evaluation failed')
            return result
        result['confirmations'].append({'repeat': repeat + 1, 'baseline': b, 'candidate': c})
        result['reasons'].extend(compare(suites, b['suites'], c['suites']))
        bp, cp = b.get('performance') or {}, c.get('performance') or {}
        for key, maximum in [('peak_memory_bytes', 1.25)]:
            if not bp.get(key) or not cp.get(key):
                result['reasons'].append(f'Missing repeated {key} measurement')
            elif cp[key] > bp[key] * maximum:
                result['reasons'].append('Milestone compute cost exceeds baseline allowance')
        if not bp.get('tokens_per_second') or not cp.get('tokens_per_second'):
            result['reasons'].append('Missing repeated inference throughput measurement')
        elif cp['tokens_per_second'] < bp['tokens_per_second'] * .75:
            result['reasons'].append('Inference throughput regressed beyond allowance')
        if result['reasons']:
            return result
    result['eligible'] = True
    return result
