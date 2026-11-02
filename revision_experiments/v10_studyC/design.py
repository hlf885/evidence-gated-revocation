"""Study C manifest and schedule. Draws layouts without consulting any robot outcome."""
from pathlib import Path
import copy, csv, json, random

ROOT = Path(__file__).resolve().parent
V7 = ROOT.parent/'v7'; V8 = ROOT.parent/'v8'; V9 = ROOT.parent/'v9'
PROTOCOL_ID = 'AR-completion-noise-v1'
DESIGN_SEED = 2026102901
N_SEEDS = 20
RULES = ['commit_only', 'revocable', 'reactive']
NOISE = [('none', 0.0)] + [(t, r) for t in ['false_invalid', 'false_consistent'] for r in [0.02, 0.05, 0.10]]
CONDITIONS = ['no_fault', 'completed_shift']
SEGMENT_SIZE = 21


def used_seeds():
    """Layout seeds of the earlier v8/v9 stages. Read from their manifests when present, otherwise from prior_seeds.json."""
    if not (V8/'formal_manifest.json').exists():
        return set(json.loads((ROOT/'prior_seeds.json').read_text(encoding='utf-8'))['seeds'])
    seeds = set(json.loads((V8/'formal_manifest.json').read_text(encoding='utf-8'))['layout_seeds'])
    try:
        v9 = json.loads((V9/'formal_manifest.json').read_text(encoding='utf-8'))
        seeds |= {s['seed'] for s in v9.get('scenarios', [])} | set(v9.get('layout_seeds', []))
        for key in ['development_seeds_reserved', 'excluded_prior_seeds']:
            value = v9.get(key, [])
            seeds |= {x for x in (value if isinstance(value, list) else []) if isinstance(x, int)}
    except FileNotFoundError:
        pass
    return seeds


def noise_label(t, r):
    return 'none' if t == 'none' else f'{t}_{int(round(r*100)):02d}'


def make_manifest():
    old = json.loads((V7/'ablation_manifest.json').read_text(encoding='utf-8'))
    templates = {s['condition']: s for s in old['scenarios'] if s['task_length'] == 3 and s['condition'] in CONDITIONS}
    assert set(templates) == set(CONDITIONS)
    rng = random.Random(DESIGN_SEED); excluded = used_seeds(); seeds = []
    while len(seeds) < N_SEEDS:
        s = rng.randrange(100000, 1000000)
        if s not in excluded and s not in seeds:
            seeds.append(s)
    scenarios, blocks = [], []
    for seed in seeds:
        layout_rng = random.Random(seed)
        offsets = {e['id']: {'x': round(layout_rng.uniform(-.008, .008), 6), 'y': 0,
                              'z': round(layout_rng.uniform(-.008, .008), 6)}
                   for e in templates['no_fault']['entities'] if e['kind'] == 'object'}
        block = []
        for condition in CONDITIONS:
            s = copy.deepcopy(templates[condition])
            s.update(seed=seed, scenario_id=f'3goals_{condition}_seed{seed}', layout_offsets=offsets)
            scenarios.append(s)
            for rule in RULES:
                for t, r in NOISE:
                    block.append({'trial_id': f"{s['scenario_id']}_{rule}_{noise_label(t, r)}", 'scenario_id': s['scenario_id'],
                                  'rule': rule, 'memory': rule, 'noise_type': t, 'noise_rate': r, 'seed': seed,
                                  'condition': condition})
        rng.shuffle(block); blocks.append(block)
    rng.shuffle(blocks)
    units = []
    for b, block in enumerate(blocks):
        for u in block:
            units.append(u | {'block': b})
    return {'protocol_id': PROTOCOL_ID,
            'scope': 'Study C: completion-state rule x synthetic watchdog observation error; same v7 FSM; geometric localization; no models',
            'design_seed': DESIGN_SEED, 'layout_seeds': seeds, 'layout_jitter_m': .008, 'rules': RULES,
            'noise_levels': [{'noise_type': t, 'noise_rate': r} for t, r in NOISE], 'conditions': CONDITIONS,
            'segment_size': SEGMENT_SIZE,
            # Endpoints fixed before any formal trial, from the registered v2 prediction power analysis.
            'primary': {'contrast': 'revocable_vs_reactive', 'noise_rate': 0.10, 'multiplicity': 'Holm within 4', 'alpha': .05,
                        'tests': [{'noise_type': 'false_consistent', 'condition': c, 'outcome': 'independent_final_task_success',
                                   'test': 'two_sided_exact_McNemar_paired_by_seed'} for c in CONDITIONS] +
                                 [{'noise_type': 'false_invalid', 'condition': c, 'outcome': 'extra_repicks_of_satisfied_objects',
                                   'test': 'two_sided_exact_sign_test_paired_by_seed'} for c in CONDITIONS]},
            'budget': old['budget'], 'evaluation': old['evaluation'], 'scenarios': scenarios, 'units': units}


PILOT_SEED = 2026102999


def make_pilot_manifest():
    """Development pilot: 1 non-formal seed x completed_shift x 3 rules x {none, 10% of each noise}. Excluded from all analyses."""
    m = make_manifest(); formal = set(m['layout_seeds']) | used_seeds()
    rng = random.Random(PILOT_SEED); seed = rng.randrange(100000, 1000000)
    while seed in formal: seed = rng.randrange(100000, 1000000)
    template = next(s for s in m['scenarios'] if s['condition'] == 'completed_shift')
    s = copy.deepcopy(template); layout_rng = random.Random(seed)
    s.update(seed=seed, scenario_id=f'pilot_3goals_completed_shift_seed{seed}',
             layout_offsets={k: {'x': round(layout_rng.uniform(-.008, .008), 6), 'y': 0, 'z': round(layout_rng.uniform(-.008, .008), 6)} for k in template['layout_offsets']})
    units = [{'trial_id': f"{s['scenario_id']}_{rule}_{noise_label(t, r)}", 'scenario_id': s['scenario_id'], 'rule': rule, 'memory': rule,
              'noise_type': t, 'noise_rate': r, 'seed': seed, 'condition': 'completed_shift', 'block': 0}
             for rule in RULES for t, r in [('none', 0.0), ('false_invalid', 0.10), ('false_consistent', 0.10)]]
    return m | {'scope': 'DEVELOPMENT PILOT ONLY - excluded from Study C analyses', 'layout_seeds': [seed], 'scenarios': [s], 'units': units}


def main():
    m = make_manifest()
    with (ROOT/'formal_manifest.json').open('x', encoding='utf-8') as f:
        json.dump(m, f, indent=2, ensure_ascii=False)
    with (ROOT/'schedule.csv').open('x', encoding='utf-8-sig', newline='') as f:
        fields = ['ordinal', 'block', 'seed', 'condition', 'rule', 'noise_type', 'noise_rate', 'trial_id']
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for i, u in enumerate(m['units']):
            w.writerow({k: v for k, v in (u | {'ordinal': i}).items() if k in fields})
    print(f"{len(m['units'])} units, {len(m['layout_seeds'])} seed blocks; no execution")


if __name__ == '__main__':
    main()
