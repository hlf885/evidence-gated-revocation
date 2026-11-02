"""Study E rules: belief completion state with three assumed error rates, a fixed two-report debounce,
and the Study C/D rules; plus pure replay functions used by the offline audit.

belief_a02 / belief_a10 / belief_a30: BeliefMemory with assumed alpha = beta = 0.02 / 0.10 / 0.30
  (other parameters as Study D). By Proposition 3 they revoke after n* = 1 / 2 / 5 consecutive INVALID reports.
debounce2: the engineering heuristic. A committed goal is revoked after 2 consecutive refreshes that are not
  CONSISTENT (INVALID or UNKNOWN, as revocable treats them); a revoked goal returns only by a new accepted
  placement; while some committed goal has exactly one pending non-CONSISTENT report the kernel re-observes
  (same S13 hook and cap as the belief rule).
"""
from pathlib import Path
import math, sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from belief_rules import BeliefMemory, BELIEF_PARAMS, belief_step   # noqa: E402
from study_d_rules import make_noise, uniform, error_now           # noqa: E402,F401
import memory_rules as v10rules                                     # noqa: E402
from contracts import ContractError, Feedback                       # noqa: E402

BELIEF_VARIANTS = {'belief_a02': {'alpha': .02, 'beta': .02}, 'belief_a10': {}, 'belief_a30': {'alpha': .30, 'beta': .30}}
RULES = ('belief_a02', 'belief_a10', 'belief_a30', 'debounce2')   # revocable/reactive: anchors from Study D
DEBOUNCE_K = 2


def params(rule):
    return dict(BELIEF_PARAMS, **BELIEF_VARIANTS[rule])


class DebounceMemory:
    revoke = 'debounce2'

    def __init__(self, trial_id, goal_ids):
        self.trial_id = trial_id; self.goals = frozenset(goal_ids); self.committed = set(); self.count = {}
        self.sequence = -1; self.time = -1; self.events = []; self.fresh = False

    def commit_placement(self, goal_id, accepted):
        if goal_id not in self.goals or accepted is not True: raise ContractError('accepted placement required')
        self.committed.add(goal_id); self.count[goal_id] = 0; self.fresh = False

    def wants_reobservation(self):
        return self.fresh and any(self.count.get(g, 0) == 1 for g in self.committed)

    def refresh(self, snapshot):
        old = set(self.committed)
        try:
            if snapshot.get('channel') != 'completion_watchdog' or snapshot.get('trialId') != self.trial_id: raise ContractError('wrong feedback source/trial')
            sequence = snapshot['sequence']; now = snapshot['simulationTime']
            if type(sequence) is not int or sequence <= self.sequence or not math.isfinite(now) or now < self.time: raise ContractError('stale feedback')
            rows = snapshot['goals']; ids = [r['goalId'] for r in rows]
            if len(ids) != len(set(ids)) or set(ids) != self.goals: raise ContractError('incomplete or duplicate goal observations')
            if any(r['state'] not in ['CONSISTENT', 'INVALID', 'UNKNOWN'] for r in rows): raise ContractError('invalid goal observation')
            self.committed = debounce_step(self.committed, self.count, {r['goalId']: r['state'] for r in rows})
            self.sequence = sequence; self.time = now; self.fresh = True
        except (ContractError, KeyError, TypeError, ValueError):
            self.committed = set(); self.count = {}; self.fresh = False
            self.events.append({'invalidated': sorted(old), 'reason': 'unusable_observation'})
            raise ContractError('completion observation unavailable or stale')
        invalidated = old-self.committed
        self.events.append({'invalidated': sorted(invalidated), 'sequence': sequence, 'retained': sorted(self.committed)})
        return invalidated

    def feedback(self, holding_state='EMPTY', holding_id=None):
        if not self.fresh: raise ContractError('fresh watchdog observation required')
        return Feedback(self.trial_id, self.sequence, holding_state, holding_id, frozenset(self.committed))


def debounce_step(committed, count, states):
    """Pure: update consecutive non-CONSISTENT counts (in place) and return the new committed set."""
    out = set()
    for g in committed:
        count[g] = 0 if states[g] == 'CONSISTENT' else count.get(g, 0)+1
        if count[g] < DEBOUNCE_K: out.add(g)
    for g in list(count):
        if g not in out: count.pop(g, None)
    return out


def make_memory(rule, trial_id, goal_ids):
    if rule in BELIEF_VARIANTS: return BeliefMemory(trial_id, goal_ids, **BELIEF_VARIANTS[rule])
    if rule == 'debounce2': return DebounceMemory(trial_id, goal_ids)
    return v10rules.make_memory(rule, trial_id, goal_ids)


# ---- offline replay (used by trial_e.py) ----
def replay_new(): return {'bel': {}, 'com': set(), 'cnt': {}}


def replay_commit(rule, st, g):
    if rule in BELIEF_VARIANTS: st['bel'][g] = max(st['bel'].get(g, 0.0), params(rule)['b_commit'])
    if rule == 'debounce2': st['com'].add(g); st['cnt'][g] = 0


def replay_refresh(rule, st, states):
    """Return the predicted verified set for the Study E rules, or None for rules audited by the v10 logic."""
    if rule in BELIEF_VARIANTS:
        p = params(rule); st['bel'] = {g: belief_step(st['bel'].get(g, 0.0), s, p['alpha'], p['beta'], p['hazard']) for g, s in states.items()}
        return {g for g, v in st['bel'].items() if v >= p['tau']}
    if rule == 'debounce2':
        st['com'] = debounce_step(st['com'], st['cnt'], states); return set(st['com'])
    return None


def n_star(rule):
    """Proposition 3: consecutive INVALID reports needed to revoke a freshly committed goal (hazard ignored)."""
    p = params(rule); o0 = p['b_commit']/(1-p['b_commit'])
    return math.ceil(math.log(o0*(1-p['tau'])/p['tau'])/math.log((1-p['beta'])/p['alpha']))
