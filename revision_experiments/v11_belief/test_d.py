"""Study D offline tests (no Unity, no models)."""
from pathlib import Path
import contextlib, io, json, shutil, sys, tempfile
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'
sys.path.insert(0, str(V10)); sys.path.insert(0, str(V10/'prediction'))
import runner as v10runner, memory_rules, shared_execution, contracts   # noqa: E402
sys.path.insert(0, str(HERE))
import kernel_d, kernel_v11, study_d_rules as sd, trial_d, analyze_d, design_d   # noqa: E402
from world_model import VirtualClock, StochasticWorld   # noqa: E402
from contracts import ContractError   # noqa: E402

passed = []
def check(name, cond):
    if not cond: raise AssertionError(name)
    passed.append(name)

# 1. error processes
def snap(seq, states): return {'channel': 'completion_watchdog', 'trialId': 't', 'sequence': seq, 'simulationTime': seq*.1,
                              'goals': [{'goalId': g, 'state': s} for g, s in zip(['g1', 'g2'], states)]}
for t, st in [('false_invalid', 'CONSISTENT'), ('false_consistent', 'INVALID')]:
    a = memory_rules.WatchdogNoise('P', 3, t, .1); b = sd.CorrelatedWatchdogNoise('P', 3, t, .1, 'independent')
    same = all(a.apply(snap(i, [st, st]))[1] == b.apply(snap(i, [st, st]))[1] for i in range(500))
    check('independent_equals_v10_noise_'+t, same)
for r in [.1, .2]:
    for c in ['independent', 'persistent']:
        n = sd.CorrelatedWatchdogNoise('P', 11, 'false_invalid', r, c); errs = []
        for i in range(20000):
            fl = n.apply(snap(i, ['CONSISTENT', 'CONSISTENT']))[1]; errs.append(any(f['goalId'] == 'g1' for f in fl))
            assert errs[-1] == n.prev['g1']
        rate = sum(errs)/len(errs); runs = []; cur = 0
        for e in errs:
            if e: cur += 1
            elif cur: runs.append(cur); cur = 0
        mean_run = sum(runs)/len(runs)
        check(f'stationary_rate_{c}_{r}', abs(rate-r) < .015)
        check(f'run_length_{c}_{r}', (abs(mean_run-1/(1-r)) < .15) if c == 'independent' else (abs(mean_run-5) < .4))
n = sd.CorrelatedWatchdogNoise('P', 5, 'false_invalid', .2, 'persistent'); n.apply(snap(0, ['CONSISTENT', 'CONSISTENT'])); n.apply(snap(1, ['INVALID', 'CONSISTENT']))
check('ineligible_resets_persistence', n.prev['g1'] is False)
for bad in [('none', .1, 'none'), ('false_invalid', .1, 'none'), ('none', 0.0, 'independent'), ('x', .1, 'independent')]:
    try: sd.CorrelatedWatchdogNoise('P', 1, *bad); check('bad_noise', False)
    except ContractError: pass
check('bad_noise_specs_rejected', True)

# 2. kernel_d == kernel_v11 for independent errors and no errors (all rules)
m = design_d.make_manifest(); scen = {s['scenario_id']: s for s in m['scenarios']}
def run_one(kmod, unit, wseed, manifest):
    clk = VirtualClock(); saved = (kmod.time, shared_execution.time, contracts.time); kmod.time = shared_execution.time = contracts.time = clk
    d = Path(tempfile.mkdtemp())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            s = kmod.run_trial(StochasticWorld(clk, wseed, {'pick_fail': .03}), scen[unit['scenario_id']], unit, manifest, d)
        ev = [json.loads(l)['event'] for l in (d/unit['trial_id']/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    finally:
        kmod.time, shared_execution.time, contracts.time = saved; shutil.rmtree(d)
    return {k: v for k, v in s.items() if k != 'total_seconds'}, ev
k = 0
for u in [u for u in m['units'] if u['noise_correlation'] in ('none', 'independent')][:30]:
    check('kernel_d_matches_v11_for_independent_errors', run_one(kernel_d, u, 9, m) == run_one(kernel_v11, u, 9, m)); k += 1
print('identical trials kernel_d vs kernel_v11:', k)

# 3. v10 runner with Study D gate patching (as d_runner.run does), on a temporary root
tmp = Path(tempfile.mkdtemp()); (tmp/'prechecks'/'pc').mkdir(parents=True)
reg = {'verified_files': 1, 'registration_sha256': 'x'}
(tmp/'prechecks'/'pc'/'precheck_gate.json').write_text(json.dumps({'passed': True}), encoding='utf-8')
(tmp/'prechecks'/'pc'/'registration_reference.json').write_text(json.dumps(reg), encoding='utf-8')
saved_runner = (v10runner.kernel, v10runner.verify, v10runner.ROOT)
clk = VirtualClock(); saved_t = (kernel_d.time, shared_execution.time, contracts.time); kernel_d.time = shared_execution.time = contracts.time = clk
v10runner.kernel = kernel_d; v10runner.verify = lambda: reg; v10runner.ROOT = tmp
try:
    small = dict(m, units=m['units'][:6])
    with contextlib.redirect_stdout(io.StringIO()):
        v10runner.execute(small, 6, 'pc', run=tmp/'run', rpc_factory=lambda: StochasticWorld(clk, 1), check_source=True)
    check('gate_patch_runs_with_registration', json.loads((tmp/'run'/'registration_reference.json').read_text(encoding='utf-8')) == reg)
    (tmp/'prechecks'/'pc'/'precheck_gate.json').write_text(json.dumps({'passed': False}), encoding='utf-8')
    try: v10runner.execute(small, 1, 'pc', run=tmp/'run2', rpc_factory=lambda: StochasticWorld(clk, 1), check_source=True); check('failed_gate_blocks', False)
    except RuntimeError: check('failed_precheck_gate_blocks_run', True)
finally:
    v10runner.kernel, v10runner.verify, v10runner.ROOT = saved_runner; shutil.rmtree(tmp)

# 4. full 1080-unit dry run in the stochastic world: replay audit (belief + persistent errors), checkpoint, final
tmp = Path(tempfile.mkdtemp()); run = tmp/'formal_D'; v10runner.kernel = kernel_d
try:
    with contextlib.redirect_stdout(io.StringIO()):
        v10runner.execute(m, 1080, None, run=run, rpc_factory=lambda: StochasticWorld(clk, 777), check_source=False)
        (tmp/'seg').mkdir(); cp = analyze_d.checkpoint(run, 'seg', exec_dir=tmp); inf = analyze_d.final(run)
finally:
    v10runner.kernel = saved_runner[0]; kernel_d.time, shared_execution.time, contracts.time = saved_t
check('dry_run_1080', inf['trials'] == 1080 and inf['assigned_trials'] == 1080)
check('replay_audit_passes_incl_persistent_and_belief', inf['audit_all_passed'] and cp['audit_all_passed'])
check('primary_family_as_registered', [(x['condition'], x['noise_type'], x['b']) for x in inf['primary']] ==
      [('no_fault', 'false_invalid', 'revocable'), ('completed_shift', 'false_invalid', 'revocable'), ('no_fault', 'false_consistent', 'reactive'), ('completed_shift', 'false_consistent', 'reactive')])
check('key_secondary_12', len(inf['key_secondary']) == 12 and all(x['p_holm'] >= x['p'] for x in inf['key_secondary']))
check('persistent_errors_flip_more_in_runs', any(r['noise_correlation'] == 'persistent' and r['observation_flips'] > 0 for r in trial_d.collect(run)[1]))
print('MODEL-WORLD dry run (not data): belief vs best other, successes /20')
for b in inf['belief_vs_best_other_descriptive']: print('  ', b)
print('  primary:', [(x['condition'], x['noise_type'], x['a_successes'], x['b_successes'], round(x['p_holm'], 5)) for x in inf['primary']])
shutil.rmtree(tmp)
print(f'{len(passed)} Study D offline checks passed; 0 Unity calls, 0 model calls')
