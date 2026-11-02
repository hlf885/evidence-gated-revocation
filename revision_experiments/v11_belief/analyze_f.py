"""Study F analysis. --checkpoint: counts + replay audit (exit 3 if the audit fails). --final: frozen inference.
Uses the frozen Study E trial audit (trial_e.py) and test helpers (analyze_e.py, analyze_d.py) unchanged."""
from pathlib import Path
import argparse, collections, datetime, json, statistics, sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import trial_e as te    # noqa: E402
import analyze_d as ad  # noqa: E402
import analyze_e as ae  # noqa: E402  (pooled_test, signflip_p)

RUN = HERE/'results/formal_F'; EXEC = HERE/'execution/formal_F'; MAX_INFRA_EXCLUSIONS = 3; AUDIT_FAILED = 3
OTHER = ['revocable', 'reactive', 'belief_a10']


def final(run=RUN):
    manifest, all_rows, checks = te.collect(run)
    if len(all_rows) != len(manifest['units']): raise RuntimeError('Final inference requires all assigned trials')
    excluded = [r for r in all_rows if r['infrastructure_excluded']]
    if len(excluded) > MAX_INFRA_EXCLUSIONS: raise RuntimeError('More infrastructure exclusions than registered')
    rows = [r for r in all_rows if not r['infrastructure_excluded']]
    primary = ad.holm_apply([ae.pooled_test(rows, s) for s in manifest['primary']['tests']])
    secondary = ad.holm_apply([ae.pooled_test(rows, s) for s in manifest['secondary']['tests']])
    per_cell = []   # descriptive: egr vs each other rule in every cell (exact McNemar, unadjusted)
    for spec in manifest['cells']:
        for b in OTHER: per_cell.append(ad.paired_success(rows, spec, 'debounce2', b))
    cells = ad.describe(rows); agg = collections.defaultdict(list)
    for r in rows: agg[(r['condition'], r['noise_type'], r['noise_correlation'], r['rule'])].append(r)
    for t in cells:
        rs = agg[(t['condition'], t['noise_type'], t['noise_correlation'], t['rule'])]
        t['mean_false_revocations'] = statistics.mean(r['false_revocations'] for r in rs) if rs else None
        t['false_completion_reports'] = sum(r['false_completion_report'] for r in rs)
        t['mean_seconds'] = statistics.mean(r['total_seconds'] for r in rs) if rs else None
    result = {'analyzed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'trials': len(rows), 'assigned_trials': len(all_rows),
              'infrastructure_exclusions': [r['trial_id'] for r in excluded], 'audit_all_passed': all(c['passed'] for c in checks),
              'failed_checks': [c for c in checks if not c['passed']], 'primary': primary, 'secondary': secondary,
              'egr_vs_each_rule_per_cell_descriptive': per_cell, 'cells': cells,
              'interpretation_limits': 'Simulation only; synthetic errors at r = 0.20 (independent or Markov-persistent, s = 0.8); 20 seeds; flat 3-goal task.'}
    te.write(Path(run)/'inference.json', result); te.write_csv(Path(run)/'trials.csv', all_rows)
    print(json.dumps({'trials': len(rows), 'audit_all_passed': result['audit_all_passed'],
                      'primary': [{k: x[k] for k in ['id', 'a_total', 'b_total', 'a_greater', 'b_greater', 'p_holm']} for x in primary],
                      'secondary': [{k: x[k] for k in ['id', 'a_total', 'b_total', 'a_greater', 'b_greater', 'p_holm']} for x in secondary]}))
    return result


def checkpoint(run, segment, exec_dir=EXEC):
    return ae.checkpoint(run, segment, exec_dir=exec_dir)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--checkpoint'); p.add_argument('--final', action='store_true'); p.add_argument('--run', default=str(RUN))
    a = p.parse_args()
    if a.checkpoint:
        if not checkpoint(Path(a.run), a.checkpoint)['audit_all_passed']: sys.exit(AUDIT_FAILED)
    elif a.final: final(Path(a.run))
    else: print(json.dumps(ad.describe(te.collect(Path(a.run))[1]), indent=1))
