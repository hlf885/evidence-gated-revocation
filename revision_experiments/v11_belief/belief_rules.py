"""v11: belief-based completion state (BCS) plus the Study C rules (imported unchanged from v10).

Each goal keeps b = P(goal still satisfied | history). A goal enters belief only through an accepted
PLACE (as in revocable memory), so a falsely CONSISTENT observation can never create completion.
Every controller-facing watchdog refresh applies
    predict:  b <- b * (1 - hazard)                          (the goal may have been undone)
    update:   CONSISTENT  b <- b(1-a) / (b(1-a) + (1-b) beta)
              INVALID     b <- b a     / (b a     + (1-b)(1-beta))
              UNKNOWN     no update (uninformative)
with assumed false-invalid rate a and false-consistent rate beta. Verified := {g : b_g >= tau}.
While some committed belief lies in the ambiguous band (lo, hi) the kernel re-observes (bounded).
Degenerate cases: a -> 1 (observations ignored) = commit_only; a = beta -> 0 = revocable on
INVALID; no memory (b reset to the current observation) = reactive.
"""
from pathlib import Path
import math, sys

HERE = Path(__file__).resolve().parent
V10 = HERE.parent/'v10_studyC'; V7 = HERE.parent/'v7'
for p in (V7, V10):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import memory_rules as v10rules                         # noqa: E402  (v10, unmodified)
from memory_rules import WatchdogNoise, uniform          # noqa: E402,F401
from contracts import ContractError, Feedback            # noqa: E402

RULES = ('belief', 'commit_only', 'revocable', 'reactive')
BELIEF_PARAMS = {'alpha': 0.10, 'beta': 0.10, 'hazard': 0.01, 'b_commit': 0.98, 'tau': 0.5, 'band': (0.2, 0.9)}


def belief_step(b, state, alpha, beta, hazard):
    """One predict+update step for a single goal; pure function used online and in the offline replay."""
    if b <= 0.0:
        return 0.0
    b = b*(1.0-hazard)
    if state == 'CONSISTENT':
        num = b*(1.0-alpha); den = num+(1.0-b)*beta
    elif state == 'INVALID':
        num = b*alpha; den = num+(1.0-b)*(1.0-beta)
    else:
        return b
    return num/den if den > 0 else b


class BeliefMemory:
    revoke = 'belief'

    def __init__(self, trial_id, goal_ids, **params):
        p = dict(BELIEF_PARAMS, **params)
        if not (0 <= p['alpha'] < 1 and 0 <= p['beta'] < 1 and 0 <= p['hazard'] < 1 and p['band'][0] < p['tau'] < p['band'][1]):
            raise ContractError('invalid belief parameters')
        self.p = p; self.trial_id = trial_id; self.goals = frozenset(goal_ids)
        self.b = {g: 0.0 for g in self.goals}; self.committed = set()
        self.sequence = -1; self.time = -1; self.events = []; self.fresh = False

    def _verified(self):
        return {g for g, v in self.b.items() if v >= self.p['tau']}

    def commit_placement(self, goal_id, accepted):
        if goal_id not in self.goals or accepted is not True:
            raise ContractError('accepted placement required')
        self.b[goal_id] = max(self.b[goal_id], self.p['b_commit']); self.committed = self._verified()
        self.fresh = False

    def wants_reobservation(self):
        lo, hi = self.p['band']
        return self.fresh and any(lo < v < hi for v in self.b.values())

    def refresh(self, snapshot):
        old = set(self.committed)
        try:
            if snapshot.get('channel') != 'completion_watchdog' or snapshot.get('trialId') != self.trial_id:
                raise ContractError('wrong feedback source/trial')
            sequence = snapshot['sequence']; now = snapshot['simulationTime']
            if type(sequence) is not int or sequence <= self.sequence or not math.isfinite(now) or now < self.time:
                raise ContractError('stale feedback')
            rows = snapshot['goals']; ids = [r['goalId'] for r in rows]
            if len(ids) != len(set(ids)) or set(ids) != self.goals:
                raise ContractError('incomplete or duplicate goal observations')
            if any(r['state'] not in ['CONSISTENT', 'INVALID', 'UNKNOWN'] for r in rows):
                raise ContractError('invalid goal observation')
            for r in rows:
                self.b[r['goalId']] = belief_step(self.b[r['goalId']], r['state'], self.p['alpha'], self.p['beta'], self.p['hazard'])
            self.committed = self._verified(); self.sequence = sequence; self.time = now; self.fresh = True
        except (ContractError, KeyError, TypeError, ValueError):
            # Same conservative failure handling as v7: an unusable observation clears completion.
            self.b = {g: 0.0 for g in self.goals}; self.committed = set(); self.fresh = False
            self.events.append({'invalidated': sorted(old), 'reason': 'unusable_observation'})
            raise ContractError('completion observation unavailable or stale')
        invalidated = old-self.committed
        self.events.append({'invalidated': sorted(invalidated), 'sequence': sequence, 'retained': sorted(self.committed),
                            'belief': dict(self.b)})
        return invalidated

    def feedback(self, holding_state='EMPTY', holding_id=None):
        if not self.fresh:
            raise ContractError('fresh watchdog observation required')
        return Feedback(self.trial_id, self.sequence, holding_state, holding_id, frozenset(self.committed))


def make_memory(rule, trial_id, goal_ids):
    if rule == 'belief':
        return BeliefMemory(trial_id, goal_ids)
    return v10rules.make_memory(rule, trial_id, goal_ids)
