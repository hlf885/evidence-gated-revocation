import json
from pathlib import Path
import tempfile
import unittest
from contracts import (ContractError, EntityRegistry, validate_sequence, Feedback,
                       ProgressLedger, TrialJournal, Sequence, Fallback, Retry, TickNode)

ENTITIES = [
    {'id': 'red_cube', 'kind': 'object', 'aliases': ['red cube', 'RedCube']},
    {'id': 'green_ball', 'kind': 'object', 'aliases': ['green ball']},
    {'id': 'plate', 'kind': 'container', 'aliases': ['white plate']},
]
VALID = '<Sequence><Action name="PICK" target="red cube"/><Action name="PLACE" target="plate"/></Sequence>'


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.registry = EntityRegistry(ENTITIES)

    def test_valid_plan_resolves_registered_alias(self):
        actions = validate_sequence(VALID, self.registry)
        self.assertEqual([(a.name, a.target) for a in actions], [('PICK', 'red_cube'), ('PLACE', 'plate')])

    def test_reject_invalid_plans(self):
        cases = ['<Sequence/>', '<Sequence>', VALID.replace('PICK', 'DANCE'),
                 VALID.replace('PICK', 'NOT_PICK'), VALID.replace('red cube', 'unseen'),
                 VALID.replace('red cube', 'plate'), VALID.replace('name="PICK"', ''),
                 '<Fallback>'+VALID+'</Fallback>', '<Sequence>'+VALID+'</Sequence>',
                 '<Sequence><Action name="PLACE" target="plate"/></Sequence>',
                 VALID.replace('name="PLACE" target="plate"', 'name="PICK" target="green ball"'),
                 '<Sequence><Action name="PICK" target="red cube"/></Sequence>',
                 VALID.replace('<Sequence>', '<Sequence>unexpected'),
                 VALID.replace('name="PICK"', 'name="PICK" ignored="x"')]
        for xml in cases:
            with self.subTest(xml=xml), self.assertRaises(ContractError):
                validate_sequence(xml, self.registry)

    def test_recovered_holding_requires_place_without_repick(self):
        xml = '<Sequence><Action name="PLACE" target="plate"/></Sequence>'
        self.assertEqual(len(validate_sequence(xml, self.registry, holding='red_cube')), 1)
        with self.assertRaises(ContractError):
            validate_sequence(VALID, self.registry, holding='red_cube')

    def test_duplicate_alias_is_not_silently_selected(self):
        with self.assertRaises(ContractError):
            EntityRegistry(ENTITIES+[{'id': 'different', 'kind': 'object', 'aliases': ['red cube']}])


class StateTests(unittest.TestCase):
    def test_unknown_is_preserved(self):
        feedback = Feedback('t', 0, 'UNKNOWN', None, frozenset())
        self.assertEqual(feedback.holding_state, 'UNKNOWN')

    def test_scoring_channel_cannot_be_controller_feedback(self):
        with self.assertRaises(ContractError):
            Feedback('t', 0, 'EMPTY', None, frozenset(), channel='offline_score')

    def test_contradictory_holding_rejected(self):
        for state, obj in [('EMPTY', 'red_cube'), ('UNKNOWN', 'red_cube'), ('HOLDING', None)]:
            with self.subTest(state=state), self.assertRaises(ContractError):
                Feedback('t', 0, state, obj, frozenset())

    def test_progress_can_be_invalidated(self):
        ledger = ProgressLedger('t', ('g1', 'g2'))
        ledger.observe(Feedback('t', 0, 'EMPTY', None, frozenset({'g1'})))
        invalidated = ledger.observe(Feedback('t', 1, 'EMPTY', None, frozenset()))
        self.assertEqual(invalidated, {'g1'})
        self.assertFalse(ledger.committed)

    def test_stale_cross_trial_and_unknown_goals_rejected(self):
        ledger = ProgressLedger('t', ('g1',))
        ledger.observe(Feedback('t', 1, 'EMPTY', None, frozenset()))
        for f in [Feedback('t', 1, 'EMPTY', None, frozenset()),
                  Feedback('other', 2, 'EMPTY', None, frozenset()),
                  Feedback('t', 2, 'EMPTY', None, frozenset({'missing'}))]:
            with self.subTest(feedback=f), self.assertRaises(ContractError):
                ledger.observe(f)


class JournalTests(unittest.TestCase):
    def test_invalid_plan_is_a_recorded_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'trial.jsonl'
            journal = TrialJournal(path, 't', 'A3', ['g1'])
            try:
                validate_sequence('<Sequence/>', EntityRegistry(ENTITIES))
            except ContractError as exc:
                journal.emit('plan_rejected', reason=str(exc))
                self.assertFalse(journal.finish('invalid_initial_plan'))
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r['event'] for r in records], ['trial_started', 'plan_rejected', 'trial_finished'])
            self.assertFalse(records[-1]['score_available'])

    def test_completed_execution_does_not_imply_success(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = TrialJournal(Path(temp)/'trial.jsonl', 't', 'A3', ['g1'])
            score = {'channel': 'offline_score', 'trialId': 't', 'taskSuccess': False, 'progress': 0,
                     'goals': [{'goalId': 'g1', 'satisfied': False}]}
            self.assertFalse(journal.finish('executor_completed', score))

    def test_all_methods_use_same_goal_truth(self):
        with tempfile.TemporaryDirectory() as temp:
            for method in ['A0', 'A3', 'BT_Retry', 'FSM_State', 'A_LLM']:
                journal = TrialJournal(Path(temp)/(method+'.jsonl'), 't', method, ['g1', 'g2'])
                score = {'channel': 'offline_score', 'trialId': 't', 'taskSuccess': True, 'progress': 1,
                         'goals': [{'goalId': 'g1', 'satisfied': True}, {'goalId': 'g2', 'satisfied': True}]}
                self.assertTrue(journal.finish('budget_end', score))

    def test_incomplete_or_forged_summary_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = TrialJournal(Path(temp)/'trial.jsonl', 't', 'FSM_State', ['g1'])
            score = {'channel': 'offline_score', 'trialId': 't', 'taskSuccess': True, 'progress': 1, 'goals': []}
            with self.assertRaises(ContractError):
                journal.finish('completed', score)
            score['goals'] = [{'goalId': 'g1', 'satisfied': False}]
            with self.assertRaises(ContractError):
                journal.finish('completed', score)
            journal.finish('scoring_error')


class Leaf(TickNode):
    def __init__(self, statuses):
        self.statuses, self.calls = list(statuses), 0

    def tick(self):
        self.calls += 1
        return self.statuses[min(self.calls-1, len(self.statuses)-1)]


class TreeTests(unittest.TestCase):
    def test_fallback_does_not_execute_second_success_branch(self):
        first, second = Leaf(['SUCCESS']), Leaf(['SUCCESS'])
        self.assertEqual(Fallback([first, second]).tick(), 'SUCCESS')
        self.assertEqual(second.calls, 0)

    def test_fallback_running_blocks_later_branch(self):
        first, second = Leaf(['RUNNING']), Leaf(['SUCCESS'])
        self.assertEqual(Fallback([first, second]).tick(), 'RUNNING')
        self.assertEqual(second.calls, 0)

    def test_fallback_reaches_recovery_only_after_failure(self):
        first, second = Leaf(['FAILURE']), Leaf(['SUCCESS'])
        self.assertEqual(Fallback([first, second]).tick(), 'SUCCESS')
        self.assertEqual(second.calls, 1)

    def test_sequence_stops_at_failure(self):
        first, second = Leaf(['FAILURE']), Leaf(['SUCCESS'])
        self.assertEqual(Sequence([first, second]).tick(), 'FAILURE')
        self.assertEqual(second.calls, 0)

    def test_retry_budget_counts_actual_failures(self):
        leaf = Leaf(['RUNNING', 'FAILURE', 'FAILURE', 'FAILURE'])
        retry = Retry(leaf, 2)
        self.assertEqual([retry.tick() for _ in range(5)], ['RUNNING', 'RUNNING', 'FAILURE', 'FAILURE', 'FAILURE'])
        self.assertEqual(leaf.calls, 3)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        from recovery_policies import Goal, ResidualPolicy, BehaviorTreePolicy, StateMachinePolicy
        self.goals = [Goal('g1', 'red_cube', 'plate'), Goal('g2', 'green_ball', 'plate')]
        self.types = [ResidualPolicy, BehaviorTreePolicy, StateMachinePolicy]

    def test_shared_progress_and_holding_decisions(self):
        from contracts import Action
        for kind in self.types:
            for held, expected in [(None, Action('PICK', 'green_ball')), ('green_ball', Action('PLACE', 'plate'))]:
                with self.subTest(policy=kind.__name__, held=held):
                    obs = Feedback('t', 0, 'HOLDING' if held else 'EMPTY', held, frozenset({'g1'}))
                    self.assertEqual(kind(self.goals).decide(obs).action, expected)

    def test_unknown_state_never_defaults_to_empty(self):
        for kind in self.types:
            decision = kind(self.goals).decide(Feedback('t', 0, 'UNKNOWN', None, frozenset()))
            self.assertEqual(decision.status, 'WAIT_FOR_OBSERVATION')
            self.assertIsNone(decision.action)

    def test_residual_policy_declares_invalidated_prefix_boundary(self):
        from recovery_policies import ResidualPolicy, BehaviorTreePolicy, StateMachinePolicy
        from contracts import Action
        for kind in [ResidualPolicy, BehaviorTreePolicy, StateMachinePolicy]:
            policy = kind(self.goals)
            policy.decide(Feedback('t', 0, 'EMPTY', None, frozenset({'g1'})))
            decision = policy.decide(Feedback('t', 1, 'EMPTY', None, frozenset()))
            if kind is ResidualPolicy:
                self.assertEqual(decision.status, 'PREFIX_INVALIDATED')
            else:
                self.assertEqual(decision.action, Action('PICK', 'red_cube'))

    def test_bt_action_failure_consumes_bounded_retry(self):
        from recovery_policies import BehaviorTreePolicy
        policy = BehaviorTreePolicy(self.goals, max_attempts=1)
        obs = Feedback('t', 0, 'EMPTY', None, frozenset())
        decision = policy.decide(obs)
        policy.report_failure(decision.action)
        self.assertEqual(policy.decide(obs).status, 'BUDGET_EXHAUSTED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
