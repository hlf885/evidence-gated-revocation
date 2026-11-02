"""Study C executor: the unmodified v7 StateMachinePolicy plus one holding-first extension.

v7 stops with HOLDING_CONFLICT whenever the gripper holds an object other than the first
pending goal's object. In v8/v9 this state was unreachable in the displacement condition
(the shift happens while the gripper is empty), but synthetic revocations can create it
while an object is held. To keep Study C about completion-state rules rather than this
guard, the executor places a held object into its own goal container when that goal is
still pending. In every state where v7 returns any other decision, the decision is
identical (checked exhaustively in test_offline.py).
"""
from pathlib import Path
import sys
V7 = Path(__file__).resolve().parent.parent/'v7'
if str(V7) not in sys.path:
    sys.path.insert(0, str(V7))
from contracts import Action                                   # noqa: E402
from recovery_policies import Decision, StateMachinePolicy     # noqa: E402


class HoldingFirstStateMachine(StateMachinePolicy):
    def decide(self, obs):
        decision = super().decide(obs)
        if decision.status != 'HOLDING_CONFLICT':
            return decision
        held_goal = next((g for g in self.goals if g.object_id == obs.holding_id), None)
        if held_goal is not None and held_goal.id not in obs.verified_goals:
            self.state, self.active_goal = 'ENSURE_PLACE_HELD', held_goal.id
            return Decision('ACTION', Action('PLACE', held_goal.container_id))
        return decision
