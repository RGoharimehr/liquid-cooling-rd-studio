"""Independent acceptance harness for a generated design.

Nothing here imports the engine's calculation functions. Every number is
re-derived from the graph's own raw data (node coordinates, routed lengths,
selected bores, declared fluid properties, declared K values and pressure
allocations) using textbook relations written out longhand, then compared with
what the engine reported. The point is to catch a wrong formula, a dropped
term, a stale field or two artifacts disagreeing - none of which a test that
calls the same function twice can see.

It does NOT validate the design against reality. Velocity caps, fitting K
values, equipment pressure allocations and fluid properties are project
assumptions; this harness only checks that the engine used them consistently.

    python3 validate_design.py --config presets/compact.json
    python3 validate_design.py --config presets/compact.json --sizing-mode preliminary
    python3 validate_design.py --graph outputs/my-design/graph.json
    python3 validate_design.py --config presets/compact.json --sweep
    python3 validate_design.py --all-presets --json report.json

Exit status is 1 if any check fails, so it drops straight into CI.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

G = 9.80665
GPM_PER_M3S = 15850.323141489
# Same commercial tables the engine cites, retyped here on purpose: a typo in
# hydraulics.CATALOGUES would otherwise validate against itself.
TABLES = {
    'copper_type_l': [(1, 1.125, .050), (1.25, 1.375, .055), (1.5, 1.625, .060), (2, 2.125, .070),
                      (2.5, 2.625, .080), (3, 3.125, .090), (3.5, 3.625, .100), (4, 4.125, .110),
                      (5, 5.125, .125), (6, 6.125, .140)],
    'carbon_steel_sch40': [(2, 2.375, .154), (2.5, 2.875, .203), (3, 3.5, .216), (3.5, 4, .226),
                           (4, 4.5, .237), (5, 5.563, .258), (6, 6.625, .280), (8, 8.625, .322),
                           (10, 10.75, .365), (12, 12.75, .406), (14, 14, .438), (16, 16, .500),
                           (18, 18, .562), (20, 20, .594), (24, 24, .688)],
    'stainless_sch10': [(1, 1.315, .109), (1.25, 1.66, .109), (1.5, 1.9, .109), (2, 2.375, .109),
                        (2.5, 2.875, .120), (3, 3.5, .120), (3.5, 4, .120), (4, 4.5, .120),
                        (5, 5.563, .134), (6, 6.625, .134), (8, 8.625, .148), (10, 10.75, .165),
                        (12, 12.75, .180), (14, 14, .188), (16, 16, .188)],
}


class Report:
    """A flat list of named findings, so CI and a human read the same thing."""

    def __init__(self, label):
        self.label = label
        self.rows = []

    def add(self, group, name, ok, measured=None, expected=None, detail='', severity='fail'):
        self.rows.append({'group': group, 'check': name,
                          'status': 'PASS' if ok else ('WARN' if severity == 'warn' else 'FAIL'),
                          'measured': measured, 'expected': expected, 'detail': detail})
        return ok

    def close(self, group, name, measured, expected, tol, detail='', severity='fail'):
        """Relative comparison that degrades to absolute near zero."""
        if measured is None or expected is None:
            return self.add(group, name, False, measured, expected,
                            detail + ' (value missing)', severity)
        scale = max(abs(expected), 1e-12)
        error = abs(measured - expected) / scale if scale > 1e-9 else abs(measured - expected)
        return self.add(group, name, error <= tol, measured, expected,
                        (detail + f' rel.err={error:.3e} tol={tol:g}').strip(), severity)

    @property
    def failed(self):
        return [r for r in self.rows if r['status'] == 'FAIL']

    @property
    def warned(self):
        return [r for r in self.rows if r['status'] == 'WARN']


# --------------------------------------------------------------------------
# Physics, written out longhand. No engine import.

def colebrook(reynolds, relative_roughness):
    factor = .02
    for _ in range(200):
        factor = 1. / (-2. * math.log10(relative_roughness / 3.7
                                        + 2.51 / (reynolds * math.sqrt(factor)))) ** 2
    return factor


def darcy(reynolds, relative_roughness):
    """Matches the regime policy stated in SIZING_BASIS.md section 2."""
    if reynolds <= 0:
        return 0.
    if reynolds < 2300:
        return 64. / reynolds
    turbulent = colebrook(max(reynolds, 4000.), relative_roughness)
    return max(64. / reynolds, turbulent) if reynolds < 10000 else turbulent


def bore(material, nominal):
    row = next((r for r in TABLES[material] if abs(r[0] - nominal) < 1e-9), None)
    return None if row is None else (row[1] - 2 * row[2]) * .0254


def smallest_bore(material, flow, cap):
    required = math.sqrt(4 * flow / (math.pi * cap))
    for nominal, od, wall in TABLES[material]:
        if (od - 2 * wall) * .0254 + 1e-12 >= required:
            return nominal, (od - 2 * wall) * .0254, required
    return None, None, required


# --------------------------------------------------------------------------

def check_thermal(graph, report):
    cfg = graph['metadata']['config']
    sizing = graph['metadata'].get('preliminary_sizing') or {}
    flows = sizing.get('thermal_flows')
    if not flows:
        report.add('thermal', 'preliminary sizing present', False, None, None,
                   'No preliminary_sizing block; thermal checks cannot run.')
        return
    fluids = sizing['fluid_properties']

    compute = cfg['rows'] * cfg['racks_per_row'] * cfg['rack_power_W']
    liquid = compute * cfg['liquid_fraction']
    network = (cfg['network_rows'] * cfg['network_racks_per_row'] * cfg['network_rack_power_W']
               + cfg['network_high_power_count'] * (cfg['network_high_power_W'] - cfg['network_rack_power_W']))
    air = compute - liquid + network + cfg.get('additional_air_load_W', 0.)

    report.close('thermal', 'liquid heat = racks x power x liquid fraction',
                 flows['liquid_heat_W'], liquid, 1e-9, 'W')
    report.close('thermal', 'air heat = residual compute + network + additional',
                 flows['air_heat_W'], air, 1e-9, 'W')
    report.close('thermal', 'plant heat = liquid + air (each load counted once)',
                 flows['plant_heat_W'], liquid + air, 1e-9, 'W')

    # Rate form of the heat equation, recomputed per service.
    tcs = fluids['TCS']
    if cfg.get('flow_input_mode') == 'lpm_per_kw':
        expected_tcs = liquid / 1000. * cfg['flow_lpm_per_kw'] / 60000.
        basis = f"{cfg['flow_lpm_per_kw']} L/min per liquid kW"
    else:
        expected_tcs = liquid / (tcs['rho_kg_m3'] * tcs['cp_J_kg_K'] * tcs['delta_K'])
        basis = 'P/(rho.cp.dT)'
    report.close('thermal', f'TCS flow from {basis}', flows['TCS_m3_s'], expected_tcs, 1e-9, 'm3/s')

    fws = fluids['FWS']
    report.close('thermal', 'FWS flow = plant heat / (rho.cp.dT)', flows['FWS_m3_s'],
                 flows['plant_heat_W'] / (fws['rho_kg_m3'] * fws['cp_J_kg_K'] * fws['delta_K']),
                 1e-9, 'm3/s')

    if flows.get('condenser_heat_W') is not None:
        cop = cfg.get('chiller_cop')
        report.close('thermal', 'condenser heat = evaporator x (1 + 1/COP)',
                     flows['condenser_heat_W'], flows['plant_heat_W'] * (1 + 1. / cop), 1e-9, 'W')
        cws = fluids['CWS']
        report.close('thermal', 'CWS flow = condenser heat / (rho.cp.dT)', flows['CWS_m3_s'],
                     flows['condenser_heat_W'] / (cws['rho_kg_m3'] * cws['cp_J_kg_K'] * cws['delta_K']),
                     1e-9, 'm3/s')

    # The two bases must be reported against each other, not silently combined.
    implied = flows.get('effective_TCS_delta_K')
    if implied is not None:
        drift = abs(implied - tcs['delta_K']) / tcs['delta_K']
        report.add('thermal', 'declared vs implied TCS temperature rise agree within 10%',
                   drift <= .10, round(implied, 4), tcs['delta_K'],
                   f'K; prescribed flow implies {implied:.3f} K against a declared {tcs["delta_K"]:g} K',
                   severity='warn')


def check_continuity(graph, report):
    sizing = graph['metadata'].get('preliminary_sizing') or {}
    estimates = {e['edge_id']: e for e in sizing.get('edge_estimates', [])}
    if not estimates:
        return
    edges = {e['id']: e for e in graph['edges']}
    meta = graph['metadata']
    boundary = {meta.get('fws_source'), meta.get('fws_sink')}
    internal_kinds = {'rack_load', 'cdu_primary', 'cdu_secondary', 'pump', 'chiller_evaporator',
                      'chiller_condenser', 'cooling_tower', 'air_coil'}

    balance = defaultdict(float)
    for eid, row in estimates.items():
        q = row.get('signed_all_online_flow_m3_s')
        if q is None:
            continue
        edge = edges[eid]
        # Equipment internals move fluid between its own two ports, which is
        # still continuity; they are included exactly like any other branch.
        balance[edge['from_node']] -= q
        balance[edge['to_node']] += q
    worst = 0.; worst_node = None
    for node, residual in balance.items():
        if node in boundary:
            continue
        if abs(residual) > worst:
            worst, worst_node = abs(residual), node
    report.add('continuity', 'node mass balance closes away from declared boundaries',
               worst < 1e-9, worst, '< 1e-9 m3/s',
               f'worst node {worst_node}' if worst_node else 'all nodes balanced')

    # Equipment sharing must add back up to the circuit total.
    flows = sizing.get('thermal_flows', {})
    by_kind = defaultdict(float)
    for eid, row in estimates.items():
        kind = edges[eid]['kind']
        if kind in internal_kinds and row.get('flow_m3_s') is not None:
            by_kind[kind] += row['flow_m3_s']
    if by_kind.get('cdu_secondary'):
        report.close('continuity', 'sum of CDU secondary flows = TCS circuit total',
                     by_kind['cdu_secondary'], flows.get('TCS_m3_s'), 1e-9, 'm3/s')
    if by_kind.get('cdu_primary') is not None and flows.get('FWS_m3_s'):
        report.close('continuity', 'CDU primary + air coil flows = FWS circuit total',
                     by_kind.get('cdu_primary', 0.) + by_kind.get('air_coil', 0.),
                     flows['FWS_m3_s'], 1e-9, 'm3/s')
    if by_kind.get('rack_load'):
        report.close('continuity', 'sum of rack flows = TCS circuit total',
                     by_kind['rack_load'], flows.get('TCS_m3_s'), 1e-9, 'm3/s')


def check_hydraulics(graph, report):
    sizing = graph['metadata'].get('preliminary_sizing') or {}
    estimates = [e for e in sizing.get('edge_estimates', []) if e.get('status') == 'SCREENING_ESTIMATE']
    if not estimates:
        report.add('hydraulic', 'per-edge estimates present', False, 0, '>0',
                   'No evaluable edge estimates.')
        return
    edges = {e['id']: e for e in graph['edges']}
    fluids = sizing['fluid_properties']
    allocations = sizing['assumptions']['allocated_dp_Pa_by_kind']
    k_by_kind = sizing['assumptions']['K_by_kind']

    worst = defaultdict(lambda: (0., None))
    double_counted = []
    unpriced = []
    for row in estimates:
        edge = edges[row['edge_id']]
        fluid = fluids[row['service']]
        diameter = row['selected_size']['id_m']
        flow = row['design_flow_m3_s']

        velocity = 4 * flow / (math.pi * diameter ** 2)
        reynolds = fluid['rho_kg_m3'] * velocity * diameter / fluid['mu_Pa_s']
        factor = darcy(reynolds, row['roughness_m'] / diameter)
        dynamic = fluid['rho_kg_m3'] * velocity ** 2 / 2
        straight = factor * edge['length_m'] / diameter * dynamic if edge['kind'] == 'pipe' else 0.
        reference = row.get('K_reference_id_m', diameter)
        k_velocity = 4 * flow / (math.pi * reference ** 2)
        fitting = row['loss_K'] * fluid['rho_kg_m3'] * k_velocity ** 2 / 2
        equipment = allocations.get(edge['kind'], 0.) if flow else 0.

        for name, mine, theirs in [('velocity', velocity, row['velocity_m_s']),
                                   ('Reynolds', reynolds, row['Reynolds']),
                                   ('Darcy factor', factor, row['friction_factor']),
                                   ('straight loss', straight, row['straight_dp_Pa']),
                                   ('fitting loss', fitting, row['fitting_dp_Pa']),
                                   ('equipment loss', equipment, row['equipment_dp_Pa']),
                                   ('total loss', straight + fitting + equipment, row['total_dp_Pa'])]:
            scale = max(abs(mine), 1e-9)
            error = abs(mine - theirs) / scale
            if error > worst[name][0]:
                worst[name] = (error, row['edge_id'])

        # Colebrook residual, so a converged-looking factor that solves the
        # wrong equation still fails.
        if reynolds >= 10000:
            residual = (1 / math.sqrt(row['friction_factor'])
                        + 2 * math.log10(row['roughness_m'] / (3.7 * diameter)
                                         + 2.51 / (reynolds * math.sqrt(row['friction_factor']))))
            if abs(residual) > worst['Colebrook residual'][0]:
                worst['Colebrook residual'] = (abs(residual), row['edge_id'])

        if edge['kind'] in allocations and row['loss_K'] != 0:
            double_counted.append(row['edge_id'])
        # A pump adds head and is excluded from its own path; an open cooling
        # tower's nozzle requirement is carried once, in the circuit static term.
        # Everything else that contributes zero is an undeclared loss.
        if edge['kind'] not in allocations and edge['kind'] not in k_by_kind \
                and edge['kind'] not in ('pipe', 'pump', 'cooling_tower') and row['total_dp_Pa'] == 0:
            unpriced.append(edge['kind'])

    for name, (error, eid) in sorted(worst.items()):
        tol = 1e-6 if name != 'Colebrook residual' else 1e-6
        report.add('hydraulic', f're-derived {name} matches engine ({len(estimates)} edges)',
                   error <= tol, error, f'<= {tol:g}', f'worst edge {eid}')

    report.add('hydraulic', 'no component carries both an allocated dp and a K',
               not double_counted, len(double_counted), 0,
               'SIZING_BASIS s2: count each loss once. ' + ', '.join(double_counted[:3]))
    report.add('hydraulic', 'every component kind has a declared loss basis',
               not unpriced, sorted(set(unpriced)), [],
               'A component with no K and no allocation contributes zero, which is unknown, not zero.',
               severity='warn')

    # A K referenced to a bore the edge's flow never passes through produces a
    # physically impossible reference velocity. velocity_cap_pass cannot see it,
    # because that test uses the edge's own bore.
    implausible = []
    for row in estimates:
        reference = row.get('K_reference_id_m')
        if not reference or not row['loss_K']:
            continue
        # Only a reference bore that differs from the edge's own is a candidate
        # for this fault. When they are the same the velocity is simply high, and
        # that is the manual-mode exceedance finding, reported separately.
        if abs(reference - row['selected_size']['id_m']) < 1e-9:
            continue
        reference_velocity = 4 * row['design_flow_m3_s'] / (math.pi * reference ** 2)
        if reference_velocity > 2 * row['velocity_cap_m_s']:
            implausible.append((round(reference_velocity, 1), row['edge_id'],
                                round(row['total_dp_Pa'] / 1000, 1)))
    implausible.sort(reverse=True)
    report.add('hydraulic', 'every fitting K is referenced to a bore its own flow passes through',
               not implausible, implausible[:3], [],
               'a K referenced to a bore the edge itself does not have, at more than twice the '
               'family limit, means the flow and the bore came from different pipe families')

    over = [r for r in estimates if r['velocity_m_s'] > r['velocity_cap_m_s'] + 1e-9]
    flagged = {u.get('edge_id') for u in sizing.get('unresolved', [])
               if u.get('code') == 'MANUAL_VELOCITY_LIMIT_EXCEEDED'}
    if sizing.get('dimension_basis') == 'manual_catalogue':
        report.add('hydraulic', 'every velocity exceedance is reported to the user',
                   all(r['edge_id'] in flagged for r in over), len(over), len(flagged),
                   'manual mode retains the bore but must surface the exceedance')
    else:
        report.add('hydraulic', 'no edge exceeds its velocity limit after catalogue rounding',
                   not over, len(over), 0, ', '.join(r['edge_id'] for r in over[:3]))


def check_paths_and_pumps(graph, report):
    sizing = graph['metadata'].get('preliminary_sizing') or {}
    screens = sizing.get('pump_screens', [])
    if not screens:
        return
    estimates = {e['edge_id']: e for e in sizing.get('edge_estimates', [])}
    edges = {e['id']: e for e in graph['edges']}
    fluids = sizing['fluid_properties']
    margin = None
    broken_path = []
    sum_mismatch = (0., None)
    for screen in screens:
        if screen.get('status') == 'NOT_EVALUABLE':
            continue
        ids = screen.get('edge_ids') or []
        # A pump duty is only meaningful on a complete circuit: the path must
        # leave the pump outlet, chain end to end, and return to its inlet.
        component = next((e for e in graph['edges']
                          if e['component_id'] == screen['component_id']
                          and e['kind'] in ('pump', 'cdu_secondary')), None)
        if component and ids:
            node = component['to_node']
            for eid in ids:
                edge = edges[eid]
                if edge['from_node'] == node:
                    node = edge['to_node']
                elif edge['to_node'] == node:
                    node = edge['from_node']
                else:
                    broken_path.append(screen['component_id']); break
            else:
                if node != component['from_node']:
                    broken_path.append(screen['component_id'])
        total = sum(estimates[i]['total_dp_Pa'] for i in ids if i in estimates)
        error = abs(total - screen['passive_dp_Pa']) / max(abs(total), 1e-9)
        if error > sum_mismatch[0]:
            sum_mismatch = (error, screen['component_id'])

        fluid = fluids[screen['circuit_id'].split('-')[0] if screen['circuit_id'].startswith('TCS')
                       else screen['circuit_id']]
        expected_dp = (screen['passive_dp_Pa'] + screen['internal_cdu_dp_Pa']
                       + screen['static_dp_Pa']) * (1 + screen['head_margin_fraction'])
        report.close('pump', f"{screen['component_id']}: dp = (friction + internal + static) x (1 + margin)",
                     screen['pump_dp_Pa'], expected_dp, 1e-9, 'Pa')
        report.close('pump', f"{screen['component_id']}: head = dp / (rho.g)",
                     screen['pump_head_m'], screen['pump_dp_Pa'] / (fluid['rho_kg_m3'] * G), 1e-9, 'm')
        report.close('pump', f"{screen['component_id']}: hydraulic power = Q.dp",
                     screen['hydraulic_power_W'], screen['design_flow_m3_s'] * screen['pump_dp_Pa'], 1e-9, 'W')
        report.close('pump', f"{screen['component_id']}: input power = Q.dp / efficiency",
                     screen['estimated_input_power_W'],
                     screen['design_flow_m3_s'] * screen['pump_dp_Pa'] / screen['efficiency'], 1e-9, 'W')
        margin = screen['head_margin_fraction']
        if screen['circuit_id'] == 'CWS':
            lift = graph['metadata']['config'].get('cws_static_lift_m')
            # An open cooling-tower loop lifts water from the basin to the
            # distribution deck. Without that lift the duty is a friction-only
            # lower bound and must say so rather than reporting a complete screen.
            report.add('pump', f"{screen['component_id']}: open tower duty without a declared lift is marked incomplete",
                       bool(lift) or screen['status'] == 'INCOMPLETE_LOWER_BOUND',
                       f"lift={lift} m, status={screen['status']}", 'lift > 0 or INCOMPLETE_LOWER_BOUND',
                       'zero is a placeholder, not a resolved requirement')
        if screen['circuit_id'] != 'CWS':
            report.add('pump', f"{screen['component_id']}: closed loop adds no static elevation",
                       screen['static_dp_Pa'] == 0, screen['static_dp_Pa'], 0,
                       'Closed-circuit risers are offset by their return columns.')

    report.add('pump', 'reported path loss equals the sum of its own edges',
               sum_mismatch[0] <= 1e-9, sum_mismatch[0], '<= 1e-9',
               f'worst {sum_mismatch[1]}')
    report.add('pump', 'every pump path is a closed circuit outlet -> inlet',
               not broken_path, broken_path, [],
               'A duty estimated on a path that does not return to the pump is not a circuit.')
    report.add('pump', 'head margin is applied once and disclosed',
               margin is not None, margin, 'declared fraction')

    # A CDU's secondary side is the pump for that loop. Published available head
    # is net at the connections, so charging the loop for the unit's own internal
    # drop counts its losses twice.
    doubled = [s['component_id'] for s in screens
               if str(s.get('circuit_id', '')).startswith('TCS') and (s.get('internal_cdu_dp_Pa') or 0) > 0]
    report.add('pump', 'no circuit is charged for the internal loss of its own source',
               not doubled, doubled[:3], [],
               'the CDU secondary side drives the TCS loop; its published head already nets its internals')

    # Enough head, enough flow, enough capacity - or the unit does not suit.
    for item in sizing.get('cdu_selection', []):
        short = [r for r in item['checks'] if r['status'] == 'SHORT']
        report.add('pump', f"{item['component_id']}: selected CDU covers the required duty",
                   not short, [r['quantity'] for r in short] or 'head, flow and capacity all within rating',
                   'no shortfall',
                   'a shortfall is a real finding, not a tolerance: size up, add units, or reduce the outage requirement',
                   severity='warn' if short else 'fail')

    # One fitting worth a third of a circuit's head is a modelling artefact far
    # more often than it is a real component.
    dominant = []
    for screen in screens:
        if not screen.get('passive_dp_Pa'):
            continue
        for eid in screen['edge_ids']:
            row = estimates.get(eid, {})
            share = (row.get('total_dp_Pa') or 0.) / screen['passive_dp_Pa']
            if share > .25 and edges[eid]['kind'] not in ('rack_load', 'cdu_primary', 'cdu_secondary',
                                                         'chiller_evaporator', 'chiller_condenser', 'air_coil'):
                dominant.append(f"{eid} ({edges[eid]['kind']}) = {share:.0%} of {screen['component_id']}")
    report.add('pump', 'no single fitting dominates a circuit pressure budget',
               not dominant, sorted(set(dominant))[:3], [],
               'a fitting worth more than a quarter of the loop is worth re-deriving by hand')


def check_valves(graph, report):
    sizing = graph['metadata'].get('preliminary_sizing') or {}
    valves = sizing.get('valve_capacities', [])
    if not valves:
        return
    fluids = sizing['fluid_properties']
    estimates = {e['edge_id']: e for e in sizing.get('edge_estimates', [])}
    worst_kv = worst_cv = 0.
    for valve in valves:
        service = estimates[valve['edge_id']]['service']
        rho = fluids[service]['rho_kg_m3']
        kv = valve['flow_m3_s'] * 3600. * math.sqrt((rho / 1000.) / (valve['allocated_dp_Pa'] / 100000.))
        worst_kv = max(worst_kv, abs(kv - valve['Kv_m3_h']) / max(kv, 1e-12))
        worst_cv = max(worst_cv, abs(1.156 * valve['Kv_m3_h'] - valve['Cv_US']) / max(valve['Cv_US'], 1e-12))
    report.add('valve', f'Kv = Q[m3/h].sqrt(SG/dp[bar]) for all {len(valves)} valves',
               worst_kv <= 1e-9, worst_kv, '<= 1e-9')
    report.add('valve', 'Cv(US) = 1.156 x Kv', worst_cv <= 1e-9, worst_cv, '<= 1e-9')


def check_catalogue(graph, report):
    sizing = graph['metadata'].get('preliminary_sizing') or {}
    families = sizing.get('size_families', [])
    if not families:
        return
    wrong_bore = []; not_smallest = []; over_cap = []
    recommending = sizing.get('dimension_basis') != 'manual_catalogue'
    for family in families:
        selection = family.get('selection')
        if not selection:
            continue
        expected = bore(family['material'], selection['nominal_size_in'])
        if expected is None or abs(expected - selection['id_m']) > 1e-9:
            wrong_bore.append(family['family'])
            continue
        nominal, ident, required = smallest_bore(family['material'], family['design_flow_m3_s'],
                                                 family['velocity_cap_m_s'])
        if recommending and nominal != selection['nominal_size_in']:
            not_smallest.append(f"{family['family']}: chose {selection['nominal_size_in']}, "
                                f"smallest fitting is {nominal}")
        velocity = 4 * family['design_flow_m3_s'] / (math.pi * selection['id_m'] ** 2)
        if recommending and velocity > family['velocity_cap_m_s'] + 1e-9:
            over_cap.append(family['family'])
    report.add('catalogue', 'selected inside diameter = (OD - 2.wall) from the named standard',
               not wrong_bore, wrong_bore, [], 'nominal size is not an inside diameter')
    report.add('catalogue', 'recommendation is the smallest catalogue bore meeting the limit',
               not not_smallest, not_smallest, [], 'rounding must go up, and no further')
    report.add('catalogue', 'no family is capped at the largest size and marked passing',
               not over_cap, over_cap, [])


def check_geometry(graph, report):
    nodes = {n['id']: (n.get('xyz_m') or n['route_hint_m']) for n in graph['nodes']}
    bad_length = (0., None); skew = []
    total = 0.
    for edge in graph['edges']:
        if edge['kind'] != 'pipe':
            continue
        a, b = nodes[edge['from_node']], nodes[edge['to_node']]
        straight = math.dist(a, b)
        total += edge['length_m']
        if sum(abs(a[k] - b[k]) > 1e-8 for k in range(3)) != 1:
            skew.append(edge['id'])
        error = abs(straight - edge['length_m']) / max(straight, 1e-9)
        if error > bad_length[0]:
            bad_length = (error, edge['id'])
    report.add('geometry', 'routed pipe length equals its own node-to-node distance',
               bad_length[0] <= 1e-9, bad_length[0], '<= 1e-9', f'worst edge {bad_length[1]}')
    report.add('geometry', 'every straight pipe is axis aligned', not skew, skew[:3], [])
    declared = graph['metadata'].get('pipe_length_m')
    if declared is not None:
        report.close('geometry', 'declared total pipe length matches the sum of segments',
                     declared, total, 1e-9, 'm')
    report.add('geometry', 'pressure loss uses routed lengths, not the 1 m placeholder',
               abs(total - sum(1. for e in graph['edges'] if e['kind'] == 'pipe')) > 1e-6,
               round(total, 3), '!= pipe count')


def check_attention(graph, report):
    """A flag on everything is a flag on nothing."""
    data = graph['metadata'].get('attention')
    if not data:
        return
    total = sum(1 for c in graph['components'] if not c.get('attachment'))
    flagged = data['summary']['flagged_components']
    report.add('attention', 'component flags stay specific rather than blanketing the model',
               flagged <= max(10, total * .05), f'{flagged} of {total} physical components',
               'at most 5% or 10 components',
               'a finding that lands on every component of a kind belongs in the systemic list, '
               'where one project input clears it, not on each object in the 3D view')
    ids = {c['id'] for c in graph['components']}
    unknown = [cid for cid in data['components'] if cid not in ids]
    unknown += [cid for item in data.get('systemic', []) for cid in item.get('component_ids', []) if cid not in ids]
    report.add('attention', 'every flag names a component that exists',
               not unknown, unknown[:3], [], 'the viewer cannot colour an object that is not in the model')
    categories = set(data['categories'])
    stray = {f['category'] for entry in data['components'].values() for f in entry['flags']} - categories
    stray |= {item['category'] for item in data.get('systemic', [])} - categories
    report.add('attention', 'every flag uses a declared category',
               not stray, sorted(stray), sorted(categories))


def check_artifact_agreement(graph, report):
    """Two blocks in one file must not answer the same question differently."""
    sizing = graph['metadata'].get('preliminary_sizing') or {}
    flows = sizing.get('thermal_flows')
    legacy = (graph.get('hydraulics') or {}).get('heat_and_flow')
    if flows and legacy:
        report.close('agreement', 'graph.hydraulics TCS flow agrees with preliminary sizing',
                     legacy['tcs_total_m3_s'], flows['TCS_m3_s'], 1e-6, 'm3/s',
                     'one design flow per circuit, or downstream consumers disagree')
        report.close('agreement', 'graph.hydraulics FWS flow agrees with preliminary sizing',
                     legacy['fws_total_m3_s'], flows['FWS_m3_s'], 1e-6, 'm3/s')
        report.close('agreement', 'graph.hydraulics liquid heat agrees with preliminary sizing',
                     legacy['total_heat_W'], flows['liquid_heat_W'], 1e-9, 'W')

    estimates = {e['edge_id']: e for e in sizing.get('edge_estimates', [])}
    mismatched = []; zero_k = 0
    for edge in graph['edges']:
        row = estimates.get(edge['id'])
        if not row or not row.get('selected_size'):
            continue
        for key in ('nominal_size_in', 'id_m', 'od_m'):
            if edge.get(key) is None or abs(edge[key] - row['selected_size'][key]) > 1e-8:
                mismatched.append(edge['id']); break
        if row.get('loss_K') and not edge.get('K'):
            zero_k += 1
    report.add('agreement', 'applied edge bores match the calculated selection',
               not mismatched, mismatched[:3], [],
               f'{len(mismatched)} edges carry a bore the sizing did not choose')
    report.add('agreement', 'edge K carries the applied loss coefficient',
               zero_k == 0, f'{zero_k} edges report K = 0 despite a nonzero loss_K', '0 rows',
               'apply_sizes zeroes K before the coefficients are chosen; the pipeline must put them back')

    # Build the actual BOM rows rather than guessing which key the emitter reads.
    try:
        from emitters import _component_row, _edge_index
    except ImportError:
        return
    index = _edge_index(graph)
    blank = 0; priced = 0
    for component in graph['components']:
        own = index.get(component['id'], [])
        if not any((estimates.get(e['id'], {}).get('total_dp_Pa') or 0) for e in own):
            continue
        priced += 1
        if not float(_component_row(component, own)['dp_Pa'] or 0):
            blank += 1
    report.add('agreement', 'BOM.csv dp_Pa column carries the calculated loss',
               blank == 0, f'{blank}/{priced} priced components export dp_Pa = 0', '0 blank rows',
               'the emitted schedule must read the field the live sizing writes')


def check_redundancy(graph, report):
    sizing = graph['metadata'].get('preliminary_sizing') or {}
    duties = sizing.get('rack_and_equipment_duties', {})
    cfg = graph['metadata']['config']
    cdus = {cid: d for cid, d in duties.items() if 'duty_TCS_m3_s' in d}
    if not cdus:
        return
    # An N-R duty must be the pod total divided by surviving units, never by
    # installed units, or a spare is silently doing work.
    bad = [cid for cid, duty in cdus.items()
           if duty['duty_TCS_m3_s'] < duty['all_online_TCS_m3_s'] - 1e-12]
    report.add('redundancy', 'CDU duty flow is never below its all-online share',
               not bad, bad, [], 'sizing an outage duty off installed units hides the spare')

    scenarios = graph.get('scenarios', [])
    designs = [s for s in scenarios if s['kind'] == 'design']
    expected_cases = math.comb(cfg['cdu_count'], cfg['redundancy'])
    report.add('redundancy', 'every requested simultaneous outage combination is enumerated',
               len(designs) == expected_cases, len(designs), expected_cases)
    connectivity = graph['metadata'].get('connectivity_scenarios', {})
    checked = {s['name'] for s in connectivity.get('scenarios', []) if s.get('required_design_check')}
    report.add('redundancy', 'every design outage case is connectivity checked',
               all(s['name'] in checked for s in designs),
               len(checked), len(designs) + 1)
    unserved = [s['name'] for s in designs if s.get('unserved_heat_W')]
    blocked = connectivity.get('blocking_failures', 0)
    report.add('redundancy', 'an unavailable pod produces a blocking finding',
               not unserved or blocked > 0, unserved[:3], 'blocking finding',
               f'{blocked} connectivity failures reported')


# --------------------------------------------------------------------------

def sweep(config_dict, report, build):
    """Behavioural probes: does the model respond the way the physics says?"""
    from model import Config

    def measure(**overrides):
        cfg = Config(**{**config_dict, 'sizing_mode': 'preliminary', **overrides})
        graph, _ = build(cfg)
        sizing = graph['metadata']['preliminary_sizing']
        tcs = [p for p in sizing['pump_screens'] if p['circuit_id'].startswith('TCS')]
        return {'flow': sizing['thermal_flows']['TCS_m3_s'],
                'head': max((p['pump_head_m'] for p in tcs), default=0.),
                'sizes': {f['family']: (f['selection'] or {}).get('nominal_size_in')
                          for f in sizing['size_families']},
                'fws': sizing['thermal_flows']['FWS_m3_s']}

    base = measure()
    doubled = measure(rack_power_W=config_dict['rack_power_W'] * 2)
    report.close('sweep', 'doubling rack power doubles prescribed TCS flow',
                 doubled['flow'], base['flow'] * 2, 1e-9, 'm3/s')

    halved = measure(flow_input_mode='heat_balance', tcs_delta_K=config_dict.get('tcs_delta_K', 12.) / 2)
    reference = measure(flow_input_mode='heat_balance')
    report.close('sweep', 'halving the temperature rise doubles heat-balance flow',
                 halved['flow'], reference['flow'] * 2, 1e-9, 'm3/s')

    loose = measure(tcs_header_velocity_cap_m_s=6., tcs_branch_velocity_cap_m_s=4., fws_velocity_cap_m_s=6.)
    grew = [f for f, size in loose['sizes'].items()
            if size is not None and base['sizes'].get(f) is not None and size > base['sizes'][f]]
    report.add('sweep', 'raising the velocity limit never increases a pipe size',
               not grew, grew, [], 'a looser criterion must not demand more steel')

    # Fixed bore, more flow: quadratic-ish loss growth is the signature of
    # Darcy-Weisbach. A flat or falling result means a dropped term.
    fixed = {'tcs_header_velocity_cap_m_s': 50., 'tcs_branch_velocity_cap_m_s': 50.,
             'fws_velocity_cap_m_s': 50., 'cws_material': config_dict.get('cws_material', 'carbon_steel_sch40')}
    small = measure(**fixed)
    big = measure(**fixed, rack_power_W=config_dict['rack_power_W'] * 2)
    if small['head'] > 0:
        exponent = math.log(big['head'] / small['head']) / math.log(2)
        report.add('sweep', 'at a fixed bore, pump head responds to flow at all',
                   exponent > .2, round(exponent, 3), '> 0.2',
                   'Darcy-Weisbach gives ~Q^1.8-2.0; a flat result means the routed friction term '
                   'is not reaching the pump screen.')
        report.add('sweep', 'pump head is driven by friction rather than flat allocations',
                   exponent >= 1.4, round(exponent, 3), '>= 1.4 for a friction-led circuit',
                   'A low exponent is not an error: it says the declared equipment/valve pressure '
                   'allocations dominate this screen, so the number is only as good as those '
                   'placeholders. Replace them with vendor curves before quoting a pump duty.',
                   severity='warn')


def validate(graph, report, config_dict=None, build=None, do_sweep=False):
    check_thermal(graph, report)
    check_continuity(graph, report)
    check_hydraulics(graph, report)
    check_paths_and_pumps(graph, report)
    check_valves(graph, report)
    check_catalogue(graph, report)
    check_geometry(graph, report)
    check_artifact_agreement(graph, report)
    check_attention(graph, report)
    check_redundancy(graph, report)
    if do_sweep and config_dict and build:
        sweep(config_dict, report, build)
    return report


def render(report, verbose=False):
    lines = [f'== {report.label} ==']
    for group in dict.fromkeys(r['group'] for r in report.rows):
        rows = [r for r in report.rows if r['group'] == group]
        bad = [r for r in rows if r['status'] != 'PASS']
        lines.append(f'  {group:12s} {len(rows) - len(bad):3d} pass'
                     + (f', {sum(r["status"] == "FAIL" for r in rows)} FAIL' if any(r['status'] == 'FAIL' for r in rows) else '')
                     + (f', {sum(r["status"] == "WARN" for r in rows)} warn' if any(r['status'] == 'WARN' for r in rows) else ''))
        for row in (rows if verbose else bad):
            mark = {'PASS': '     ok', 'WARN': '   warn', 'FAIL': '   FAIL'}[row['status']]
            lines.append(f'  {mark}  {row["check"]}')
            if row['status'] != 'PASS' or verbose:
                lines.append(f'           measured={row["measured"]!r} expected={row["expected"]!r}')
                if row['detail']:
                    lines.append(f'           {row["detail"]}')
    lines.append(f'  TOTAL {len(report.rows)} checks, {len(report.failed)} failed, {len(report.warned)} warnings')
    return '\n'.join(lines)


# The choice lists that change geometry or the calculation path, as opposed to
# the numeric inputs that only move a number. Every combination of these is a
# distinct design the generator must produce and the checks above must pass on.
MATRIX_AXES = ('layout_style', 'return_topology', 'cdu_placement', 'plant_type', 'sizing_mode')


def design_space():
    """Inventory the configurable design choices, grouped by studio section."""
    from parameters import catalog
    sections = {}
    for field in catalog():
        section = sections.setdefault(field['group'], {'inputs': 0, 'choices': [], 'toggles': 0,
                                                       'numeric': 0, 'lists': 0})
        section['inputs'] += 1
        if field['type'] == 'select':
            section['choices'].append((field['key'], list(field.get('options') or [])))
        elif field['type'] == 'boolean':
            section['toggles'] += 1
        elif field['type'] == 'json':
            section['lists'] += 1
        else:
            section['numeric'] += 1
    for section in sections.values():
        named = 1
        for _, options in section['choices']:
            named *= max(1, len(options))
        section['named_variants'] = named
        section['with_toggles'] = named * 2 ** section['toggles']
    return sections


def render_design_space(sections):
    lines = ['== Configurable design space, by studio section ==',
             f"  {'section':<20}{'inputs':>7}{'lists':>7}{'toggles':>8}{'numeric':>8}"
             f"{'named':>8}{'x toggles':>12}"]
    total_named = total_all = 1
    for name, section in sorted(sections.items(), key=lambda kv: -kv[1]['named_variants']):
        lines.append(f"  {name:<20}{section['inputs']:>7}{len(section['choices']):>7}"
                     f"{section['toggles']:>8}{section['numeric']:>8}"
                     f"{section['named_variants']:>8}{section['with_toggles']:>12,}")
        for key, options in section['choices']:
            lines.append(f"        {key:<32}{len(options)}  ·  " + ', '.join(map(str, options)))
        total_named *= section['named_variants']
        total_all *= section['with_toggles']
    lines += ['',
              f'  {total_named:,} combinations of the choice lists alone;',
              f'  {total_all:,} once the install/routing toggles are included;',
              '  and every numeric input moves continuously on top of that.',
              '',
              f"  --matrix validates the {len(MATRIX_AXES)} axes that change geometry or the",
              '  calculation path: ' + ', '.join(MATRIX_AXES) + '.',
              '  The rest move numbers the checks already re-derive from first principles.']
    return '\n'.join(lines)


def matrix_cases(values):
    """Every combination of the geometry-shaping choice lists."""
    from itertools import product
    from parameters import OPTIONS
    axes = [(axis, OPTIONS[axis]) for axis in MATRIX_AXES]
    for combo in product(*(options for _, options in axes)):
        overrides = dict(zip((axis for axis, _ in axes), combo))
        label = ' · '.join(f'{v}' for v in combo)
        yield label, {**values, **overrides}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--config', help='parameter JSON to build and validate')
    source.add_argument('--graph', help='an already emitted graph.json')
    source.add_argument('--all-presets', action='store_true', help='validate every bundled preset')
    source.add_argument('--design-space', action='store_true',
                        help='inventory the configurable design choices by studio section and exit')
    parser.add_argument('--matrix', action='store_true',
                        help='with --config or --all-presets: validate every combination of the '
                             'geometry-shaping choice lists (slow; see --design-space)')
    parser.add_argument('--sizing-mode', choices=('manual', 'preliminary'),
                        help='override the sizing mode before building')
    parser.add_argument('--plant-type', choices=('boundary', 'air_cooled', 'water_cooled'))
    parser.add_argument('--sweep', action='store_true', help='also run behavioural probes (slow)')
    parser.add_argument('--verbose', action='store_true', help='list passing checks too')
    parser.add_argument('--json', help='write the full findings to this path')
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    reports = []

    if args.design_space:
        print(render_design_space(design_space()))
        return 0
    if args.graph:
        graph = json.loads(Path(args.graph).read_text())
        reports.append(validate(graph, Report(args.graph)))
    else:
        from model import Config
        from pipeline import build
        if args.all_presets:
            from parameters import PRESETS
            cases = [(name, dict(preset['config'])) for name, preset in PRESETS.items()]
        else:
            cases = [(args.config, json.loads(Path(args.config).read_text()))]
        for label, values in cases:
            if args.sizing_mode:
                values['sizing_mode'] = args.sizing_mode
            if args.plant_type:
                values['plant_type'] = args.plant_type
            variants = list(matrix_cases(values)) if args.matrix else [
                (f"{values.get('sizing_mode')}/{values.get('plant_type')}", values)]
            for variant, settings in variants:
                report = Report(f'{label} [{variant}]')
                try:
                    graph, _ = build(Config.from_dict(dict(settings)))
                except Exception as exc:
                    report.add('build', 'the generator produces this design',
                               False, f'{type(exc).__name__}: {exc}', 'a built graph')
                    reports.append(report)
                    continue
                reports.append(validate(graph, report, settings, build, args.sweep))

    for report in reports:
        if args.matrix and not report.failed and not args.verbose:
            print(f'== {report.label} ==  {len(report.rows)} checks, all pass'
                  + (f', {len(report.warned)} warnings' if report.warned else ''))
            continue
        print(render(report, args.verbose))
    if args.json:
        Path(args.json).write_text(json.dumps(
            [{'label': r.label, 'rows': r.rows} for r in reports], indent=2))
    failures = sum(len(r.failed) for r in reports)
    print(f'\n{failures} failing check(s) across {len(reports)} design(s).')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
