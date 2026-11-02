"""Study D manifest: belief completion state vs revocable vs reactive under independent and persistent
observation errors, with the belief rule's assumed error rate (0.10) correct (r = 0.10) or too low (r = 0.20).
3 rules x 2 conditions x 9 error levels x 20 NEW seeds = 1080 trials. Written before any Study D trial."""
from pathlib import Path
import copy, csv, json, random, sys
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'
sys.path.insert(0, str(V10)); sys.path.insert(0, str(HERE))
import design as v10design    # noqa: E402
import design_v11             # noqa: E402
from study_d_rules import BELIEF_PARAMS   # noqa: E402

PROTOCOL_ID = 'AR-belief-D-v1'
DESIGN_SEED = 2026103002
N_SEEDS = 20
RULES = ['belief', 'revocable', 'reactive']
CONDITIONS = ['no_fault', 'completed_shift']
LEVELS = [('none', 0.0, 'none')] + [(t, r, c) for t in ['false_invalid', 'false_consistent'] for r in [0.10, 0.20]
                                    for c in ['independent', 'persistent']]
SEGMENT_SIZE = 27


def label(t, r, c):
    return 'none' if t == 'none' else f"{t}_{int(round(r*100)):02d}_{'ind' if c == 'independent' else 'per'}"


def excluded_seeds():
    return design_v11.excluded_seeds() | set(design_v11.make_pilot_manifest()['layout_seeds'])


PRIMARY = [  # belief vs the rule that each error type is known to defeat; independent errors at the assumed rate 0.10
    {'condition': c, 'noise_type': t, 'noise_rate': 0.10, 'noise_correlation': 'independent', 'a': 'belief', 'b': b,
     'outcome': 'independent_final_task_success', 'test': 'two_sided_exact_McNemar_paired_by_seed'}
    for t, b in [('false_invalid', 'revocable'), ('false_consistent', 'reactive')] for c in CONDITIONS]
KEY_SECONDARY = [  # the same four contrasts where the belief rule's assumptions fail: persistent errors, and rate 0.20 (misspecified)
    dict(p, noise_rate=r, noise_correlation=c) for p in PRIMARY for r, c in [(0.10, 'persistent'), (0.20, 'independent'), (0.20, 'persistent')]]


def make_manifest():
    base = v10design.make_manifest(); templates = {}
    for s in base['scenarios']:
        templates.setdefault(s['condition'], s)
    rng = random.Random(DESIGN_SEED); excl = excluded_seeds(); seeds = []
    while len(seeds) < N_SEEDS:
        s = rng.randrange(100000, 1000000)
        if s not in excl and s not in seeds: seeds.append(s)
    scenarios, blocks = [], []
    for seed in seeds:
        lr = random.Random(seed)
        offsets = {k: {'x': round(lr.uniform(-.008, .008), 6), 'y': 0, 'z': round(lr.uniform(-.008, .008), 6)} for k in templates['no_fault']['layout_offsets']}
        block = []
        for cond in CONDITIONS:
            s = copy.deepcopy(templates[cond]); s.update(seed=seed, scenario_id=f'D_3goals_{cond}_seed{seed}', layout_offsets=offsets); scenarios.append(s)
            for rule in RULES:
                for t, r, c in LEVELS:
                    block.append({'trial_id': f"{s['scenario_id']}_{rule}_{label(t, r, c)}", 'scenario_id': s['scenario_id'], 'rule': rule, 'memory': rule,
                                  'noise_type': t, 'noise_rate': r, 'noise_correlation': c, 'seed': seed, 'condition': cond})
        rng.shuffle(block); blocks.append(block)
    rng.shuffle(blocks)
    units = [u | {'block': b} for b, block in enumerate(blocks) for u in block]
    return {'protocol_id': PROTOCOL_ID,
            'scope': 'Study D: belief completion state vs revocable vs reactive; independent/persistent synthetic watchdog errors; same v7 FSM + holding-first; geometric localization; no models',
            'design_seed': DESIGN_SEED, 'layout_seeds': seeds, 'layout_jitter_m': .008, 'rules': RULES, 'conditions': CONDITIONS,
            'noise_levels': [{'noise_type': t, 'noise_rate': r, 'noise_correlation': c} for t, r, c in LEVELS], 'persistence': 0.8,
            'belief_params': {k: list(v) if isinstance(v, tuple) else v for k, v in BELIEF_PARAMS.items()},
            'segment_size': SEGMENT_SIZE,
            'primary': {'multiplicity': 'Holm within 4', 'alpha': .05, 'tests': PRIMARY},
            'key_secondary': {'multiplicity': 'Holm within 12', 'tests': KEY_SECONDARY},
            'budget': base['budget'], 'evaluation': base['evaluation'], 'scenarios': scenarios, 'units': units}


def main():
    m = make_manifest()
    with (HERE/'d_manifest.json').open('x', encoding='utf-8') as f: json.dump(m, f, indent=2, ensure_ascii=False)
    with (HERE/'d_schedule.csv').open('x', encoding='utf-8-sig', newline='') as f:
        fields = ['ordinal', 'block', 'seed', 'condition', 'rule', 'noise_type', 'noise_rate', 'noise_correlation', 'trial_id']
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for i, u in enumerate(m['units']): w.writerow({k: v for k, v in (u | {'ordinal': i}).items() if k in fields})
    print(len(m['units']), 'units; seeds', m['layout_seeds'])


if __name__ == '__main__':
    main()
