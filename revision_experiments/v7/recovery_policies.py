"""Three distinct execution representations over the same online observations.

These are development recovery policies, not yet wired to the camera/robot loop.
A3 explicitly refuses invalidated/non-prefix progress; BT/FSM recheck goals.
"""
from dataclasses import dataclass
import xml.etree.ElementTree as ET
from contracts import Action, ContractError, Feedback, Sequence, Fallback, Retry, TickNode


@dataclass(frozen=True)
class Goal:
    id: str
    object_id: str
    container_id: str


@dataclass(frozen=True)
class Decision:
    status: str
    action: Action | None = None
    residual_xml: str | None = None


class Policy:
    def __init__(self, goals):
        self.goals = tuple(goals)
        if not self.goals or len({g.id for g in self.goals}) != len(self.goals):
            raise ContractError('nonempty unique goals required')

    def guard(self, obs):
        if not isinstance(obs, Feedback) or obs.channel != 'controller_feedback':
            raise ContractError('common online feedback is required')
        if not obs.verified_goals <= {g.id for g in self.goals}:
            raise ContractError('unknown verified goals')
        if obs.holding_state == 'UNKNOWN':
            return Decision('WAIT_FOR_OBSERVATION')
        if all(g.id in obs.verified_goals for g in self.goals):
            return Decision('PLAN_COMPLETE')
        pending = next(g for g in self.goals if g.id not in obs.verified_goals)
        if obs.holding_state == 'HOLDING' and obs.holding_id != pending.object_id:
            return Decision('HOLDING_CONFLICT')
        return None


class ResidualPolicy(Policy):
    """A3 revision: validated flat plan + verified prefix + observed holding."""
    def __init__(self, goals):
        super().__init__(goals)
        root = ET.Element('Sequence')
        for goal in self.goals:
            ET.SubElement(root,'Action',name='PICK',target=goal.object_id)
            ET.SubElement(root,'Action',name='PLACE',target=goal.container_id)
        self.original_xml = ET.tostring(root, encoding='unicode')
        self.previously_verified = frozenset()

    def decide(self, obs):
        stopped = self.guard(obs)
        if stopped:
            return stopped
        if self.previously_verified - obs.verified_goals:
            return Decision('PREFIX_INVALIDATED')
        prefix = 0
        for goal in self.goals:
            if goal.id not in obs.verified_goals:
                break
            prefix += 1
        if any(g.id in obs.verified_goals for g in self.goals[prefix:]):
            return Decision('NON_PREFIX_STATE')
        self.previously_verified = obs.verified_goals
        cursor = 2*prefix + int(obs.holding_state == 'HOLDING')
        leaves = list(ET.fromstring(self.original_xml))
        residual = ET.Element('Sequence')
        residual.extend(leaves[cursor:])
        first = residual[0]
        return Decision('ACTION', Action(first.attrib['name'],first.attrib['target']),ET.tostring(residual,encoding='unicode'))


class StateMachinePolicy(Policy):
    """Task-state baseline: rescan verified goals, then ENSURE_PICK/ENSURE_PLACE."""
    def __init__(self, goals):
        super().__init__(goals)
        self.state, self.active_goal = 'CHECK_GOALS', None

    def decide(self, obs):
        stopped = self.guard(obs)
        if stopped:
            self.state = stopped.status
            return stopped
        self.state = 'CHECK_GOALS'
        for goal in self.goals:
            if goal.id in obs.verified_goals:
                continue
            self.active_goal = goal.id
            if obs.holding_state == 'HOLDING':
                self.state = 'ENSURE_PLACE'
                return Decision('ACTION',Action('PLACE',goal.container_id))
            self.state = 'ENSURE_PICK'
            return Decision('ACTION',Action('PICK',goal.object_id))
        raise ContractError('unreachable state')


class Condition(TickNode):
    def __init__(self,predicate):
        self.predicate=predicate

    def tick(self):
        return 'SUCCESS' if self.predicate() else 'FAILURE'


class RequestAction(TickNode):
    def __init__(self,owner,action):
        self.owner,self.action=owner,action

    def tick(self):
        # Dispatch is asynchronous. A caller must return the outcome on the next tick.
        if self.owner.failed_action == self.action:
            self.owner.failed_action = None
            return 'FAILURE'
        self.owner.requested=self.action
        return 'RUNNING'


class BehaviorTreePolicy(Policy):
    """Reactive goal guards with actual Fallback and bounded Retry semantics."""
    def __init__(self, goals, max_attempts=3):
        super().__init__(goals)
        self.obs, self.requested, self.failed_action = None,None,None
        subtrees=[]
        for goal in self.goals:
            achieved=Condition(lambda g=goal: g.id in self.obs.verified_goals)
            holding=Condition(lambda g=goal: self.obs.holding_state=='HOLDING' and self.obs.holding_id==g.object_id)
            pick=RequestAction(self,Action('PICK',goal.object_id))
            place=RequestAction(self,Action('PLACE',goal.container_id))
            subtrees.append(Fallback([achieved,Retry(Sequence([Fallback([holding,pick]),place]),max_attempts)]))
        self.root=Sequence(subtrees)

    def report_failure(self, action):
        self.failed_action=action

    def decide(self, obs):
        stopped=self.guard(obs)
        if stopped:
            return stopped
        self.obs,self.requested=obs,None
        status=self.root.tick()
        if self.requested is not None:
            return Decision('ACTION',self.requested)
        return Decision('RETRY_TICK' if status=='RUNNING' else 'BUDGET_EXHAUSTED' if status=='FAILURE' else 'PLAN_COMPLETE')
