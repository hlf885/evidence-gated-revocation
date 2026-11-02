"""Derive e_runner.py and e_manager.py from d_runner.py / d_manager.py by asserted text substitutions
(paths formal_E, precheck_E, registration_E.json, e_manifest.json, kernel_e, analyze_e, Study E file list, segment default 20).
Re-running it regenerates identical files."""
from pathlib import Path
s = Path('d_runner.py').read_text(encoding='utf-8')
def sub(old, new, n=1):
    global s
    assert s.count(old) == n, (old, s.count(old)); s = s.replace(old, new)
sub('"""Study D runner.', '"""Study E runner (generated from d_runner.py by make_e_scripts.py).')
sub("the Study D kernel, the Study D registration and the Study D precheck gate", "the Study E kernel, the Study E registration and the Study E precheck gate")
sub("import kernel_d              # noqa: E402\n", "import kernel_e              # noqa: E402\n")
sub("RUN = HERE/'results/formal_D'; PRECHECK_ID = 'precheck_D'; REG = HERE/'registration_D.json'",
    "RUN = HERE/'results/formal_E'; PRECHECK_ID = 'precheck_E'; REG = HERE/'registration_E.json'")
start = s.index("FILES = ["); end = s.index("DEPS = ")
s = s[:start] + """FILES = ['study_e_rules.py', 'study_d_rules.py', 'belief_rules.py', 'kernel_e.py', 'make_kernel_e.py', 'kernel_d.py', 'kernel_d_derivation.json',
         'make_kernel_d.py', 'make_kernel_v11.py', 'trial_e.py', 'make_trial_e.py', 'trial_d.py', 'make_trial_d.py', 'make_analyze_v11.py',
         'analyze_e.py', 'analyze_d.py', 'design_e.py', 'design_d.py', 'design_v11.py', 'e_runner.py', 'e_manager.py', 'make_e_scripts.py',
         'test_e.py', 'e_manifest.json', 'e_schedule.csv']
""" + s[end:]
sub("def manifest(): return v10runner.read(HERE/'d_manifest.json')", "def manifest(): return v10runner.read(HERE/'e_manifest.json')")
sub("Frozen Study D source mismatch", "Frozen Study E source mismatch")
sub("Study D registration exists", "Study E registration exists"); sub("Study D run exists", "Study E run exists")
sub("'pilot_evidence': 'results/pilot_belief_01 (60 development trials, excluded from inference)'",
    "'prior_evidence': 'Study D results/formal_D (1080 trials) and post-hoc log analysis analysis_cascade/ were inspected before this design'")
sub("def precheck(rpc_factory=kernel_d.UnityRPC):", "def precheck(rpc_factory=kernel_e.UnityRPC):")
sub("kernel_d.precheck(rpc, m, run)", "kernel_e.precheck(rpc, m, run)")
sub("v10runner.kernel = kernel_d; v10runner.verify = verify; v10runner.ROOT = HERE   # gate: HERE/prechecks/precheck_D",
    "v10runner.kernel = kernel_e; v10runner.verify = verify; v10runner.ROOT = HERE   # gate: HERE/prechecks/precheck_E")
sub("p.add_argument('--max-trials', type=int, default=27)", "p.add_argument('--max-trials', type=int, default=20)")
for bad in ['kernel_d.precheck', 'kernel_d.UnityRPC', '= kernel_d', "'results/formal_D'", 'precheck_D', 'd_manifest']:
    assert bad not in s, bad
Path('e_runner.py').write_text(s, encoding='utf-8')
m = Path('d_manager.py').read_text(encoding='utf-8')
for a, b in [('"""Study D manager (Windows).', '"""Study E manager (Windows; generated from d_manager.py by make_e_scripts.py).'),
             ('Segments end on multiples of 27.', 'Segments end on multiples of 20.'),
             ('Usage:  python d_manager.py --precheck      then      python d_manager.py --expected-completed 0', 'Usage:  python e_manager.py --precheck      then      python e_manager.py --expected-completed 0'),
             ("import d_runner as dr   # noqa: E402", "import e_runner as dr   # noqa: E402"),
             ("EXEC = HERE/'execution/formal_D'", "EXEC = HERE/'execution/formal_E'"),
             ("def cmd(*args): return [sys.executable, '-u', str(HERE/'d_runner.py'), *args]", "def cmd(*args): return [sys.executable, '-u', str(HERE/'e_runner.py'), *args]")]:
    assert m.count(a) == 1, a; m = m.replace(a, b)
assert m.count("str(HERE/'analyze_d.py')") == 2; m = m.replace("str(HERE/'analyze_d.py')", "str(HERE/'analyze_e.py')")
for bad in ['d_runner', 'formal_D', 'analyze_d']:
    assert bad not in m, bad
Path('e_manager.py').write_text(m, encoding='utf-8')
print('ok')
