"""Figure: Study D. Task success (Wilson 95% CI) for three rules across error type, rate, persistence and condition."""
import collections
from common import trials, wilson, STYLE, setup_mpl, WIDTH, MM, OUT
plt = setup_mpl()
rows = trials('D'); cells = collections.defaultdict(list)
for r in rows: cells[(r['condition'], r['noise_type'], r['noise_rate'], r['noise_correlation'], r['rule'])].append(r['success'])
fig, axes = plt.subplots(2, 2, figsize=(WIDTH, 92*MM), sharey=True)
types = [('false_invalid', 'False-invalid reports'), ('false_consistent', 'False-consistent reports')]
conds = [('no_fault', 'No disturbance'), ('completed_shift', 'Completed object displaced')]
levels = [('none', 0.0, 'none', 'no\nerrors'), (None, 0.10, 'independent', '10%\nind.'), (None, 0.10, 'persistent', '10%\npers.'),
          (None, 0.20, 'independent', '20%\nind.'), (None, 0.20, 'persistent', '20%\npers.')]
rules = ['revocable', 'reactive', 'belief_a10']; off = dict(zip(rules, [-0.22, 0.0, 0.22]))
for i, (t, tl) in enumerate(types):
    for j, (c, cl) in enumerate(conds):
        ax = axes[i][j]
        for x, (lt, rt, corr, _) in enumerate(levels):
            if x: ax.axvspan(x-0.5, x+0.5, color='0.96' if x % 2 else 'white', zorder=0, lw=0)
            for rule in rules:
                v = cells[(c, lt or t, rt, corr, rule)]; k, n = sum(v), len(v); a, b = wilson(k, n); col, mk, lab = STYLE[rule]
                ax.errorbar([x+off[rule]], [k/n], yerr=[[k/n-a], [b-k/n]], color=col, marker=mk, ms=3.5, capsize=1.5, elinewidth=0.6, ls='none',
                            label=lab if (x == 0) else None)
        ax.set_xticks(range(len(levels))); ax.set_xticklabels([l[3] for l in levels]); ax.set_xlim(-0.6, len(levels)-0.4)
        ax.set_ylim(-0.04, 1.04); ax.grid(axis='y', lw=0.3, color='0.85')
        if i == 0: ax.set_title(cl)
        if j == 0: ax.set_ylabel(f'{tl}\nTask success')
h, l = axes[0][0].get_legend_handles_labels()
fig.tight_layout(h_pad=0.8, w_pad=0.6, rect=(0, 0, 1, 0.95))
fig.legend(h, l, frameon=False, loc='upper center', ncol=3, bbox_to_anchor=(0.5, 1.0))
fig.savefig(OUT/'figures/fig_studyD.pdf'); print('fig_studyD.pdf')
