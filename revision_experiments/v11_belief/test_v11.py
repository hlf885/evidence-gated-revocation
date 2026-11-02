"""v11 offline tests (no Unity, no models)."""
from pathlib import Path
import contextlib, io, json, shutil, sys, tempfile
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'
sys.path.insert(0, str(V10)); sys.path.insert(0, str(V10/'prediction'))
import runner as v10runner, kernel as k10, shared_execution, contracts   # noqa: E402
sys.path.insert(0, str(HERE))
import kernel_v11 as k11, belief_rules as br, analyze_v11 as an, design_v11, pilot_report   # noqa: E402
from world_model import VirtualClock, StochasticWorld   # noqa: E402
from contracts import ContractError   # noqa: E402

passed = []
def check(name, cond):
    if not cond: raise AssertionError(name)
    passed.append(name)

P = br.BELIEF_PARAMS; step = lambda b, s: br.belief_step(b, s, P['alpha'], P['beta'], P['hazard'])
# 1. belief arithmetic
b1 = step(P['b_commit'], 'INVALID'); b2 = step(b1, 'INVALID')
check('one_false_invalid_does_not_revoke', b1 >= P['tau'] and P['band'][0] < b1 < P['band'][1])
check('two_invalid_revoke', b2 < P['tau'])
check('consistent_restores_after_single_revocation', step(b2, 'CONSISTENT') >= P['tau'])
b3 = step(b2, 'INVALID')
check('three_invalid_needs_two_consistent', step(b3, 'CONSISTENT') < P['tau'] and step(step(b3, 'CONSISTENT'), 'CONSISTENT') >= P['tau'])
check('unknown_uninformative', abs(step(.9, 'UNKNOWN')-.9*(1-P['hazard'])) < 1e-12)
check('never_committed_never_verified', all(step(0.0, s) == 0.0 for s in ['CONSISTENT', 'INVALID', 'UNKNOWN']))
b = P['b_commit']
for _ in range(50): b = step(b, 'CONSISTENT')
check('steady_state_stays_verified_under_hazard', b >= .99)

# 2. memory object
def snap(seq, states): return {'channel': 'completion_watchdog', 'trialId': 't', 'sequence': seq, 'simulationTime': seq*.1,
                              'goals': [{'goalId': g, 'state': s} for g, s in zip(['g1', 'g2'], states)]}
m = br.make_memory('belief', 't', ['g1', 'g2'])
m.refresh(snap(0, ['INVALID', 'INVALID'])); m.commit_placement('g1', True)
check('commit_verifies', m.committed == {'g1'})
inv = m.refresh(snap(1, ['INVALID', 'CONSISTENT']))
check('single_invalid_keeps_and_requests_reobservation', m.committed == {'g1'} and not inv and m.wants_reobservation())
inv = m.refresh(snap(2, ['INVALID', 'CONSISTENT']))
check('second_invalid_revokes', inv == {'g1'} and m.committed == set())
check('false_consistent_cannot_create_completion', 'g2' not in m.committed)
try: m.refresh(snap(2, ['CONSISTENT', 'CONSISTENT'])); check('stale_rejected', False)
except ContractError: check('stale_snapshot_clears_and_raises', m.committed == set() and not m.fresh)
check('other_rules_unchanged', type(br.make_memory('revocable', 't', ['g1'])).__name__ == 'CompletionMemory')

# 3. kernel_v11 == v10 kernel for the Study C rules (same world seed, same noise)
manifest = design_v11.make_pilot_manifest(); scen = {s['scenario_id']: s for s in manifest['scenarios']}
def run_one(kmod, unit, wseed):
    clk = VirtualClock(); saved = (kmod.time, shared_execution.time, contracts.time)
    kmod.time = shared_execution.time = contracts.time = clk
    d = Path(tempfile.mkdtemp())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            s = kmod.run_trial(StochasticWorld(clk, wseed, {'pick_fail': .03}), scen[unit['scenario_id']], unit, manifest, d)
        ev = [json.loads(l) for l in (d/unit['trial_id']/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    finally:
        kmod.time, shared_execution.time, contracts.time = saved; shutil.rmtree(d)
    return s, ev
same = 0
for u in [u for u in manifest['units'] if u['rule'] != 'belief'][:24]:
    a, ea = run_one(k10, u, 7); b, eb = run_one(k11, u, 7)
    strip = lambda e: [{k: v for k, v in x.items() if k not in ('utc', 'wall_time', 't', 'time', 'monotonic', 'perf')} for x in e]
    check('v11_kernel_identical_for_old_rules', {k: v for k, v in a.items() if k != 'total_seconds'} == {k: v for k, v in b.items() if k != 'total_seconds'}
          and len(ea) == len(eb) and [x['event'] for x in ea] == [x['event'] for x in eb])
    same += 1
print('identical trials (v10 vs v11 kernel, old rules):', same)

# 4. full pilot manifest on the stochastic world: audit replay incl. belief, report logic
clk = VirtualClock(); saved = (k11.time, shared_execution.time, contracts.time)
k11.time = shared_execution.time = contracts.time = clk
tmp = Path(tempfile.mkdtemp()); run = tmp/'pilot'
old_kernel = v10runner.kernel; v10runner.kernel = k11
try:
    with contextlib.redirect_stdout(io.StringIO()):
        v10runner.execute(manifest, 60, None, run=run, rpc_factory=lambda: StochasticWorld(clk, 4242), check_source=False)
    mf, rows, checks, table = pilot_report.summarize(run)
    res, go = pilot_report.decide(rows, checks, table)
finally:
    v10runner.kernel = old_kernel; k11.time, shared_execution.time, contracts.time = saved
check('pilot_dry_run_complete', len(rows) == 60)
check('belief_replay_audit_passes', all(c['passed'] for c in checks))
check('belief_reobserves_somewhere', sum(r['belief_reobservations'] for r in rows if r['rule'] == 'belief') > 0)
check('old_rules_never_reobserve', all(r['belief_reobservations'] == 0 for r in rows if r['rule'] != 'belief'))
print('MODEL-WORLD dry run (not data):')
for k, v in table.items(): print('  ', k, {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()})
print('  criteria:', res, 'GO' if go else 'NO-GO')
shutil.rmtree(tmp)
print(f'{len(passed)} v11 offline checks passed; 0 Unity calls, 0 model calls')
