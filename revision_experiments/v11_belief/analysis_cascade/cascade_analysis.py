"""Post-hoc (exploratory, not pre-registered) analysis of false revocations and revocation cascades.
Reads sealed trials of Study C (v10 results/formal_02) and Study D (v11 results/formal_D); never modifies them.
Definitions (event-level, from the paired audit observations that the controller never sees):
  revocation       a goal leaves the controller's verified set at a memory refresh
  false revocation the independent score says that goal was satisfied at that refresh
    - noise        a synthetic flip hit that goal in this or the previous 2 controller refreshes
    - physical     no recent flip: the true watchdog said INVALID/UNKNOWN while the score said satisfied
  repick           a later PICK dispatch of the falsely revoked goal's object
  collateral       during that repick and its PLACE, another goal sharing the container goes from satisfied
                   to unsatisfied in the independent score (a physical disturbance caused by the repair)
  exposure         a controller refresh at which a goal was verified by the controller and satisfied by the score
"""
from pathlib import Path
import collections, csv, json, statistics, sys
HERE = Path(__file__).resolve().parent; V11 = HERE.parent; V10 = V11.parent/'v10_studyC'
RUNS = {'C': V10/'results/formal_02', 'D': V11/'results/formal_D'}


def analyse_trial(folder, scenario):
    ev = [json.loads(l) for l in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    cont = {g['id']: g['containerId'] for g in scenario['goals']}; obj = {g['id']: g['objectId'] for g in scenario['goals']}
    goal_of = {v: k for k, v in obj.items()}
    last_pair = None; recent_flips = collections.deque(maxlen=3); out = collections.Counter(); pending = []  # (goal, stage, S_before)
    for e in ev:
        k = e['event']
        if k == 'paired_observation':
            last_pair = e; sat = {g['goalId']: g['satisfied'] for g in e['score']['goals']}
            for p in pending:
                if p['stage'] == 'watch':
                    for g2 in p['S_before']:
                        if g2 != p['goal'] and cont[g2] == cont[p['goal']] and not sat.get(g2, True) and not p['hit']:
                            p['hit'] = True; out['collateral'] += 1
        elif k == 'controller_watchdog':
            recent_flips.append({f['goalId'] for f in e.get('flips', [])})
        elif k == 'memory_refresh':
            if last_pair is None: continue
            sat = {g['goalId']: g['satisfied'] for g in last_pair['score']['goals']}
            out['exposures'] += sum(1 for g in e['before'] if sat.get(g))
            for g in e['invalidated']:
                out['revocations'] += 1
                if sat.get(g):
                    flipped = any(g in s for s in recent_flips)
                    out['false_revocations'] += 1; out['false_revocations_noise' if flipped else 'false_revocations_physical'] += 1
                    pending.append({'goal': g, 'stage': 'await_pick', 'S_before': None, 'hit': False})
                else:
                    out['true_revocations'] += 1
        elif k == 'primitive_dispatched':
            name = e['action']['name']; tgt = e['action']['target']
            for p in pending:
                if p['stage'] == 'await_pick' and name == 'PICK' and goal_of.get(tgt) == p['goal']:
                    p['stage'] = 'watch'; out['repicks_after_false_revocation'] += 1
                    p['S_before'] = {g['goalId'] for g in last_pair['score']['goals'] if g['satisfied']} if last_pair else set()
        elif k == 'action_outcome':
            if e['action']['name'] == 'PLACE':
                for p in pending:
                    if p['stage'] == 'watch' and goal_of.get(e['action'].get('target')) is None:
                        p['stage'] = 'done'   # PLACE targets a container; close the watch window after the repair PLACE
    out['trials_with_collateral'] = int(out['collateral'] > 0); out['trials_with_false_revocation'] = int(out['false_revocations'] > 0)
    return out


def main():
    rows = []
    for study, run in RUNS.items():
        m = json.loads((run/'manifest.json').read_text(encoding='utf-8')); scen = {s['scenario_id']: s for s in m['scenarios']}
        for u in m['units']:
            f = run/u['trial_id']; s = json.loads((f/'summary.json').read_text(encoding='utf-8'))
            c = analyse_trial(f, scen[u['scenario_id']])
            rows.append({'study': study, 'trial_id': u['trial_id'], 'rule': u['rule'], 'condition': u['condition'], 'noise_type': u['noise_type'],
                         'noise_rate': u['noise_rate'], 'noise_correlation': u.get('noise_correlation', 'independent' if u['noise_type'] != 'none' else 'none'),
                         'success': s['success'], **{k: c.get(k, 0) for k in ['exposures', 'revocations', 'true_revocations', 'false_revocations', 'false_revocations_noise',
                         'false_revocations_physical', 'repicks_after_false_revocation', 'collateral', 'trials_with_collateral', 'trials_with_false_revocation']}})
    with (HERE/'cascade_trials.csv').open('w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    agg = collections.defaultdict(list)
    for r in rows: agg[(r['study'], r['rule'], r['noise_type'], r['noise_rate'], r['noise_correlation'])].append(r)
    summary = []
    for k, rs in sorted(agg.items(), key=str):
        exp = sum(r['exposures'] for r in rs); fr = sum(r['false_revocations'] for r in rs)
        coll = [r for r in rs if r['trials_with_collateral']]; nocoll = [r for r in rs if not r['trials_with_collateral'] and r['trials_with_false_revocation']]
        summary.append({'study': k[0], 'rule': k[1], 'noise_type': k[2], 'noise_rate': k[3], 'noise_correlation': k[4], 'trials': len(rs),
                        'exposures': exp, 'false_revocations': fr, 'fr_per_exposure': round(fr/exp, 4) if exp else None,
                        'fr_noise': sum(r['false_revocations_noise'] for r in rs), 'fr_physical': sum(r['false_revocations_physical'] for r in rs),
                        'repicks_after_fr': sum(r['repicks_after_false_revocation'] for r in rs), 'collateral_events': sum(r['collateral'] for r in rs),
                        'trials_with_collateral': len(coll), 'success_if_collateral': f"{sum(r['success'] for r in coll)}/{len(coll)}",
                        'success_if_fr_without_collateral': f"{sum(r['success'] for r in nocoll)}/{len(nocoll)}",
                        'success': f"{sum(r['success'] for r in rs)}/{len(rs)}"})
    (HERE/'cascade_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    return rows, summary


if __name__ == '__main__':
    rows, summary = main()
    for s in summary:
        if s['noise_type'] != 'none' or True:
            print(s['study'], s['rule'][:6], s['noise_type'][:8], s['noise_rate'], s['noise_correlation'][:4], 'n', s['trials'], 'exp', s['exposures'], 'FR', s['false_revocations'],
                  'rate', s['fr_per_exposure'], 'noise/phys', s['fr_noise'], s['fr_physical'], 'repick', s['repicks_after_fr'], 'coll', s['collateral_events'],
                  'Tcoll', s['trials_with_collateral'], 'succ|coll', s['success_if_collateral'], 'succ|FRnocoll', s['success_if_fr_without_collateral'], 'succ', s['success'])
