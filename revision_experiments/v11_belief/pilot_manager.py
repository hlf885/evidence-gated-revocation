"""v11 gate-2 pilot manager (Windows). Reuses the v10 manager's Unity ownership (hidden batch Unity per segment,
start-up retries, terminate/kill escalation, keep-awake, early-end handling). Usage: python pilot_manager.py --expected-completed 0"""
from pathlib import Path
import argparse, subprocess, sys, time
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'
sys.path.insert(0, str(V10))
import manager as m10   # noqa: E402  (v10, unmodified)
fr = m10.fr
sys.path.insert(0, str(HERE))
import pilot_runner as pr   # noqa: E402

EXEC = HERE/'execution/pilot_belief_01'


def main():
    p = argparse.ArgumentParser(); p.add_argument('--expected-completed', type=int, required=True); a = p.parse_args()
    EXEC.mkdir(parents=True, exist_ok=True); pr.verify()
    manifest = fr.read(HERE/'pilot_manifest.json'); total = len(manifest['units']); size = manifest['segment_size']
    with fr.exclusive_lock(EXEC):
        start = len(fr.inspect_resume(pr.RUN, manifest)) if pr.RUN.exists() else 0
        if start != a.expected_completed: raise RuntimeError(f'Expected {a.expected_completed}, found {start}')
        m10.keep_awake(True)
        try:
            while start < total:
                if (HERE/'STOP_AFTER_SEGMENT').exists():
                    m10.status(EXEC, state='stopped_at_boundary', sealed=start, planned=total); return
                k = m10.segment_plan(start, size, total)
                seg = EXEC/f'segment_{len(list(EXEC.glob("segment_*")))+1:03d}'; seg.mkdir(exist_ok=False)
                fr.create_json(seg/'plan.json', {'start_sealed': start, 'max_trials': k, 'utc': fr.now()})
                m10.with_unity(EXEC, seg, [sys.executable, '-u', str(HERE/'pilot_runner.py'), 'run', '--max-trials', str(k)], k*240+1800)
                done = len(fr.inspect_resume(pr.RUN, manifest))
                early = m10.check_segment(start, k, done, fr.read(pr.RUN/'progress.json'), manifest['units'])
                start = done; m10.status(EXEC, state='segment_complete', sealed=start, planned=total, early_end=early)
            with (EXEC/'pilot_report.log').open('ab') as log:
                code = subprocess.run([sys.executable, str(HERE/'pilot_report.py')], cwd=HERE, stdout=log, stderr=subprocess.STDOUT, **m10.hidden()).returncode
            m10.status(EXEC, state='complete', sealed=start, planned=total, report_exit_code=code)
        except BaseException as exc:
            fr.create_json(EXEC/f'halt_{int(time.time())}.json', {'utc': fr.now(), 'error_type': type(exc).__name__, 'error': str(exc)})
            m10.status(EXEC, state='halted', error=str(exc), instruction='Preserve evidence; inspect status.json before any continuation.')
            raise
        finally:
            m10.keep_awake(False)


if __name__ == '__main__':
    main()
