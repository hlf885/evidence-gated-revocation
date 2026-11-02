"""v11 gate-2 pilot report. CRITERIA are fixed before any pilot trial. n=5 per cell: directional evidence only."""
from pathlib import Path
import json, statistics, sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_v11 as an   # noqa: E402

CELLS = [('no_fault', 'false_invalid', 0.10), ('completed_shift', 'false_invalid', 0.10),
         ('completed_shift', 'false_consistent', 0.10), ('completed_shift', 'none', 0.0)]
CRITERIA = {
    'C1_false_invalid_success': 'In both false_invalid 10% cells: belief successes >= max(revocable, reactive) - 1',
    'C2_false_invalid_cost': 'In both false_invalid 10% cells: belief mean extra repicks < revocable mean extra repicks',
    'C3_false_consistent': 'completed_shift x false_consistent 10%: belief successes >= revocable - 1 and > reactive',
    'C4_repair': 'completed_shift x none: belief successes >= revocable - 1',
    'C5_integrity': 'all replay audits pass and no infrastructure exclusions',
}


def summarize(run):
    manifest, rows, checks = an.collect(run)
    table = {}
    for c, t, r in CELLS:
        for rule in manifest['rules']:
            rs = [x for x in rows if (x['condition'], x['noise_type'], x['noise_rate'], x['rule']) == (c, t, r, rule)]
            table[(c, t, r, rule)] = {'n': len(rs), 'successes': sum(x['success'] for x in rs),
                'extra_repicks': statistics.mean(x['extra_repicks_of_satisfied_objects'] for x in rs) if rs else None,
                'dispatches': statistics.mean(x['primitive_dispatches'] for x in rs) if rs else None,
                'seconds': statistics.mean(x['total_seconds'] for x in rs) if rs else None,
                'budget_stops': sum(x['budget_stop'] for x in rs), 'reobservations': statistics.mean(x['belief_reobservations'] for x in rs) if rs else None}
    return manifest, rows, checks, table


def decide(rows, checks, table):
    s = lambda c, t, r, rule: table[(c, t, r, rule)]['successes']
    x = lambda c, t, r, rule: table[(c, t, r, rule)]['extra_repicks']
    fi = [('no_fault', 'false_invalid', .10), ('completed_shift', 'false_invalid', .10)]
    res = {'C1_false_invalid_success': all(s(*k, 'belief') >= max(s(*k, 'revocable'), s(*k, 'reactive'))-1 for k in fi),
           'C2_false_invalid_cost': all(x(*k, 'belief') < x(*k, 'revocable') for k in fi),
           'C3_false_consistent': s('completed_shift', 'false_consistent', .10, 'belief') >= s('completed_shift', 'false_consistent', .10, 'revocable')-1
                                  and s('completed_shift', 'false_consistent', .10, 'belief') > s('completed_shift', 'false_consistent', .10, 'reactive'),
           'C4_repair': s('completed_shift', 'none', 0.0, 'belief') >= s('completed_shift', 'none', 0.0, 'revocable')-1,
           'C5_integrity': all(c['passed'] for c in checks) and not any(r['infrastructure_excluded'] for r in rows)}
    return res, all(res.values())


def main(run=an.RUN):
    manifest, rows, checks, table = summarize(run)
    if len(rows) != len(manifest['units']): raise RuntimeError(f'incomplete pilot: {len(rows)}/{len(manifest["units"])}')
    res, go = decide(rows, checks, table)
    out = {'pilot': str(run), 'trials': len(rows), 'criteria': CRITERIA, 'results': res, 'GO': go,
           'table': [{'condition': k[0], 'noise_type': k[1], 'noise_rate': k[2], 'rule': k[3], **v} for k, v in table.items()],
           'failed_checks': [c for c in checks if not c['passed']], 'note': 'n=5 per cell: directional development evidence, not inference.'}
    (Path(run)/'pilot_report.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    an.write_csv(Path(run)/'pilot_trials.csv', rows)
    for k, v in table.items(): print(k, v)
    print(json.dumps({'results': res, 'GO': go}))
    return out


if __name__ == '__main__':
    main()
