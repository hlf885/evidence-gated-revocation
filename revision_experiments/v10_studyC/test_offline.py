"""Offline tests: no Unity, no models. A deterministic fake world stands in for the RPC."""
from pathlib import Path
import json, shutil, sys, tempfile, types, collections
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import memory_rules as mr, kernel, runner, analyze, design
from contracts import ContractError

passed = []
def check(name, cond):
    if not cond: raise AssertionError(name)
    passed.append(name)


class FakeWorld:
    """Minimal deterministic world implementing the REV_* verbs used by the kernel."""
    def __init__(self): self.trial = None
    def call(self, verb, trial_id='', timeout=30, **p):
        r = {'pong': True} if verb == 'REV_PING' else getattr(self, verb.lower())(trial_id, **p)
        r.setdefault('ok', True); return r
    def close(self): pass
    def rev_reset(self, tid, **p): return {}
    def rev_config(self, tid, configuration, **p):
        c = configuration; self.tid = tid; self.goals = c['goals']; self.faults = [dict(f, attempted=False, applied=False, observedEffect=False) for f in c['faults']]
        self.where = {e['id']: 'table' for e in c['entities'] if e['kind'] == 'object'}; self.held = None; self.seq = 0; self.t = 0.0
        return {'initialState': [{'id': k, 'position': {'x': 0, 'y': 0, 'z': 0}} for k in self.where]}
    def _tick(self): self.seq += 1; self.t += 0.1
    def _watch(self):
        rows = []
        for g in self.goals:
            o = g['objectId']
            st = 'INVALID' if self.held == o or self.where[o] != g['containerId'] else 'CONSISTENT'
            rows.append({'goalId': g['id'], 'state': st, 'reason': 'fake', 'overlap': 1.0 if st == 'CONSISTENT' else 0.0})
        return {'channel': 'completion_watchdog', 'trialId': self.tid, 'sequence': self.seq, 'simulationTime': self.t, 'goals': rows}
    def _score(self):
        goals = [{'goalId': g['id'], 'objectId': g['objectId'], 'satisfied': self.held != g['objectId'] and self.where[g['objectId']] == g['containerId'], 'reason': 'fake'} for g in self.goals]
        k = sum(x['satisfied'] for x in goals)
        return {'channel': 'offline_score', 'trialId': self.tid, 'simulationTime': self.t, 'goals': goals, 'taskSuccess': k == len(goals), 'progress': k/len(goals)}
    def _hold(self):
        return {'channel': 'controller_feedback', 'state': 'HOLDING' if self.held else 'EMPTY', **({'objectId': self.held} if self.held else {})}
    def rev_observe_audit(self, tid, **p):
        self._tick(); return {'watchdog': self._watch(), 'holding': self._hold(), 'score': self._score()}
    def rev_locate(self, tid, action, target, **p):
        return {'location': {'channel': 'controlled_simulator_observation', 'action': action, 'target': target, 'position': {'x': 0.0, 'y': 0.72, 'z': 0.05}}}  # A1: inside the S11 workspace
    def rev_disturb(self, tid, eventId, anchor, **p):
        for f in self.faults:
            if f['id'] == eventId:
                f.update(attempted=True, applied=True, observedEffect=True, attemptedAt=self.t, observedAt=self.t)
                if f['type'] == 'object_shift': self.where[f['targetId']] = 'table'
        return {'faults': self.faults}
    def rev_action(self, tid, action, target, position, **p):
        self._tick()
        if action == 'PICK':
            if self.held is None:
                self.held = target; self.where[target] = 'gripper'; return {'primitiveStatus': 'STATUS:GRASP_SUCCESS', 'motions': []}
            return {'primitiveStatus': 'STATUS:GRASP_FAILED', 'motions': []}
        if self.held:
            o = self.held; self.held = None; self.where[o] = target
            names = {'bowl': 'bowl02', 'yellow_plate': 'plate02'}
            return {'primitiveStatus': 'STATUS:PLACE_SUCCESS|'+json.dumps({'container': names[target], 'bbox_overlap': .95}), 'motions': []}
        return {'primitiveStatus': 'STATUS:PLACE_FAILED', 'motions': []}
    def rev_hold(self, tid, **p): return {'holding': self._hold()}
    def rev_end(self, tid, **p): return {'score': self._score(), 'faults': self.faults}
    def rev_abort(self, tid, **p): return {}


# 1. memory rules
goals = ['g1', 'g2']
def snap(seq, states): return {'channel': 'completion_watchdog', 'trialId': 't', 'sequence': seq, 'simulationTime': seq*.1,
                              'goals': [{'goalId': g, 'state': s} for g, s in zip(goals, states)]}
for rule in mr.RULES:
    m = mr.make_memory(rule, 't', goals)
    m.refresh(snap(0, ['INVALID', 'INVALID'])); m.commit_placement('g1', True)
    m.refresh(snap(1, ['CONSISTENT', 'CONSISTENT']))
    v1 = set(m.committed)
    m.refresh(snap(2, ['INVALID', 'CONSISTENT'])); v2 = set(m.committed)
    m.refresh(snap(3, ['CONSISTENT', 'CONSISTENT'])); v3 = set(m.committed)
    exp = {'commit_only': ({'g1'}, {'g1'}, {'g1'}), 'revocable': ({'g1'}, set(), set()), 'reactive': ({'g1', 'g2'}, {'g2'}, {'g1', 'g2'})}[rule]
    check(f'rule_semantics_{rule}', (v1, v2, v3) == exp)
r = mr.make_memory('reactive', 't', goals)
try: r.refresh({'channel': 'x'}); check('reactive_rejects_bad', False)
except ContractError: check('reactive_rejects_bad_snapshot', not r.fresh and not r.committed)

# 1b. holding-first FSM equals v7 FSM wherever v7 does not stop with HOLDING_CONFLICT
import itertools
from policy import HoldingFirstStateMachine
from recovery_policies import Goal, StateMachinePolicy
from contracts import Feedback
G = [Goal('g1', 'red_cube', 'bowl'), Goal('g2', 'green_ball', 'yellow_plate'), Goal('g3', 'yellow_cylinder', 'bowl')]
same = changed = 0
for r in range(4):
    for verified in itertools.combinations(['g1', 'g2', 'g3'], r):
        for hold in [('EMPTY', None), ('UNKNOWN', None)] + [('HOLDING', g.object_id) for g in G]:
            fb = Feedback('t', 1, hold[0], hold[1], frozenset(verified))
            a, b = StateMachinePolicy(G).decide(fb), HoldingFirstStateMachine(G).decide(fb)
            if a.status == 'HOLDING_CONFLICT':
                changed += 1
                held = next(g for g in G if g.object_id == hold[1])
                check('holding_first_places_held_or_keeps_stop', (b.status == 'ACTION' and b.action.name == 'PLACE' and b.action.target == held.container_id and held.id not in verified) or (b.status == 'HOLDING_CONFLICT' and held.id in verified))
            else:
                same += 1; check('holding_first_identical_elsewhere', a == b)
check('holding_first_state_space', same + changed == 8*5)
print('fsm states identical:', same, 'v7 HOLDING_CONFLICT states:', changed)

# 2. noise
base = snap(5, ['CONSISTENT', 'INVALID'])
n0 = mr.WatchdogNoise('P', 1, 'none', 0.0); out, f = n0.apply(base); check('none_is_identity', out == base and f == [])
def flips(t, rate, seed=7, k=400):
    n = mr.WatchdogNoise('P', seed, t, rate); s = set()
    for i in range(k):
        _, fl = n.apply(base); s |= {(x['refresh_index'], x['goalId']) for x in fl}
    return s
lo, hi = flips('false_invalid', .02), flips('false_invalid', .10)
check('nested_rates', lo <= hi)
check('false_invalid_only_on_consistent', all(g == 'g1' for _, g in hi))
check('false_consistent_only_on_invalid', all(g == 'g2' for _, g in flips('false_consistent', .10)))
check('rate_plausible', 20 <= len(hi) <= 65)
check('crn_identical_across_calls', flips('false_consistent', .05) == flips('false_consistent', .05))
check('input_not_mutated', base['goals'][0]['state'] == 'CONSISTENT')
for bad in [('none', .1), ('false_invalid', 0), ('other', .1)]:
    try: mr.WatchdogNoise('P', 1, *bad); check('bad_noise', False)
    except ContractError: pass
check('bad_noise_rejected', True)

# 3. design
m = design.make_manifest()
check('840_units', len(m['units']) == 840 and len({u['trial_id'] for u in m['units']}) == 840)
cnt = collections.Counter((u['condition'], u['rule'], u['noise_type'], u['noise_rate']) for u in m['units'])
check('balanced_cells', len(cnt) == 42 and set(cnt.values()) == {20})
check('blocks_contiguous', all(len({u['seed'] for u in m['units'][i*42:(i+1)*42]}) == 1 for i in range(20)))
check('seeds_new', not set(m['layout_seeds']) & design.used_seeds())
check('design_reproducible', design.make_manifest() == m)

# 4. end-to-end on the fake world: one seed block (42 trials)
kernel.time = types.SimpleNamespace(sleep=lambda s: None, perf_counter_ns=__import__('time').perf_counter_ns, monotonic=__import__('time').monotonic)
tmp = Path(tempfile.mkdtemp()); run = tmp/'formal_02'
mini = dict(m); mini['units'] = m['units'][:42]
runner.execute(mini, 30, 'x', run=run, rpc_factory=FakeWorld, check_source=False)
runner.execute(mini, 30, 'x', run=run, rpc_factory=FakeWorld, check_source=False)   # resume, no rerun
check('resume_completes_block', len(runner.inspect_resume(run, mini)) == 42)
manifest, rows, checks = analyze.collect(run)
check('offline_audit_passes', all(c['passed'] for c in checks) and len(rows) == 42)
by = {(r['condition'], r['rule'], r['noise_type'], r['noise_rate']): r for r in rows}
check('noise0_shift_commit_only_fails', not by['completed_shift', 'commit_only', 'none', 0.0]['success'])
check('noise0_shift_revocable_succeeds', by['completed_shift', 'revocable', 'none', 0.0]['success'])
check('noise0_shift_reactive_succeeds', by['completed_shift', 'reactive', 'none', 0.0]['success'])
check('noise0_nofault_all_succeed', all(by['no_fault', r, 'none', 0.0]['success'] for r in mr.RULES))
check('commit_only_ignores_false_invalid', all(by[c, 'commit_only', 'false_invalid', .10]['observation_flips'] >= 0 for c in design.CONDITIONS))
check('flips_recorded', sum(r['observation_flips'] for r in rows if r['noise_type'] != 'none') > 0)
print(json.dumps(analyze.describe(rows)[:3], ensure_ascii=False))
for k, v in sorted(by.items(), key=str):
    if v['noise_rate'] == .10: print(k, v['success'], v['termination_reason'], v['observation_flips'], v['primitive_dispatches'])
try:
    shutil.rmtree(run/mini['units'][-1]['trial_id']/'summary.json', ignore_errors=True)
    (run/mini['units'][-1]['trial_id']/'events.jsonl').write_text('tampered', encoding='utf-8')
    runner.inspect_resume(run, mini); check('tamper_detected', False)
except RuntimeError: check('tamper_detected', True)
shutil.rmtree(tmp)

# 5. full 840-unit dry run of the frozen analysis on the stochastic prediction world (no Unity)
sys.path.insert(0, str(ROOT/'prediction'))
import io, contextlib, shared_execution, contracts
from world_model import VirtualClock, StochasticWorld
clk = VirtualClock(); saved = (kernel.time, shared_execution.time, contracts.time)
kernel.time = shared_execution.time = contracts.time = clk
tmp = Path(tempfile.mkdtemp()); run = tmp/'formal_02'
with contextlib.redirect_stdout(io.StringIO()):
    runner.execute(m, 840, 'x', run=run, rpc_factory=lambda: StochasticWorld(clk, 31337), check_source=False)
    inf = analyze.final(run)
kernel.time, shared_execution.time, contracts.time = saved
check('final_audit_passes', inf['audit_all_passed'] and inf['trials'] == 840)
outs = [(x['noise_type'], x['condition'], x['outcome']) for x in inf['primary']]
check('primary_endpoints_as_registered', outs == [('false_consistent', 'no_fault', 'independent_final_task_success'),
      ('false_consistent', 'completed_shift', 'independent_final_task_success'),
      ('false_invalid', 'no_fault', 'extra_repicks_of_satisfied_objects'),
      ('false_invalid', 'completed_shift', 'extra_repicks_of_satisfied_objects')])
check('holm_monotone', all(x['p_holm'] >= x['p'] for x in inf['primary']))
check('false_invalid_success_now_secondary', any(s['noise_type'] == 'false_invalid' and s['noise_rate'] == .10 and s['a'] == 'revocable' and s['b'] == 'reactive' for s in inf['secondary']))
check('false_consistent_success_not_duplicated', not any(s['noise_type'] == 'false_consistent' and s['noise_rate'] == .10 and s['a'] == 'revocable' and s['b'] == 'reactive' for s in inf['secondary']))
print('dry-run primary:', [(x['noise_type'], x['condition'], round(x['p_holm'], 6)) for x in inf['primary']])
shutil.rmtree(tmp)
# 6. Amendment A1: S9 fault precondition, S10 budget timeout, S11 workspace, S12 action timeout,
#    runner early end / infrastructure exclusions, manager segment plan, analysis counts.
import manager
from world_model import VirtualClock
check('workspace_inside', kernel.within_workspace({'x': 0.0, 'y': 0.72, 'z': 0.05}))
check('workspace_outside_each_axis', not any(kernel.within_workspace(p) for p in
      [{'x': .45, 'y': .7, 'z': .05}, {'x': 0, 'y': .50, 'z': .05}, {'x': 0, 'y': 1.05, 'z': .05}, {'x': 0, 'y': .7, 'z': -.2}, {'x': 0, 'y': .7, 'z': .45}]))
SC = next(s for s in m['scenarios'] if s['condition'] == 'completed_shift'); F = SC['faults'][0]
def sc_score(sat): return {'goals': [{'goalId': g, 'satisfied': bool(v)} for g, v in zip(['g1', 'g2', 'g3'], sat)]}
check('precondition_holds', kernel.fault_precondition(F, SC, sc_score([1, 0, 0]), {'state': 'HOLDING', 'objectId': 'green_ball'}))
check('precondition_unsatisfied_defers', not kernel.fault_precondition(F, SC, sc_score([0, 0, 0]), {'state': 'EMPTY'}))
check('precondition_target_held_defers', not kernel.fault_precondition(F, SC, sc_score([1, 0, 0]), {'state': 'HOLDING', 'objectId': 'red_cube'}))
check('precondition_other_fault_types', kernel.fault_precondition({'type': 'grasp_loss', 'targetId': 'red_cube'}, SC, sc_score([0, 0, 0]), {'state': 'EMPTY'}))

def unit_for(cond, rule, t='none', rate=0.0):
    return next(u for u in m['units'] if u['condition'] == cond and u['rule'] == rule and u['noise_type'] == t and u['noise_rate'] == rate)
def one(world, unit):
    tmpd = Path(tempfile.mkdtemp()); sc = next(s for s in m['scenarios'] if s['scenario_id'] == unit['scenario_id'])
    with contextlib.redirect_stdout(io.StringIO()):
        s = kernel.run_trial(world, sc, unit, m, tmpd)
    ev = [json.loads(l) for l in (tmpd/unit['trial_id']/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    shutil.rmtree(tmpd); return s, ev
kernel.time = types.SimpleNamespace(sleep=lambda s: None, perf_counter_ns=__import__('time').perf_counter_ns, monotonic=__import__('time').monotonic)

class BounceWorld(FakeWorld):
    """First PLACE of red_cube is reported as success but the cube ends on the table (score unsatisfied)."""
    bounced = False
    def rev_action(self, tid, action, target, position, **p):
        if action == 'PLACE' and self.held == 'red_cube' and not self.bounced:
            self.bounced = True; r = super().rev_action(tid, action, target, position); self.where['red_cube'] = 'table'; return r
        return super().rev_action(tid, action, target, position)
s, ev = one(BounceWorld(), unit_for('completed_shift', 'commit_only'))
names = [e['event'] for e in ev]
check('S9_defers_shift_of_unsatisfied_goal', 'fault_deferred_precondition' in names and 'fault_requested' not in names)
check('S9_deferred_trial_is_scored', not s['infrastructure_error'] and s['score_available'] and not s['success'])
s, ev = one(BounceWorld(), unit_for('completed_shift', 'revocable'))
names = [e['event'] for e in ev]
check('S9_fires_after_repair', 'fault_requested' in names and s['success'] and not s['infrastructure_error'])
s, ev = one(FakeWorld(), unit_for('completed_shift', 'revocable'))
check('S9_normal_shift_unchanged', [e['event'] for e in ev].count('fault_requested') == 1 and 'fault_deferred_precondition' not in [e['event'] for e in ev] and s['success'])

class FarWorld(FakeWorld):
    def rev_locate(self, tid, action, target, **p):
        r = super().rev_locate(tid, action, target)
        if target == 'red_cube': r['location']['position'] = {'x': 0.3, 'y': 0.2, 'z': -0.4}
        return r
s, ev = one(FarWorld(), unit_for('no_fault', 'revocable'))
canc = [e for e in ev if e['event'] == 'action_cancelled']
check('S11_cancels_outside_target', canc and all(e['reason'] == 'target_outside_workspace' for e in canc))
check('S11_never_dispatches_outside', not any(e['event'] == 'primitive_dispatched' and e['action']['target'] == 'red_cube' for e in ev))
check('S11_ends_as_scored_budget_stop', s['termination_reason'].startswith('BudgetExceeded') and not s['infrastructure_error'] and s['score_available'])

class TimeoutWorld(FakeWorld):
    def rev_action(self, tid, action, target, position, **p):
        if action == 'PLACE': raise TimeoutError('Unity RPC timeout: REV_ACTION')
        return super().rev_action(tid, action, target, position)
s, ev = one(TimeoutWorld(), unit_for('no_fault', 'revocable'))
check('S12_action_timeout_scored', s['termination_reason'].startswith('ACTION_TIMEOUT: TimeoutError') and not s['infrastructure_error'] and s['score_available'])

class LocateTimeoutWorld(FakeWorld):
    def rev_locate(self, tid, action, target, **p): raise TimeoutError('Unity RPC timeout: REV_LOCATE')
s, ev = one(LocateTimeoutWorld(), unit_for('no_fault', 'revocable'))
check('S12_other_timeouts_stay_infrastructure', s['infrastructure_error'] and not s['termination_reason'].startswith('ACTION_TIMEOUT'))

clk = VirtualClock(); saved = (kernel.time, shared_execution.time)
kernel.time = shared_execution.time = clk
class SlowWorld(FakeWorld):
    def call(self, verb, trial_id='', timeout=30, **p):
        if verb == 'REV_ACTION' and p.get('action') == 'PLACE':
            clk.advance(timeout); raise TimeoutError('Unity RPC timeout: REV_ACTION')
        clk.advance(200 if verb == 'REV_CONFIG' else 0.1); return super().call(verb, trial_id, timeout, **p)  # timeout at PLACE = remaining budget
w = SlowWorld(); s, ev = one(w, unit_for('no_fault', 'revocable'))
check('S10_budget_expiry_is_BudgetExceeded_not_infra', s['termination_reason'] == 'BudgetExceeded: wall_time_budget' and not s['infrastructure_error'])
kernel.time, shared_execution.time = saved
kernel.time = types.SimpleNamespace(sleep=lambda s: None, perf_counter_ns=__import__('time').perf_counter_ns, monotonic=__import__('time').monotonic)

# runner + manager plan with scripted action timeout (unit 3) and infrastructure exclusion (unit 7)
mini = dict(m); mini['units'] = m['units'][:42]
class ScriptWorld(FakeWorld):
    def __init__(self, modes): super().__init__(); self.modes = modes
    def rev_config(self, tid, configuration, **p): self.mode = self.modes.get(tid); return super().rev_config(tid, configuration)
    def rev_locate(self, tid, action, target, **p):
        if self.mode == 'infra': raise TimeoutError('Unity RPC timeout: REV_LOCATE')
        return super().rev_locate(tid, action, target)
    def rev_action(self, tid, action, target, position, **p):
        if self.mode == 'action_timeout' and action == 'PICK': raise TimeoutError('Unity RPC timeout: REV_ACTION')
        return super().rev_action(tid, action, target, position)
modes = {mini['units'][3]['trial_id']: 'action_timeout', mini['units'][7]['trial_id']: 'infra'}
tmp = Path(tempfile.mkdtemp()); run = tmp/'formal_02'; start = 0; causes = []; plans = []
with contextlib.redirect_stdout(io.StringIO()):
    while start < 42:
        k = manager.segment_plan(start, 21, 42); plans.append(k)
        runner.execute(mini, k, 'x', run=run, rpc_factory=lambda: ScriptWorld(modes), check_source=False)
        done = len(runner.inspect_resume(run, mini))
        causes.append(manager.check_segment(start, k, done, runner.read(run/'progress.json'), mini['units'])); start = done
check('segments_end_early_and_realign', plans == [21, 17, 13, 21] and causes == ['action_timeout_restart_unity', 'infrastructure_exclusion', None, None])
check('exclusion_recorded_once', [e['trial_id'] for e in runner.exclusions(run)] == [mini['units'][7]['trial_id']])
manifest_, rows, checks = analyze.collect(run)
check('A1_audit_passes_with_exclusion', all(c['passed'] for c in checks) and len(rows) == 42)
r_by = {r['trial_id']: r for r in rows}
check('A1_rows_flag_timeout_and_exclusion', r_by[mini['units'][3]['trial_id']]['action_timeout'] and r_by[mini['units'][7]['trial_id']]['infrastructure_excluded']
      and sum(r['infrastructure_excluded'] for r in rows) == 1 and sum(r['action_timeout'] for r in rows) == 1)
(tmp/'seg').mkdir()
with contextlib.redirect_stdout(io.StringIO()):
    cp = analyze.checkpoint(run, 'seg', exec_dir=tmp); inf6 = analyze.final(run)
check('checkpoint_counts_A1', cp['audit_all_passed'] and cp['infrastructure_exclusions'] == 1 and cp['action_timeouts'] == 1)
check('final_drops_excluded_pair', inf6['trials'] == 41 and inf6['assigned_trials'] == 42 and len(inf6['infrastructure_exclusions']) == 1)
try: manager.check_segment(0, 21, 5, {'early_end': None}, mini['units']); check('short_segment_rejected', False)
except RuntimeError: check('short_segment_without_early_end_rejected', True)
try: manager.check_segment(5, 16, 5, {'early_end': None}, mini['units']); check('no_progress_rejected', False)
except RuntimeError: check('no_progress_rejected', True)
check('segment_plan_last_block', manager.segment_plan(830, 21, 840) == 10 and manager.segment_plan(819, 21, 840) == 21)
ex = run/'infrastructure_exclusions.json'; saved_ex = ex.read_text(encoding='utf-8'); ex.unlink()
try: runner.inspect_resume(run, mini); check('unregistered_infra_rejected', False)
except RuntimeError: check('unregistered_infra_trial_rejected', True)
ex.write_text(saved_ex, encoding='utf-8'); shutil.rmtree(tmp)

tmp = Path(tempfile.mkdtemp()); run = tmp/'formal_02'
modes = {u['trial_id']: 'infra' for u in mini['units'][:4]}
with contextlib.redirect_stdout(io.StringIO()):
    for i in range(3): runner.execute(mini, 21, 'x', run=run, rpc_factory=lambda: ScriptWorld(modes), check_source=False)
    try: runner.execute(mini, 21, 'x', run=run, rpc_factory=lambda: ScriptWorld(modes), check_source=False); halted = False
    except RuntimeError: halted = True
check('fourth_exclusion_halts', halted and (run/'halt.json').exists() and len(runner.exclusions(run)) == 4)
try: runner.inspect_resume(run, mini); check('halt_blocks_resume', False)
except RuntimeError: check('halt_blocks_resume', True)
shutil.rmtree(tmp)

# external interruption (reboot mid-trial): author-invoked marking, then resume
tmp = Path(tempfile.mkdtemp()); run = tmp/'formal_02'
with contextlib.redirect_stdout(io.StringIO()):
    runner.execute(mini, 2, 'x', run=run, rpc_factory=FakeWorld, check_source=False)
u2 = mini['units'][2]['trial_id']
runner.create_json(run/'intents'/(u2+'.json'), {'started_utc': runner.now()}); (run/u2).mkdir()
(run/u2/'events.jsonl').write_text('{"event": "protocol"}\n{"event": "rpc", "ver', encoding='utf-8')   # truncated by power loss
try: runner.inspect_resume(run, mini); check('unsealed_started_blocks', False)
except RuntimeError: check('unsealed_started_trial_blocks_resume', True)
try: runner.mark_interrupted(mini, mini['units'][3]['trial_id'], run=run); check('mark_wrong_trial', False)
except RuntimeError: check('mark_interrupted_only_first_unsealed', True)
runner.mark_interrupted(mini, u2, run=run)
with contextlib.redirect_stdout(io.StringIO()):
    runner.execute(mini, 4, 'x', run=run, rpc_factory=FakeWorld, check_source=False)
manifest_, rows, checks = analyze.collect(run)
check('interrupted_trial_excluded_and_resumed', len(rows) == 7 and all(c['passed'] for c in checks)
      and [r['trial_id'] for r in rows if r['infrastructure_excluded']] == [u2])
shutil.rmtree(tmp)
print(f'{len(passed)} offline checks passed; 0 Unity calls, 0 model calls')
