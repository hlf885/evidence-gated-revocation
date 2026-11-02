"""Revocation-only refresh of markers committed by accepted PLACE actions.

The online watchdog is simulator-derived contradiction evidence, not the
independent task scorer or a certificate that an unexecuted goal is complete.
"""
import math
from contracts import ContractError,Feedback

class CompletionMemory:
    def __init__(self,trial_id,goal_ids,*,revoke=True):
        if type(revoke) is not bool:raise ContractError('boolean revocation condition required')
        self.revoke=revoke
        self.trial_id=trial_id;self.goals=frozenset(goal_ids);self.committed=set();self.sequence=-1;self.time=-1;self.events=[];self.fresh=False
    def commit_placement(self,goal_id,accepted):
        if goal_id not in self.goals or accepted is not True:raise ContractError('accepted placement required')
        self.committed.add(goal_id)
        self.fresh=False
    def refresh(self,snapshot):
        # Clear stale markers before propagating any observation error.
        old=set(self.committed)
        try:
            if snapshot.get('channel')!='completion_watchdog' or snapshot.get('trialId')!=self.trial_id:
                raise ContractError('wrong feedback source/trial')
            sequence=snapshot['sequence'];now=snapshot['simulationTime']
            if type(sequence) is not int or sequence<=self.sequence or not math.isfinite(now) or now<self.time:
                raise ContractError('stale feedback')
            rows=snapshot['goals'];ids=[r['goalId'] for r in rows]
            if len(ids)!=len(set(ids)) or set(ids)!=self.goals:raise ContractError('incomplete or duplicate goal observations')
            if any(r['state'] not in ['CONSISTENT','INVALID','UNKNOWN'] for r in rows):raise ContractError('invalid goal observation')
            consistent={r['goalId'] for r in rows if r['state']=='CONSISTENT'}
            if self.revoke:self.committed.intersection_update(consistent)
            self.sequence=sequence;self.time=now;self.fresh=True
        except (ContractError,KeyError,TypeError,ValueError):
            self.committed.clear();self.fresh=False;self.events.append({'invalidated':sorted(old),'reason':'unusable_observation'})
            raise ContractError('completion observation unavailable or stale')
        invalidated=old-self.committed
        self.events.append({'invalidated':sorted(invalidated),'sequence':sequence,'retained':sorted(self.committed)})
        return invalidated
    def feedback(self,holding_state='EMPTY',holding_id=None):
        if not self.fresh:raise ContractError('fresh watchdog observation required')
        return Feedback(self.trial_id,self.sequence,holding_state,holding_id,frozenset(self.committed))
