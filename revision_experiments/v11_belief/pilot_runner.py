"""v11 gate-2 pilot runner. Reuses the registered v10 runner (intent/seal, exclusions, early end) with the v11 kernel.
Modes: freeze (write pilot_registration.json once), verify, run --max-trials k."""
from pathlib import Path
import argparse, hashlib, json, sys
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'; V7 = HERE.parent/'v7'
sys.path.insert(0, str(V10))
import runner as v10runner   # noqa: E402  (v10, unmodified; imports v10 kernel)
sys.path.insert(0, str(HERE))
import kernel_v11            # noqa: E402

RUN = HERE/'results/pilot_belief_01'
FILES = ['belief_rules.py', 'kernel_v11.py', 'kernel_v11_derivation.json', 'make_kernel_v11.py', 'analyze_v11.py', 'make_analyze_v11.py',
         'design_v11.py', 'pilot_runner.py', 'pilot_manager.py', 'pilot_report.py', 'pilot_manifest.json', 'test_v11.py']
DEPS = {'v10/'+n: V10/n for n in ['memory_rules.py', 'policy.py', 'runner.py', 'manager.py', 'analyze.py', 'kernel_derivation.json', 'make_kernel.py', 'design.py']}
DEPS.update({'v7/'+n: V7/n for n in ['ablation_runner.py', 'completion_memory.py', 'contracts.py', 'recovery_policies.py', 'shared_execution.py', 'transport.py']})


def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def hashes(): return {**{n: digest(HERE/n) for n in FILES}, **{n: digest(p) for n, p in DEPS.items()}}


def freeze():
    if (HERE/'pilot_registration.json').exists(): raise RuntimeError('already frozen')
    if RUN.exists(): raise RuntimeError('pilot already started')
    v10runner.create_json(HERE/'pilot_registration.json', {'protocol_id': 'AR-belief-pilot-v1', 'frozen_utc': v10runner.now(),
        'type': 'development pilot (gate 2), not confirmatory', 'sha256': hashes(),
        'go_criteria': 'see pilot_report.py CRITERIA (fixed before any pilot trial)'})
    return verify()


def verify():
    reg = v10runner.read(HERE/'pilot_registration.json'); now = hashes()
    bad = [n for n in set(reg['sha256']) | set(now) if reg['sha256'].get(n) != now.get(n)]
    if bad: raise RuntimeError('pilot source changed since freeze: '+str(sorted(bad)))
    return {'verified_files': len(now), 'registration_sha256': digest(HERE/'pilot_registration.json')}


def run(max_trials):
    ref = verify(); v10runner.kernel = kernel_v11   # the only change: the v11 kernel (adds S13)
    manifest = v10runner.read(HERE/'pilot_manifest.json')
    return v10runner.execute(manifest, max_trials, None, run=RUN, check_source=False) if ref else None


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('mode', choices=['freeze', 'verify', 'run', 'dryrun'])
    p.add_argument('--max-trials', type=int, default=20); a = p.parse_args()
    if a.mode == 'freeze': print(json.dumps(freeze()))
    elif a.mode == 'verify': print(json.dumps(verify()))
    elif a.mode == 'dryrun':
        m = v10runner.read(HERE/'pilot_manifest.json'); done = v10runner.inspect_resume(RUN, m) if RUN.exists() else []
        print(json.dumps(verify() | {'completed': len(done), 'planned': len(m['units'])}))
    else: print(json.dumps({'sealed': run(a.max_trials)}))
