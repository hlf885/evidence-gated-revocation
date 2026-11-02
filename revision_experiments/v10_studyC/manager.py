"""Study C segment manager (Windows). Adapted from v8/execution/continue_registered.py.

One foreground job owns one hidden batch-mode Unity per segment (at most 21 trials, ending
on a multiple of 21), runs `runner.py run --max-trials k`, then quits Unity and writes a
descriptive checkpoint. Amendment A1: a segment ends early after an ACTION_TIMEOUT or an
infrastructure exclusion so that the next trial starts in a freshly launched Unity; Unity
start-up is retried (no trial is affected); the PC is kept awake while the manager runs.
Outcomes never affect continuation. Create a file named STOP_AFTER_SEGMENT in this
folder to stop cleanly at the next segment boundary.
Usage:  python manager.py --expected-completed 0
"""
from pathlib import Path
import argparse, os, shutil, socket, subprocess, sys, time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import runner as fr  # noqa: E402

UNITY = Path(os.environ.get('UNITY_EDITOR', 'Unity'))   # path to the Unity 2020.3.49f1 editor executable
PROJECT = ROOT.parent/'v7/UnityRevision'
EXEC = ROOT/'execution'/'formal_02'      # A1: per-run folder (execution/ holds formal_01 evidence)
STARTUP_ATTEMPTS = 3
AUDIT_FAILED = 3                          # analyze.py exit code for a failed replay audit


def keep_awake(on=True):
    """Prevent Windows sleep (sleep would count against trial wall-time budgets)."""
    if os.name != 'nt': return
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def segment_plan(start, size, total):
    """Trials to run next so that segments end on multiples of `size`."""
    return min(size-start % size, total-start)


def check_segment(start, k, done, progress, units):
    """A1: accept a short segment only when the runner recorded an early end at the last sealed trial."""
    if done <= start: raise RuntimeError(f'No trial sealed in segment (start {start})')
    if done > start+k: raise RuntimeError(f'Unexpected sealed count {done} > {start+k}')
    if done < start+k:
        e = (progress or {}).get('early_end')
        if not e or e['trial_id'] != units[done-1]['trial_id']:
            raise RuntimeError(f'Short segment without a recorded early end ({done} of {start+k})')
        return e['cause']
    return None


def status(folder, **values):
    value = {'updated_utc': fr.now(), 'manager_pid': os.getpid(), **values}
    tmp = folder/'status.tmp'; tmp.write_text(fr.json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, folder/'status.json'); print(fr.json.dumps(value, ensure_ascii=False), flush=True)


def hidden():
    info = subprocess.STARTUPINFO(); info.dwFlags |= subprocess.STARTF_USESHOWWINDOW; info.wShowWindow = 0
    return {'startupinfo': info, 'creationflags': subprocess.CREATE_NO_WINDOW}


def assert_ports_free(wait=90):
    deadline = time.monotonic()+wait
    while True:
        try:
            for port in [5505, 5506]:
                with socket.socket() as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1); s.bind(('127.0.0.1', port))
            return
        except OSError:
            if time.monotonic() > deadline: raise RuntimeError('Ports 5505/5506 still busy; another Unity or runner is running')
            time.sleep(3)


def ready(unity, segment):
    deadline = time.monotonic()+180
    while time.monotonic() < deadline:
        if unity.poll() is not None: raise RuntimeError('Owned Unity exited during startup')
        try:
            with socket.create_connection(('127.0.0.1', 5505), timeout=1): pass
        except OSError:
            time.sleep(1); continue
        rpc = fr.kernel.UnityRPC()
        try:
            fr.create_json(segment/'unity_ping.json', rpc.call('REV_PING', timeout=20)); return
        finally:
            rpc.close()
    raise TimeoutError('Owned Unity startup exceeded 180 seconds')


def close_owned_unity(unity, segment):
    if unity.poll() is not None:
        fr.create_json(segment/'unity_exit.json', {'exit_code': unity.returncode, 'utc': fr.now(), 'already_exited': True}); return
    error = None
    try:
        rpc = fr.kernel.UnityRPC()
        try: fr.create_json(segment/'quit.json', rpc.call('REV_QUIT', timeout=10))
        finally: rpc.close()
        unity.wait(timeout=30)
    except Exception as exc:
        error = type(exc).__name__+': '+str(exc)
    for stop in (unity.terminate, unity.kill):  # A1: escalate; only a surviving process is fatal
        if unity.poll() is not None: break
        stop()
        try: unity.wait(timeout=20)
        except subprocess.TimeoutExpired: pass
    fr.create_json(segment/'unity_exit.json', {'exit_code': unity.returncode, 'utc': fr.now(), 'graceful_quit_error': error,
                   'still_running': unity.poll() is None})
    if unity.poll() is None: raise RuntimeError('Owned Unity could not be stopped: '+str(error))


def run_command(precheck=False, max_trials=21):
    if precheck:
        return [sys.executable, '-u', str(ROOT/'runner.py'), 'precheck', '--precheck-id', fr.PRECHECK_ID]
    return [sys.executable, '-u', str(ROOT/'runner.py'), 'run', '--max-trials', str(max_trials), '--precheck-id', fr.PRECHECK_ID]


def launch_ready(folder, segment):
    """Launch Unity and wait for REV_PING; retried because no trial has started yet (A1)."""
    for attempt in range(1, STARTUP_ATTEMPTS+1):
        where = segment if attempt == 1 else segment/f'startup_retry_{attempt}'; where.mkdir(exist_ok=True)
        assert_ports_free()
        cmd = [str(UNITY), '-batchmode', '-nographics', '-projectPath', str(PROJECT), '-executeMethod', 'RobotBatch.Start',
               '-revisionRobot', '-logFile', str(where/'unity.log')]
        unity = subprocess.Popen(cmd, cwd=ROOT, **hidden())
        fr.create_json(where/'launch.json', {'process_id': unity.pid, 'project': str(PROJECT), 'started_utc': fr.now(),
                       'command': cmd, 'manager_pid': os.getpid(), 'attempt': attempt})
        status(folder, state='unity_starting', segment=segment.name, unity_pid=unity.pid, attempt=attempt)
        try:
            ready(unity, where); return unity, where
        except Exception as exc:
            fr.create_json(where/'startup_failure.json', {'utc': fr.now(), 'error': type(exc).__name__+': '+str(exc)})
            close_owned_unity(unity, where)
            if attempt == STARTUP_ATTEMPTS: raise
            time.sleep(30)


def with_unity(folder, segment, command, timeout):
    if shutil.disk_usage(ROOT).free < 3*1024**3: raise RuntimeError('Less than 3 GiB free')
    unity, where = launch_ready(folder, segment); child = None
    try:
        with (segment/'runner.log').open('xb') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, **hidden())
            status(folder, state='running', segment=segment.name, unity_pid=unity.pid, runner_pid=child.pid)
            try: code = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=15); raise RuntimeError('Segment stalled; no automatic retry')
            if code: raise RuntimeError(f'Runner exited {code}; see {segment/"runner.log"}; no automatic retry')
    finally:
        if child is not None and child.poll() is None: child.kill(); child.wait(timeout=15)
        close_owned_unity(unity, where)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--expected-completed', type=int)
    p.add_argument('--precheck', action='store_true', help='run the registered interface precheck only')
    p.add_argument('--pilot', action='store_true', help='run the 9-trial development pilot (before freeze; excluded from analysis)')
    a = p.parse_args()
    EXEC.mkdir(parents=True, exist_ok=True)
    if a.pilot:
        seg = EXEC/'pilot_01'; seg.mkdir(exist_ok=False)
        with_unity(EXEC, seg, [sys.executable, '-u', str(ROOT/'runner.py'), 'pilot'], 9*240+1800)
        status(EXEC, state='pilot_done', results=str(ROOT/'results/pilot_01')); return
    fr.verify(); manifest = fr.read(ROOT/'formal_manifest.json'); total = len(manifest['units'])
    if a.precheck:
        seg = EXEC/fr.PRECHECK_ID; seg.mkdir(exist_ok=False)
        with_unity(EXEC, seg, run_command(precheck=True), 900)
        gate = fr.read(ROOT/'prechecks'/fr.PRECHECK_ID/'precheck_gate.json'); status(EXEC, state='precheck_done', passed=gate['passed']); return
    if a.expected_completed is None: raise SystemExit('--expected-completed is required')
    with fr.exclusive_lock(EXEC):
        start = len(fr.inspect_resume(fr.RUN, manifest)) if fr.RUN.exists() else 0
        if start != a.expected_completed: raise RuntimeError(f'Expected {a.expected_completed}, found {start}')
        keep_awake(True)
        try:
            while start < total:
                if (ROOT/'STOP_AFTER_SEGMENT').exists():
                    status(EXEC, state='stopped_at_boundary', sealed=start, planned=total); return
                k = segment_plan(start, manifest['segment_size'], total)
                seg = EXEC/f'segment_{len(list(EXEC.glob("segment_*")))+1:03d}'; seg.mkdir(exist_ok=False)
                fr.create_json(seg/'plan.json', {'start_sealed': start, 'max_trials': k, 'utc': fr.now()})
                with_unity(EXEC, seg, run_command(max_trials=k), k*240+1800)
                done = len(fr.inspect_resume(fr.RUN, manifest))
                early = check_segment(start, k, done, fr.read(fr.RUN/'progress.json'), manifest['units'])
                # Checkpoints are descriptive. A failed replay audit halts; an analysis-script error is logged only.
                with (seg/'checkpoint.log').open('xb') as log:
                    code = subprocess.run([sys.executable, str(ROOT/'analyze.py'), '--checkpoint', seg.name], cwd=ROOT,
                                          stdout=log, stderr=subprocess.STDOUT, **hidden()).returncode
                if code == AUDIT_FAILED: raise RuntimeError(f'Checkpoint replay audit failed; see {seg/"checkpoint.json"}')
                start = done; status(EXEC, state='segment_complete', sealed=start, planned=total, early_end=early,
                                     checkpoint_exit_code=code, infrastructure_exclusions=len(fr.exclusions(fr.RUN)))
            with (EXEC/'final_analysis.log').open('ab') as log:
                code = subprocess.run([sys.executable, str(ROOT/'analyze.py'), '--final'], cwd=ROOT, stdout=log,
                                      stderr=subprocess.STDOUT, **hidden()).returncode
            status(EXEC, state='complete', sealed=start, planned=total, final_analysis_exit_code=code)
        except BaseException as exc:
            fr.create_json(EXEC/f'halt_{int(time.time())}.json', {'utc': fr.now(), 'error_type': type(exc).__name__, 'error': str(exc)})
            status(EXEC, state='halted', error=str(exc), instruction='Preserve evidence; inspect before any continuation.')
            raise
        finally:
            keep_awake(False)


if __name__ == '__main__':
    main()
