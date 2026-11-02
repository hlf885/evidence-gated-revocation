"""Study C completion-state rules and synthetic watchdog observation errors.

Only the controller-facing completion-watchdog snapshot is perturbed. Holding
feedback, localization, primitive acceptance and the independent offline score
are never touched. The v7 CompletionMemory is imported unmodified.
"""
from pathlib import Path
import copy, hashlib, math, sys

V7 = Path(__file__).resolve().parent.parent/'v7'
if str(V7) not in sys.path:
    sys.path.insert(0, str(V7))
from contracts import ContractError, Feedback          # noqa: E402  (v7, unmodified)
from completion_memory import CompletionMemory         # noqa: E402  (v7, unmodified)

RULES = ('commit_only', 'revocable', 'reactive')
NOISE_TYPES = ('none', 'false_invalid', 'false_consistent')


class ReactiveMemory:
    """No retained completion memory: verified := goals CONSISTENT in the current valid snapshot.

    Mirrors a behavior tree that re-checks every goal condition on each tick. Same
    validation and failure handling as v7 CompletionMemory, so only the rule differs.
    """
    revoke = None

    def __init__(self, trial_id, goal_ids):
        self.trial_id = trial_id; self.goals = frozenset(goal_ids)
        self.committed = set(); self.accepted_placements = set()
        self.sequence = -1; self.time = -1; self.events = []; self.fresh = False

    def commit_placement(self, goal_id, accepted):
        if goal_id not in self.goals or accepted is not True:
            raise ContractError('accepted placement required')
        # Logged for audit only; acceptance does not create completion under this rule.
        self.accepted_placements.add(goal_id)
        self.fresh = False

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
            self.committed = {r['goalId'] for r in rows if r['state'] == 'CONSISTENT'}
            self.sequence = sequence; self.time = now; self.fresh = True
        except (ContractError, KeyError, TypeError, ValueError):
            self.committed.clear(); self.fresh = False
            self.events.append({'invalidated': sorted(old), 'reason': 'unusable_observation'})
            raise ContractError('completion observation unavailable or stale')
        invalidated = old - self.committed
        self.events.append({'invalidated': sorted(invalidated), 'sequence': sequence, 'retained': sorted(self.committed)})
        return invalidated

    def feedback(self, holding_state='EMPTY', holding_id=None):
        if not self.fresh:
            raise ContractError('fresh watchdog observation required')
        return Feedback(self.trial_id, self.sequence, holding_state, holding_id, frozenset(self.committed))


def make_memory(rule, trial_id, goal_ids):
    if rule == 'commit_only':
        return CompletionMemory(trial_id, goal_ids, revoke=False)
    if rule == 'revocable':
        return CompletionMemory(trial_id, goal_ids, revoke=True)
    if rule == 'reactive':
        return ReactiveMemory(trial_id, goal_ids)
    raise ContractError('unknown completion rule: '+str(rule))


def uniform(protocol_id, seed, noise_type, refresh_index, goal_id):
    """Common random number in [0,1): identical across rules and nested across rates."""
    key = f'{protocol_id}|{seed}|{noise_type}|{refresh_index}|{goal_id}'.encode('utf-8')
    return int.from_bytes(hashlib.sha256(key).digest()[:8], 'big') / 2**64


class WatchdogNoise:
    def __init__(self, protocol_id, seed, noise_type, rate):
        if noise_type not in NOISE_TYPES:
            raise ContractError('unknown noise type')
        if noise_type == 'none' and rate != 0 or noise_type != 'none' and not 0 < rate < 1:
            raise ContractError('invalid noise rate')
        self.protocol_id = protocol_id; self.seed = seed; self.noise_type = noise_type; self.rate = rate
        self.refresh_index = 0; self.flip_count = 0

    def apply(self, snapshot):
        """Return (controller_snapshot, flips). The input snapshot is never mutated."""
        k = self.refresh_index; self.refresh_index += 1
        noisy = copy.deepcopy(snapshot); flips = []
        if self.noise_type == 'none':
            return noisy, flips
        for row in noisy.get('goals', []):
            true_state = row.get('state')
            eligible = (self.noise_type == 'false_invalid' and true_state == 'CONSISTENT') or \
                       (self.noise_type == 'false_consistent' and true_state in ('INVALID', 'UNKNOWN'))
            if not eligible:
                continue
            u = uniform(self.protocol_id, self.seed, self.noise_type, k, row['goalId'])
            if u < self.rate:
                row['state'] = 'INVALID' if self.noise_type == 'false_invalid' else 'CONSISTENT'
                row['reason'] = 'synthetic_observation_error'
                flips.append({'goalId': row['goalId'], 'true_state': true_state, 'reported_state': row['state'],
                              'refresh_index': k, 'u': u})
        self.flip_count += len(flips)
        return noisy, flips
