"""Compare a generated design against a published reference design.

`validate_design.py` proves the engine is internally coherent: every number it
reports follows from its own inputs by the relations in SIZING_BASIS.md. That is
necessary and not sufficient. It cannot tell you whether 1.2 L/min per kW and a
2.7 m/s header cap are the right inputs, or whether the result resembles what a
vendor actually builds.

This module closes that gap the only way it can be closed - against a real
published design. A benchmark fixture holds:

  * provenance for the source document, including its SHA-256, so a figure can
    always be traced back to a page;
  * the configuration that represents that design in this generator;
  * the values the document publishes, each with a unit, a tolerance and the
    page it came from;
  * and, just as important, a `not_published` list naming what the document does
    NOT state, so an unchecked quantity is visible rather than silently absent.

A benchmark is not a test of the document and not a certification of the model.
A difference is a finding to adjudicate: the model may be wrong, the fixture may
misread the source, or the two may be making different declared assumptions. The
runner reports the delta and the evidence and leaves the judgement to a person.

    python3 benchmark.py --all
    python3 benchmark.py --fixture references/benchmarks/rd113_r0_maxq.json
    python3 benchmark.py --all --json findings.json

Exit status is 1 if any published value is outside its tolerance.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / 'references' / 'benchmarks'


# ---------------------------------------------------------------- readers ---
# Each reader turns a dotted quantity name into a number from the built design.
# Keeping them small and named means a fixture reads like an engineering
# comparison rather than a set of JSON pointers.

def _thermal(graph, key):
    return (graph['metadata'].get('preliminary_sizing') or {}).get('thermal_flows', {}).get(key)


def _family(graph, name, attribute):
    for family in (graph['metadata'].get('preliminary_sizing') or {}).get('size_families', []):
        if family['family'] != name or not family.get('selection'):
            continue
        selection = family['selection']
        if attribute == 'nominal_in':
            return selection['nominal_size_in']
        if attribute == 'id_mm':
            return selection['id_m'] * 1000.
        if attribute == 'design_L_min':
            return family['design_flow_m3_s'] * 60000.
        if attribute == 'velocity_m_s':
            return 4 * family['design_flow_m3_s'] / (math.pi * selection['id_m'] ** 2)
        raise KeyError(f'unknown pipe attribute {attribute!r}')
    return None


def _pump(graph, component, attribute):
    for screen in (graph['metadata'].get('preliminary_sizing') or {}).get('pump_screens', []):
        if screen['component_id'] != component or screen.get('pump_dp_Pa') is None:
            continue
        return {'head_m': screen['pump_head_m'], 'dp_kPa': screen['pump_dp_Pa'] / 1000.,
                'flow_L_min': screen['design_flow_m3_s'] * 60000.,
                'input_kW': screen['estimated_input_power_W'] / 1000.}.get(attribute)
    return None


def _valve(graph, component, attribute):
    for valve in (graph['metadata'].get('preliminary_sizing') or {}).get('valve_capacities', []):
        if valve['component_id'] == component:
            return {'Kv': valve['Kv_m3_h'], 'Cv': valve['Cv_US'],
                    'flow_L_min': valve['flow_m3_s'] * 60000.}.get(attribute)
    return None


def _duty(graph, component, attribute):
    duty = (graph['metadata'].get('preliminary_sizing') or {}).get('rack_and_equipment_duties', {}).get(component)
    if not duty:
        return None
    return {'heat_kW': (duty.get('screening_duty_heat_W') or duty.get('FWS_duty_heat_W')
                        or duty.get('CWS_duty_heat_W') or 0.) / 1000.,
            'TCS_L_min': (duty.get('duty_TCS_m3_s') or 0.) * 60000.,
            'FWS_L_min': (duty.get('duty_FWS_m3_s') or duty.get('FWS_duty_m3_s') or 0.) * 60000.}.get(attribute)


def resolve(graph, config, quantity):
    """Return the model's value for a dotted quantity name, or None."""
    head, _, rest = quantity.partition('.')
    if head == 'thermal':
        return _thermal(graph, rest)
    if head == 'config':
        return getattr(config, rest, None)
    if head == 'count':
        return sum(1 for c in graph['components'] if c.get('kind') == rest)
    if head == 'temperature':
        return {'tcs_supply_C': config.tcs_supply_C,
                'tcs_return_C': config.tcs_supply_C + config.tcs_delta_K,
                'fws_supply_C': config.fws_supply_C,
                'fws_return_C': config.fws_supply_C + config.fws_delta_K,
                'cws_supply_C': config.cws_supply_C,
                'cws_return_C': config.cws_supply_C + config.cws_delta_K}.get(rest)
    if head in ('pipe', 'pump', 'valve', 'duty'):
        target, _, attribute = rest.partition('.')
        if not attribute:
            raise ValueError(f'{quantity!r} needs a target and an attribute, e.g. pipe.tcs_main.nominal_in')
        return {'pipe': _family, 'pump': _pump, 'valve': _valve, 'duty': _duty}[head](graph, target, attribute)
    raise ValueError(f'unknown quantity {quantity!r}; expected thermal/config/count/temperature/pipe/pump/valve/duty')


# ----------------------------------------------------------------- runner ---

def load_config(fixture):
    from model import Config
    spec = fixture['config']
    if 'preset' in spec:
        from parameters import PRESETS
        values = {**PRESETS[spec['preset']]['config'], **spec.get('overrides', {})}
    else:
        values = dict(spec)
    return Config.from_dict(values)


def compare(fixture, graph, config):
    rows = []
    for item in fixture.get('expected', []):
        published, tolerance = item['published'], item.get('tolerance', 0.)
        try:
            measured = resolve(graph, config, item['quantity'])
        except (ValueError, KeyError) as exc:
            rows.append({**item, 'measured': None, 'verdict': 'ERROR', 'detail': str(exc)})
            continue
        if measured is None:
            rows.append({**item, 'measured': None, 'verdict': 'UNRESOLVED',
                         'detail': 'the model does not produce this quantity for this design'})
            continue
        scale = max(abs(published), 1e-12)
        error = abs(measured - published) / scale
        rows.append({**item, 'measured': measured, 'error': error,
                     'verdict': 'MATCH' if error <= tolerance + 1e-12 else 'DIFFERS',
                     'detail': f'{error:.2%} against a {tolerance:.2%} tolerance'})
    return rows


def render(fixture, rows, verbose=False):
    source = fixture.get('source', {})
    out = [f"== {fixture['benchmark']} ==",
           f"   {source.get('title', 'source not named')}"
           + (f" · rev {source['revision']}" if source.get('revision') else ''),
           f"   sha256 {source.get('sha256') or 'NOT RECORDED - figures cannot be traced to a page'}",
           f"   status {fixture.get('status', 'unstated')}", '']
    width = max((len(r['id']) for r in rows), default=10)
    out.append(f"   {'quantity':<{width}}{'published':>14}{'model':>14}{'delta':>10}  verdict")
    for row in rows:
        measured = row.get('measured')
        shown = f'{measured:,.4g}' if isinstance(measured, (int, float)) else '-'
        delta = f"{row['error']:.2%}" if row.get('error') is not None else '-'
        mark = {'MATCH': 'ok  ', 'DIFFERS': 'DIFF', 'UNRESOLVED': 'n/a ', 'ERROR': 'ERR '}[row['verdict']]
        out.append(f"   {row['id']:<{width}}{row['published']:>14,.4g}{shown:>14}{delta:>10}  {mark}"
                   + (f"  {row.get('unit', '')}" if row.get('unit') else ''))
        if row['verdict'] != 'MATCH' or verbose:
            out.append(f"   {'':<{width}}  {row['quantity']}  ·  {row.get('evidence', 'no page evidence recorded')}")
            if row['verdict'] == 'DIFFERS':
                out.append(f"   {'':<{width}}  {row['detail']}")
    gaps = fixture.get('not_published', [])
    if gaps:
        out += ['', f'   {len(gaps)} quantity group(s) this document does not publish, so they stay unchecked here:']
        out += [f"     · {g['quantity']} — {g['note']}" for g in gaps]
    differing = [r for r in rows if r['verdict'] in ('DIFFERS', 'ERROR')]
    out += ['', f"   {sum(r['verdict'] == 'MATCH' for r in rows)}/{len(rows)} published values match; "
                f"{len(differing)} differ; {sum(r['verdict'] == 'UNRESOLVED' for r in rows)} unresolved"]
    return '\n'.join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--fixture', help='a benchmark fixture JSON')
    source.add_argument('--all', action='store_true', help='every fixture in references/benchmarks')
    parser.add_argument('--verbose', action='store_true', help='show evidence for matching rows too')
    parser.add_argument('--json', help='write the full comparison to this path')
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pipeline import build

    paths = sorted(FIXTURES.glob('*.json')) if args.all else [Path(args.fixture)]
    if not paths:
        print(f'No fixtures in {FIXTURES}. See the module docstring for the format.')
        return 0
    findings = []; differing = 0
    for path in paths:
        fixture = json.loads(path.read_text())
        config = load_config(fixture)
        graph, _ = build(config)
        rows = compare(fixture, graph, config)
        differing += sum(r['verdict'] in ('DIFFERS', 'ERROR') for r in rows)
        findings.append({'benchmark': fixture['benchmark'], 'source': fixture.get('source', {}), 'rows': rows})
        print(render(fixture, rows, args.verbose)); print()
    if args.json:
        Path(args.json).write_text(json.dumps(findings, indent=2))
    print(f'{differing} published value(s) outside tolerance across {len(paths)} benchmark(s).')
    return 1 if differing else 0


if __name__ == '__main__':
    raise SystemExit(main())
