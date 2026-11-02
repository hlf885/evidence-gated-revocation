"""Shared loaders for the paper's numbers and figures. Reads sealed results only; never writes into them."""
from pathlib import Path
import csv, json, math, sys
EXP = Path(__file__).resolve().parents[2]/'revision_experiments'
RUNS = {'C': EXP/'v10_studyC/results/formal_02', 'D': EXP/'v11_belief/results/formal_D', 'E': EXP/'v11_belief/results/formal_E', 'F': EXP/'v11_belief/results/formal_F'}
sys.path.insert(0, str(EXP/'v11_belief'/'analysis_cascade'))
OUT = Path(__file__).resolve().parents[1]
BOOL = {'success', 'false_completion_report', 'budget_stop', 'infrastructure_error', 'infrastructure_excluded', 'action_timeout'}
INT = {'seed', 'observation_flips', 'extra_repicks_of_satisfied_objects', 'repair_repicks', 'effective_faults', 'action_attempts',
       'primitive_dispatches', 'recoveries', 'fault_requested', 'fault_deferrals', 'workspace_cancellations', 'belief_reobservations', 'false_revocations'}


def trials(study):
    rows = list(csv.DictReader(open(RUNS[study]/'trials.csv', encoding='utf-8-sig')))
    for r in rows:
        for k, v in list(r.items()):
            if k in BOOL: r[k] = v == 'True'
            elif k in INT: r[k] = int(v)
            elif k in ('noise_rate', 'total_seconds'): r[k] = float(v)
        r.setdefault('noise_correlation', 'none' if r['noise_type'] == 'none' else 'independent')
        if r['rule'] == 'belief': r['rule'] = 'belief_a10'
    return rows


def inference(study): return json.loads((RUNS[study]/'inference.json').read_text(encoding='utf-8'))


def wilson(k, n, z=1.959963984540054):
    p = k/n; d = 1+z*z/n; c = p+z*z/(2*n); h = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))
    return max(0.0, (c-h)/d), min(1.0, (c+h)/d)


# Okabe-Ito palette, one fixed colour + marker per rule across all figures
STYLE = {'commit_only': ('#7F7F7F', 's', 'commit-only'), 'revocable': ('#0072B2', 'o', 'revocable'), 'reactive': ('#D55E00', '^', 'memoryless'),
         'belief_a10': ('#009E73', 'D', r'belief, $\hat\alpha{=}0.10$'), 'belief_a02': ('#56B4E9', 'v', r'belief, $\hat\alpha{=}0.02$'),
         'belief_a30': ('#E69F00', 'P', r'belief, $\hat\alpha{=}0.30$'), 'debounce2': ('#CC79A7', 'X', r'debounce ($n^*{=}2$)')}


def setup_mpl():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'STIXGeneral', 'mathtext.fontset': 'stix', 'font.size': 8, 'axes.labelsize': 8, 'axes.titlesize': 8,
                         'legend.fontsize': 7, 'xtick.labelsize': 7, 'ytick.labelsize': 7, 'axes.linewidth': 0.6, 'xtick.major.width': 0.6,
                         'ytick.major.width': 0.6, 'lines.linewidth': 1.0, 'lines.markersize': 4, 'pdf.fonttype': 42, 'ps.fonttype': 42,
                         'axes.spines.top': False, 'axes.spines.right': False, 'savefig.bbox': 'tight', 'savefig.pad_inches': 0.02})
    return plt


MM = 1/25.4
WIDTH = 147*MM
