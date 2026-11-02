"""v3 (amendment A1). Stochastic stand-in for the Unity/PhysX world, used ONLY to generate predictions.

The real Study C control code (kernel.run_trial, memory rules, noise injection, FSM,
budgets) runs unchanged against this model. Only the physics is replaced by a small
probabilistic model calibrated from v8 three-goal trials (see README.md):
  PICK  failure 2.7% (30/1110); PLACE failure 0.1% (1/1000)
  durations N(8.55, 2.0) s and N(6.95, 1.5) s: the v8 per-primitive round trips (10.7/8.7 s)
  scaled by 0.8 so that a no-fault three-goal trial totals ~53.5 s, as observed in v8
  PLACE accepted with overlap < 0.9 (object still in container): 1%  -> watchdog INVALID,
        independent score satisfied (the 'rejected but satisfied' path seen in v8/v9)
  transient settling UNKNOWN of an object already in the same container after a PLACE: 1%
v2 adds two physical failure paths and per-replicate parameter uncertainty (see predict.py):
  post_place_slip  : placed object ends outside the container (not accepted, unsatisfied)
  contact_displace : placing into a container pushes an object already there out of it
v3 (A1): localized positions lie inside the A1 workspace (the v2 placeholder (.1,.1,.1) would
now be rejected by the S11 guard); a rare REV_ACTION timeout path (per-action probability
'action_timeout', consuming the kernel's RPC timeout) exercises S10/S12. The S9 fault
precondition is applied by the real kernel, not by this model.
Nothing here is experimental data.
"""
import hashlib, json, random


class VirtualClock:
    def __init__(self): self.t = 0.0
    def monotonic(self): return self.t
    def sleep(self, s): self.t += max(0.0, s)
    def advance(self, s): self.t += max(0.0, s)
    def perf_counter_ns(self): return int(self.t*1e9)
    def perf_counter(self): return self.t


P = {'pick_fail': 30/1110, 'place_fail': 1/1000, 'place_low_overlap': 0.01, 'settle_unknown': 0.01,
     'post_place_slip': 0.0, 'contact_displace': 0.0, 'duration_scale': 1.0, 'action_timeout': 0.0,
     'pick_s': (8.55, 2.0), 'place_s': (6.95, 1.5), 'observe_s': 0.12, 'locate_s': 0.15, 'config_s': 1.5}


class StochasticWorld:
    def __init__(self, clock, model_seed, params=None):
        self.clock = clock; self.model_seed = model_seed; self.p = dict(P, **(params or {})); self.rng = None

    def call(self, verb, trial_id='', timeout=30, **p):
        self.timeout = timeout
        r = {'pong': True} if verb == 'REV_PING' else getattr(self, verb.lower())(trial_id, **p)
        r.setdefault('ok', True); return r

    def close(self): pass
    def rev_reset(self, tid, **p): self.clock.advance(0.5); return {}

    def rev_config(self, tid, configuration, **p):
        c = configuration; self.tid = tid
        h = hashlib.sha256(f'{self.model_seed}|{tid}'.encode()).digest()
        self.rng = random.Random(int.from_bytes(h[:8], 'big'))
        self.goals = c['goals']; self.cont = {g['objectId']: g['containerId'] for g in self.goals}
        self.faults = [dict(f, attempted=False, applied=False, observedEffect=False) for f in c['faults']]
        self.where = {e['id']: 'table' for e in c['entities'] if e['kind'] == 'object'}
        self.low_overlap = set(); self.unknown_once = set(); self.held = None; self.seq = 0
        self.clock.advance(self.p['config_s'])
        return {'initialState': [{'id': k, 'position': {'x': 0, 'y': 0, 'z': 0}} for k in self.where]}

    def _state(self, o):
        g_cont = self.cont[o]
        if self.held == o: return 'INVALID'
        if self.where[o] != g_cont or o in self.low_overlap: return 'INVALID'
        if o in self.unknown_once: return 'UNKNOWN'
        return 'CONSISTENT'

    def rev_observe_audit(self, tid, **p):
        self.seq += 1; self.clock.advance(self.p['observe_s']); t = self.clock.t
        watch = {'channel': 'completion_watchdog', 'trialId': tid, 'sequence': self.seq, 'simulationTime': t,
                 'goals': [{'goalId': g['id'], 'state': self._state(g['objectId']), 'reason': 'model', 'overlap': 1.0} for g in self.goals]}
        self.unknown_once.clear()
        goals = [{'goalId': g['id'], 'objectId': g['objectId'], 'reason': 'model',
                  'satisfied': self.held != g['objectId'] and self.where[g['objectId']] == g['containerId']} for g in self.goals]
        k = sum(x['satisfied'] for x in goals)
        score = {'channel': 'offline_score', 'trialId': tid, 'simulationTime': t, 'goals': goals,
                 'taskSuccess': k == len(goals), 'progress': k/len(goals)}
        hold = {'channel': 'controller_feedback', 'state': 'HOLDING' if self.held else 'EMPTY', **({'objectId': self.held} if self.held else {})}
        return {'watchdog': watch, 'holding': hold, 'score': score}

    def rev_locate(self, tid, action, target, **p):
        self.clock.advance(self.p['locate_s'])
        return {'location': {'channel': 'controlled_simulator_observation', 'action': action, 'target': target, 'position': {'x': 0.0, 'y': 0.72, 'z': 0.05}}}

    def rev_disturb(self, tid, eventId, anchor, **p):
        for f in self.faults:
            if f['id'] == eventId:
                f.update(attempted=True, applied=True, observedEffect=True, attemptedAt=self.clock.t, observedAt=self.clock.t+1)
                if f['type'] == 'object_shift':
                    self.where[f['targetId']] = 'table'; self.low_overlap.discard(f['targetId'])
        self.clock.advance(1.0)
        return {'faults': self.faults}

    def _dur(self, key):
        m, s = self.p[key]; k = self.p.get('duration_scale', 1.0); return max(2.0, self.rng.gauss(m*k, s*k))

    def rev_action(self, tid, action, target, position, **p):
        if self.rng.random() < self.p['action_timeout']:
            self.clock.advance(self.timeout); raise TimeoutError('Unity RPC timeout: REV_ACTION')
        if action == 'PICK':
            self.clock.advance(self._dur('pick_s'))
            if self.held is None and self.rng.random() >= self.p['pick_fail']:
                self.held = target; self.where[target] = 'gripper'; self.low_overlap.discard(target)
                return {'primitiveStatus': 'STATUS:GRASP_SUCCESS', 'motions': []}
            return {'primitiveStatus': 'STATUS:GRASP_FAILED', 'motions': []}
        self.clock.advance(self._dur('place_s'))
        if self.held is None or self.rng.random() < self.p['place_fail']:
            return {'primitiveStatus': 'STATUS:PLACE_FAILED', 'motions': []}
        o = self.held; self.held = None; self.where[o] = target
        overlap = 0.95
        for other, w in list(self.where.items()):
            if other != o and w == target:
                if self.rng.random() < self.p['contact_displace']:
                    self.where[other] = 'table'; self.low_overlap.discard(other)
                elif self.rng.random() < self.p['settle_unknown']:
                    self.unknown_once.add(other)
        if self.rng.random() < self.p['post_place_slip']:
            self.where[o] = 'table'; overlap = 0.3
        elif self.rng.random() < self.p['place_low_overlap']:
            self.low_overlap.add(o); overlap = 0.85
        names = {'bowl': 'bowl02', 'yellow_plate': 'plate02'}
        return {'primitiveStatus': 'STATUS:PLACE_SUCCESS|'+json.dumps({'container': names[target], 'bbox_overlap': overlap}), 'motions': []}

    def rev_hold(self, tid, **p):
        return {'holding': {'channel': 'controller_feedback', 'state': 'HOLDING' if self.held else 'EMPTY', **({'objectId': self.held} if self.held else {})}}

    def rev_end(self, tid, **p):
        return {'score': self.rev_observe_audit(tid)['score'], 'faults': self.faults}

    def rev_abort(self, tid, **p): return {}
