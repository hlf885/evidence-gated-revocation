"""Study E analysis. --checkpoint: counts + replay audit (exit 3 if the audit fails). --final: frozen inference."""
from pathlib import Path
import argparse, collections, datetime, json, statistics, sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import trial_e as te   # noqa: E402
import analyze_d as ad  # noqa: E402  (generic helpers: describe, paired_success, holm_apply)

RUN = te.RUN; EXEC = te.EXEC; MAX_INFRA_EXCLUSIONS = 3; AUDIT_FAILED = 3


def in_pool(r, pool): return any(all(r[k] == p[k] for k in p) for p in pool)


def per_seed(rows, rule, pool, outcome):
    tot = collections.Counter(); n = collections.Counter()
    for r in rows:
        if r['rule'] == rule and in_pool(r, pool):
            tot[r['seed']] += (r['success'] if outcome == 'independent_final_task_success' else r[outcome]); n[r['seed']] += 1
    return tot, n


def signflip_p(d):
    """Exact two-sided sign-flip permutation p-value for sum(d), integer differences (DP over the 2^n sign patterns)."""
    dist = {0: 1}
    for x in d:
        nxt = collections.Counter()
        for s, c in dist.items(): nxt[s+x] += c; nxt[s-x] += c
        dist = nxt
    obs = abs(sum(d)); return sum(c for s, c in dist.items() if abs(s) >= obs)/2**len(d)


def pooled_test(rows, spec):
    ta, na = per_seed(rows, spec['a'], spec['pool'], spec['outcome']); tb, nb = per_seed(rows, spec['b'], spec['pool'], spec['outcome'])
    seeds = sorted(s for s in na if na[s] == nb.get(s) == len(spec['pool']))   # complete seeds only (registered exclusions drop a seed)
    d = [ta[s]-tb[s] for s in seeds]; pos = sum(x > 0 for x in d); neg = sum(x < 0 for x in d)
    return {'id': spec['id'], 'a': spec['a'], 'b': spec['b'], 'outcome': spec['outcome'], 'expected': spec['expected'], 'seeds': len(seeds),
            'a_total': sum(ta[s] for s in seeds), 'b_total': sum(tb[s] for s in seeds), 'a_greater': pos, 'b_greater': neg, 'ties': len(d)-pos-neg,
            'mean_difference_per_seed': sum(d)/len(d) if d else None, 'p': signflip_p(d), 'p_sign_test_sensitivity': te.mcnemar_exact(pos, neg)}


def final(run=RUN):
    manifest, all_rows, checks = te.collect(run)
    if len(all_rows) != len(manifest['units']): raise RuntimeError('Final inference requires all assigned trials')
    excluded = [r for r in all_rows if r['infrastructure_excluded']]
    if len(excluded) > MAX_INFRA_EXCLUSIONS: raise RuntimeError('More infrastructure exclusions than registered')
    rows = [r for r in all_rows if not r['infrastructure_excluded']]
    primary = ad.holm_apply([pooled_test(rows, s) for s in manifest['primary']['tests']])
    debounce = []   # descriptive: debounce2 vs belief_a10 in every cell
    for spec in manifest['cells']:
        if True:
            debounce.append(ad.paired_success(rows, spec, 'belief_a10', 'debounce2'))
            debounce.append(ad.paired_count(rows, spec, 'belief_a10', 'debounce2', 'false_revocations'))
    cells = ad.describe(rows)
    fr = collections.defaultdict(list)
    for r in rows: fr[(r['condition'], r['noise_type'], r['noise_correlation'], r['rule'])].append(r['false_revocations'])
    for t in cells: t['mean_false_revocations'] = statistics.mean(fr[(t['condition'], t['noise_type'], t['noise_correlation'], t['rule'])])
    result = {'analyzed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'trials': len(rows), 'assigned_trials': len(all_rows),
              'infrastructure_exclusions': [r['trial_id'] for r in excluded], 'audit_all_passed': all(c['passed'] for c in checks),
              'failed_checks': [c for c in checks if not c['passed']], 'primary': primary, 'belief_a10_vs_debounce2_descriptive': debounce, 'cells': cells,
              'interpretation_limits': 'Simulation only; synthetic errors at r = 0.20 (independent or Markov-persistent, s = 0.8); 20 seeds; flat 3-goal task.'}
    te.write(Path(run)/'inference.json', result); te.write_csv(Path(run)/'trials.csv', all_rows)
    print(json.dumps({'trials': len(rows), 'audit_all_passed': result['audit_all_passed'],
                      'primary': [{k: x[k] for k in ['id', 'a_total', 'b_total', 'a_greater', 'b_greater', 'p_holm']} for x in primary]}))
    return result


def checkpoint(run, segment, exec_dir=EXEC):
    manifest, rows, checks = te.collect(run)
    out = {'segment': segment, 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'sealed': len(rows), 'planned': len(manifest['units']),
           'audit_all_passed': all(c['passed'] for c in checks), 'failed_checks': [c for c in checks if not c['passed']],
           'infrastructure_exclusions': sum(r['infrastructure_excluded'] for r in rows), 'action_timeouts': sum(r['action_timeout'] for r in rows),
           'note': 'Administrative checkpoint: counts only, no inference; outcomes never affect continuation.'}
    te.write(Path(exec_dir)/segment/'checkpoint.json', out); te.write_csv(Path(exec_dir)/segment/'checkpoint_trials.csv', rows)
    print(json.dumps(out)); return out


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--checkpoint'); p.add_argument('--final', action='store_true'); p.add_argument('--run', default=str(RUN))
    a = p.parse_args()
    if a.checkpoint:
        if not checkpoint(Path(a.run), a.checkpoint)['audit_all_passed']: sys.exit(AUDIT_FAILED)
    elif a.final: final(Path(a.run))
    else: print(json.dumps(ad.describe(te.collect(Path(a.run))[1]), indent=1))
