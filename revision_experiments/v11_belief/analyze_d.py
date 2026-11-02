"""Study D analysis. --checkpoint: descriptive counts + replay audit (exit 3 if the audit fails). --final: frozen inference.
Per-trial rows and the replay audit come from trial_d.py (generated from the registered v10 analysis)."""
from pathlib import Path
import argparse, collections, datetime, json, statistics, sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import trial_d as td   # noqa: E402

RUN = td.RUN; EXEC = td.EXEC; MAX_INFRA_EXCLUSIONS = 3; AUDIT_FAILED = 3
KEY = ('condition', 'noise_type', 'noise_rate', 'noise_correlation')


def level(r): return tuple(r[k] for k in KEY)


def describe(rows):
    cells = collections.defaultdict(list)
    for r in rows: cells[level(r)+(r['rule'],)].append(r)
    out = []
    for k, rs in sorted(cells.items(), key=str):
        n = len(rs); s = sum(r['success'] for r in rs)
        out.append(dict(zip(KEY+('rule',), k)) | {'n': n, 'successes': s, 'wilson95': td.wilson(s, n),
                    'budget_stops': sum(r['budget_stop'] for r in rs), 'false_completion_reports': sum(r['false_completion_report'] for r in rs),
                    'mean_extra_repicks': statistics.mean(r['extra_repicks_of_satisfied_objects'] for r in rs),
                    'mean_dispatches': statistics.mean(r['primitive_dispatches'] for r in rs),
                    'mean_seconds': statistics.mean(r['total_seconds'] for r in rs),
                    'mean_flips': statistics.mean(r['observation_flips'] for r in rs),
                    'mean_belief_reobservations': statistics.mean(r['belief_reobservations'] for r in rs),
                    'action_timeouts': sum(r['action_timeout'] for r in rs),
                    'trials_with_fault_requested': sum(r['fault_requested'] > 0 for r in rs),
                    'trials_with_fault_deferral': sum(r['fault_deferrals'] > 0 for r in rs)})
    return out


def pairs(rows, spec, a, b):
    want = tuple(spec[k] for k in KEY)
    by = {(r['seed'], r['rule']): r for r in rows if level(r) == want}
    seeds = sorted({s for s, _ in by if (s, a) in by and (s, b) in by})
    return by, seeds


def paired_success(rows, spec, a, b):
    by, seeds = pairs(rows, spec, a, b)
    ab = sum(by[s, a]['success'] and not by[s, b]['success'] for s in seeds); ba = sum(by[s, b]['success'] and not by[s, a]['success'] for s in seeds)
    return {**{k: spec[k] for k in KEY}, 'a': a, 'b': b, 'outcome': 'independent_final_task_success', 'pairs': len(seeds),
            'a_successes': sum(by[s, a]['success'] for s in seeds), 'b_successes': sum(by[s, b]['success'] for s in seeds),
            'a_only_success': ab, 'b_only_success': ba,
            'risk_difference_a_minus_b': (sum(by[s, a]['success'] for s in seeds)-sum(by[s, b]['success'] for s in seeds))/len(seeds) if seeds else None,
            'p': td.mcnemar_exact(ab, ba)}


def paired_count(rows, spec, a, b, key):
    by, seeds = pairs(rows, spec, a, b); d = [by[s, a][key]-by[s, b][key] for s in seeds]
    pos = sum(x > 0 for x in d); neg = sum(x < 0 for x in d)
    return {**{k: spec[k] for k in KEY}, 'a': a, 'b': b, 'outcome': key, 'pairs': len(seeds), 'a_greater': pos, 'b_greater': neg,
            'mean_difference_a_minus_b': sum(d)/len(d) if d else None, 'p': td.mcnemar_exact(pos, neg)}


def holm_apply(tests):
    for x, adj in zip(tests, td.holm([x['p'] for x in tests])): x['p_holm'] = adj
    return tests


def final(run=RUN):
    manifest, all_rows, checks = td.collect(run)
    if len(all_rows) != len(manifest['units']): raise RuntimeError('Final inference requires all assigned trials')
    excluded = [r for r in all_rows if r['infrastructure_excluded']]
    if len(excluded) > MAX_INFRA_EXCLUSIONS: raise RuntimeError('More infrastructure exclusions than registered')
    rows = [r for r in all_rows if not r['infrastructure_excluded']]
    primary = holm_apply([paired_success(rows, s, s['a'], s['b']) for s in manifest['primary']['tests']])
    key_sec = holm_apply([paired_success(rows, s, s['a'], s['b']) for s in manifest['key_secondary']['tests']])
    other = []   # belief vs the rule each error type does NOT defeat; and every level, both comparators
    for lv in manifest['noise_levels']:
        for c in manifest['conditions']:
            spec = dict(lv, condition=c)
            for b in ['revocable', 'reactive']:
                other.append(paired_success(rows, spec, 'belief', b))
                other.append(paired_count(rows, spec, 'belief', b, 'extra_repicks_of_satisfied_objects'))
    costs = [{**dict(lv, condition=c), 'a': 'belief', 'b': b, 'metric': m,
              'difference': td.bootstrap_diff([dict(r, noise_type=r['noise_type']) for r in rows if level(r) == (c, lv['noise_type'], lv['noise_rate'], lv['noise_correlation'])],
                                              c, lv['noise_type'], lv['noise_rate'], 'belief', b, m)}
             for lv in manifest['noise_levels'] for c in manifest['conditions'] for b in ['revocable', 'reactive']
             for m in ['primitive_dispatches', 'total_seconds']]
    table = describe(rows); best = []
    by = {(t['condition'], t['noise_type'], t['noise_rate'], t['noise_correlation'], t['rule']): t['successes'] for t in table}
    for lv in manifest['noise_levels']:
        for c in manifest['conditions']:
            k = (c, lv['noise_type'], lv['noise_rate'], lv['noise_correlation'])
            best.append(dict(zip(KEY, k)) | {'belief': by.get(k+('belief',)), 'revocable': by.get(k+('revocable',)), 'reactive': by.get(k+('reactive',)),
                        'belief_minus_best_other': by.get(k+('belief',), 0)-max(by.get(k+('revocable',), 0), by.get(k+('reactive',), 0))})
    result = {'analyzed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'trials': len(rows), 'assigned_trials': len(all_rows),
              'infrastructure_exclusions': [{k: r[k] for k in ['trial_id', 'condition', 'rule', 'noise_type', 'noise_rate', 'noise_correlation', 'termination_reason']} for r in excluded],
              'audit_all_passed': all(c['passed'] for c in checks), 'failed_checks': [c for c in checks if not c['passed']],
              'primary': primary, 'key_secondary': key_sec, 'other_contrasts_uncorrected': other, 'exploratory_costs': costs,
              'belief_vs_best_other_descriptive': best, 'cells': table,
              'interpretation_limits': 'Simulation only; synthetic watchdog errors (independent or Markov-persistent, s=0.8); belief assumes alpha=beta=0.10; flat 3-goal task; no equivalence margins.'}
    td.write(Path(run)/'inference.json', result); td.write_csv(Path(run)/'trials.csv', all_rows)
    print(json.dumps({'trials': len(rows), 'audit_all_passed': result['audit_all_passed'],
                      'primary': [{k: x[k] for k in ['condition', 'noise_type', 'b', 'a_successes', 'b_successes', 'p_holm']} for x in primary]}, ensure_ascii=False))
    return result


def checkpoint(run, segment, exec_dir=EXEC):
    manifest, rows, checks = td.collect(run)
    out = {'segment': segment, 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'sealed': len(rows), 'planned': len(manifest['units']),
           'audit_all_passed': all(c['passed'] for c in checks), 'failed_checks': [c for c in checks if not c['passed']],
           'infrastructure_exclusions': sum(r['infrastructure_excluded'] for r in rows), 'action_timeouts': sum(r['action_timeout'] for r in rows),
           'note': 'Administrative checkpoint: counts only, no inference; outcomes never affect continuation.'}
    td.write(Path(exec_dir)/segment/'checkpoint.json', out); td.write_csv(Path(exec_dir)/segment/'checkpoint_trials.csv', rows)
    print(json.dumps(out, ensure_ascii=False)); return out


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--checkpoint'); p.add_argument('--final', action='store_true'); p.add_argument('--run', default=str(RUN))
    a = p.parse_args()
    if a.checkpoint:
        if not checkpoint(Path(a.run), a.checkpoint)['audit_all_passed']: sys.exit(AUDIT_FAILED)
    elif a.final: final(Path(a.run))
    else: print(json.dumps(describe(td.collect(Path(a.run))[1]), ensure_ascii=False, indent=1))
