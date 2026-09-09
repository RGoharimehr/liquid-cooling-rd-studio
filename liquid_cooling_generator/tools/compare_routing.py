#!/usr/bin/env python3
"""Baseline against optimised, measured the same way on both.

    python3 tools/compare_routing.py --config presets/compact.json

Runs the generator twice from one configuration - once with `route_optimizer`
off, once on - and reports length, fittings, cost and supply/return pairing for
each, plus the rectilinear bound so the gap is visible rather than implied.
"""
import argparse, json, sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from model import Config
from pipeline import build
import route_cost


def summarise(g):
    cost = route_cost.evaluate(g)
    chains = route_cost.chain_report(g)
    return {
        'cost': cost['total'],
        'by_service': cost['by_service'],
        'pairing': cost['pairing'],
        'chains': {k: {kk: v[kk] for kk in ('routed_m', 'bound_m', 'excess_m',
                                            'excess_fraction')}
                   for k, v in chains.items()},
        'blocking_failures': g['metadata']['geometry_diagnostics']['blocking_failures'],
        'components': len(g['components']),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--json', type=Path, help='write the full comparison here')
    args = ap.parse_args()

    base_cfg = Config.from_dict(json.loads(args.config.read_text()))
    runs = {}
    for label, flag in (('baseline', False), ('optimised', True)):
        cfg = replace(base_cfg, route_optimizer=flag)
        g, _ = build(cfg)
        runs[label] = summarise(g)
        runs[label]['links'] = g['metadata'].get('route_optimizer', {}).get('links', [])

    b, o = runs['baseline'], runs['optimised']
    print(f"{'':22s}{'baseline':>12s}{'optimised':>12s}{'delta':>12s}")
    rows = [('transport pipe, m', 'length_m', 2), ('elbows', 'elbows', 0),
            ('tees', 'tees', 0), ('pipe cost', 'pipe', 0),
            ('fitting cost', 'fittings', 0), ('support cost', 'supports', 0),
            ('capex', 'capex', 0), ('unpaired supply, m', 'unpaired_m', 2)]
    for label, key, dp in rows:
        bv, ov = b['cost'][key], o['cost'][key]
        print(f'{label:22s}{bv:12,.{dp}f}{ov:12,.{dp}f}{ov - bv:+12,.{dp}f}')
    print(f"{'blocking failures':22s}{b['blocking_failures']:12d}{o['blocking_failures']:12d}"
          f"{o['blocking_failures'] - b['blocking_failures']:+12d}")

    print('\nrouted length against the rectilinear bound')
    for svc in sorted(set(b['chains']) | set(o['chains'])):
        bc, oc = b['chains'].get(svc, {}), o['chains'].get(svc, {})
        print(f"  {svc:5s} baseline {bc.get('routed_m', 0):7.1f} m "
              f"(+{bc.get('excess_fraction', 0) * 100:4.0f}% over {bc.get('bound_m', 0):6.1f}) "
              f"-> optimised {oc.get('routed_m', 0):7.1f} m "
              f"(+{oc.get('excess_fraction', 0) * 100:4.0f}% over {oc.get('bound_m', 0):6.1f})")

    print('\nsupply main running alongside its return, within 1 m')
    for svc in sorted(set(b['pairing']) | set(o['pairing'])):
        bp = b['pairing'].get(svc, {}).get('paired_fraction', {}).get('1.0', 0.)
        op = o['pairing'].get(svc, {}).get('paired_fraction', {}).get('1.0', 0.)
        print(f'  {svc:5s} {bp * 100:5.1f}%  ->  {op * 100:5.1f}%')
    shared = sum(r.get('shared_m', 0.) for r in o['links'] if r['chosen'] == 'optimized')
    print(f'  {shared:.1f} m of transport now shares a corridor with a line routed before it.')
    print('  The whole-network figure moves little because it is dominated by the'
          '\n  collector banks, whose spacing is a layout parameter, not a routing outcome.')

    achievable = sum(r['bound_m'] for r in o['links'])
    lanes = sum(r['lane_m'] for r in o['links'])
    routed = sum(r.get('routed_m', r['lane_m']) for r in o['links'])
    print(f'\noptimizer-managed links: {lanes:.1f} m of lane, {achievable:.1f} m achievable '
          f'bound, {routed:.1f} m routed')
    if lanes > achievable:
        print(f'  recovered {lanes - routed:.1f} m of the {lanes - achievable:.1f} m that was '
              f'available ({(lanes - routed) / (lanes - achievable) * 100:.0f}%)')
    print('\nper link')
    for row in o['links']:
        if row['chosen'] == 'optimized':
            print(f"  {row['link']:24s} {row['lane_m']:7.2f} -> {row['routed_m']:7.2f} m "
                  f"(bound {row['bound_m']:6.2f}, gap {row['gap_over_bound'] * 100:4.1f}%, "
                  f"shared {row['shared_m']:5.2f} m)")
        else:
            print(f"  {row['link']:24s} kept the deterministic lane: {row.get('reason', '')}")

    if args.json:
        args.json.write_text(json.dumps(runs, indent=2, default=str) + '\n')
        print(f'\nwrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
