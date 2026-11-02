"""Derive f_runner.py and f_manager.py from e_runner.py / e_manager.py by asserted text substitutions
(paths formal_F, precheck_F, registration_F.json, f_manifest.json, analyze_f, Study F file list, segment of 32). The kernel stays kernel_e.
Re-running it regenerates byte-identical files on any OS (files are written as UTF-8 with LF line endings)."""
from pathlib import Path
s = Path('e_runner.py').read_text(encoding='utf-8')
def sub(old, new, n=1):
    global s
    assert s.count(old) == n, (old, s.count(old)); s = s.replace(old, new)
sub('"""Study E runner (generated from d_runner.py by make_e_scripts.py).', '"""Study F runner (generated from e_runner.py by make_f_scripts.py; kernel_e unchanged).')
sub("the Study E kernel, the Study E registration and the Study E precheck gate", "the frozen Study E kernel, the Study F registration and the Study F precheck gate")
sub("RUN = HERE/'results/formal_E'; PRECHECK_ID = 'precheck_E'; REG = HERE/'registration_E.json'",
    "RUN = HERE/'results/formal_F'; PRECHECK_ID = 'precheck_F'; REG = HERE/'registration_F.json'")
start = s.index("FILES = ["); end = s.index("DEPS = ")
s = s[:start] + """FILES = ['study_e_rules.py', 'study_d_rules.py', 'belief_rules.py', 'kernel_e.py', 'make_kernel_e.py', 'kernel_d.py', 'kernel_d_derivation.json',
         'make_kernel_d.py', 'make_kernel_v11.py', 'trial_e.py', 'make_trial_e.py', 'trial_d.py', 'make_trial_d.py', 'make_analyze_v11.py',
         'analyze_f.py', 'analyze_e.py', 'analyze_d.py', 'design_f.py', 'design_e.py', 'design_d.py', 'design_v11.py', 'f_runner.py', 'f_manager.py',
         'make_f_scripts.py', 'e_runner.py', 'e_manager.py', 'test_f.py', 'f_manifest.json', 'f_schedule.csv']
""" + s[end:]
sub("def manifest(): return v10runner.read(HERE/'e_manifest.json')", "def manifest(): return v10runner.read(HERE/'f_manifest.json')")
sub("Frozen Study E source mismatch", "Frozen Study F source mismatch")
sub("Study E registration exists", "Study F registration exists"); sub("Study E run exists", "Study F run exists")
sub("'prior_evidence': 'Study D results/formal_D (1080 trials) and post-hoc log analysis analysis_cascade/ were inspected before this design'",
    "'prior_evidence': 'Studies C, D, E (2400 trials), post-hoc analyses analysis_cascade/ (prop3_transient, sensitivity_model) and an internal pre-submission review were inspected before this design'")
sub("v10runner.kernel = kernel_e; v10runner.verify = verify; v10runner.ROOT = HERE   # gate: HERE/prechecks/precheck_E",
    "v10runner.kernel = kernel_e; v10runner.verify = verify; v10runner.ROOT = HERE   # gate: HERE/prechecks/precheck_F")
sub("p.add_argument('--max-trials', type=int, default=20)", "p.add_argument('--max-trials', type=int, default=32)")
for bad in ["'results/formal_E'", 'precheck_E', 'e_manifest', 'registration_E']:
    assert bad not in s, bad
Path('f_runner.py').write_bytes(s.encode('utf-8'))   # LF on every OS (amendment A0)
m = Path('e_manager.py').read_text(encoding='utf-8')
for a, b in [('"""Study E manager (Windows; generated from d_manager.py by make_e_scripts.py).', '"""Study F manager (Windows; generated from e_manager.py by make_f_scripts.py).'),
             ('Segments end on multiples of 20.', 'Segments end on multiples of 32.'),
             ('Usage:  python e_manager.py --precheck      then      python e_manager.py --expected-completed 0', 'Usage:  python f_manager.py --precheck      then      python f_manager.py --expected-completed 0'),
             ("import e_runner as dr   # noqa: E402", "import f_runner as dr   # noqa: E402"),
             ("EXEC = HERE/'execution/formal_E'", "EXEC = HERE/'execution/formal_F'"),
             ("def cmd(*args): return [sys.executable, '-u', str(HERE/'e_runner.py'), *args]", "def cmd(*args): return [sys.executable, '-u', str(HERE/'f_runner.py'), *args]")]:
    assert m.count(a) == 1, a; m = m.replace(a, b)
assert m.count("str(HERE/'analyze_e.py')") == 2; m = m.replace("str(HERE/'analyze_e.py')", "str(HERE/'analyze_f.py')")
for bad in ['e_runner', 'formal_E', 'analyze_e']:
    assert bad not in m, bad
Path('f_manager.py').write_bytes(m.encode('utf-8'))   # LF on every OS (amendment A0)
print('ok')
