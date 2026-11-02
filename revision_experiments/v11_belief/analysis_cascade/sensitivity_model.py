"""Post-hoc model sensitivity (2026-11-01). MODEL SIMULATION, NOT EXPERIMENTAL DATA.
Runs the real Study E kernel against the v3 stochastic world (as in the registered predictions) while varying
(i) the recovery budget and (ii) the belief rule's hazard. Writes sens_<tag>_rep<k>.json under sens_out/.
Usage: python sensitivity_model.py --tag budget5 --reps 1 3
"""
from pathlib import Path
import argparse, contextlib, io, json, shutil, sys, tempfile, collections
HERE = Path(__file__).resolve().parent; D = HERE.parent; V10 = D.parent/'v10_studyC'; PV10 = V10/'prediction'
for p in (V10, PV10, D): sys.path.insert(0, str(p))
import kernel_e, design_e, trial_e, shared_execution, contracts, belief_rules   # noqa: E402
from world_model import VirtualClock, StochasticWorld   # noqa: E402
import predict as pv3   # noqa: E402
SEED_BASE = 20271101
TAGS = {'budget3': {'rec': 3}, 'budget5': {'rec': 5}, 'budget10': {'rec': 10},
        'hazard001': {'rec': 3, 'h': 0.001}, 'hazard05': {'rec': 3, 'h': 0.05}}
RULES = ['revocable', 'reactive', 'belief_a10', 'debounce2']


def run(tag, rep, work):
    cfg = TAGS[tag]; belief_rules.BELIEF_PARAMS['hazard'] = cfg.get('h', 0.01)
    clk = VirtualClock(); kernel_e.time = shared_execution.time = contracts.time = clk
    m = design_e.make_manifest(); m['protocol_id'] += f'|sensitivity_{tag}_rep{rep}'
    extra = cfg['rec']-3; m['budget'] = {'seconds': 240+40*extra, 'max_actions': 12+2*extra, 'max_recoveries': cfg['rec']}
    rules = RULES if 'h' not in cfg else ['belief_a10']
    units = []
    for u in m['units']:
        if u['rule'] != 'belief_a10': continue
        for r in rules: units.append(u | {'rule': r, 'memory': r, 'trial_id': u['trial_id'].replace('belief_a10', r)})
    m['units'] = units; params = pv3.sample_params(rep); world = StochasticWorld(clk, SEED_BASE+rep, params)
    out = Path(work)/f'{tag}{rep}'; out.mkdir(parents=True); scen = {s['scenario_id']: s for s in m['scenarios']}; agg = collections.Counter(); checks = []
    for u in units:
        with contextlib.redirect_stdout(io.StringIO()): kernel_e.run_trial(world, scen[u['scenario_id']], u, m, out)
        row = trial_e.trial_row(out, u, m, checks); shutil.rmtree(out/u['trial_id'])
        key = f"{u['rule']}|{u['condition']}|{u['noise_type']}|{u['noise_correlation']}"; agg[key+'|succ'] += row['success']; agg[key+'|n'] += 1
    bad = [c for c in checks if not c['passed']]
    if bad: raise RuntimeError(f'audit failed {bad[:2]}')
    return dict(agg)


if __name__ == '__main__':
    a = argparse.ArgumentParser(); a.add_argument('--tag', required=True); a.add_argument('--reps', nargs=2, type=int, required=True); a = a.parse_args()
    od = HERE/'sens_out'; od.mkdir(exist_ok=True); work = tempfile.mkdtemp()
    for rep in range(a.reps[0], a.reps[1]+1):
        f = od/f'sens_{a.tag}_rep{rep:03d}.json'
        if f.exists(): continue
        f.write_text(json.dumps(run(a.tag, rep, work)), encoding='utf-8'); print(a.tag, rep, 'done', flush=True)
    shutil.rmtree(work)
