"""Shared experiment contracts. No model calls or original application imports.

Offline goal scores may finalize a trial, but cannot be passed to a recovery
policy as controller feedback. All policies must use the same online interface.
"""
from dataclasses import dataclass, field, asdict
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class Action:
    name: str
    target: str


class EntityRegistry:
    def __init__(self, entities):
        self.by_id, self.aliases = {}, {}
        for entity in entities:
            key = entity['id']
            if not isinstance(key, str) or not key.strip() or key in self.by_id:
                raise ContractError('empty or duplicate entity id')
            if entity['kind'] not in ('object', 'container'):
                raise ContractError('unsupported entity kind')
            aliases = {a.strip().lower() for a in [key, *entity.get('aliases', [])]}
            if '' in aliases or aliases.intersection(self.aliases):
                raise ContractError('empty or ambiguous entity alias')
            self.by_id[key] = dict(entity)
            self.aliases.update({a: key for a in aliases})

    def resolve(self, name, kind):
        if not isinstance(name, str) or name.strip().lower() not in self.aliases:
            raise ContractError('unregistered target')
        key = self.aliases[name.strip().lower()]
        if self.by_id[key]['kind'] != kind:
            raise ContractError('wrong target kind')
        return key


def validate_sequence(xml, registry, *, holding=None, max_actions=64):
    """Only a flat, nonempty Sequence of exact PICK/PLACE leaves is supported.

    None means positively observed EMPTY. UNKNOWN must be handled before parsing.
    Validate physical action order without claiming semantic task completion.
    """
    if not isinstance(xml, str) or len(xml) > 65536 or '<!DOCTYPE' in xml.upper():
        raise ContractError('invalid or oversized plan')
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ContractError('malformed XML') from exc
    if root.tag != 'Sequence' or root.attrib or (root.text or '').strip():
        raise ContractError('only a flat Sequence is supported')
    if not 1 <= len(root) <= max_actions:
        raise ContractError('empty or oversized action sequence')
    held = registry.resolve(holding, 'object') if holding is not None else None
    actions = []
    for node in root:
        if node.tag != 'Action' or len(node) or set(node.attrib) != {'name', 'target'}:
            raise ContractError('unsupported node or attributes')
        if (node.text or '').strip() or (node.tail or '').strip():
            raise ContractError('unexpected plan text')
        name = node.attrib['name']
        if name not in ('PICK', 'PLACE'):
            raise ContractError('unknown action')
        target = registry.resolve(node.attrib['target'], 'object' if name == 'PICK' else 'container')
        if name == 'PICK':
            if held is not None:
                raise ContractError('PICK while holding an object')
            held = target
        else:
            if held is None:
                raise ContractError('PLACE with an empty gripper')
            held = None
        actions.append(Action(name, target))
    if held is not None:
        raise ContractError('this placement-task protocol requires a final release')
    return tuple(actions)


@dataclass(frozen=True)
class Feedback:
    trial_id: str
    sequence: int
    holding_state: str
    holding_id: str | None
    verified_goals: frozenset[str]
    channel: str = 'controller_feedback'

    def __post_init__(self):
        if self.channel != 'controller_feedback':
            raise ContractError('offline task scores are not controller feedback')
        if self.holding_state not in ('EMPTY', 'HOLDING', 'UNKNOWN'):
            raise ContractError('invalid holding state')
        if (self.holding_state == 'HOLDING') != bool(self.holding_id):
            raise ContractError('inconsistent holding observation')
        if self.sequence < 0:
            raise ContractError('negative observation sequence')


@dataclass
class ProgressLedger:
    """Committed progress comes from current online verification, never dispatch."""
    trial_id: str
    goal_ids: tuple[str, ...]
    committed: frozenset[str] = frozenset()
    last_sequence: int = -1
    events: list = field(default_factory=list)

    def observe(self, feedback):
        if feedback.trial_id != self.trial_id or feedback.sequence <= self.last_sequence:
            raise ContractError('stale or cross-trial feedback')
        if not feedback.verified_goals <= set(self.goal_ids):
            raise ContractError('unknown verified goal')
        invalidated = self.committed - feedback.verified_goals
        self.events.append({'stage': 'verified', 'sequence': feedback.sequence,
                            'committed': sorted(feedback.verified_goals),
                            'invalidated': sorted(invalidated)})
        self.committed = feedback.verified_goals
        self.last_sequence = feedback.sequence
        return invalidated


class TrialJournal:
    """Start before parsing/model inference so all scheduled units are accounted for."""
    def __init__(self, path, trial_id, method, expected_goal_ids):
        self.path = Path(path)
        self.trial_id = trial_id
        self.expected_goal_ids = tuple(expected_goal_ids)
        if not self.expected_goal_ids or len(set(self.expected_goal_ids)) != len(self.expected_goal_ids):
            raise ContractError('invalid expected goals')
        self.started = time.perf_counter()
        self.closed = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('x', encoding='utf-8')
        self.emit('trial_started', method=method)

    def emit(self, event, **data):
        if self.closed:
            raise ContractError('trial already finalized')
        self.handle.write(json.dumps({'trial_id': self.trial_id, 'event': event,
            'elapsed_s': time.perf_counter()-self.started, **data}, ensure_ascii=False, allow_nan=False)+'\n')
        self.handle.flush()

    def finish(self, reason, score=None):
        success, progress = False, None
        if score is not None:
            if score.get('channel') != 'offline_score' or score.get('trialId') != self.trial_id:
                raise ContractError('wrong score source/trial')
            goals = score.get('goals', [])
            ids = [g.get('goalId') for g in goals]
            if len(ids) != len(set(ids)) or set(ids) != set(self.expected_goal_ids):
                raise ContractError('missing, duplicate or extra goal scores')
            if any(type(g.get('satisfied')) is not bool for g in goals):
                raise ContractError('invalid goal score type')
            progress = sum(g['satisfied'] for g in goals)/len(goals)
            success = all(g['satisfied'] for g in goals)
            # Recompute instead of trusting an implementation-specific summary flag.
            if score.get('taskSuccess') is not success or not math.isclose(score.get('progress', -1), progress, abs_tol=1e-6):
                raise ContractError('inconsistent offline score summary')
        self.emit('trial_finished', termination_reason=reason, success=success, final_progress=progress,
                  score_available=score is not None)
        self.handle.close()
        self.closed = True
        return success


def independent_score_summary(records):
    """Descriptive counts only. No CI or independence claim for fixture data."""
    return {'scheduled_trials': len(records), 'successes': sum(r['success'] for r in records),
            'unscored': sum(not r['score_available'] for r in records)}


class TickNode:
    def tick(self):
        raise NotImplementedError


class Sequence(TickNode):
    def __init__(self, children):
        if not children:
            raise ContractError('empty BT Sequence')
        self.children = tuple(children)

    def tick(self):
        for child in self.children:
            status = child.tick()
            if status not in ('SUCCESS', 'FAILURE', 'RUNNING'):
                raise ContractError('invalid BT status')
            if status != 'SUCCESS':
                return status
        return 'SUCCESS'


class Fallback(Sequence):
    def tick(self):
        for child in self.children:
            status = child.tick()
            if status not in ('SUCCESS', 'FAILURE', 'RUNNING'):
                raise ContractError('invalid BT status')
            if status != 'FAILURE':
                return status
        return 'FAILURE'


class Retry(TickNode):
    """Bounded retry decorator; failures consumed once per tick, no hidden loop."""
    def __init__(self, child, max_attempts):
        if type(max_attempts) is not int or max_attempts < 1:
            raise ContractError('invalid retry budget')
        self.child, self.max_attempts, self.failures = child, max_attempts, 0

    def tick(self):
        if self.failures >= self.max_attempts:
            return 'FAILURE'
        status = self.child.tick()
        if status == 'FAILURE':
            self.failures += 1
            return 'FAILURE' if self.failures >= self.max_attempts else 'RUNNING'
        if status not in ('SUCCESS', 'RUNNING'):
            raise ContractError('invalid BT status')
        return status
