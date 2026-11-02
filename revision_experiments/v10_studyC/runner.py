"""Study C runner: freeze / verify / dryrun / precheck / run, with per-trial intent+seal.

Adapted from v8/formal_runner.py. Never re-runs a started trial; never skips a gap.
"""
from pathlib import Path
import argparse, contextlib, datetime, hashlib, json, os, sys, zipfile

ROOT = Path(__file__).resolve().parent
V7 = ROOT.parent/'v7'
sys.path.insert(0, str(ROOT))
import kernel  # noqa: E402

RUN = ROOT/'results/formal_02'          # A1: formal_01 aborted at trial 44 (see docs/STUDIES.md)
PRECHECK_ID = 'precheck_A1'
MAX_INFRA_EXCLUSIONS = 3                 # A1: more than this halts the run
A0 = ROOT/'amendments/A0_original_freeze'
V7_DEPS = ['ablation_runner.py', 'completion_memory.py', 'contracts.py', 'recovery_policies.py', 'shared_execution.py',
           'transport.py', 'ablation_manifest.json', 'UnityRevision/Assets/Scripts/SimpleRobotSocketRevision.cs',
           'UnityRevision/Assets/Scripts/CompletionWatchdog.cs', 'UnityRevision/Assets/Scripts/RevisionRuntime.cs']
OWN = ['memory_rules.py', 'policy.py', 'kernel.py', 'kernel_derivation.json', 'make_kernel.py', 'design.py', 'runner.py', 'manager.py',
       'analyze.py', 'formal_manifest.json', 'schedule.csv']


def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()


def create_json(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False); f.flush(); os.fsync(f.fileno())


def files():
    out = {n: ROOT/n for n in OWN}
    out.update({'dependencies/v7/'+n: V7/n for n in V7_DEPS})
    return out


def freeze():
    if (ROOT/'registration.json').exists():
        raise RuntimeError('Registration exists; never re-freeze in place')
    if RUN.exists():
        raise RuntimeError('Formal run exists; cannot claim prospective freeze')
    fs = files(); hashes = {n: digest(p) for n, p in fs.items()}
    with zipfile.ZipFile(ROOT/'registered_source.zip', 'x', zipfile.ZIP_DEFLATED) as z:
        for n, p in fs.items():
            z.write(p, n)
    create_json(ROOT/'registration.json', {'protocol_id': read(ROOT/'formal_manifest.json')['protocol_id'], 'frozen_utc': now(),
                'type': 'local prospective registration, not a public registry', 'core_sha256': hashes,
                'source_zip_sha256': digest(ROOT/'registered_source.zip'), 'formal_trials_at_registration': 0,
                'vlm_calls': 0, 'llm_calls': 0, 'amendment': 'A1 (see docs/STUDIES.md)',
                'supersedes_registration_sha256': digest(A0/'registration.json') if (A0/'registration.json').exists() else None,
                'aborted_runs_excluded_from_analysis': ['results/formal_01'], 'new_run': str(RUN.relative_to(ROOT)).replace('\\', '/')})
    return verify()


def verify():
    reg = read(ROOT/'registration.json'); fs = files()
    bad = [n for n, h in reg['core_sha256'].items() if digest(fs[n]) != h]
    if set(reg['core_sha256']) != set(fs): bad.append('file_set')
    if digest(ROOT/'registered_source.zip') != reg['source_zip_sha256']: bad.append('registered_source.zip')
    if bad: raise RuntimeError('Frozen source mismatch: '+str(bad))
    return {'verified_files': len(reg['core_sha256'])+1, 'registration_sha256': digest(ROOT/'registration.json')}


def exclusions(run):
    f = run/'infrastructure_exclusions.json'
    return read(f) if f.exists() else []


def add_exclusion(run, value):
    rows = exclusions(run)+[value]; tmp = run/'infrastructure_exclusions.tmp'
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8'); os.replace(tmp, run/'infrastructure_exclusions.json')
    return rows


def trial_seal(run, tid):
    folder = run/tid
    return {str(p.relative_to(folder)).replace('\\', '/'): digest(p) for p in sorted(folder.rglob('*')) if p.is_file()}


def inspect_resume(run, manifest):
    completed = []; missing_seen = False
    if (run/'halt.json').exists():
        raise RuntimeError('Halt requires documented review; automatic continuation disabled')
    allowed = {u['trial_id'] for u in manifest['units']}; excluded = {e['trial_id'] for e in exclusions(run)}
    for folder in run.glob('*'):
        if folder.is_dir() and folder.name not in allowed | {'intents', 'seals'}:
            raise RuntimeError('Unexpected trial folder: '+folder.name)
    for unit in manifest['units']:
        tid = unit['trial_id']; folder = run/tid
        intent = run/'intents'/(tid+'.json'); seal = run/'seals'/(tid+'.json')
        if seal.exists():
            if missing_seen or not intent.exists(): raise RuntimeError('Noncontiguous or unclaimed sealed trial: '+tid)
            if read(seal)['sha256'] != trial_seal(run, tid): raise RuntimeError('Raw trial changed after sealing: '+tid)
            s = read(folder/'summary.json')
            if s['trial_id'] != tid or s['scenario_id'] != unit['scenario_id'] or s['rule'] != unit['rule'] \
               or s['noise_type'] != unit['noise_type'] or s['noise_rate'] != unit['noise_rate']:
                raise RuntimeError('Trial identity mismatch: '+tid)
            if (s['infrastructure_error'] or not s['score_available']) and tid not in excluded:
                raise RuntimeError('Infrastructure-invalid sealed trial not registered as exclusion: '+tid)
            if s['counts']['vlm_calls'] or s['counts']['llm_calls']: raise RuntimeError('Unexpected model calls')
            completed.append(s)
        else:
            missing_seen = True
            if intent.exists() or folder.exists(): raise RuntimeError('Started but unsealed trial; do not repeat automatically: '+tid)
    return completed


def mark_interrupted(manifest, tid, run=RUN):
    """A1: author-invoked after review, for a trial that was started but never sealed because the PC or the
    process was interrupted from outside (reboot, power loss). Seals it as an infrastructure exclusion; never re-run."""
    unit = next((u for u in manifest['units'] if not (run/'seals'/(u['trial_id']+'.json')).exists()), None)
    if unit is None or unit['trial_id'] != tid: raise RuntimeError('Only the first unsealed trial can be marked interrupted')
    if not (run/'intents'/(tid+'.json')).exists(): raise RuntimeError('Trial was never started; nothing to mark')
    folder = run/tid; folder.mkdir(exist_ok=True)
    if (folder/'summary.json').exists(): raise RuntimeError('Trial has a summary; it ended normally - needs individual review')
    create_json(folder/'summary.json', {'trial_id': tid, 'scenario_id': unit['scenario_id'], 'memory': unit['rule'], 'rule': unit['rule'],
                'noise_type': unit['noise_type'], 'noise_rate': unit['noise_rate'], 'success': False,
                'termination_reason': 'EXTERNAL_INTERRUPTION: started, never completed', 'infrastructure_error': True,
                'score_available': False, 'final_score': None, 'faults': [], 'interruption_marked_utc': now(),
                'counts': {'action_attempts': 0, 'primitive_dispatches': 0, 'recoveries': 0, 'llm_calls': 0, 'vlm_calls': 0, 'observation_flips': 0},
                'total_seconds': 0.0})
    rows = add_exclusion(run, {'trial_id': tid, 'reason': 'EXTERNAL_INTERRUPTION', 'utc': now(), 'unit': unit})
    create_json(run/'seals'/(tid+'.json'), {'sealed_utc': now(), 'sha256': trial_seal(run, tid), 'sealed_after_external_interruption': True})
    if len(rows) > MAX_INFRA_EXCLUSIONS:
        create_json(run/'halt.json', {'trial_id': tid, 'reason': 'more than %d infrastructure exclusions' % MAX_INFRA_EXCLUSIONS, 'utc': now()})
    return len(rows)


@contextlib.contextmanager
def exclusive_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':  # offline tests only
        yield; return
    import msvcrt
    with (folder/'runner.lock').open('a+b') as f:
        if f.tell() == 0: f.write(b'0'); f.flush()
        f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        try: yield
        finally: f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def precheck(manifest, precheck_id, rpc_factory=kernel.UnityRPC):
    reg = verify()
    run = ROOT/'prechecks'/precheck_id; run.mkdir(parents=True, exist_ok=False)
    create_json(run/'registration_reference.json', reg)
    m = json.loads(json.dumps(manifest))
    m['scenarios'][0]['seed'] = 990000001
    m['scenarios'][0]['layout_offsets'] = {e['id']: {'x': 0, 'y': 0, 'z': 0} for e in m['scenarios'][0]['entities'] if e['kind'] == 'object'}
    rpc = rpc_factory()
    try:
        create_json(run/'unity_ping.json', rpc.call('REV_PING', timeout=10))
        kernel.precheck(rpc, m, run)
    finally:
        rpc.close()


def execute(manifest, max_trials, precheck_id, run=RUN, rpc_factory=kernel.UnityRPC, check_source=True):
    if max_trials <= 0: raise ValueError('max-trials must be positive')
    registration = verify() if check_source else {'offline_test': True}
    if check_source:
        gate = ROOT/'prechecks'/precheck_id
        if not read(gate/'precheck_gate.json')['passed'] or read(gate/'registration_reference.json') != registration:
            raise RuntimeError('Matching registered precheck required')
    run.mkdir(parents=True, exist_ok=True); (run/'intents').mkdir(exist_ok=True); (run/'seals').mkdir(exist_ok=True)
    with exclusive_lock(run):
        if not (run/'registration_reference.json').exists():
            create_json(run/'registration_reference.json', registration); create_json(run/'manifest.json', manifest)
            create_json(run/'run_metadata.json', {'scope': manifest['scope'], 'started_utc': now(), 'python': sys.version,
                        'platform': sys.platform, 'llm_calls': 0, 'vlm_calls': 0, 'registration': registration})
        if read(run/'registration_reference.json') != registration or read(run/'manifest.json') != manifest:
            raise RuntimeError('Run/registration mismatch')
        completed = inspect_resume(run, manifest); start = len(completed)
        end = min(len(manifest['units']), start+max_trials)
        scenarios = {s['scenario_id']: s for s in manifest['scenarios']}
        if len(exclusions(run)) > MAX_INFRA_EXCLUSIONS: raise RuntimeError('Infrastructure exclusion limit exceeded')
        rpc = rpc_factory(); early_end = None
        try:
            rpc.call('REV_PING', timeout=10)
            for unit in manifest['units'][start:end]:
                if check_source: verify()
                tid = unit['trial_id']
                create_json(run/'intents'/(tid+'.json'), {'started_utc': now(), 'unit': unit, **registration})
                result = kernel.run_trial(rpc, scenarios[unit['scenario_id']], unit, manifest, run)
                create_json(run/'seals'/(tid+'.json'), {'sealed_utc': now(), 'sha256': trial_seal(run, tid)})
                completed.append(result); kernel.write(run/'summary.json', completed)
                if result['infrastructure_error'] or not result['score_available']:
                    # A1: sealed, never repeated, excluded from inference; Unity is restarted before the next trial.
                    rows = add_exclusion(run, {'trial_id': tid, 'reason': result['termination_reason'], 'utc': now(), 'unit': unit})
                    if len(rows) > MAX_INFRA_EXCLUSIONS:
                        create_json(run/'halt.json', {'trial_id': tid, 'reason': 'more than %d infrastructure exclusions' % MAX_INFRA_EXCLUSIONS, 'utc': now()})
                        raise RuntimeError('Infrastructure exclusion limit exceeded; batch halted and evidence retained')
                    early_end = {'trial_id': tid, 'cause': 'infrastructure_exclusion', 'reason': result['termination_reason']}; break
                if result['termination_reason'].startswith('ACTION_TIMEOUT'):
                    early_end = {'trial_id': tid, 'cause': 'action_timeout_restart_unity', 'reason': result['termination_reason']}; break
            kernel.write(run/'progress.json', {'completed': len(completed), 'planned': len(manifest['units']), 'updated_utc': now(), 'early_end': early_end,
                         'next_trial': manifest['units'][len(completed)]['trial_id'] if len(completed) < len(manifest['units']) else None})
        finally:
            rpc.close()
    return len(completed)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['freeze', 'verify', 'dryrun', 'precheck', 'run', 'pilot', 'interrupted'])
    p.add_argument('--trial-id')
    p.add_argument('--max-trials', type=int, default=21)
    p.add_argument('--precheck-id', default=PRECHECK_ID)
    a = p.parse_args()
    if a.mode == 'freeze': print(json.dumps(freeze())); return
    if a.mode == 'pilot':
        import design
        pm = design.make_pilot_manifest(); pr = ROOT/'results'/'pilot_01'
        if pr.exists(): raise RuntimeError('Pilot already exists; inspect it instead of rerunning')
        print(json.dumps({'pilot_completed': execute(pm, len(pm['units']), None, run=pr, check_source=False)})); return
    m = read(ROOT/'formal_manifest.json')
    if a.mode in ['verify', 'dryrun']:
        info = verify()
        if a.mode == 'dryrun':
            done = inspect_resume(RUN, m) if RUN.exists() else []
            info |= {'completed': len(done), 'planned': len(m['units']),
                     'next_trial': m['units'][len(done)]['trial_id'] if len(done) < len(m['units']) else None}
        print(json.dumps(info)); return
    if a.mode == 'interrupted':
        verify(); print(json.dumps({'infrastructure_exclusions': mark_interrupted(m, a.trial_id)})); return
    if a.mode == 'precheck': precheck(m, a.precheck_id)
    else: execute(m, a.max_trials, a.precheck_id)


if __name__ == '__main__':
    main()
