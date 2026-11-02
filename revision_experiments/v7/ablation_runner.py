"""Same FSM, same execution path; only completion-memory revocation differs."""
from pathlib import Path
from dataclasses import asdict
import argparse,datetime,hashlib,json,math,time,zipfile
from contracts import ContractError,EntityRegistry,TrialJournal,validate_sequence
from completion_memory import CompletionMemory
from recovery_policies import Goal,StateMachinePolicy
from shared_execution import Budget,BudgetExceeded,online_packet,accept
from transport import UnityRPC
ROOT=Path(__file__).resolve().parent

def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def signature(obs):return obs.holding_state,obs.holding_id,obs.verified_goals
def configure(rpc,scenario,trial_id,manifest,budget):
    rpc.call('REV_RESET',timeout=min(30,budget.remaining()))
    return rpc.call('REV_CONFIG',trial_id,timeout=min(15,budget.remaining()),seed=scenario['seed'],recoveryCondition='preserve_resume',
        configuration={'trialId':trial_id,'entities':scenario['entities'],'goals':scenario['goals'],
            'faults':scenario['faults'],'evaluation':manifest['evaluation']},
        offsets=[{'id':key,'offset':value} for key,value in scenario['layout_offsets'].items()])

def core_paths():
    paths=list(ROOT.glob('*.py'))+[ROOT/'state_ablation_protocol.md',ROOT/'ablation_manifest.json',ROOT/'bootstrap_manifest.json']
    for folder,pattern in [('Assets/Scripts','*.cs'),('Assets/Scripts','*.cs.meta'),('Assets/Editor','*.cs'),('Assets/Scenes','*.unity'),('ProjectSettings','*.asset'),('Packages','*.json')]:
        paths+=list((ROOT/'UnityRevision'/folder).glob(pattern))
    return sorted(paths)

def freeze(run,manifest):
    paths=core_paths();hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    write(run/'run_metadata.json',{'scope':manifest['scope'],'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'core_sha256':hashes,'llm_calls':0,'vlm_calls':0,'localization':'privileged named simulator collider geometry'})
    write(run/'manifest.json',manifest)
    with zipfile.ZipFile(run/'frozen_source.zip','x',zipfile.ZIP_DEFLATED) as archive:
        for p in paths:archive.write(p,str(p.relative_to(ROOT)))

class FeedbackChanged(RuntimeError):pass

def run_trial(rpc,scenario,unit,manifest,run):
    tid=unit['trial_id'];memory_name=unit['memory'];folder=run/tid;folder.mkdir(exist_ok=False)
    journal=TrialJournal(folder/'events.jsonl',tid,memory_name,[g['id'] for g in scenario['goals']])
    budget=Budget(**manifest['budget']);configured=False;score=None;faults=[];infra=False;reason='unhandled'
    goals=[Goal(g['id'],g['objectId'],g['containerId']) for g in scenario['goals']]
    # The sole experimental switch. All action/observation/budget code is shared.
    if memory_name not in ['commit_only','revocable']:raise ContractError('unknown memory condition')
    memory=CompletionMemory(tid,[g.id for g in goals],revoke=memory_name=='revocable')
    policy=StateMachinePolicy(goals);registry=EntityRegistry(scenario['entities'])
    triggered=set();rpc_number=0;dispatches=0;unknown_waits=0
    def call(verb,**payload):
        nonlocal rpc_number
        response=rpc.call(verb,tid,timeout=min(60,budget.remaining()),**payload)
        rpc_number+=1;name=f'rpc_{rpc_number:03d}_{verb}.json'
        write(folder/name,{'verb':verb,'request':payload,'response':response});journal.emit('rpc',verb=verb,file=name)
        return response
    def paired(label):
        response=call('REV_OBSERVE_AUDIT')
        # Offline data are recorded here; only the explicit online allowlist is returned.
        journal.emit('paired_observation',label=label,watchdog=response['watchdog'],holding=response['holding'],score=response['score'])
        return online_packet(response)
    def observe(label):
        packet=paired(label);before=sorted(memory.committed);invalidated=memory.refresh(packet['watchdog'])
        journal.emit('memory_refresh',sequence=packet['watchdog']['sequence'],before=before,retained=sorted(memory.committed),invalidated=sorted(invalidated))
        held=packet['holding'];return memory.feedback(held['state'],held.get('objectId') if held['state']=='HOLDING' else None),invalidated
    def recovery(cause):
        budget.consume('recoveries');journal.emit('recovery_started',number=budget.recoveries,cause=cause)
    def fault_at(anchor):
        nonlocal faults
        attempted=False
        for f in scenario['faults']:
            if f['anchor']!=anchor or f['id'] in triggered:continue
            triggered.add(f['id']);paired('before_fault_audit_only')
            journal.emit('fault_requested',event_id=f['id'],anchor=anchor)
            response=call('REV_DISTURB',eventId=f['id'],anchor=anchor)
            faults=response['faults'];journal.emit('fault_observed',faults=faults)
            paired('after_fault_audit_only');attempted=True
        return attempted
    journal.emit('protocol',scope=manifest['scope'],scenario=scenario,memory=memory_name,budget=manifest['budget'],
        controller='same StateMachinePolicy',initial_plan='curated valid goal order',localization='controlled simulator geometry',llm_calls=0,vlm_calls=0)
    try:
        setup=configure(rpc,scenario,tid,manifest,budget);configured=True
        journal.emit('initial_state_for_audit_only',poses=setup['initialState'])
        validate_sequence(scenario['initial_plan_xml'],registry)
        while True:
            obs,invalidated=observe('before_decision')
            if invalidated:recovery('progress_revoked_before_decision')
            started=time.perf_counter_ns();decision=policy.decide(obs);decision_ns=time.perf_counter_ns()-started
            journal.emit('policy_decision',feedback=asdict(obs)|{'verified_goals':sorted(obs.verified_goals)},
                decision=asdict(decision),fsm_state=policy.state,decision_ms=decision_ns/1e6)
            if decision.status=='WAIT_FOR_OBSERVATION':
                if unknown_waits>=2:reason='UNKNOWN_OBSERVATION_LIMIT';break
                unknown_waits+=1;journal.emit('bounded_reobservation',number=unknown_waits,wait_seconds=.25);time.sleep(.25);continue
            unknown_waits=0
            if decision.status!='ACTION':reason='executor_completed' if decision.status=='PLAN_COMPLETE' else decision.status;break
            action=decision.action;budget.consume('actions');journal.emit('action_attempt',number=budget.actions,action=asdict(action))
            goal=next((g for g in goals if g.object_id==(action.target if action.name=='PICK' else obs.holding_id)),None)
            if goal is None:raise ContractError('action has no task goal')
            accepted=False;failure=None;cancelled=False
            try:
                location=call('REV_LOCATE',action=action.name,target=action.target)['location']
                journal.emit('localization',action=asdict(action),location=location)
                fault_at(goal.id+(':after_pick_localization' if action.name=='PICK' else ':after_place_localization'))
                fresh,_=observe('before_dispatch')
                if signature(fresh)!=signature(obs):
                    cancelled=True;raise FeedbackChanged('online_state_changed_during_localization')
                dispatches+=1;journal.emit('primitive_dispatched',action=asdict(action),position=location['position'])
                started=time.monotonic();response=call('REV_ACTION',action=action.name,target=action.target,position=location['position'])
                status=response.get('primitiveStatus') or '';state=call('REV_HOLD')['holding']
                accepted=accept(action,status,state,registry,goal)
                journal.emit('primitive_completed',action=asdict(action),status=status,holding=state,accepted_by_primitive_interface=accepted,
                    primitive_roundtrip_s=time.monotonic()-started,motions=response.get('motions'))
                if action.name=='PLACE':
                    if accepted:
                        memory.commit_placement(goal.id,True);journal.emit('completion_committed',goal_id=goal.id)
                    journal.emit('common_post_place_settle',seconds=1);time.sleep(1);budget.remaining()
                if accepted and action.name=='PICK' and fault_at(goal.id+':after_verified_pick'):
                    state=call('REV_HOLD')['holding']
                    if state['state']!='HOLDING' or state.get('objectId')!=action.target:
                        accepted=False;failure='holding_lost_after_verified_pick'
            except FeedbackChanged as exc:
                failure=str(exc);journal.emit('action_cancelled',action=asdict(action),reason=failure)
            paired('after_action_audit_only')
            journal.emit('action_outcome',action=asdict(action),accepted=accepted,failure=failure,cancelled_before_dispatch=cancelled)
            if not accepted:recovery(failure or 'primitive_interface_rejected')
    except BudgetExceeded as exc:
        reason='BudgetExceeded: '+str(exc);journal.emit('trial_error',error=reason)
        try:rpc.call('REV_ABORT',tid,timeout=10)
        except Exception:pass
    except Exception as exc:
        reason=type(exc).__name__+': '+str(exc);infra=True;journal.emit('trial_error',error=reason,infrastructure_error=True)
        try:rpc.call('REV_ABORT',tid,timeout=10)
        except Exception:pass
    finally:
        if configured:
            try:
                result=rpc.call('REV_END',tid,timeout=15);score=result['score'];faults=result['faults']
                write(folder/'final_response.json',result);journal.emit('final_offline_score',score=score,faults=faults)
            except Exception as exc:infra=True;journal.emit('final_score_error',error=str(exc))
        counts={'action_attempts':budget.actions,'primitive_dispatches':dispatches,'recoveries':budget.recoveries,'llm_calls':0,'vlm_calls':0}
        journal.emit('resource_counts',**counts);success=journal.finish(reason,score)
        summary={'trial_id':tid,'scenario_id':scenario['scenario_id'],'memory':memory_name,'success':success,
            'termination_reason':reason,'infrastructure_error':infra,'score_available':score is not None,'final_score':score,'faults':faults,
            'counts':counts,'total_seconds':time.monotonic()-budget.started}
        write(folder/'summary.json',summary)
        print(json.dumps({k:v for k,v in summary.items() if k not in ['final_score','faults']}|{'effective_faults':sum(f['observedEffect'] for f in faults)},ensure_ascii=True),flush=True)
    return summary

def precheck(rpc,manifest,run):
    scenario=json.loads(json.dumps(manifest['scenarios'][0]));scenario['faults']=[];tid='paired_precheck'
    configure(rpc,scenario,tid,manifest,Budget(seconds=60));samples=[];checks=[]
    try:
        for i in range(2):samples.append(rpc.call('REV_OBSERVE_AUDIT',tid,timeout=15))
        for i,r in enumerate(samples):
            w=r['watchdog'];s=r['score'];online=online_packet(r)
            checks += [{'name':f'sample{i}_same_time','passed':w['simulationTime']==s['simulationTime']},
                {'name':f'sample{i}_separate_channels','passed':w['channel']=='completion_watchdog' and s['channel']=='offline_score' and r['holding']['channel']=='controller_feedback'},
                {'name':f'sample{i}_correct_trial','passed':w['trialId']==s['trialId']==tid},
                {'name':f'sample{i}_goal_coverage','passed':{g['goalId'] for g in s['goals']}=={g['goalId'] for g in w['goals']}=={g['id'] for g in scenario['goals']}},
                {'name':f'sample{i}_score_excluded_from_online','passed':set(online)=={'holding','watchdog'}}]
        checks.append({'name':'monotonic_sequence','passed':samples[1]['watchdog']['sequence']>samples[0]['watchdog']['sequence']})
        locations=[]
        for action,target in [('PICK',scenario['goals'][0]['objectId']),('PLACE',scenario['goals'][0]['containerId'])]:
            location=rpc.call('REV_LOCATE',tid,action=action,target=target,timeout=15)['location'];locations.append(location)
            checks.append({'name':'controlled_localization_'+action,'passed':location['channel']=='controlled_simulator_observation'
                and location['action']==action and location['target']==target and all(math.isfinite(location['position'][axis]) for axis in 'xyz')})
        write(run/'paired_samples.json',samples);write(run/'locations.json',locations)
        write(run/'precheck_gate.json',{'passed':all(x['passed'] for x in checks),'checks':checks})
        if not all(x['passed'] for x in checks):raise RuntimeError('paired observation precheck failed')
        print(str(len(checks))+' observation/localization prechecks passed; no robot actions or model calls',flush=True)
    finally:rpc.call('REV_END',tid,timeout=15)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);parser.add_argument('--precheck',action='store_true')
    parser.add_argument('--precheck-run-id',default='precheck_02');args=parser.parse_args()
    run=ROOT/'results'/args.run_id;run.mkdir(exist_ok=False)
    manifest=json.loads((ROOT/'ablation_manifest.json').read_text(encoding='utf-8'));freeze(run,manifest)
    rpc=UnityRPC();results=[]
    try:
        rpc.call('REV_PING',timeout=10)
        if args.precheck:precheck(rpc,manifest,run)
        else:
            gate_path=ROOT/'results'/args.precheck_run_id
            gate=json.loads((gate_path/'precheck_gate.json').read_text(encoding='utf-8'))
            if not gate['passed']:raise RuntimeError('Precheck required')
            prior=json.loads((gate_path/'run_metadata.json').read_text(encoding='utf-8'))['core_sha256']
            for name in ['ablation_runner.py','shared_execution.py','completion_memory.py','recovery_policies.py','ablation_manifest.json','UnityRevision/Assets/Scripts/SimpleRobotSocketRevision.cs']:
                if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=prior[name]:raise RuntimeError('Execution changed since precheck: '+name)
            scenarios={s['scenario_id']:s for s in manifest['scenarios']}
            for unit in manifest['units']:
                result=run_trial(rpc,scenarios[unit['scenario_id']],unit,manifest,run)
                results.append(result);write(run/'summary.json',results)
                if result['infrastructure_error'] or not result['score_available']:raise RuntimeError('Infrastructure/protocol failure; remaining units not run')
    finally:rpc.close()

if __name__=='__main__':main()
