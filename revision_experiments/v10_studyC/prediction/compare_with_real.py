"""Study C prediction (v3, after amendment A1): compare the observed Study C results with the registered prediction, metric by metric.

Usage (after the formal run):  python compare_with_real.py
Reads ../results/formal_02 (observed) and predicted_metrics_v3.csv (prediction).
Writes prediction_vs_observed_v3.csv and prediction_vs_observed_v3.md.
"""
from pathlib import Path
import csv, json, sys
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import analyze, summarize  # noqa: E402

REAL = HERE.parent/'results/formal_02'
INV = {v: k for k, v in summarize.LABEL.items()}


def main(real=REAL, here=HERE):
    reg_file = here/'prediction_registration.json'
    registered = json.loads(reg_file.read_text(encoding='utf-8'))['registered_utc'] if reg_file.exists() else 'not available'
    manifest, rows, checks = analyze.collect(real)
    rows = [r for r in rows if not r['infrastructure_excluded']]   # registered exclusions are not compared
    cells = analyze.cells(rows); fns = {n: fn for n, _, fn in summarize.METRICS}
    out = []
    for p in csv.DictReader(open(here/'predicted_metrics_v3.csv', encoding='utf-8-sig')):
        k = (INV[p['condition']], INV[p['error_type']], float(p['error_rate']), p['rule']); rs = cells.get(k)
        if not rs: continue
        v = fns[p['metric']](rs); lo, hi = float(p['predicted_95_lo']), float(p['predicted_95_hi'])
        p['observed'] = round(v, 3); p['inside_95'] = 'yes' if lo-1e-9 <= v <= hi+1e-9 else ('above' if v > hi else 'below')
        p['observed_minus_predicted_mean'] = round(v-float(p['predicted_mean']), 3); out.append(p)
    analyze.write_csv(here/'prediction_vs_observed_v3.csv', out)
    succ = [o for o in out if o['metric'] == 'success_count']; miss = [o for o in succ if o['inside_95'] != 'yes']
    allmiss = [o for o in out if o['inside_95'] != 'yes']
    lines = ['# Prediction versus observation (Study C, v3)', '', f'Prediction registered: {registered}',
             f'Observed trials: {len(rows)}; compared metrics: {len(out)}; outside the 95% prediction interval: {len(allmiss)}', '',
             f'## Success counts: {len(miss)} of {len(succ)} cells outside the interval', '']
    lines += [f"- {o['condition']} / {o['error_type']} {o['error_rate']} / {o['rule']}: observed {o['observed']}, predicted {o['predicted_mean']} "
              f"(95% {o['predicted_95_lo']}-{o['predicted_95_hi']}), {o['inside_95']}" for o in miss] or ['- all inside the interval']
    lines += ['', 'A value outside its interval indicates that the simulator differs from the prediction model; it is not used to change data or tests.']
    (here/'prediction_vs_observed_v3.md').write_text('\n'.join(lines)+'\n', encoding='utf-8'); print('\n'.join(lines))


if __name__ == '__main__':
    main()
