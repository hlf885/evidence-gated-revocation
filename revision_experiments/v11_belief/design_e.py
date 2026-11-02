"""Study E manifest (written before any Study E trial). Questions: (1) does the assumed error rate set the
number of reports needed to revoke, trading false revocations against missed repairs as Proposition 3 predicts?
(2) is the belief rule's benefit reproduced by a fixed two-report debounce?
4 rules x 6 cells x 20 NEW seeds = 480 trials. Cells: false_invalid 20% (independent, persistent) x (no_fault, completed_shift)
and false_consistent 20% (independent, persistent) x completed_shift. (false_consistent x no_fault is omitted: every rule is at
ceiling there in Study D and in the prediction; revocable/reactive are omitted: Study D already measured them.)
Design revised before freezing after a prediction-based power check (10 seeds, 5 rules, 8 cells gave power 0.5-0.7)."""
from pathlib import Path
import copy, csv, json, random, sys
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'
sys.path.insert(0, str(V10)); sys.path.insert(0, str(HERE))
import design as v10design   # noqa: E402
import design_d              # noqa: E402
from study_e_rules import RULES, BELIEF_VARIANTS, params   # noqa: E402

PROTOCOL_ID = 'AR-belief-E-v1'
DESIGN_SEED = 2026103101
N_SEEDS = 20
CONDITIONS = ['no_fault', 'completed_shift']
LEVELS = [(t, 0.20, c) for t in ['false_invalid', 'false_consistent'] for c in ['independent', 'persistent']]
CELLS = [(k, 'false_invalid', 0.20, c) for k in CONDITIONS for c in ['independent', 'persistent']] + \
        [('completed_shift', 'false_consistent', 0.20, c) for c in ['independent', 'persistent']]
SEGMENT_SIZE = 24
FI = [{'noise_type': 'false_invalid', 'noise_rate': 0.20, 'noise_correlation': c, 'condition': k} for c in ['independent', 'persistent'] for k in CONDITIONS]
FC_SHIFT = [{'noise_type': 'false_consistent', 'noise_rate': 0.20, 'noise_correlation': c, 'condition': 'completed_shift'} for c in ['independent', 'persistent']]
PRIMARY = [   # Proposition 3: a larger assumed error rate needs more consecutive reports, so fewer false revocations
    {'id': 'H1', 'a': 'belief_a02', 'b': 'belief_a10', 'outcome': 'false_revocations', 'pool': FI, 'expected': 'a > b',
     'test': 'two_sided_exact_sign_flip_permutation_test_on_per_seed_totals'},
    {'id': 'H2', 'a': 'belief_a10', 'b': 'belief_a30', 'outcome': 'false_revocations', 'pool': FI, 'expected': 'a > b',
     'test': 'two_sided_exact_sign_flip_permutation_test_on_per_seed_totals'},
]


def excluded_seeds():
    return design_d.excluded_seeds() | set(design_d.make_manifest()['layout_seeds'])


def make_manifest():
    base = v10design.make_manifest(); templates = {}
    for s in base['scenarios']: templates.setdefault(s['condition'], s)
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
            s = copy.deepcopy(templates[cond]); s.update(seed=seed, scenario_id=f'E_3goals_{cond}_seed{seed}', layout_offsets=offsets); scenarios.append(s)
            for rule in RULES:
                for t, r, c in [(t, r, c) for k, t, r, c in CELLS if k == cond]:
                    block.append({'trial_id': f"{s['scenario_id']}_{rule}_{design_d.label(t, r, c)}", 'scenario_id': s['scenario_id'], 'rule': rule, 'memory': rule,
                                  'noise_type': t, 'noise_rate': r, 'noise_correlation': c, 'seed': seed, 'condition': cond})
        rng.shuffle(block); blocks.append(block)
    rng.shuffle(blocks)
    units = [u | {'block': b} for b, block in enumerate(blocks) for u in block]
    return {'protocol_id': PROTOCOL_ID,
            'scope': 'Study E: assumed error rate of the belief rule (0.02/0.10/0.30) and a two-report debounce, under 20% independent/persistent errors; same kernel as Study D',
            'cells': [{'condition': k, 'noise_type': t, 'noise_rate': r, 'noise_correlation': c} for k, t, r, c in CELLS],
            'design_seed': DESIGN_SEED, 'layout_seeds': seeds, 'layout_jitter_m': .008, 'rules': list(RULES), 'conditions': CONDITIONS,
            'noise_levels': [{'noise_type': t, 'noise_rate': r, 'noise_correlation': c} for t, r, c in LEVELS], 'persistence': 0.8,
            'belief_variants': {k: {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in params(k).items()} for k in BELIEF_VARIANTS},
            'segment_size': SEGMENT_SIZE, 'primary': {'multiplicity': 'Holm within 2', 'alpha': .05, 'tests': PRIMARY},
            'budget': base['budget'], 'evaluation': base['evaluation'], 'scenarios': scenarios, 'units': units}


def main():
    m = make_manifest()
    with (HERE/'e_manifest.json').open('x', encoding='utf-8') as f: json.dump(m, f, indent=2, ensure_ascii=False)
    with (HERE/'e_schedule.csv').open('x', encoding='utf-8-sig', newline='') as f:
        fields = ['ordinal', 'block', 'seed', 'condition', 'rule', 'noise_type', 'noise_rate', 'noise_correlation', 'trial_id']
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for i, u in enumerate(m['units']): w.writerow({k: v for k, v in (u | {'ordinal': i}).items() if k in fields})
    print(len(m['units']), 'units; seeds', m['layout_seeds'])


if __name__ == '__main__':
    main()
