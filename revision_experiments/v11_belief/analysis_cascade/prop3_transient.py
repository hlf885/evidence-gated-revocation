"""Post-hoc check of Proposition 3 with the post-placement transient (2026-11-01).
For every exposure (a refresh at which a goal is in the controller's record and satisfied by the independent score),
n* is computed from a 'clean' belief: b_commit after an accepted placement, then one CONSISTENT update per refresh
while the goal stays in the record (no injected report is used). The predicted number of false revocations is the sum
over exposures of r^n* (independent errors) or p0*s^(n*-1) (persistent errors). Nothing is fitted to trial outcomes.
Reads sealed trials only; writes prop3_transient.json next to this file.
"""
from pathlib import Path
import collections, json, sys
HERE = Path(__file__).resolve().parent; V11 = HERE.parent; V10 = V11.parent/'v10_studyC'
sys.path.insert(0, str(V11))
from belief_rules import belief_step, BELIEF_PARAMS   # noqa: E402
RUNS = {'C': V10/'results/formal_02', 'D': V11/'results/formal_D', 'E': V11/'results/formal_E'}
VAR = {'belief': {}, 'belief_a10': {}, 'belief_a02': {'alpha': .02, 'beta': .02}, 'belief_a30': {'alpha': .30, 'beta': .30}}
S = 0.8


def P(rule): return dict(BELIEF_PARAMS, **VAR[rule])


def nstar_from(rule, b):
    if rule in ('revocable', 'reactive'): return 1
    if rule == 'debounce2': return 2
    p = P(rule); n = 0
    while b >= p['tau'] and n < 50:
        b = belief_step(b, 'INVALID', p['alpha'], p['beta'], p['hazard']); n += 1
    return n


def steady(rule):
    p = P(rule); b = p['b_commit']
    for _ in range(500): b = belief_step(b, 'CONSISTENT', p['alpha'], p['beta'], p['hazard'])
    return b


def q(n, r, corr):
    if corr == 'independent': return r**n
    p0 = r*(1-S)/(1-r); return p0*S**(n-1)


def trial(folder, rule):
    ev = [json.loads(l) for l in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    belief = rule in VAR; p = P(rule) if belief else None
    clean = {}; last_pair = None; out = collections.Counter(); hist = collections.Counter()
    for e in ev:
        k = e['event']
        if k == 'paired_observation': last_pair = e
        elif k == 'completion_committed':
            if belief: clean[e['goal_id']] = p['b_commit']
        elif k == 'memory_refresh':
            before = set(e['before']); after = set(e['retained'])
            if last_pair is not None:
                sat = {g['goalId']: g['satisfied'] for g in last_pair['score']['goals']}
                for g in before:
                    if sat.get(g):
                        b = clean.get(g, P(rule)['tau'] if belief else None)
                        n = nstar_from(rule, b) if belief else nstar_from(rule, None)
                        out['exposures'] += 1; hist[n] += 1
                for g in e['invalidated']:
                    if sat.get(g): out['fr'] += 1
            if belief:
                for g in list(clean):
                    if g in after: clean[g] = belief_step(clean[g], 'CONSISTENT', p['alpha'], p['beta'], p['hazard'])
                    else: clean.pop(g)
                for g in after - before - set(clean):
                    clean[g] = P(rule)['tau']   # re-entry by observation: belief just above tau
    return out, hist


def main():
    agg = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
    for study, run in RUNS.items():
        m = json.loads((run/'manifest.json').read_text(encoding='utf-8'))
        for u in m['units']:
            if u['noise_type'] != 'false_invalid' or u['rule'] == 'commit_only': continue
            corr = u.get('noise_correlation', 'independent')
            o, h = trial(run/u['trial_id'], u['rule'])
            a = agg[(study, u['rule'], u['noise_rate'], corr)]; a[0].update(o); a[1].update(h)
    rows = []
    for (study, rule, r, corr), (o, h) in sorted(agg.items(), key=str):
        ns = nstar_from(rule, steady(rule)) if rule in VAR else nstar_from(rule, None)
        pt = sum(c*q(n, r, corr) for n, c in h.items()); ps = o['exposures']*q(ns, r, corr)
        rows.append({'study': study, 'rule': rule, 'rate': r, 'corr': corr, 'exposures': o['exposures'], 'fr': o['fr'],
                     'obs_rate': round(o['fr']/o['exposures'], 4), 'n_steady': ns, 'pred_steady': round(ps/o['exposures'], 4),
                     'pred_transient': round(pt/o['exposures'], 4), 'nstar_hist': dict(sorted(h.items()))})
    (HERE/'prop3_transient.json').write_text(json.dumps(rows, indent=1), encoding='utf-8')
    for x in rows: print(x)


if __name__ == '__main__': main()
