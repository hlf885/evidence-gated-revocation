"""Summarize the Study D PREDICTION replicates (model simulation, NOT data) into comparison tables."""
from pathlib import Path
import collections, csv, json, statistics, sys
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE.parent.parent/'v10_studyC'))
import analyze_d, design_d, trial_d   # noqa: E402

BOOL = ['success', 'false_completion_report', 'budget_stop', 'infrastructure_error', 'infrastructure_excluded', 'action_timeout']
INT = ['seed', 'observation_flips', 'extra_repicks_of_satisfied_objects', 'repair_repicks', 'primitive_dispatches', 'recoveries', 'action_attempts',
       'fault_requested', 'fault_deferrals', 'workspace_cancellations', 'belief_reobservations']


def load(f):
    rows = list(csv.DictReader(open(f, encoding='utf-8-sig')))
    for r in rows:
        for k in BOOL: r[k] = r[k] == 'True'
        for k in INT: r[k] = int(r[k])
        for k in ['noise_rate', 'total_seconds']: r[k] = float(r[k])
    return rows


def q(v, p): v = sorted(v); x = (len(v)-1)*p; i = int(x); return v[i]+(v[min(i+1, len(v)-1)]-v[i])*(x-i)


def main():
    m = design_d.make_manifest(); files = sorted((HERE/'replicates').glob('predicted_trials_rep*.csv'))
    succ = collections.defaultdict(list); xr = collections.defaultdict(list); prim = collections.defaultdict(list); sec = collections.defaultdict(list)
    for f in files:
        rows = load(f)
        for t in analyze_d.describe(rows):
            k = (t['condition'], t['noise_type'], t['noise_rate'], t['noise_correlation'], t['rule']); succ[k].append(t['successes']); xr[k].append(t['mean_extra_repicks'])
        for fam, store in [(m['primary']['tests'], prim), (m['key_secondary']['tests'], sec)]:
            res = analyze_d.holm_apply([analyze_d.paired_success(rows, s, s['a'], s['b']) for s in fam])
            for x in res: store[(x['condition'], x['noise_type'], x['noise_rate'], x['noise_correlation'], x['b'])].append((x['p_holm'] < .05, x['a_successes']-x['b_successes']))
    table = [{'condition': k[0], 'noise_type': k[1], 'noise_rate': k[2], 'noise_correlation': k[3], 'rule': k[4],
              'pred_success_mean': round(statistics.mean(v), 2), 'pred_success_95lo': q(v, .025), 'pred_success_95hi': q(v, .975),
              'pred_extra_repicks_mean': round(statistics.mean(xr[k]), 3), 'real_successes': '', 'inside_95': ''} for k, v in sorted(succ.items(), key=str)]
    trial_d.write_csv(HERE/'predicted_success_D.csv', table)
    tests = lambda store, fam: [{'contrast': f'belief - {k[4]}', 'condition': k[0], 'noise_type': k[1], 'noise_rate': k[2], 'noise_correlation': k[3],
                                 'pred_success_diff_mean': round(statistics.mean(d for _, d in v), 2), 'pred_diff_95': [q([d for _, d in v], .025), q([d for _, d in v], .975)],
                                 'pred_power_holm': round(sum(s for s, _ in v)/len(v), 3), 'family': fam} for k, v in store.items()]
    out = {'type': 'PREDICTION (model simulation), NOT data', 'replicates': len(files), 'world': 'v10 prediction v3 stochastic world; no contact coupling (cascades not modelled)',
           'primary': tests(prim, 'primary (Holm 4)'), 'key_secondary': tests(sec, 'key secondary (Holm 12)')}
    (HERE/'predicted_tests_D.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    for x in out['primary']+out['key_secondary']: print(x['family'][:9], x['condition'][:9], x['noise_type'][:8], x['noise_rate'], x['noise_correlation'][:4], x['contrast'], x['pred_success_diff_mean'], x['pred_diff_95'], 'power', x['pred_power_holm'])
    for t in table:
        if t['noise_type'] != 'none': print(t['condition'][:9], t['noise_type'][:8], t['noise_rate'], t['noise_correlation'][:4], t['rule'][:6], t['pred_success_mean'], (t['pred_success_95lo'], t['pred_success_95hi']))


if __name__ == '__main__':
    main()
