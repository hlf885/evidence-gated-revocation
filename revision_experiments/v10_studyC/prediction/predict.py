"""v3 (amendment A1). Generate PREDICTED (simulated) Study C outcomes. Not experimental data.

Runs the real Study C control code over the frozen-to-be 840-unit manifest against
world_model.StochasticWorld, for several model seeds (replicates).
Usage: python predict.py --replicates 1 3 --out <dir>   (replicate ids are inclusive range)
"""
from pathlib import Path
import argparse, contextlib, io, json, shutil, sys, tempfile
HERE = Path(__file__).resolve().parent; ROOT = HERE.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import kernel, design, analyze, shared_execution, contracts   # noqa: E402
from world_model import VirtualClock, StochasticWorld        # noqa: E402

MODEL_SEED_BASE = 20261130   # same seeds as v2, so v3-v2 differences come from A1 (plus the new timeout draw)
import random


def sample_params(rep):
    """Per-replicate parameter uncertainty around the v8 calibration (deliberately wide)."""
    r = random.Random(MODEL_SEED_BASE*7+rep)
    return {'pick_fail': r.uniform(0.015, 0.05), 'place_fail': r.uniform(0.0, 0.005),
            'place_low_overlap': r.uniform(0.002, 0.02), 'settle_unknown': r.uniform(0.0, 0.03),
            'post_place_slip': r.uniform(0.0, 0.01), 'contact_displace': r.uniform(0.0, 0.01),
            'duration_scale': r.uniform(0.9, 1.1),
            'action_timeout': r.uniform(0.0, 0.002)}   # v3: appended last so the v2 parameter draws are unchanged


def run_replicate(rep, workdir):
    clock = VirtualClock()
    kernel.time = clock; shared_execution.time = clock; contracts.time = clock
    manifest = design.make_manifest(); params = sample_params(rep)
    # The real run's flip pattern is fixed by its key but depends on trajectories we cannot predict;
    # a per-replicate key represents that uncertainty in the prediction.
    manifest['protocol_id'] = manifest['protocol_id']+f'|prediction_v3_rep{rep}'
    world = StochasticWorld(clock, MODEL_SEED_BASE+rep, params)
    run = Path(workdir)/f'rep{rep:02d}'
    if run.exists(): shutil.rmtree(run)
    run.mkdir(parents=True); rows = []; checks = []
    scenarios = {s['scenario_id']: s for s in manifest['scenarios']}
    for u in manifest['units']:
        with contextlib.redirect_stdout(io.StringIO()):
            kernel.run_trial(world, scenarios[u['scenario_id']], u, manifest, run)
        row = analyze.trial_row(run, u, manifest, checks)
        rows.append({'data_type': 'PREDICTED_SIMULATION_NOT_REAL', 'prediction_version': 'v3', 'replicate': rep} | row)
        shutil.rmtree(run/u['trial_id'])
    bad = [c for c in checks if not c['passed']]
    if bad: raise RuntimeError(f'prediction audit failed: {bad[:3]}')
    return rows, params


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--replicates', nargs=2, type=int, required=True)
    p.add_argument('--out', required=True); a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True); work = Path(tempfile.mkdtemp())
    for rep in range(a.replicates[0], a.replicates[1]+1):
        rows, params = run_replicate(rep, work)
        analyze.write_csv(out/f'predicted_trials_rep{rep:03d}.csv', rows)
        (out/f'params_rep{rep:03d}.json').write_text(json.dumps(params, indent=1), encoding='utf-8')
        print(json.dumps({'replicate': rep, 'trials': len(rows), 'successes': sum(r['success'] for r in rows)}), flush=True)
    shutil.rmtree(work)
