"""Study C prediction (v3, after amendment A1): summarise the predicted replicates into comparison tables.
The outputs are model predictions, not experimental data."""
from pathlib import Path
import argparse, collections, csv, json, statistics, sys
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent))
import analyze, design  # noqa: E402

RULES = ['commit_only', 'revocable', 'reactive']
METRICS = [('success_count', 'count/20', lambda rs: sum(r['success'] for r in rs)),
           ('success_rate', '%', lambda rs: 100*sum(r['success'] for r in rs)/len(rs)),
           ('false_completion_count', 'count/20', lambda rs: sum(r['false_completion_report'] for r in rs)),
           ('budget_stop_count', 'count/20', lambda rs: sum(r['budget_stop'] for r in rs)),
           ('mean_progress', 'fraction', lambda rs: statistics.mean(r['progress'] for r in rs)),
           ('mean_extra_repicks_of_satisfied_objects', 'per trial', lambda rs: statistics.mean(r['extra_repicks_of_satisfied_objects'] for r in rs)),
           ('mean_repair_repicks', 'per trial', lambda rs: statistics.mean(r['repair_repicks'] for r in rs)),
           ('mean_primitive_dispatches', 'per trial', lambda rs: statistics.mean(r['primitive_dispatches'] for r in rs)),
           ('mean_total_seconds', 's per trial', lambda rs: statistics.mean(r['total_seconds'] for r in rs)),
           ('mean_observation_flips', 'per trial', lambda rs: statistics.mean(r['observation_flips'] for r in rs)),
           ('fault_deferral_trials', 'count/20', lambda rs: sum(r['fault_deferrals'] > 0 for r in rs)),
           ('action_timeout_count', 'count/20', lambda rs: sum(r['action_timeout'] for r in rs))]
LABEL = {'no_fault': 'no disturbance', 'completed_shift': 'completed-object displacement', 'none': 'no errors', 'false_invalid': 'false-invalid', 'false_consistent': 'false-consistent'}


def load(path):
    rows = list(csv.DictReader(open(path, encoding='utf-8-sig')))
    for r in rows:
        for k in ['success', 'false_completion_report', 'budget_stop', 'infrastructure_error', 'infrastructure_excluded', 'action_timeout']: r[k] = r[k] == 'True'
        for k in ['noise_rate', 'total_seconds', 'progress']: r[k] = float(r[k])
        for k in ['seed', 'observation_flips', 'extra_repicks_of_satisfied_objects', 'repair_repicks', 'primitive_dispatches', 'recoveries', 'action_attempts',
                  'fault_requested', 'fault_deferrals', 'workspace_cancellations']: r[k] = int(r[k])
    return rows


def q(v, p):
    v = sorted(v); x = (len(v)-1)*p; i = int(x); return v[i]+(v[min(i+1, len(v)-1)]-v[i])*(x-i)


def sign_test(rows, cond, t, rate, a, b, key):
    by = {(r['seed'], r['rule']): r for r in rows if r['condition'] == cond and r['noise_type'] == t and r['noise_rate'] == rate}
    seeds = {s for s, _ in by}
    pos = sum(by[s, a][key] > by[s, b][key] for s in seeds); neg = sum(by[s, a][key] < by[s, b][key] for s in seeds)
    return analyze.mcnemar_exact(pos, neg), statistics.mean(by[s, a][key]-by[s, b][key] for s in seeds)


def main(src, out):
    files = sorted(Path(src).glob('predicted_trials_rep*.csv')); m = design.make_manifest()
    vals = collections.defaultdict(list); contrasts = collections.defaultdict(list); totals = []
    for f in files:
        rows = load(f); totals.append((sum(r['success'] for r in rows), f.name))
        for k, rs in analyze.cells(rows).items():
            for name, unit, fn in METRICS: vals[(k, name)].append(fn(rs))
        prim = []   # exactly the frozen primary family (analyze.final), Holm within 4
        for spec in m['primary']['tests']:
            if spec['outcome'] == 'independent_final_task_success':
                x = analyze.paired(rows, spec['condition'], spec['noise_type'], .10, 'revocable', 'reactive')
                prim.append((('primary: success', spec['noise_type'], spec['condition'], '10%'), x['p_exact_mcnemar'], 100*x['risk_difference_a_minus_b']))
            else:
                x = analyze.paired_count(rows, spec['condition'], spec['noise_type'], .10, 'revocable', 'reactive', spec['outcome'])
                prim.append((('primary: extra re-grasps', spec['noise_type'], spec['condition'], '10%'), x['p_exact_sign_test'], x['mean_difference_a_minus_b']))
        for (key, _, d), adj in zip(prim, analyze.holm([p for _, p, _ in prim])): contrasts[key].append((adj < .05, d))
        for c in m['conditions']:
            x = analyze.paired(rows, c, 'false_invalid', .10, 'revocable', 'reactive')
            contrasts[('secondary: success, false-invalid', 'false_invalid', c, '10%')].append((x['p_exact_mcnemar'] < .05, 100*x['risk_difference_a_minus_b']))
        for c in m['conditions']:
            x = analyze.paired(rows, c, 'none', 0.0, 'revocable', 'commit_only'); contrasts[('success: revocable - commit_only, no errors', 'none', c, '0')].append((x['p_exact_mcnemar'] < .05, 100*x['risk_difference_a_minus_b']))
            x = analyze.paired(rows, c, 'none', 0.0, 'revocable', 'reactive'); contrasts[('success: revocable - reactive, no errors', 'none', c, '0')].append((x['p_exact_mcnemar'] < .05, 100*x['risk_difference_a_minus_b']))
    long = []
    for (k, name), v in sorted(vals.items(), key=lambda x: (x[0][0], [n for n, *_ in METRICS].index(x[0][1]))):
        unit = next(u for n, u, _ in METRICS if n == name)
        long.append({'condition': LABEL[k[0]], 'error_type': LABEL[k[1]], 'error_rate': k[2], 'rule': k[3], 'metric': name, 'unit': unit,
                     'predicted_mean': round(statistics.mean(v), 3), 'predicted_80_lo': round(q(v, .10), 3), 'predicted_80_hi': round(q(v, .90), 3),
                     'predicted_95_lo': round(q(v, .025), 3), 'predicted_95_hi': round(q(v, .975), 3), 'observed': '', 'inside_95': ''})
    analyze.write_csv(Path(out)/'predicted_metrics_v3.csv', long)
    wide = []
    for c in m['conditions']:
        for nl in m['noise_levels']:
            row = {'condition': LABEL[c], 'errors': LABEL[nl['noise_type']]+('' if nl['noise_type'] == 'none' else f" {int(nl['noise_rate']*100)}%")}
            for rule in RULES:
                v = vals[((c, nl['noise_type'], nl['noise_rate'], rule), 'success_count')]
                row[rule+' predicted successes (mean)'] = round(statistics.mean(v), 1); row[rule+' 95% interval'] = f'{q(v,.025):.0f}-{q(v,.975):.0f}'
                row[rule+' predicted success %'] = round(5*statistics.mean(v), 1)
            wide.append(row)
    analyze.write_csv(Path(out)/'predicted_success_rates_v3.csv', wide)
    cs = [{'contrast': k[0], 'errors': LABEL[k[1]], 'condition': LABEL[k[2]], 'error_rate': k[3],
           'predicted_difference_mean': round(statistics.mean(d for _, d in v), 2), 'predicted_difference_95': [round(q([d for _, d in v], .025), 2), round(q([d for _, d in v], .975), 2)],
           'predicted_power': round(sum(s for s, _ in v)/len(v), 3),
           'unit': 'percentage points (revocable minus comparison rule)' if 'success' in k[0] else 'per trial (revocable minus reactive)',
           'power_definition': 'share of replicates with Holm-adjusted p<0.05' if k[0].startswith('primary') else 'share of replicates with unadjusted p<0.05'} for k, v in contrasts.items()]
    totals.sort(); median_file = totals[len(totals)//2][1]
    summary = {'version': 'v3 (after amendment A1)', 'note': 'Model prediction, not experimental data. Intervals reflect physical randomness, parameter uncertainty and error-injection uncertainty.',
               'replicates': len(files), 'predicted_total_successes_840_trials': {'mean': round(statistics.mean(t for t, _ in totals), 1), '95_interval': [q([t for t, _ in totals], .025), q([t for t, _ in totals], .975)]},
               'median_replicate': median_file, 'contrasts': cs}
    Path(out, 'predicted_tests_v3.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary, wide


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--src', required=True); p.add_argument('--out', default=str(HERE)); a = p.parse_args()
    s, w = main(a.src, a.out)
    print(json.dumps({k: v for k, v in s.items() if k != 'contrasts'}, ensure_ascii=False))
    for c in s['contrasts']: print(c['contrast'], c['errors'], c['condition'], c['predicted_difference_mean'], c['predicted_difference_95'], 'power', c['predicted_power'])
    for r in w: print(r)
