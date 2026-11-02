"""Figure 1: one paired example from Study D (same seed, same injected errors): revocable memory vs the belief rule
under 10% independent false-invalid reports, no disturbance. Data read from the sealed event logs."""
import json
from common import RUNS, STYLE, setup_mpl, WIDTH, MM, OUT
plt = setup_mpl()
from matplotlib.patches import Rectangle
TID = 'D_3goals_no_fault_seed368364_{}_false_invalid_10_ind'
GOALS = [('g1', 'red cube $\\rightarrow$ bowl'), ('g2', 'green ball $\\rightarrow$ plate'), ('g3', 'cylinder $\\rightarrow$ bowl')]


def parse(rule):
    ev = [json.loads(l) for l in open(RUNS['D']/TID.format(rule)/'events.jsonl', encoding='utf-8')]
    rec = []; acts = []; flips = []; recov = []; open_act = None; end = None; summ = json.loads((RUNS['D']/TID.format(rule)/'summary.json').read_text(encoding='utf-8'))
    for e in ev:
        t = float(e['elapsed_s']); k = e['event']
        if k == 'memory_refresh': rec.append((t, set(e['retained'])))
        elif k == 'completion_committed': rec.append((t, (rec[-1][1] if rec else set()) | {e['goal_id']}))
        elif k == 'controller_watchdog':
            for f in e['flips']: flips.append((t, f['goalId']))
        elif k == 'primitive_dispatched': open_act = (t, e['action']['name'])
        elif k == 'primitive_completed' and open_act: acts.append((open_act[0], t, open_act[1], e['accepted_by_primitive_interface'] in (True, 'True'))); open_act = None
        elif k == 'recovery_started': recov.append((t, int(e['number']), e['cause']))
        elif k == 'trial_finished': end = t
    return rec, acts, flips, recov, end, summ


fig, axes = plt.subplots(2, 1, figsize=(WIDTH, 70*MM), sharex=True)
for ax, rule, title in [(axes[0], 'revocable', 'Revocable memory'), (axes[1], 'belief', r'Belief rule ($\hat\alpha{=}0.10$)')]:
    rec, acts, flips, recov, end, summ = parse(rule); col = STYLE['belief_a10' if rule == 'belief' else rule][0]
    for i, (g, lab) in enumerate(GOALS):
        y = 3-i
        for (t0, s0), (t1, _) in zip(rec, rec[1:]+[(end, None)]):
            if g in s0: ax.add_patch(Rectangle((t0, y-0.18), t1-t0, 0.36, color=col, alpha=0.55, lw=0))
        for t, fg in flips:
            if fg == g: ax.plot([t], [y], marker='x', color='black', ms=5, mew=1.1, zorder=5)
    for t0, t1, name, ok in acts:
        ax.add_patch(Rectangle((t0, -0.25), t1-t0, 0.5, facecolor='white' if ok else '0.75', edgecolor='0.35', lw=0.5, hatch=None if ok else '////'))
        ax.text((t0+t1)/2, 0, 'pick' if name == 'PICK' else 'place', ha='center', va='center', fontsize=5.5, color='0.2')
    for t, n, cause in recov:
        ax.annotate(str(n), (t, 0.55), ha='center', va='center', fontsize=6, color='white',
                    bbox=dict(boxstyle='circle,pad=0.15', fc='#444444', ec='none'))
    outcome = 'task completed' if summ['success'] else 'recovery budget exhausted'
    ax.axvline(end, color='0.4', lw=0.6, ls=':'); ax.text(end+0.8, 3.45, outcome, fontsize=6.5, va='center', color='0.2')
    ax.set_yticks([3, 2, 1, 0]); ax.set_yticklabels([l for _, l in GOALS]+['primitives']); ax.set_ylim(-0.5, 3.7)
    ax.set_title(title, loc='left'); ax.spines['left'].set_visible(False); ax.tick_params(axis='y', length=0)
axes[1].set_xlabel('Time in trial (s)'); axes[1].set_xlim(0, 100)
fig.tight_layout(h_pad=0.6)
fig.savefig(OUT/'figures/fig_timeline.pdf'); print('fig_timeline.pdf')
