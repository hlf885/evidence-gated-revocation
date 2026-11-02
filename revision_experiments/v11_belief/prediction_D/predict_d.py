"""PREDICTION for Study D (model simulation, NOT data). Real Study D control code (kernel_d, belief rule, persistent errors)
against the v3 stochastic world (v10 prediction folder) with the same per-replicate parameter uncertainty as prediction v3.
The world has no contact coupling between objects, so revocation cascades are NOT modelled.
Usage: python predict_d.py --replicates 1 25 --out replicates"""
from pathlib import Path
import argparse, contextlib, io, json, shutil, sys, tempfile
HERE = Path(__file__).resolve().parent; D = HERE.parent; V10 = D.parent/'v10_studyC'; PV10 = V10/'prediction'
for p in (V10, PV10, D): sys.path.insert(0, str(p))
import kernel_d, design_d, trial_d, shared_execution, contracts   # noqa: E402
from world_model import VirtualClock, StochasticWorld   # noqa: E402
import predict as pv3   # noqa: E402  (v3 parameter sampler)

MODEL_SEED_BASE = 20261231


def run_replicate(rep, work):
    clk = VirtualClock(); kernel_d.time = shared_execution.time = contracts.time = clk
    m = design_d.make_manifest(); m['protocol_id'] += f'|prediction_D_rep{rep}'; params = pv3.sample_params(rep)
    world = StochasticWorld(clk, MODEL_SEED_BASE+rep, params); run = Path(work)/f'rep{rep:03d}'; run.mkdir(parents=True)
    scen = {s['scenario_id']: s for s in m['scenarios']}; rows = []; checks = []
    for u in m['units']:
        with contextlib.redirect_stdout(io.StringIO()): kernel_d.run_trial(world, scen[u['scenario_id']], u, m, run)
        rows.append({'data_type': 'PREDICTED_SIMULATION_NOT_REAL', 'prediction': 'StudyD', 'replicate': rep} | trial_d.trial_row(run, u, m, checks))
        shutil.rmtree(run/u['trial_id'])
    bad = [c for c in checks if not c['passed']]
    if bad: raise RuntimeError(f'prediction audit failed: {bad[:2]}')
    return rows, params


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--replicates', nargs=2, type=int, required=True); p.add_argument('--out', required=True); a = p.parse_args()
    out = HERE/a.out; out.mkdir(exist_ok=True); work = Path(tempfile.mkdtemp())
    for rep in range(a.replicates[0], a.replicates[1]+1):
        rows, params = run_replicate(rep, work)
        trial_d.write_csv(out/f'predicted_trials_rep{rep:03d}.csv', rows); (out/f'params_rep{rep:03d}.json').write_text(json.dumps(params, indent=1), encoding='utf-8')
        print(json.dumps({'replicate': rep, 'successes': sum(r['success'] for r in rows)}), flush=True)
    shutil.rmtree(work)
