"""Dump every number quoted in the manuscript to numbers.md (single source for the text)."""
import collections, statistics
from common import trials, inference, OUT
L = []
for st in 'CDE':
    rows = trials(st); L.append(f'## Study {st}: {len(rows)} trials; excluded {sum(r["infrastructure_excluded"] for r in rows)}')
    by = collections.defaultdict(list)
    for r in rows: by[r['rule']].append(r)
    for rule, rs in sorted(by.items()):
        L.append(f'- {rule}: success {sum(r["success"] for r in rs)}/{len(rs)}; mean s {statistics.mean(r["total_seconds"] for r in rs):.1f}; '
                 f'dispatch {statistics.mean(r["primitive_dispatches"] for r in rs):.2f}; reobs {statistics.mean(r.get("belief_reobservations", 0) for r in rs):.2f}; '
                 f'false-completion {sum(r["false_completion_report"] for r in rs)}; budget stops {sum(r["budget_stop"] for r in rs)}')
    nz = [r for r in rows if r['noise_type'] == 'none']
    for rule in sorted({r['rule'] for r in nz}):
        z = [r for r in nz if r['rule'] == rule]; L.append(f'  - no-error {rule}: success {sum(r["success"] for r in z)}/{len(z)}, mean s {statistics.mean(r["total_seconds"] for r in z):.1f}')
    inf = inference(st)
    for key in ['primary', 'key_secondary']:
        for x in inf.get(key, []):
            L.append(f'- {key}: ' + ', '.join(f'{k}={x[k]}' for k in ['id', 'condition', 'noise_type', 'noise_rate', 'noise_correlation', 'a', 'b', 'a_successes', 'b_successes',
                     'a_only_success', 'b_only_success', 'a_total', 'b_total', 'a_greater', 'b_greater', 'ties', 'risk_difference_a_minus_b', 'mean_difference_a_minus_b', 'p', 'p_holm'] if k in x))
(OUT/'analysis/numbers.md').write_text('\n'.join(L), encoding='utf-8'); print('\n'.join(L))
