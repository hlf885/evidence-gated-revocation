"""Study F runner (generated from e_runner.py by make_f_scripts.py; kernel_e unchanged). Reuses the registered v10 runner (intent/seal, registered exclusions, early end, halt rules) with
the frozen Study E kernel, the Study F registration and the Study F precheck gate (module attributes patched at call time).
Modes: freeze | verify | precheck | run --max-trials k | dryrun | interrupted --trial-id X"""
from pathlib import Path
import argparse, hashlib, json, sys
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'; V7 = HERE.parent/'v7'
sys.path.insert(0, str(V10))
import runner as v10runner   # noqa: E402  (v10, unmodified)
sys.path.insert(0, str(HERE))
import kernel_e              # noqa: E402

RUN = HERE/'results/formal_F'; PRECHECK_ID = 'precheck_F'; REG = HERE/'registration_F.json'
FILES = ['study_e_rules.py', 'study_d_rules.py', 'belief_rules.py', 'kernel_e.py', 'make_kernel_e.py', 'kernel_d.py', 'kernel_d_derivation.json',
         'make_kernel_d.py', 'make_kernel_v11.py', 'trial_e.py', 'make_trial_e.py', 'trial_d.py', 'make_trial_d.py', 'make_analyze_v11.py',
         'analyze_f.py', 'analyze_e.py', 'analyze_d.py', 'design_f.py', 'design_e.py', 'design_d.py', 'design_v11.py', 'f_runner.py', 'f_manager.py',
         'make_f_scripts.py', 'e_runner.py', 'e_manager.py', 'test_f.py', 'f_manifest.json', 'f_schedule.csv']
DEPS = {'v10/'+n: V10/n for n in ['memory_rules.py', 'policy.py', 'runner.py', 'manager.py', 'analyze.py', 'kernel_derivation.json', 'make_kernel.py', 'design.py']}
DEPS.update({'v7/'+n: V7/n for n in ['ablation_runner.py', 'completion_memory.py', 'contracts.py', 'recovery_policies.py', 'shared_execution.py',
             'transport.py', 'ablation_manifest.json', 'UnityRevision/Assets/Scripts/SimpleRobotSocketRevision.cs',
             'UnityRevision/Assets/Scripts/CompletionWatchdog.cs', 'UnityRevision/Assets/Scripts/RevisionRuntime.cs']})


def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def hashes(): return {**{n: digest(HERE/n) for n in FILES}, **{n: digest(p) for n, p in DEPS.items()}}
def manifest(): return v10runner.read(HERE/'f_manifest.json')


def freeze():
    if REG.exists(): raise RuntimeError('Study F registration exists; never re-freeze in place')
    if RUN.exists(): raise RuntimeError('Study F run exists; cannot claim prospective freeze')
    v10runner.create_json(REG, {'protocol_id': manifest()['protocol_id'], 'frozen_utc': v10runner.now(),
        'type': 'local prospective registration, not a public registry', 'sha256': hashes(), 'formal_trials_at_registration': 0,
        'llm_calls': 0, 'vlm_calls': 0, 'prior_evidence': 'Studies C, D, E (2400 trials), post-hoc analyses analysis_cascade/ (prop3_transient, sensitivity_model) and an internal pre-submission review were inspected before this design'})
    return verify()


def verify():
    reg = v10runner.read(REG); now = hashes()
    bad = sorted(n for n in set(reg['sha256']) | set(now) if reg['sha256'].get(n) != now.get(n))
    if bad: raise RuntimeError('Frozen Study F source mismatch: '+str(bad))
    return {'verified_files': len(now), 'registration_sha256': digest(REG)}


def precheck(rpc_factory=kernel_e.UnityRPC):
    reg = verify(); run = HERE/'prechecks'/PRECHECK_ID; run.mkdir(parents=True, exist_ok=False)
    v10runner.create_json(run/'registration_reference.json', reg)
    m = json.loads(json.dumps(manifest()))
    m['scenarios'][0]['seed'] = 990000001
    m['scenarios'][0]['layout_offsets'] = {e['id']: {'x': 0, 'y': 0, 'z': 0} for e in m['scenarios'][0]['entities'] if e['kind'] == 'object'}
    rpc = rpc_factory()
    try:
        v10runner.create_json(run/'unity_ping.json', rpc.call('REV_PING', timeout=10)); kernel_e.precheck(rpc, m, run)
    finally:
        rpc.close()


def run(max_trials):
    v10runner.kernel = kernel_e; v10runner.verify = verify; v10runner.ROOT = HERE   # gate: HERE/prechecks/precheck_F
    return v10runner.execute(manifest(), max_trials, PRECHECK_ID, run=RUN, check_source=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('mode', choices=['freeze', 'verify', 'precheck', 'run', 'dryrun', 'interrupted'])
    p.add_argument('--max-trials', type=int, default=32); p.add_argument('--trial-id'); a = p.parse_args()
    if a.mode == 'freeze': print(json.dumps(freeze()))
    elif a.mode == 'verify': print(json.dumps(verify()))
    elif a.mode == 'precheck': precheck()
    elif a.mode == 'run': print(json.dumps({'sealed': run(a.max_trials)}))
    elif a.mode == 'interrupted': verify(); print(json.dumps({'infrastructure_exclusions': v10runner.mark_interrupted(manifest(), a.trial_id, run=RUN)}))
    else:
        m = manifest(); done = v10runner.inspect_resume(RUN, m) if RUN.exists() else []
        print(json.dumps(verify() | {'completed': len(done), 'planned': len(m['units']),
                                     'next_trial': m['units'][len(done)]['trial_id'] if len(done) < len(m['units']) else None}))
