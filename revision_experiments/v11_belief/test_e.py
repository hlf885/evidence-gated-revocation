"""Study E offline tests (no Unity, no models)."""
from pathlib import Path
import contextlib, io, json, shutil, sys, tempfile
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'
sys.path.insert(0, str(V10)); sys.path.insert(0, str(V10/'prediction'))
import runner as v10runner, shared_execution, contracts   # noqa: E402
sys.path.insert(0, str(HERE))
import kernel_e, kernel_d, study_e_rules as se, trial_e, analyze_e, design_e   # noqa: E402
from world_model import VirtualClock, StochasticWorld   # noqa: E402
from contracts import ContractError   # noqa: E402

passed = []
def check(name, cond):
    if not cond: raise AssertionError(name)
    passed.append(name)

def snap(seq, states): return {'channel': 'completion_watchdog', 'trialId': 't', 'sequence': seq, 'simulationTime': seq*.1,
                              'goals': [{'goalId': g, 'state': s} for g, s in zip(['g1', 'g2'], states)]}
# 1. rules
def reports_to_revoke(rule):
    m = se.make_memory(rule, 't', ['g1', 'g2']); m.refresh(snap(0, ['INVALID', 'INVALID'])); m.commit_placement('g1', True)
    for i in range(1, 12):
        m.refresh(snap(i, ['INVALID', 'INVALID']))
        if 'g1' not in m.committed: return i
check('n_star_closed_form', [se.n_star(r) for r in ['belief_a02', 'belief_a10', 'belief_a30']] == [1, 2, 5])
check('revocation_counts_a02_a10_a30_debounce', [reports_to_revoke(r) for r in ['belief_a02', 'belief_a10', 'belief_a30', 'debounce2', 'revocable']] == [1, 2, 4, 2, 1])
d = se.make_memory('debounce2', 't', ['g1', 'g2']); d.refresh(snap(0, ['INVALID', 'INVALID'])); d.commit_placement('g1', True)
d.refresh(snap(1, ['UNKNOWN', 'INVALID'])); check('debounce_one_report_keeps_and_reobserves', d.committed == {'g1'} and d.wants_reobservation())
d.refresh(snap(2, ['CONSISTENT', 'INVALID'])); check('debounce_consistent_resets', d.committed == {'g1'} and not d.wants_reobservation())
d.refresh(snap(3, ['INVALID', 'INVALID'])); d.refresh(snap(4, ['UNKNOWN', 'INVALID'])); check('debounce_two_reports_revoke', d.committed == set())
d.refresh(snap(5, ['CONSISTENT', 'CONSISTENT'])); check('debounce_no_restoration_without_commit', d.committed == set())
try: d.refresh(snap(5, ['CONSISTENT', 'CONSISTENT'])); check('stale', False)
except ContractError: check('debounce_stale_rejected', not d.fresh)
b = se.make_memory('belief_a10', 't', ['g1', 'g2']); b.refresh(snap(0, ['INVALID', 'INVALID'])); b.commit_placement('g1', True)
b.refresh(snap(1, ['INVALID', 'INVALID'])); b.refresh(snap(2, ['INVALID', 'INVALID'])); b.refresh(snap(3, ['CONSISTENT', 'INVALID']))
check('belief_restores_after_revocation_debounce_does_not', b.committed == {'g1'})
st = se.replay_new(); se.replay_commit('debounce2', st, 'g1')
check('replay_debounce', se.replay_refresh('debounce2', st, {'g1': 'INVALID', 'g2': 'INVALID'}) == {'g1'} and se.replay_refresh('debounce2', st, {'g1': 'UNKNOWN', 'g2': 'INVALID'}) == set())
check('replay_none_for_v10_rules', se.replay_refresh('revocable', se.replay_new(), {'g1': 'INVALID'}) is None)

# 2. kernel_e == kernel_d for rules both know (Study D belief == belief_a10)
m = design_e.make_manifest(); scen = {s['scenario_id']: s for s in m['scenarios']}
def run_one(kmod, unit, manifest):
    clk = VirtualClock(); saved = (kmod.time, shared_execution.time, contracts.time); kmod.time = shared_execution.time = contracts.time = clk
    dd = Path(tempfile.mkdtemp())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            s = kmod.run_trial(StochasticWorld(clk, 5, {'pick_fail': .03}), scen[unit['scenario_id']], unit, manifest, dd)
        ev = [json.loads(l)['event'] for l in (dd/unit['trial_id']/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    finally:
        kmod.time, shared_execution.time, contracts.time = saved; shutil.rmtree(dd)
    return {k: v for k, v in s.items() if k not in ('total_seconds', 'memory', 'rule')}, ev
for u in [u for u in m['units'] if u['rule'] == 'belief_a10'][:24]:
    ud = dict(u, rule='belief' if u['rule'] == 'belief_a10' else u['rule'], memory='belief' if u['rule'] == 'belief_a10' else u['rule'])
    check('kernel_e_matches_kernel_d', run_one(kernel_e, u, m) == run_one(kernel_d, ud, m))

# 3. full 400-unit dry run: replay audit for every Study E rule, false-revocation counts, frozen inference
clk = VirtualClock(); saved = (kernel_e.time, shared_execution.time, contracts.time); kernel_e.time = shared_execution.time = contracts.time = clk
tmp = Path(tempfile.mkdtemp()); run = tmp/'formal_E'; old = v10runner.kernel; v10runner.kernel = kernel_e
try:
    with contextlib.redirect_stdout(io.StringIO()):
        v10runner.execute(m, 480, None, run=run, rpc_factory=lambda: StochasticWorld(clk, 99), check_source=False)
        (tmp/'seg').mkdir(); cp = analyze_e.checkpoint(run, 'seg', exec_dir=tmp); inf = analyze_e.final(run)
finally:
    v10runner.kernel = old; kernel_e.time, shared_execution.time, contracts.time = saved
check('dry_run_480', inf['trials'] == 480 and inf['audit_all_passed'] and cp['audit_all_passed'])
check('primary_two_tests', [x['id'] for x in inf['primary']] == ['H1', 'H2'] and all(x['seeds'] == 20 for x in inf['primary']))
check('signflip_exact', analyze_e.signflip_p([1, 1, 1]) == 0.25 and analyze_e.signflip_p([0, 0]) == 1.0 and abs(analyze_e.signflip_p([3, 1, 2, 2]) - 2/16) < 1e-12)
rows = trial_e.collect(run)[1]
check('false_revocations_counted', sum(r['false_revocations'] for r in rows if r['rule'] == 'belief_a02') > sum(r['false_revocations'] for r in rows if r['rule'] == 'belief_a30'))
check('debounce_reobserves', sum(r['belief_reobservations'] for r in rows if r['rule'] == 'debounce2') > 0)
print('MODEL-WORLD dry run (not data):', [(x['id'], x['a_total'], x['b_total'], x['a_greater'], x['b_greater'], round(x['p_holm'], 4)) for x in inf['primary']])
shutil.rmtree(tmp)
print(f'{len(passed)} Study E offline checks passed; 0 Unity calls, 0 model calls')
