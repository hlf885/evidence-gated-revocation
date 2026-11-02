"""VLM calibration, step 1 (not a registered study): capture camera frames along real executions with the independent score as ground truth.
Runs 20 trials of the frozen Study E kernel (evidence-gated revocation 'debounce2', no injected errors) on 10 new layouts x 2 conditions.
After every audit observation it captures the main and side RGB images (512 x 512 JPEG) and stores them with the per-goal ground truth.
Unity is started in batch mode WITH graphics, because cameras do not render with -nographics.
Usage:  python capture_states.py launch      (starts Unity, runs 'python capture_states.py run', closes Unity)"""
from pathlib import Path
import base64, collections, copy, json, random, subprocess, sys, time
HERE = Path(__file__).resolve().parent; EXP = HERE.parent; V10 = EXP/'v10_studyC'; V11 = EXP/'v11_belief'
for p in (V10, V11): sys.path.insert(0, str(p))
import runner as v10runner   # noqa: E402
import manager as m10        # noqa: E402
import design as v10design   # noqa: E402
import kernel_e, design_f    # noqa: E402

RUN = HERE/'capture_run'; FRAMES = HERE/'frames'; EXEC = HERE/'execution'; SEED = 2026110201; N_LAYOUTS = 10


def make_manifest():
    base = v10design.make_manifest(); templates = {}
    for s in base['scenarios']: templates.setdefault(s['condition'], s)
    excl = design_f.excluded_seeds() | set(design_f.make_manifest()['layout_seeds']); rng = random.Random(SEED); seeds = []
    while len(seeds) < N_LAYOUTS:
        s = rng.randrange(100000, 1000000)
        if s not in excl and s not in seeds: seeds.append(s)
    scenarios, units = [], []
    for seed in seeds:
        lr = random.Random(seed)
        off = {k: {'x': round(lr.uniform(-.008, .008), 6), 'y': 0, 'z': round(lr.uniform(-.008, .008), 6)} for k in templates['no_fault']['layout_offsets']}
        for cond in ['no_fault', 'completed_shift']:
            s = copy.deepcopy(templates[cond]); s.update(seed=seed, scenario_id=f'V_3goals_{cond}_seed{seed}', layout_offsets=off); scenarios.append(s)
            units.append({'trial_id': f"{s['scenario_id']}_debounce2_none", 'scenario_id': s['scenario_id'], 'rule': 'debounce2', 'memory': 'debounce2',
                          'noise_type': 'none', 'noise_rate': 0.0, 'noise_correlation': 'none', 'seed': seed, 'condition': cond})
    m = design_f.make_manifest()
    return {k: m[k] for k in ['budget', 'evaluation', 'persistence']} | {
        'protocol_id': 'VLM-calibration-capture-v1', 'scope': 'Calibration captures for a VLM goal check (not a registered study); no injected errors',
        'rules': ['debounce2'], 'conditions': ['no_fault', 'completed_shift'], 'layout_seeds': seeds, 'segment_size': 20,
        'scenarios': scenarios, 'units': units, 'cells': [], 'primary': {'tests': []}}


class CapturingRPC:
    """Delegates to UnityRPC; after each REV_OBSERVE_AUDIT it requests REV_CAPTURE and stores the frames with the audit ground truth."""
    def __init__(self, inner): self.inner = inner; self.k = collections.Counter(); FRAMES.mkdir(exist_ok=True)
    def __getattr__(self, name): return getattr(self.inner, name)
    def call(self, verb, trial_id='', timeout=30, **payload):
        r = self.inner.call(verb, trial_id, timeout=timeout, **payload)
        if verb == 'REV_OBSERVE_AUDIT' and trial_id:
            k = self.k[trial_id]; self.k[trial_id] += 1; d = FRAMES/trial_id; d.mkdir(exist_ok=True); row = {'trial_id': trial_id, 'k': k, 'utc': time.time()}
            try:
                img = self.inner.call('REV_CAPTURE', trial_id, timeout=30)['images']
                for view, key in [('main', 'mainRgb'), ('side', 'sideRgb')]:
                    (d/f'{k:04d}_{view}.jpg').write_bytes(base64.b64decode(img[key])); row[view] = f'{trial_id}/{k:04d}_{view}.jpg'
            except Exception as exc:
                row['capture_error'] = type(exc).__name__+': '+str(exc)
            row |= {'score': r.get('score'), 'watchdog': r.get('watchdog'), 'holding': r.get('holding')}
            with (FRAMES/'frames.jsonl').open('a', encoding='utf-8') as f: f.write(json.dumps(row)+'\n')
        return r


def run():
    v10runner.kernel = kernel_e
    return v10runner.execute(make_manifest(), 20, None, run=RUN, rpc_factory=lambda: CapturingRPC(kernel_e.UnityRPC()), check_source=False)


def launch():
    EXEC.mkdir(exist_ok=True); seg = EXEC/f'capture_{int(time.time())}'; seg.mkdir()
    m10.assert_ports_free()
    cmd = [str(m10.UNITY), '-batchmode', '-projectPath', str(m10.PROJECT), '-executeMethod', 'RobotBatch.Start', '-revisionRobot', '-logFile', str(seg/'unity.log')]
    unity = subprocess.Popen(cmd, cwd=m10.ROOT, **m10.hidden())
    try:
        m10.ready(unity, seg)
        with (seg/'runner.log').open('xb') as log:
            code = subprocess.run([sys.executable, '-u', str(Path(__file__)), 'run'], cwd=HERE, stdout=log, stderr=subprocess.STDOUT, timeout=20*400).returncode
        if code: raise RuntimeError(f'capture run exited {code}; see {seg/"runner.log"}')
    finally:
        m10.close_owned_unity(unity, seg)
    n = sum(1 for _ in (FRAMES/'frames.jsonl').open(encoding='utf-8')); print(json.dumps({'frames': n, 'folder': str(FRAMES)}))


if __name__ == '__main__':
    {'run': lambda: print(json.dumps({'sealed': run()})), 'launch': launch, 'manifest': lambda: print(len(make_manifest()['units']))}[sys.argv[1]]()
