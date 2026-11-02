"""VLM calibration, step 2: ask a vision-language model whether each goal holds in each captured frame (main and side view).
The API key is read from the environment variable DASHSCOPE_API_KEY. It is held in memory only and is never printed,
logged, or written to any file.
Pass 1: every frame x goal x view, temperature 0.  Pass 2 (repeat consistency): a fixed 10% subset, 3 more queries at temperature 0.7.
Answers are cached in answers.jsonl (resumable). Usage: python query_vlm.py [--workers 4] [--dry-run]"""
from pathlib import Path
import argparse, base64, concurrent.futures as cf, json, os, random, sys, threading, time, urllib.request
HERE = Path(__file__).resolve().parent; FRAMES = HERE/'frames'; OUT = HERE/'answers.jsonl'
API_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'; MODEL = 'qwen3-vl-plus'
GOALS = {'g1': ('red cube', 'in', 'bowl'), 'g2': ('green ball', 'on', 'yellow plate'), 'g3': ('yellow cylinder', 'in', 'bowl')}
PROMPT = 'Look at the image. Is the {o} resting {p} the {c}? Answer with exactly one word: yes, no, or unclear.'
lock = threading.Lock()


def get_key():
    """Return the DashScope API key from the environment, or None."""
    return os.environ.get('DASHSCOPE_API_KEY', '').strip() or None


def parse(text):
    w = (text or '').strip().lower().lstrip('*"\' ').split()
    w = w[0].strip('.,!*"\'') if w else ''
    return {'yes': 'CONSISTENT', 'no': 'INVALID'}.get(w, 'UNKNOWN')


def ask(img_path, goal, temperature, key):
    o, p, c = GOALS[goal]; b64 = base64.b64encode((FRAMES/img_path).read_bytes()).decode()
    body = {'model': MODEL, 'temperature': temperature, 'max_tokens': 20,
            'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,'+b64}},
                                                      {'type': 'text', 'text': PROMPT.format(o=o, p=p, c=c)}]}]}
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: data = json.loads(r.read())
            return data['choices'][0]['message']['content']
        except Exception as exc:
            if attempt == 4: return 'ERROR '+type(exc).__name__
            time.sleep(2**attempt)


def jobs():
    if not (FRAMES/'frames.jsonl').exists():
        sys.exit('frames/frames.jsonl not found: run capture_states.py first, or extract the data archive.')
    rows = [json.loads(l) for l in (FRAMES/'frames.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    rows = [r for r in rows if 'main' in r and r.get('score')]
    rng = random.Random(20261102); subset = set(rng.sample(range(len(rows)), max(1, len(rows)//10)))
    for i, r in enumerate(rows):
        for view in ['main', 'side']:
            for g in GOALS:
                yield (r['trial_id'], r['k'], view, g, 0, 0.0, r[view])
                if i in subset:
                    for rep in (1, 2, 3): yield (r['trial_id'], r['k'], view, g, rep, 0.7, r[view])


def main():
    a = argparse.ArgumentParser(); a.add_argument('--workers', type=int, default=4); a.add_argument('--dry-run', action='store_true'); a = a.parse_args()
    done = set()
    if OUT.exists():
        for l in OUT.read_text(encoding='utf-8').splitlines():
            x = json.loads(l)
            if not x['raw'].startswith('ERROR'): done.add((x['trial_id'], x['k'], x['view'], x['goal'], x['rep']))
    todo = [j for j in jobs() if j[:5] not in done]
    print(json.dumps({'queries_to_run': len(todo), 'already_done': len(done)}), flush=True)
    if a.dry_run: return
    key = get_key()
    if not key: sys.exit('Set the environment variable DASHSCOPE_API_KEY before running this script.')
    print('DashScope API key found in the environment.', flush=True)
    def work(j):
        raw = ask(j[6], j[3], j[5], key)
        rec = {'trial_id': j[0], 'k': j[1], 'view': j[2], 'goal': j[3], 'rep': j[4], 'temperature': j[5], 'raw': raw, 'state': parse(raw), 'model': MODEL}
        with lock:
            with OUT.open('a', encoding='utf-8') as f: f.write(json.dumps(rec)+'\n')
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for i, _ in enumerate(ex.map(work, todo), 1):
            if i % 200 == 0: print(f'{i}/{len(todo)}', flush=True)
    print('done', flush=True)


if __name__ == '__main__':
    main()
