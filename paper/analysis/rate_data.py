"""Exposures and false revocations per (study, rule, error level), with Proposition 3 predictions. Writes rate_data.json."""
import collections, json
from common import RUNS, OUT
import cascade_analysis as ca
import prop3_transient as pt   # post-placement transient
S = 0.8
NSTAR = {'revocable': 1, 'reactive': 1, 'belief_a10': 2, 'belief': 2, 'debounce2': 2, 'belief_a02': 2, 'belief_a30': 5}


def predict(rule, r, corr):
    n = NSTAR[rule]; p0 = r*(1-S)/(1-r)
    return r**n if corr == 'independent' else p0*S**(n-1)


def main():
    out = []
    for study, run in RUNS.items():
        m = json.loads((run/'manifest.json').read_text(encoding='utf-8')); scen = {s['scenario_id']: s for s in m['scenarios']}
        agg = collections.defaultdict(collections.Counter)
        for u in m['units']:
            if u['noise_type'] != 'false_invalid' or u['rule'] == 'commit_only': continue
            c = ca.analyse_trial(run/u['trial_id'], scen[u['scenario_id']])
            k = (u['rule'], u['noise_rate'], u.get('noise_correlation', 'independent'))
            agg[k]['exposures'] += c['exposures']; agg[k]['fr'] += c['false_revocations']; agg[k]['trials'] += 1
            o, h = pt.trial(run/u['trial_id'], u['rule']); assert o['exposures'] == c['exposures']
            for n, cnt in h.items(): agg[k]['pt'] += cnt*pt.q(n, u['noise_rate'], u.get('noise_correlation', 'independent'))
        for (rule, r, corr), v in sorted(agg.items()):
            rule = 'belief_a10' if rule == 'belief' else rule
            out.append({'study': study, 'rule': rule, 'rate': r, 'correlation': corr, 'trials': v['trials'], 'exposures': v['exposures'],
                        'false_revocations': v['fr'], 'observed': v['fr']/v['exposures'], 'predicted': v['pt']/v['exposures'], 'predicted_steady': predict(rule, r, corr), 'n_star': NSTAR[rule]})
    (OUT/'analysis/rate_data.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    for o in out: print(o['study'], o['rule'], o['rate'], o['correlation'][:4], o['exposures'], o['false_revocations'], round(o['observed'], 4), round(o['predicted'], 4))


if __name__ == '__main__':
    main()
