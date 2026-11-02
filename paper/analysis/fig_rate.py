"""Figure: Proposition 3 predicted vs observed false-revocation rate per exposure (exact Poisson 95% CI), all studies."""
import json, math
from common import STYLE, setup_mpl, WIDTH, MM, OUT
plt = setup_mpl()
data = json.loads((OUT/'analysis/rate_data.json').read_text(encoding='utf-8'))


def pois_cdf(k, mu):
    return sum(math.exp(-mu+i*math.log(mu)-math.lgamma(i+1)) for i in range(k+1)) if mu > 0 else 1.0


def pois_ci(k, a=0.05):
    def solve(f, lo, hi):
        for _ in range(200):
            mid = (lo+hi)/2
            if f(mid): hi = mid
            else: lo = mid
        return (lo+hi)/2
    lo = 0.0 if k == 0 else solve(lambda mu: 1-pois_cdf(k-1, mu) >= a/2, 0, 10*k+10)
    hi = solve(lambda mu: pois_cdf(k, mu) <= a/2, 0, 10*k+20)
    return lo, hi


FLOOR = 4e-4
fig, ax = plt.subplots(figsize=(WIDTH*0.62, WIDTH*0.56))
xs = [1e-4, 0.5]; ax.plot(xs, xs, color='0.3', lw=0.7, zorder=1)
ax.plot(xs, [2*x for x in xs], color='0.6', lw=0.5, ls='--', zorder=1); ax.plot(xs, [x/2 for x in xs], color='0.6', lw=0.5, ls='--', zorder=1)
seen = set()
for d in data:
    col, mk, lab = STYLE[d['rule']]; lo, hi = pois_ci(d['false_revocations']); e = d['exposures']
    if d['rule'] == 'debounce2': lab = r'evidence-gated ($n^*{=}2$)'
    y = max(d['observed'], FLOOR); filled = d['correlation'] == 'independent'
    ax.errorbar([d['predicted']], [y], yerr=[[y-max(lo/e, FLOOR*0.8)], [hi/e-y]], fmt=mk, color=col, mfc=col if filled else 'white', mec=col,
                ms=4, elinewidth=0.6, capsize=1.2, zorder=3, label=lab if d['rule'] not in seen else None)
    seen.add(d['rule'])
ax.set_xscale('log'); ax.set_yscale('log'); ax.set_xlim(1.5e-4, 0.4); ax.set_ylim(3e-4, 0.4)
ax.set_xlabel('Predicted false revocations per exposure (Proposition 3)'); ax.set_ylabel('Observed false revocations per exposure')
ax.text(0.2, 0.2*1.25, 'equal', rotation=37, fontsize=6.5, color='0.3', ha='center')
ax.text(0.1, 0.2*1.3, r'$\times 2$', fontsize=6.5, color='0.45', ha='center')
ax.text(0.25, 0.125*0.62, r'$\div 2$', fontsize=6.5, color='0.45', ha='center')
ax.text(1.8e-4, FLOOR*1.12, 'none observed', fontsize=6, color='0.4')
ax.axhline(FLOOR, color='0.85', lw=0.5, zorder=0)
leg = ax.legend(frameon=False, loc='upper left', fontsize=6.5)
ax.text(0.02, 0.62, 'filled: independent errors\nopen: persistent errors', transform=ax.transAxes, fontsize=6.5, color='0.25', va='top')
fig.savefig(OUT/'figures/fig_rate.pdf'); print('fig_rate.pdf')
