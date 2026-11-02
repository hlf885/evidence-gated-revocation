"""v11 gate-2 pilot design: belief vs revocable vs reactive on the four decisive Study C cells.
5 NEW layout seeds (disjoint from v8/v9/v10 formal and pilot seeds); development evidence only."""
from pathlib import Path
import copy, json, random, sys
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'
sys.path.insert(0, str(V10))
import design as v10design   # noqa: E402  (v10, unmodified)

PROTOCOL_ID = 'AR-belief-pilot-v1'
PILOT_DESIGN_SEED = 2026103001
N_SEEDS = 5
RULES = ['belief', 'revocable', 'reactive']
CELLS = [('no_fault', 'false_invalid', 0.10), ('completed_shift', 'false_invalid', 0.10),
         ('completed_shift', 'false_consistent', 0.10), ('completed_shift', 'none', 0.0)]
SEGMENT_SIZE = 20


def excluded_seeds():
    v10 = v10design.make_manifest(); pilot = v10design.make_pilot_manifest()
    return v10design.used_seeds() | set(v10['layout_seeds']) | set(pilot['layout_seeds'])


def make_pilot_manifest():
    base = v10design.make_manifest()
    templates = {}
    for s in base['scenarios']:
        templates.setdefault(s['condition'], s)
    rng = random.Random(PILOT_DESIGN_SEED); excl = excluded_seeds(); seeds = []
    while len(seeds) < N_SEEDS:
        s = rng.randrange(100000, 1000000)
        if s not in excl and s not in seeds: seeds.append(s)
    scenarios, blocks = [], []
    for seed in seeds:
        lr = random.Random(seed)
        offsets = {k: {'x': round(lr.uniform(-.008, .008), 6), 'y': 0, 'z': round(lr.uniform(-.008, .008), 6)}
                   for k in templates['no_fault']['layout_offsets']}
        for cond in ['no_fault', 'completed_shift']:
            s = copy.deepcopy(templates[cond]); s.update(seed=seed, scenario_id=f'belief_pilot_{cond}_seed{seed}', layout_offsets=offsets)
            scenarios.append(s)
        block = [{'trial_id': f'belief_pilot_{c}_seed{seed}_{rule}_{v10design.noise_label(t, r)}', 'scenario_id': f'belief_pilot_{c}_seed{seed}',
                  'rule': rule, 'memory': rule, 'noise_type': t, 'noise_rate': r, 'seed': seed, 'condition': c}
                 for c, t, r in CELLS for rule in RULES]
        rng.shuffle(block); blocks.append(block)
    units = [u | {'block': b} for b, block in enumerate(blocks) for u in block]
    return {'protocol_id': PROTOCOL_ID, 'scope': 'v11 GATE-2 DEVELOPMENT PILOT: belief completion state vs revocable vs reactive; excluded from confirmatory analyses',
            'design_seed': PILOT_DESIGN_SEED, 'layout_seeds': seeds, 'rules': RULES,
            'cells': [{'condition': c, 'noise_type': t, 'noise_rate': r} for c, t, r in CELLS],
            'segment_size': SEGMENT_SIZE, 'budget': base['budget'], 'evaluation': base['evaluation'],
            'scenarios': scenarios, 'units': units}


if __name__ == '__main__':
    m = make_pilot_manifest(); out = HERE/'pilot_manifest.json'
    with out.open('x', encoding='utf-8') as f: json.dump(m, f, ensure_ascii=False, indent=2)
    print(len(m['units']), 'units; seeds', m['layout_seeds'])
