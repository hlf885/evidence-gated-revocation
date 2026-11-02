"""Figure: Study C dose-response. Success proportion (Wilson 95% CI) vs injected error rate, per rule."""
import collections
from common import trials, wilson, STYLE, setup_mpl, WIDTH, MM, OUT
plt = setup_mpl()
rows = trials('C'); cells = collections.defaultdict(list)
for r in rows: cells[(r['condition'], r['noise_type'], r['noise_rate'], r['rule'])].append(r['success'])
fig, axes = plt.subplots(2, 2, figsize=(WIDTH, 92*MM), sharex=True, sharey=True)
types = [('false_invalid', 'False-invalid reports'), ('false_consistent', 'False-consistent reports')]
conds = [('no_fault', 'No disturbance'), ('completed_shift', 'Completed object displaced')]
rates = [0.0, 0.02, 0.05, 0.10]; off = {'commit_only': -0.0025, 'revocable': 0.0, 'reactive': 0.0025}
for i, (t, tl) in enumerate(types):
    for j, (c, cl) in enumerate(conds):
        ax = axes[i][j]
        for rule in ['commit_only', 'revocable', 'reactive']:
            col, mk, lab = STYLE[rule]; xs, ys, lo, hi = [], [], [], []
            for rt in rates:
                v = cells[(c, 'none' if rt == 0 else t, rt, rule)]; k, n = sum(v), len(v); a, b = wilson(k, n)
                xs.append(rt*100+off[rule]*100); ys.append(k/n); lo.append(k/n-a); hi.append(b-k/n)
            ax.errorbar(xs, ys, yerr=[lo, hi], color=col, marker=mk, ms=3.5, capsize=1.5, elinewidth=0.6, label=lab)
        ax.set_ylim(-0.04, 1.04); ax.set_xticks([0, 2, 5, 10]); ax.grid(axis='y', lw=0.3, color='0.85')
        if i == 0: ax.set_title(cl)
        if j == 0: ax.set_ylabel(f'{tl}\nTask success')
        if i == 1: ax.set_xlabel('Injected error rate (%)')
axes[0][0].legend(frameon=False, loc='lower left')
fig.savefig(OUT/'figures/fig_studyC_dose.pdf')
print('fig_studyC_dose.pdf')
