"""Figure: Study E. (a) False revocations per trial under false-invalid reports (seed-bootstrap 95% CI);
(b) task success under false-invalid (4 cells) and false-consistent reports with a displaced object (2 cells), Wilson 95% CI."""
import collections, random
from common import trials, wilson, STYLE, setup_mpl, WIDTH, MM, OUT
plt = setup_mpl()
rows = trials('E'); rules = ['belief_a02', 'belief_a10', 'belief_a30', 'debounce2']
names = [r'belief' '\n' r'$\hat\alpha{=}0.02$', r'belief' '\n' r'$\hat\alpha{=}0.10$', r'belief' '\n' r'$\hat\alpha{=}0.30$', 'debounce\n' r'$n^*{=}2$']
fig, (a1, a2) = plt.subplots(1, 2, figsize=(WIDTH, 58*MM), gridspec_kw={'width_ratios': [1, 1.25]})
rng = random.Random(20261101)
for x, rule in enumerate(rules):
    per = collections.defaultdict(list)
    for r in rows:
        if r['rule'] == rule and r['noise_type'] == 'false_invalid': per[r['seed']].append(r['false_revocations'])
    seeds = sorted(per); m = [sum(per[s])/len(per[s]) for s in seeds]; mean = sum(m)/len(m)
    boots = sorted(sum(rng.choice(m) for _ in m)/len(m) for _ in range(4000)); lo, hi = boots[99], boots[3899]
    col, mk, _ = STYLE[rule]
    a1.errorbar([x], [mean], yerr=[[mean-lo], [hi-mean]], color=col, marker=mk, ms=4, capsize=1.5, elinewidth=0.6)
a1.set_xticks(range(4)); a1.set_xticklabels(names); a1.set_xlim(-0.5, 3.5); a1.set_ylim(0, None)
a1.set_ylabel('False revocations per trial'); a1.set_title('(a) False-invalid reports, 20%', loc='left'); a1.grid(axis='y', lw=0.3, color='0.85')
groups = [('false_invalid', None, 'false-invalid\n(4 cells)'), ('false_consistent', 'completed_shift', 'false-consistent,\nobject displaced (2 cells)')]
for g, (t, cond, lab) in enumerate(groups):
    for j, rule in enumerate(rules):
        v = [r['success'] for r in rows if r['rule'] == rule and r['noise_type'] == t and (cond is None or r['condition'] == cond)]
        k, n = sum(v), len(v); lo, hi = wilson(k, n); col, mk, _ = STYLE[rule]; x = g+(j-1.5)*0.17
        a2.errorbar([x], [k/n], yerr=[[k/n-lo], [hi-k/n]], color=col, marker=mk, ms=4, capsize=1.5, elinewidth=0.6, ls='none',
                    label=names[j].replace('\n', ' ') if g == 0 else None)
a2.set_xticks([0, 1]); a2.set_xticklabels([g[2] for g in groups]); a2.set_xlim(-0.5, 1.5); a2.set_ylim(0.5, 1.02)
a2.set_ylabel('Task success'); a2.set_title('(b) Task success, 20% errors', loc='left'); a2.grid(axis='y', lw=0.3, color='0.85')
a2.legend(frameon=False, loc='lower left', fontsize=6.5)
fig.tight_layout(w_pad=1.2)
fig.savefig(OUT/'figures/fig_studyE.pdf'); print('fig_studyE.pdf')
