import unittest
from completion_memory import CompletionMemory
from contracts import ContractError
from recovery_policies import Goal,ResidualPolicy,BehaviorTreePolicy,StateMachinePolicy

def observation(sequence=1,states=('CONSISTENT','INVALID')):
    return {'channel':'completion_watchdog','trialId':'test','sequence':sequence,'simulationTime':sequence*.1,
            'goals':[{'goalId':g,'state':s} for g,s in zip(['g1','g2'],states)]}

class CompletionTests(unittest.TestCase):
    def setUp(self):self.memory=CompletionMemory('test',['g1','g2'])
    def test_geometry_cannot_create_unexecuted_completion(self):
        self.memory.refresh(observation(states=('CONSISTENT','CONSISTENT')));self.assertFalse(self.memory.committed)
    def test_dispatch_or_rejected_place_cannot_commit(self):
        with self.assertRaises(ContractError):self.memory.commit_placement('g1',False)
    def test_fresh_contradiction_revokes_completed_goal(self):
        self.memory.commit_placement('g1',True);self.memory.refresh(observation())
        self.assertEqual(self.memory.refresh(observation(2,('INVALID','INVALID'))),{'g1'})
    def test_unknown_invalidates_instead_of_retaining(self):
        self.memory.commit_placement('g1',True)
        self.assertEqual(self.memory.refresh(observation(states=('UNKNOWN','INVALID'))),{'g1'})
    def test_stale_feedback_clears_progress(self):
        self.memory.commit_placement('g1',True);self.memory.refresh(observation())
        with self.assertRaises(ContractError):self.memory.refresh(observation())
        self.assertFalse(self.memory.committed)
        with self.assertRaises(ContractError):self.memory.feedback()
    def test_incomplete_feedback_clears_progress(self):
        self.memory.commit_placement('g1',True);data=observation();data['goals'].pop()
        with self.assertRaises(ContractError):self.memory.refresh(data)
        self.assertFalse(self.memory.committed)
    def test_offline_score_and_other_trial_rejected(self):
        for key,value in [('channel','offline_score'),('trialId','other')]:
            with self.subTest(key=key):
                data=observation();data[key]=value;self.memory.commit_placement('g1',True)
                with self.assertRaises(ContractError):self.memory.refresh(data)
                self.assertFalse(self.memory.committed)
    def test_policies_do_not_skip_invalidated_prefix(self):
        goals=[Goal('g1','red_cube','bowl'),Goal('g2','green_ball','plate')]
        policies=[ResidualPolicy(goals),BehaviorTreePolicy(goals),StateMachinePolicy(goals)]
        self.memory.commit_placement('g1',True);self.memory.refresh(observation())
        for policy in policies:self.assertEqual(policy.decide(self.memory.feedback()).action.target,'green_ball')
        self.memory.refresh(observation(2,('INVALID','INVALID')))
        self.assertEqual(policies[0].decide(self.memory.feedback()).status,'PREFIX_INVALIDATED')
        for policy in policies[1:]:self.assertEqual(policy.decide(self.memory.feedback()).action.target,'red_cube')

if __name__=='__main__':unittest.main()
