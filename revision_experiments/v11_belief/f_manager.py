"""Study F manager (Windows; generated from e_manager.py by make_f_scripts.py). Reuses the v10 manager's Unity ownership (hidden batch Unity per segment, start-up retries,
terminate/kill escalation, keep-awake, early-end checks). Segments end on multiples of 32.
Usage:  python f_manager.py --precheck      then      python f_manager.py --expected-completed 0"""
from pathlib import Path
import argparse, subprocess, sys, time
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'
sys.path.insert(0, str(V10))
import manager as m10   # noqa: E402  (v10, unmodified)
fr = m10.fr
sys.path.insert(0, str(HERE))
import f_runner as dr   # noqa: E402

EXEC = HERE/'execution/formal_F'


def cmd(*args): return [sys.executable, '-u', str(HERE/'f_runner.py'), *args]


def main():
    p = argparse.ArgumentParser(); p.add_argument('--expected-completed', type=int); p.add_argument('--precheck', action='store_true'); a = p.parse_args()
    EXEC.mkdir(parents=True, exist_ok=True); dr.verify(); manifest = dr.manifest(); total = len(manifest['units']); size = manifest['segment_size']
    if a.precheck:
        seg = EXEC/dr.PRECHECK_ID; seg.mkdir(exist_ok=False)
        m10.with_unity(EXEC, seg, cmd('precheck'), 900)
        gate = fr.read(HERE/'prechecks'/dr.PRECHECK_ID/'precheck_gate.json'); m10.status(EXEC, state='precheck_done', passed=gate['passed']); return
    if a.expected_completed is None: raise SystemExit('--expected-completed is required')
    with fr.exclusive_lock(EXEC):
        start = len(fr.inspect_resume(dr.RUN, manifest)) if dr.RUN.exists() else 0
        if start != a.expected_completed: raise RuntimeError(f'Expected {a.expected_completed}, found {start}')
        m10.keep_awake(True)
        try:
            while start < total:
                if (HERE/'STOP_AFTER_SEGMENT').exists():
                    m10.status(EXEC, state='stopped_at_boundary', sealed=start, planned=total); return
                k = m10.segment_plan(start, size, total)
                seg = EXEC/f'segment_{len(list(EXEC.glob("segment_*")))+1:03d}'; seg.mkdir(exist_ok=False)
                fr.create_json(seg/'plan.json', {'start_sealed': start, 'max_trials': k, 'utc': fr.now()})
                m10.with_unity(EXEC, seg, cmd('run', '--max-trials', str(k)), k*240+1800)
                done = len(fr.inspect_resume(dr.RUN, manifest))
                early = m10.check_segment(start, k, done, fr.read(dr.RUN/'progress.json'), manifest['units'])
                with (seg/'checkpoint.log').open('xb') as log:
                    code = subprocess.run([sys.executable, str(HERE/'analyze_f.py'), '--checkpoint', seg.name], cwd=HERE, stdout=log,
                                          stderr=subprocess.STDOUT, **m10.hidden()).returncode
                if code == m10.AUDIT_FAILED: raise RuntimeError(f'Checkpoint replay audit failed; see {seg/"checkpoint.json"}')
                start = done; m10.status(EXEC, state='segment_complete', sealed=start, planned=total, early_end=early, checkpoint_exit_code=code,
                                         infrastructure_exclusions=len(fr.exclusions(dr.RUN)))
            with (EXEC/'final_analysis.log').open('ab') as log:
                code = subprocess.run([sys.executable, str(HERE/'analyze_f.py'), '--final'], cwd=HERE, stdout=log, stderr=subprocess.STDOUT, **m10.hidden()).returncode
            m10.status(EXEC, state='complete', sealed=start, planned=total, final_analysis_exit_code=code)
        except BaseException as exc:
            fr.create_json(EXEC/f'halt_{int(time.time())}.json', {'utc': fr.now(), 'error_type': type(exc).__name__, 'error': str(exc)})
            m10.status(EXEC, state='halted', error=str(exc), instruction='Preserve evidence; inspect status.json before any continuation.')
            raise
        finally:
            m10.keep_awake(False)


if __name__ == '__main__':
    main()
