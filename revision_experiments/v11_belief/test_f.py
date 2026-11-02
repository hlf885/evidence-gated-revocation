"""Study F offline tests (no Unity, no models)."""
from pathlib import Path
import collections, contextlib, hashlib, io, json, shutil, subprocess, sys, tempfile
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'
sys.path.insert(0, str(V10)); sys.path.insert(0, str(V10/'prediction'))
import runner as v10runner, shared_execution, contracts   # noqa: E402
sys.path.insert(0, str(HERE))
import kernel_e, study_e_rules as se, trial_e, analyze_f, design_f, design_e, design_d, f_runner   # noqa: E402
from world_model import VirtualClock, StochasticWorld   # noqa: E402

passed = []
def check(name, cond):
    if not cond: raise AssertionError(name)
    passed.append(name)
def snap(seq, states): return {'channel': 'completion_watchdog', 'trialId': 't', 'sequence': seq, 'simulationTime': seq*.1,
                              'goals': [{'goalId': g, 'state': s} for g, s in zip(['g1', 'g2'], states)]}
# 1. manifest
m = design_f.make_manifest(); stored = json.loads((HERE/'f_manifest.json').read_text(encoding='utf-8'))
check('manifest_reproducible', json.loads(json.dumps(m)) == stored)
check('640_units', len(m['units']) == 640 and len({u['trial_id'] for u in m['units']}) == 640)
check('20_new_seeds', len(m['layout_seeds']) == 20 and not set(m['layout_seeds']) & design_f.excluded_seeds())
check('excludes_study_e_seeds', set(design_e.make_manifest()['layout_seeds']) <= design_f.excluded_seeds())
per_seed = collections.Counter(u['seed'] for u in m['units']); check('32_units_per_seed', set(per_seed.values()) == {32})
cells = collections.Counter((u['rule'], u['condition'], u['noise_type'], u['noise_correlation']) for u in m['units'])
check('full_factorial', len(cells) == 4*8 and set(cells.values()) == {20})
check('blocks_contiguous', all(len({u['seed'] for u in m['units'][i:i+32]}) == 1 for i in range(0, 640, 32)))
check('primary_secondary', [t['id'] for t in m['primary']['tests']] == ['H1', 'H2'] and [t['id'] for t in m['secondary']['tests']] == ['S1', 'S2'])
# 2. rules used unchanged
def reports_to_revoke(rule):
    mm = se.make_memory(rule, 't', ['g1', 'g2']); mm.refresh(snap(0, ['INVALID', 'INVALID'])); mm.commit_placement('g1', True)
    for i in range(1, 12):
        mm.refresh(snap(i, ['INVALID', 'INVALID']))
        if 'g1' not in mm.committed: return i
check('egr_needs_two_reports', [reports_to_revoke(r) for r in ['debounce2', 'revocable', 'belief_a10']] == [2, 1, 2])
d = se.make_memory('debounce2', 't', ['g1', 'g2']); d.refresh(snap(0, ['INVALID', 'INVALID'])); d.commit_placement('g1', True)
d.refresh(snap(1, ['UNKNOWN', 'INVALID'])); d.refresh(snap(2, ['INVALID', 'INVALID'])); d.refresh(snap(3, ['CONSISTENT', 'CONSISTENT']))
check('egr_placement_only_reentry', d.committed == set())
# 3. generated scripts reproducible
gen = Path(tempfile.mkdtemp())   # regenerate in a scratch folder; registered files are never rewritten by the test (amendment A0)
for n in ['e_runner.py', 'e_manager.py', 'make_f_scripts.py']: shutil.copy2(HERE/n, gen/n)
subprocess.run([sys.executable, 'make_f_scripts.py'], cwd=gen, check=True, capture_output=True)
check('scripts_regenerate_identically', all((gen/n).read_bytes() == (HERE/n).read_bytes() for n in ['f_runner.py', 'f_manager.py'])); shutil.rmtree(gen)
check('registered_files_exist', all((HERE/n).exists() for n in f_runner.FILES if n != 'f_runner.py') and all(p.exists() for p in f_runner.DEPS.values()))
check('runner_paths', f_runner.RUN.name == 'formal_F' and f_runner.PRECHECK_ID == 'precheck_F' and f_runner.REG.name == 'registration_F.json')
# 4. full 640-unit dry run in the model world: replay audit, checkpoint, frozen inference
clk = VirtualClock(); saved = (kernel_e.time, shared_execution.time, contracts.time); kernel_e.time = shared_execution.time = contracts.time = clk
tmp = Path(tempfile.mkdtemp()); run = tmp/'formal_F'; old = v10runner.kernel; v10runner.kernel = kernel_e
try:
    with contextlib.redirect_stdout(io.StringIO()):
        v10runner.execute(m, 640, None, run=run, rpc_factory=lambda: StochasticWorld(clk, 99), check_source=False)
        (tmp/'seg').mkdir(); cp = analyze_f.checkpoint(run, 'seg', exec_dir=tmp); inf = analyze_f.final(run)
finally:
    v10runner.kernel = old; kernel_e.time, shared_execution.time, contracts.time = saved
check('dry_run_640', inf['trials'] == 640 and inf['audit_all_passed'] and cp['audit_all_passed'])
check('tests_use_20_seeds', all(x['seeds'] == 20 for x in inf['primary']+inf['secondary']))
check('per_cell_descriptive', len(inf['egr_vs_each_rule_per_cell_descriptive']) == 8*3)
rows = trial_e.collect(run)[1]
check('egr_reobserves', sum(r['belief_reobservations'] for r in rows if r['rule'] == 'debounce2') > 0)
check('false_revocations_egr_below_revocable', sum(r['false_revocations'] for r in rows if r['rule'] == 'debounce2') < sum(r['false_revocations'] for r in rows if r['rule'] == 'revocable'))
print('MODEL-WORLD dry run (not data):', [(x['id'], x['a_total'], x['b_total'], x['a_greater'], x['b_greater'], round(x['p_holm'], 4)) for x in inf['primary']+inf['secondary']])
shutil.rmtree(tmp)
print(f'{len(passed)} Study F offline checks passed; 0 Unity calls, 0 model calls')
