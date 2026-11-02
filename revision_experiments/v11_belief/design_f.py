"""Study F manifest (written before any Study F trial). Question: does evidence-gated revocation, the rule recommended by the
analysis (revoke after n* = 2 consecutive reports that are not CONSISTENT; readmit only by an accepted placement; implemented as the
Study E 'debounce2' memory), outperform the fixed rule that each error type defeats, when all rules run in the same study?
4 rules x 8 cells x 20 NEW seeds = 640 trials. Cells: {false_invalid, false_consistent} 20% x {independent, persistent (s = 0.8)}
x {no_fault, completed_shift}. Kernel, rules and audit are the frozen Study E files, used unchanged.
Primary (Holm within 2, exact two-sided sign-flip permutation test on per-seed success totals over four cells):
  H1 egr (debounce2) vs revocable under false-invalid reports;  H2 egr vs memoryless (reactive) under false-consistent reports.
Secondary (Holm within 2, same test): S1 egr vs belief_a10 under false-consistent; S2 egr vs belief_a10 under false-invalid."""
from pathlib import Path
import copy, csv, json, random, sys
HERE = Path(__file__).resolve().parent; V10 = HERE.parent/'v10_studyC'
sys.path.insert(0, str(V10)); sys.path.insert(0, str(HERE))
import design as v10design   # noqa: E402
import design_d, design_e    # noqa: E402

PROTOCOL_ID = 'AR-egr-F-v1'
DESIGN_SEED = 2026110101
N_SEEDS = 20
RULES = ('debounce2', 'revocable', 'reactive', 'belief_a10')
CONDITIONS = ['no_fault', 'completed_shift']
TYPES = ['false_invalid', 'false_consistent']
CORR = ['independent', 'persistent']
CELLS = [(k, t, 0.20, c) for t in TYPES for c in CORR for k in CONDITIONS]
SEGMENT_SIZE = 32
SUCC = 'independent_final_task_success'
POOL = {t: [{'noise_type': t, 'noise_rate': 0.20, 'noise_correlation': c, 'condition': k} for c in CORR for k in CONDITIONS] for t in TYPES}
TEST = 'two_sided_exact_sign_flip_permutation_test_on_per_seed_totals'
PRIMARY = [{'id': 'H1', 'a': 'debounce2', 'b': 'revocable', 'outcome': SUCC, 'pool': POOL['false_invalid'], 'expected': 'a > b', 'test': TEST},
           {'id': 'H2', 'a': 'debounce2', 'b': 'reactive', 'outcome': SUCC, 'pool': POOL['false_consistent'], 'expected': 'a > b', 'test': TEST}]
SECONDARY = [{'id': 'S1', 'a': 'debounce2', 'b': 'belief_a10', 'outcome': SUCC, 'pool': POOL['false_consistent'], 'expected': 'a > b', 'test': TEST},
             {'id': 'S2', 'a': 'debounce2', 'b': 'belief_a10', 'outcome': SUCC, 'pool': POOL['false_invalid'], 'expected': 'none (two-sided)', 'test': TEST}]


def excluded_seeds():
    return design_e.excluded_seeds() | set(design_e.make_manifest()['layout_seeds'])


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
            s = copy.deepcopy(templates[cond]); s.update(seed=seed, scenario_id=f'F_3goals_{cond}_seed{seed}', layout_offsets=offsets); scenarios.append(s)
            for rule in RULES:
                for t, r, c in [(t, r, c) for k, t, r, c in CELLS if k == cond]:
                    block.append({'trial_id': f"{s['scenario_id']}_{rule}_{design_d.label(t, r, c)}", 'scenario_id': s['scenario_id'], 'rule': rule, 'memory': rule,
                                  'noise_type': t, 'noise_rate': r, 'noise_correlation': c, 'seed': seed, 'condition': cond})
        rng.shuffle(block); blocks.append(block)
    rng.shuffle(blocks)
    units = [u | {'block': b} for b, block in enumerate(blocks) for u in block]
    return {'protocol_id': PROTOCOL_ID,
            'scope': 'Study F: evidence-gated revocation (n* = 2, placement-only re-entry; Study E debounce2) against revocable memory, memoryless re-checking and the belief rule, under 20% independent/persistent errors; frozen Study E kernel',
            'cells': [{'condition': k, 'noise_type': t, 'noise_rate': r, 'noise_correlation': c} for k, t, r, c in CELLS],
            'design_seed': DESIGN_SEED, 'layout_seeds': seeds, 'layout_jitter_m': .008, 'rules': list(RULES), 'rule_labels': {'debounce2': 'evidence-gated revocation, n* = 2', 'reactive': 'memoryless re-checking'},
            'conditions': CONDITIONS, 'noise_levels': [{'noise_type': t, 'noise_rate': .20, 'noise_correlation': c} for t in TYPES for c in CORR], 'persistence': 0.8,
            'segment_size': SEGMENT_SIZE, 'primary': {'multiplicity': 'Holm within 2', 'alpha': .05, 'tests': PRIMARY},
            'secondary': {'multiplicity': 'Holm within 2', 'alpha': .05, 'tests': SECONDARY},
            'budget': base['budget'], 'evaluation': base['evaluation'], 'scenarios': scenarios, 'units': units}


def main():
    m = make_manifest()
    with (HERE/'f_manifest.json').open('x', encoding='utf-8') as f: json.dump(m, f, indent=2, ensure_ascii=False)
    with (HERE/'f_schedule.csv').open('x', encoding='utf-8-sig', newline='') as f:
        fields = ['ordinal', 'block', 'seed', 'condition', 'rule', 'noise_type', 'noise_rate', 'noise_correlation', 'trial_id']
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for i, u in enumerate(m['units']): w.writerow({k: v for k, v in (u | {'ordinal': i}).items() if k in fields})
    print(len(m['units']), 'units; seeds', m['layout_seeds'])


if __name__ == '__main__':
    main()
