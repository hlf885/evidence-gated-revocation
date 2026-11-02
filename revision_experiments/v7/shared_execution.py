import json,time
from contracts import ContractError

class BudgetExceeded(RuntimeError):pass
class Budget:
    def __init__(self,seconds=240,max_actions=12,max_recoveries=3):
        self.started=time.monotonic();self.seconds=seconds;self.max_actions=max_actions;self.max_recoveries=max_recoveries
        self.actions=0;self.recoveries=0
    def remaining(self):
        value=self.seconds-(time.monotonic()-self.started)
        if value<=0:raise BudgetExceeded('wall_time_budget')
        return value
    def consume(self,kind):
        self.remaining();value=getattr(self,kind)+1
        if value>getattr(self,'max_'+kind):raise BudgetExceeded(kind+'_budget')
        setattr(self,kind,value)

def online_packet(response):
    # This allowlist is the only route from a paired audit response to the controller.
    return {'holding':response['holding'],'watchdog':response['watchdog']}

def accept(action,status,holding,registry,goal):
    if action.name=='PICK':
        return status.startswith('STATUS:GRASP_SUCCESS') and holding['state']=='HOLDING' and holding.get('objectId')==action.target
    if not status.startswith('STATUS:PLACE_SUCCESS') or '|' not in status:return False
    payload=json.loads(status.split('|',1)[1])
    try:container=registry.resolve(payload.get('container'),'container')
    except ContractError:return False
    return holding['state']=='EMPTY' and container==goal.container_id==action.target and payload.get('bbox_overlap',0)>=.9
