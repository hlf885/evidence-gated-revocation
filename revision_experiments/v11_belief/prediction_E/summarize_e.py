"""Summarize Study E PREDICTION replicates (model simulation, NOT data): cell means/intervals and power of H1-H3."""
from pathlib import Path
import collections, csv, json, statistics, sys
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE.parent.parent/'v10_studyC'))
sys.path.insert(0, str(HERE.parent/'prediction_D'))
import analyze_e, design_e, trial_e   # noqa: E402
import summarize_d                   # noqa: E402

def load(f):
    rows = summarize_d.load(f)
    for r in rows: r['false_revocations'] = int(r['false_revocations'])
    return rows

def q(v, p): return summarize_d.q(v, p)

def main():
    m = design_e.make_manifest(); files = sorted((HERE/'replicates').glob('predicted_trials_rep*.csv'))
    succ = collections.defaultdict(list); frs = collections.defaultdict(list); tests = collections.defaultdict(list)
    for f in files:
        rows = load(f)
        for t in analyze_e.ad.describe(rows):
            k = (t['condition'], t['noise_type'], t['noise_correlation'], t['rule']); succ[k].append(t['successes'])
        cnt = collections.defaultdict(list)
        for r in rows: cnt[(r['condition'], r['noise_type'], r['noise_correlation'], r['rule'])].append(r['false_revocations'])
        for k, v in cnt.items(): frs[k].append(statistics.mean(v))
        for x in analyze_e.ad.holm_apply([analyze_e.pooled_test(rows, s) for s in m['primary']['tests']]):
            tests[x['id']].append((x['p_holm'] < .05, x['a_total']-x['b_total'], x['a_greater'], x['b_greater']))
    table = [{'condition': k[0], 'noise_type': k[1], 'noise_rate': 0.2, 'noise_correlation': k[2], 'rule': k[3],
              'pred_success_mean': round(statistics.mean(v), 2), 'pred_success_95lo': q(v, .025), 'pred_success_95hi': q(v, .975),
              'pred_false_revocations_mean': round(statistics.mean(frs[k]), 3), 'real_successes': '', 'inside_95': ''} for k, v in sorted(succ.items(), key=str)]
    trial_e.write_csv(HERE/'predicted_success_E.csv', table)
    out = {'type': 'PREDICTION (model simulation), NOT data', 'replicates': len(files),
           'primary': [{'id': k, 'pred_power_holm': round(sum(s for s, *_ in v)/len(v), 3), 'pred_total_diff_mean': round(statistics.mean(d for _, d, *_ in v), 2),
                        'pred_total_diff_95': [q([d for _, d, *_ in v], .025), q([d for _, d, *_ in v], .975)]} for k, v in sorted(tests.items())]}
    (HERE/'predicted_tests_E.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(out['primary']))
    for t in table: print(t['condition'][:9], t['noise_type'][:8], t['noise_correlation'][:4], t['rule'], t['pred_success_mean'], (t['pred_success_95lo'], t['pred_success_95hi']), 'FR', t['pred_false_revocations_mean'])

if __name__ == '__main__':
    main()
