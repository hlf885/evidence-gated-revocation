"""Offline test of the capture wrapper with the stochastic model world (no Unity): fake JPEG frames, real kernel and runner."""
from pathlib import Path
import base64, contextlib, io, json, shutil, sys, tempfile
HERE = Path(__file__).resolve().parent; EXP = HERE.parent; V10 = EXP/'v10_studyC'
sys.path.insert(0, str(V10/'prediction'))
import capture_states as cs, kernel_e, shared_execution, contracts, runner as v10runner   # noqa: E402
from world_model import VirtualClock, StochasticWorld   # noqa: E402
JPEG = base64.b64encode(b'\xff\xd8\xff\xe0fake').decode()

class FakeUnity:
    def __init__(self, w): self.w = w
    def __getattr__(self, n): return getattr(self.w, n)
    def call(self, verb, trial_id='', timeout=30, **p):
        if verb == 'REV_CAPTURE': return {'ok': True, 'images': {'mainRgb': JPEG, 'sideRgb': JPEG}}
        return self.w.call(verb, trial_id, timeout=timeout, **p)

tmp = Path(tempfile.mkdtemp()); cs.RUN = tmp/'run'; cs.FRAMES = tmp/'frames'
clk = VirtualClock(); saved = (kernel_e.time, shared_execution.time, contracts.time); kernel_e.time = shared_execution.time = contracts.time = clk
try:
    v10runner.kernel = kernel_e
    with contextlib.redirect_stdout(io.StringIO()):
        n = v10runner.execute(cs.make_manifest(), 20, None, run=cs.RUN, rpc_factory=lambda: cs.CapturingRPC(FakeUnity(StochasticWorld(clk, 7))), check_source=False)
finally:
    kernel_e.time, shared_execution.time, contracts.time = saved
rows = [json.loads(l) for l in (cs.FRAMES/'frames.jsonl').read_text(encoding='utf-8').splitlines()]
assert n == 20 and len(rows) > 200, (n, len(rows))
assert all('main' in r and 'side' in r and r['score'] and r['score'].get('goals') for r in rows), rows[0]
assert len({r['trial_id'] for r in rows}) == 20
print(json.dumps({'trials': n, 'frames': len(rows), 'per_trial': round(len(rows)/20, 1), 'example_score_keys': list(rows[0]['score'])}))
shutil.rmtree(tmp)
