"""VLM calibration, step 3: error structure of the VLM goal check against the independent score.
alpha_contra = P(report is not CONSISTENT | goal satisfied)  (what evidence-gated revocation counts as a contradiction)
alpha_invalid = P(INVALID | satisfied), alpha_unknown = P(UNKNOWN | satisfied), beta = P(CONSISTENT | not satisfied)
s = P(error at frame k+1 | error at frame k), same goal, same view, same ground truth (persistence across refreshes)
cross-view: P(error in side view | error in main view), same frame and goal; repeat: P(error on a repeated query | error on the first).
Proposition 3 with the measured (r, s): per-exposure false-revocation probability for n* = 1..4 (same view), and for n* = 2 when the
second report comes from the other view. Writes vlm_error_structure.json."""
from pathlib import Path
import collections, json
HERE = Path(__file__).resolve().parent


def load():
    frames = {(r['trial_id'], r['k']): r for r in map(json.loads, (HERE/'frames/frames.jsonl').read_text(encoding='utf-8').splitlines()) if r.get('score')}
    ans = collections.defaultdict(dict)
    for x in map(json.loads, (HERE/'answers.jsonl').read_text(encoding='utf-8').splitlines()):
        if not x['raw'].startswith('ERROR'): ans[(x['trial_id'], x['k'], x['view'], x['goal'])][x['rep']] = x['state']
    return frames, ans


def truth(fr, g):
    sat = {x['goalId']: x['satisfied'] for x in fr['score']['goals']}[g]
    held = (fr.get('holding') or {}).get('objectId') == {'g1': 'red_cube', 'g2': 'green_ball', 'g3': 'yellow_cylinder'}[g]
    return sat, held


def err(state, sat): return state != 'CONSISTENT' if sat else state == 'CONSISTENT'


def ratio(a, b): return round(a/b, 4) if b else None


def structure(frames, ans, exclude_held):
    out = {}
    for view in ['main', 'side']:
        c = collections.Counter(); seq = collections.defaultdict(list)
        for (t, k, v, g), reps in ans.items():
            if v != view or 0 not in reps: continue
            sat, held = truth(frames[(t, k)], g)
            if exclude_held and held: continue
            s0 = reps[0]; c['sat' if sat else 'unsat'] += 1
            if sat: c['sat_I'] += s0 == 'INVALID'; c['sat_U'] += s0 == 'UNKNOWN'
            else: c['unsat_C'] += s0 == 'CONSISTENT'
            seq[(t, g)].append((k, sat, err(s0, sat)))
        pc = collections.Counter()
        for key, xs in seq.items():
            xs.sort()
            for (k1, s1, e1), (k2, s2, e2) in zip(xs, xs[1:]):
                if k2 == k1+1 and s1 == s2:
                    lab = 'sat' if s1 else 'unsat'; pc[lab+'_pairs'] += 1; pc[lab+'_e1'] += e1; pc[lab+'_e1e2'] += e1 and e2
        out[view] = {'satisfied_samples': c['sat'], 'unsatisfied_samples': c['unsat'],
                     'alpha_invalid': ratio(c['sat_I'], c['sat']), 'alpha_unknown': ratio(c['sat_U'], c['sat']),
                     'alpha_contra': ratio(c['sat_I']+c['sat_U'], c['sat']), 'beta': ratio(c['unsat_C'], c['unsat']),
                     's_satisfied': ratio(pc['sat_e1e2'], pc['sat_e1']), 's_unsatisfied': ratio(pc['unsat_e1e2'], pc['unsat_e1']),
                     'consecutive_pairs': {'satisfied': pc['sat_pairs'], 'unsatisfied': pc['unsat_pairs']}}
    cv = collections.Counter(); rp = collections.Counter()
    for (t, k, v, g), reps in ans.items():
        sat, held = truth(frames[(t, k)], g)
        if exclude_held and held or 0 not in reps: continue
        if v == 'main' and 0 in ans.get((t, k, 'side', g), {}):
            em = err(reps[0], sat); es = err(ans[(t, k, 'side', g)][0], sat); lab = 'sat' if sat else 'unsat'
            cv[lab+'_n'] += 1; cv[lab+'_em'] += em; cv[lab+'_es'] += es; cv[lab+'_both'] += em and es
        e0 = err(reps[0], sat)
        for j in (1, 2, 3):
            if j in reps: rp['n'] += 1; rp['e0'] += e0; rp['both'] += e0 and err(reps[j], sat); rp['agree'] += reps[j] == reps[0]
    out['cross_view'] = {lab: {'P_err_main': ratio(cv[lab+'_em'], cv[lab+'_n']), 'P_err_side': ratio(cv[lab+'_es'], cv[lab+'_n']),
                               'P_err_side_given_main': ratio(cv[lab+'_both'], cv[lab+'_em'])} for lab in ['sat', 'unsat']}
    out['repeat_queries'] = {'pairs': rp['n'], 'agreement': ratio(rp['agree'], rp['n']), 'P_err_repeat_given_err_first': ratio(rp['both'], rp['e0'])}
    m = out['main']; r = m['alpha_contra']; s = m['s_satisfied']
    if r and s is not None and r < 1:
        p0 = r*(1-s)/(1-r) if s >= r else r   # Markov onset probability (s < r would mean anti-persistence; then use r)
        out['proposition3_main_view'] = {'r': r, 's': s, 'q_same_view': {n: round(p0*s**(n-1) if n > 1 else p0, 5) for n in (1, 2, 3, 4)},
                                         'q_n2_second_report_from_side_view': round(p0*(out['cross_view']['sat']['P_err_side_given_main'] or 0), 5),
                                         'note': 'per-exposure probability that a false revocation starts; Markov model of Section 3'}
    return out


def main():
    frames, ans = load()
    res = {'all_frames': structure(frames, ans, False), 'excluding_frames_where_the_goal_object_is_held': structure(frames, ans, True),
           'frames': len(frames), 'answered_samples': len(ans)}
    (HERE/'vlm_error_structure.json').write_text(json.dumps(res, indent=1), encoding='utf-8'); print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
