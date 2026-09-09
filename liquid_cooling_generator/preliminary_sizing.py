"""Prescribed-demand screening, deliberately separate from the physical graph.

This module never solves nodal pressures, balances parallel branches or changes
geometry. It can assign flows by continuity on a passive *tree* once equipment
flows have been prescribed. Looped or underspecified networks remain unresolved.
Catalogue selections and independent maximum-duty envelopes are recommendations,
not a simultaneous operating condition or a manufacturer equipment selection.
"""
from collections import defaultdict, deque
from math import isfinite, log10, pi, sqrt

from hydraulics import CATALOGUES, select_size

G = 9.80665
SOURCES = {
    'pipe_loss': 'https://handbook.ashrae.org/Handbooks/F25/SI/F25_Ch22/F25_Ch22_si.aspx',
    'fluid_flow': 'https://handbook.ashrae.org/Handbooks/F25/SI/F25_Ch03/F25_Ch03_si.aspx',
    'valve_kv': 'https://content.spiraxsarco.com/-/media/spiraxsarco/international/documents/it/ti/en/5953_5954_7c-400-en.ashx?rev=464a50ced2484cd5bf79dafc5608b49e',
    'valve_cv': 'https://content.spiraxsarco.com/-/media/spiraxsarco/international/documents/en/ti/dcv4-ti-p134-04-en.ashx?rev=f5642c16121e464785d2417ae1d93237',
    'pump_power': 'https://www.grundfos.com/ca/learn/ecademy/all-courses/basic-hydraulics-and-pump-performance/basic-hydraulics',
}
# Explicit screening assumptions, not universal fitting properties. Coefficients
# use the local pipe bore except reducers, which use the smaller connected bore.
DEFAULT_K = {'elbow': .6, 'tee_run': .6, 'tee_branch': 1.8,
             'isolation_valve': .2, 'check_valve': 2.5, 'reducer': .15,
             'strainer': 2., 'air_separator': 1., 'quick_disconnect': 2., 'flex_connector': 0.}
INTERNAL_KINDS = {'rack_load', 'cdu_primary', 'cdu_secondary', 'pump',
                  'chiller_evaporator', 'chiller_condenser', 'cooling_tower','air_coil'}


def _get(config, name, default=None):
    return config.get(name, default) if isinstance(config, dict) else getattr(config, name, default)


def _number(config, name, default, *, positive=False, nonnegative=False):
    value = _get(config, name, default)
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(name + ' must be a finite number')
    if positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(name + (' must be positive' if positive else ' must be nonnegative'))
    return float(value)


def friction_factor(reynolds, relative_roughness):
    """Darcy factor, with a visible uncertainty flag for transitional flow.

    Iteration is only the scalar Colebrook equation for one known pipe flow; it
    is not a flow-network solver. ASHRAE identifies 2300–10000 as uncertain.
    """
    if reynolds <= 0:
        return {'darcy_factor': 0., 'regime': 'no_flow', 'method': 'zero prescribed flow'}
    if reynolds < 2300:
        return {'darcy_factor': 64. / reynolds, 'regime': 'laminar', 'method': '64/Re'}
    trial_re = max(reynolds, 4000.)
    factor = .02
    for _ in range(40):
        updated = 1. / (-2. * log10(relative_roughness / 3.7 + 2.51 / (trial_re * sqrt(factor)))) ** 2
        if abs(updated - factor) < 1e-12:
            factor = updated
            break
        factor = updated
    if reynolds < 10000:
        return {'darcy_factor': max(64. / reynolds, factor), 'regime': 'transitional_uncertain',
                'method': 'PROJECT screening assumption: max(laminar, Colebrook at max(Re,4000)); not a guaranteed bound'}
    return {'darcy_factor': factor, 'regime': 'turbulent', 'method': 'Colebrook iteration'}


def valve_capacity(flow_m3_s, density_kg_m3, allocated_dp_Pa):
    """Non-cavitating incompressible-liquid Kv and US Cv at allocated valve dp."""
    if flow_m3_s < 0 or density_kg_m3 <= 0 or allocated_dp_Pa <= 0:
        raise ValueError('Valve sizing requires nonnegative flow, positive density and pressure allocation')
    kv = flow_m3_s * 3600. * sqrt((density_kg_m3 / 1000.) / (allocated_dp_Pa / 100000.))
    return {'Kv_m3_h': kv, 'Cv_US': 1.156 * kv, 'allocated_dp_Pa': allocated_dp_Pa,
            'specific_gravity': density_kg_m3 / 1000.,
            'basis': 'Kv=Q[m3/h]*sqrt(SG/dp[bar]); Cv(US)=1.156*Kv. No valve authority, cavitation or rangeability check.'}


def _circuit(edge, comp):
    circuit = edge.get('circuit_id') or comp.get('circuit_id')
    if not circuit or circuit == 'MULTI':
        return 'TCS-P%02d' % (comp.get('pod') or 1) if edge['service'] == 'TCS' else edge['service']
    return circuit


def _fluid_inputs(config):
    fluids = {}
    for service, defaults in [('TCS', (1025., 3900., .002)), ('FWS', (998., 4180., .001)), ('CWS', (998., 4180., .001))]:
        prefix = service.lower()
        fluids[service] = {
            'rho_kg_m3': _number(config, prefix + '_density_kg_m3', defaults[0], positive=True),
            'cp_J_kg_K': _number(config, prefix + '_specific_heat_J_kgK', defaults[1], positive=True),
            'mu_Pa_s': _number(config, prefix + '_viscosity_Pa_s', defaults[2], positive=True),
            'delta_K': _number(config, prefix + '_delta_K', 12. if service == 'TCS' else 10. if service == 'FWS' else 5., positive=True),
            'status': 'Project input at intended mean temperature; formulation and manufacturer property curve require confirmation',
        }
    return fluids


def _family(edge):
    if edge.get('pipe_family'):return edge['pipe_family']
    service, level = edge['service'], edge.get('level', 'main')
    if service == 'TCS':
        return 'rack' if level in ('rack', 'row_branch') else 'row' if level == 'row' else 'tcs_' + level
    return service.lower() + ('_cdu' if level == 'cdu' and service == 'FWS' else '_main')


def _passive_flows(edges, prescribed, extra_injections):
    """Apply continuity on forests only; return signed flows and unresolved IDs."""
    by_circuit = defaultdict(list)
    for edge in edges:
        by_circuit[edge['_circuit']].append(edge)
    assigned = dict(prescribed)
    issues = []
    for circuit, circuit_edges in by_circuit.items():
        injection = defaultdict(float)
        adj = defaultdict(list)
        uncertain_nodes = set()
        for edge in circuit_edges:
            eid, a, b = edge['id'], edge['from_node'], edge['to_node']
            if eid in prescribed:
                injection[a] -= prescribed[eid]
                injection[b] += prescribed[eid]
            elif edge.get('internal') or edge['kind'] in INTERNAL_KINDS:
                uncertain_nodes.update((a, b))
            else:
                adj[a].append((b, eid)); adj[b].append((a, eid))
        for node, value in extra_injections.get(circuit, {}).items():
            injection[node] += value
        seen = set()
        for start in sorted(set(adj) | set(injection) | uncertain_nodes):
            if start in seen:
                continue
            order, parent, component_edges = [], {start: (None, None)}, set()
            queue = [start]; seen.add(start)
            while queue:
                node = queue.pop(); order.append(node)
                for other, eid in adj[node]:
                    component_edges.add(eid)
                    if other not in seen:
                        seen.add(other); parent[other] = (node, eid); queue.append(other)
            residual = sum(injection[n] for n in order)
            tolerance = max(1e-10, sum(abs(injection[n]) for n in order) * 1e-8)
            reason = ('Unknown equipment flow' if uncertain_nodes.intersection(order) else
                      'Passive network contains a loop; branch allocation requires downstream analysis' if len(component_edges) != len(order) - 1 else
                      'Terminal demands are not conserved in this disconnected section' if abs(residual) > tolerance else None)
            if reason:
                issues.append({'circuit_id': circuit, 'reason': reason, 'edge_ids': sorted(component_edges),
                               'node_ids': order, 'residual_m3_s': residual})
                continue
            totals = dict(injection)
            edge_map = {e['id']: e for e in circuit_edges}
            for node in reversed(order):
                previous, eid = parent[node]
                if previous is None:
                    continue
                flow_to_parent = totals.get(node, 0.)
                assigned[eid] = flow_to_parent if edge_map[eid]['from_node'] == node else -flow_to_parent
                totals[previous] = totals.get(previous, 0.) + flow_to_parent
    return assigned, issues


def _longest_directed_path(edges, estimates, signed_flows, start, end, exclude_kinds):
    """Maximum prescribed-route loss on a DAG. Cycles are reported, never solved."""
    adjacency = defaultdict(list); reverse = defaultdict(list)
    for edge in edges:
        if edge['kind'] in exclude_kinds:
            continue
        flow = signed_flows.get(edge['id'])
        result = estimates.get(edge['id'], {})
        if flow is None or abs(flow) < 1e-12:
            continue
        a, b = edge['from_node'], edge['to_node']
        if flow < 0:
            a, b = b, a
        adjacency[a].append((b, edge['id'])); reverse[b].append(a)
    def reachable(root, neighbors):
        found = {root}; stack = [root]
        while stack:
            for node in neighbors(stack.pop()):
                if node not in found:
                    found.add(node); stack.append(node)
        return found
    forward = reachable(start, lambda n: (x[0] for x in adjacency[n]))
    if end not in forward:
        return {'status': 'NOT_EVALUABLE', 'reason': 'No complete route with assigned flow between pump outlet and inlet'}
    relevant = forward & reachable(end, lambda n: reverse[n])
    indegree = dict.fromkeys(relevant, 0)
    for node in relevant:
        for other, _ in adjacency[node]:
            if other in relevant:
                indegree[other] += 1
    queue = deque(sorted(n for n, degree in indegree.items() if degree == 0)); order = []
    while queue:
        node = queue.popleft(); order.append(node)
        for other, _ in adjacency[node]:
            if other in relevant:
                indegree[other] -= 1
                if indegree[other] == 0:
                    queue.append(other)
    if len(order) != len(relevant):
        return {'status': 'NOT_EVALUABLE', 'reason': 'Passive route contains a directed cycle; no longest-path estimate assigned'}
    distance = {start: 0.}; previous = {}
    for node in order:
        if node not in distance:
            continue
        for other, eid in adjacency[node]:
            if other not in relevant:
                continue
            loss = estimates[eid].get('total_dp_Pa')
            if loss is None:
                return {'status': 'NOT_EVALUABLE', 'reason': 'A required path component has unresolved diameter or pressure loss', 'edge_id': eid}
            candidate = distance[node] + loss
            if candidate > distance.get(other, -1):
                distance[other] = candidate; previous[other] = (node, eid)
    path = []; current = end
    while current != start:
        current, eid = previous[current]; path.append(eid)
    path.reverse()
    return {'status': 'SCREENING_ESTIMATE', 'edge_ids': path, 'passive_dp_Pa': distance[end],
            'straight_dp_Pa': sum(estimates[e]['straight_dp_Pa'] for e in path),
            'fitting_dp_Pa': sum(estimates[e]['fitting_dp_Pa'] for e in path),
            'equipment_dp_Pa': sum(estimates[e]['equipment_dp_Pa'] for e in path)}


def evaluate(graph, config):
    """Return independent sizing recommendations and transparent assumptions.

    The returned ``size_families`` can be applied to nominal-size parameters by
    the caller, followed by a complete geometry rebuild and collision check.
    Nothing in ``graph`` or ``config`` is mutated here.
    """
    mode = _get(config, 'flow_input_mode', 'lpm_per_kw')
    if mode not in ('lpm_per_kw', 'heat_balance'):
        raise ValueError('flow_input_mode must be lpm_per_kw or heat_balance')
    ratio = _number(config, 'flow_lpm_per_kw', 1.2, positive=True)
    efficiency = _number(config, 'pump_efficiency', .7, positive=True)
    if efficiency > 1:
        raise ValueError('pump_efficiency must be greater than zero and at most one')
    margin = _number(config, 'pump_head_margin_fraction', .15, nonnegative=True)
    fluids = _fluid_inputs(config)
    valve_dp = _number(config, 'valve_design_dp_kPa', 20., positive=True) * 1000
    allocations = {'rack_load': _number(config, 'rack_design_dp_kPa', 30., nonnegative=True) * 1000,
                   'cdu_primary': _number(config, 'cdu_design_dp_kPa', 50., nonnegative=True) * 1000,
                   'cdu_secondary': _number(config, 'cdu_design_dp_kPa', 50., nonnegative=True) * 1000,
                   'chiller_evaporator': _number(config, 'chiller_design_dp_kPa', 50., nonnegative=True) * 1000,
                   'chiller_condenser': _number(config, 'chiller_design_dp_kPa', 50., nonnegative=True) * 1000,
                   'balancing_valve': valve_dp, 'control_valve': valve_dp,
                   'air_coil': _number(config, 'air_unit_design_dp_kPa',35.,nonnegative=True)*1000}
    k_values = dict(DEFAULT_K)
    overrides = _get(config, 'fitting_loss_coefficients', {})
    if not isinstance(overrides, dict):
        raise ValueError('fitting_loss_coefficients must be a kind-to-K object')
    for kind, value in overrides.items():
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError('Fitting loss coefficients must be finite and nonnegative')
        k_values[kind] = value
    components = {comp['id']: comp for comp in graph['components']}
    edges = [dict(edge, _circuit=_circuit(edge, components[edge['component_id']])) for edge in graph['edges']]
    edge_by_id = {e['id']: e for e in edges}
    warnings = []; prescribed = {}; duties = {}; heat_by_pod = defaultdict(float); flow_by_pod = defaultdict(float)
    def heat_flow(heat, service):
        fluid = fluids[service]
        return heat / (fluid['rho_kg_m3'] * fluid['cp_J_kg_K'] * fluid['delta_K'])
    rack_edges = [e for e in edges if e['kind'] == 'rack_load']
    row_flows = defaultdict(float)
    for edge in rack_edges:
        comp = components[edge['component_id']]
        heat = comp.get('heat_W', comp.get('power_W', _get(config, 'rack_power_W', 132000.)) * comp.get('liquid_fraction', _get(config, 'liquid_fraction', .95)))
        if type(heat) not in (int, float) or not isfinite(heat) or heat < 0:
            raise ValueError('Rack liquid heat must be finite and nonnegative: ' + comp['id'])
        flow = heat / 1000. * ratio / 60000. if mode == 'lpm_per_kw' else heat_flow(heat, 'TCS')
        prescribed[edge['id']] = flow
        duties[edge['component_id']] = {'liquid_heat_W': heat, 'TCS_m3_s': flow, 'TCS_L_min': flow * 60000.}
        heat_by_pod[edge['_circuit']] += heat; flow_by_pod[edge['_circuit']] += flow
        row_flows[(edge['_circuit'], edge.get('row') or comp.get('row'))] += flow
    if not rack_edges:
        warnings.append({'code': 'NO_RACK_DEMAND', 'detail': 'No aggregate rack_load edges; rack and plant duties are unresolved.'})
    total_heat = sum(heat_by_pod.values())
    from air_cooling import heat_ledger
    ledger=heat_ledger(config); air_heat=ledger['air_W']; plant_heat=total_heat+air_heat
    fws_total=heat_flow(plant_heat,'FWS')
    air_edges=[e for e in edges if e['kind']=='air_coil']
    if air_heat and not air_edges:
        warnings.append({'code':'AIR_LOAD_UNROUTED','detail':'Air heat is included in plant duty but this graph has no air coil branches.'})
    for edge in air_edges:
        heat=components[edge['component_id']].get('heat_W',air_heat/len(air_edges))
        flow=heat_flow(heat,'FWS');prescribed[edge['id']]=flow
        duties[edge['component_id']]={'FWS_duty_heat_W':heat,'FWS_duty_m3_s':flow,'air_heat_W':heat}
    if air_heat:
        warnings.append({'code':'AIR_COIL_PERFORMANCE_UNRESOLVED','detail':'Air coils share the declared FWS supply. Verify entering water/air conditions with the coil vendor; warm CDU facility water may require a separate chilled-water circuit for air cooling.'})
    cop = _get(config, 'chiller_cop', None)
    if cop is not None and (type(cop) not in (int, float) or not isfinite(cop) or cop <= 0):
        raise ValueError('chiller_cop must be positive when specified')
    condenser_heat = plant_heat * (1 + 1. / cop) if cop else plant_heat
    cws_total = heat_flow(condenser_heat, 'CWS')
    cdu_by_pod = defaultdict(list)
    for edge in edges:
        if edge['kind'] == 'cdu_secondary':
            cdu_by_pod[edge['_circuit']].append(edge)
    global_spares = int(_get(config, 'redundancy', 0))
    duty_flows = {(e['component_id'],'FWS'):prescribed[e['id']] for e in air_edges}; family_totals = dict(flow_by_pod, FWS=fws_total, CWS=cws_total)
    for circuit, items in cdu_by_pod.items():
        installed = len(items); surviving = installed - global_spares
        if surviving <= 0:
            warnings.append({'code': 'POD_SPARES_UNRESOLVED', 'circuit_id': circuit,
                             'detail': 'Configured global CDU outages can remove every CDU in this pod; no duty-capacity guarantee.'})
            surviving = 1
        for edge in items:
            prescribed[edge['id']] = flow_by_pod[circuit] / installed
            cid = edge['component_id']
            duty_flows[(cid, 'TCS')] = flow_by_pod[circuit] / surviving
            duty_flows[(cid, 'FWS')] = heat_flow(heat_by_pod[circuit], 'FWS') / surviving
            duties[cid] = {'pod': circuit, 'all_online_heat_W': heat_by_pod[circuit] / installed,
                           'screening_duty_heat_W': heat_by_pod[circuit] / surviving,
                           'all_online_TCS_m3_s': prescribed[edge['id']],
                           'duty_TCS_m3_s': duty_flows[(cid, 'TCS')], 'duty_FWS_m3_s': duty_flows[(cid, 'FWS')]}
    kinds = defaultdict(list)
    for edge in edges:
        kinds[(edge['service'], edge['kind'])].append(edge)
    for edge in kinds[('FWS', 'cdu_primary')]:
        cid = edge['component_id']; duty = duties.get(cid)
        if duty:
            prescribed[edge['id']] = heat_flow(duty['all_online_heat_W'], 'FWS')
    for service, kind, stem, heat in [('FWS', 'chiller_evaporator', 'chiller', plant_heat),
                                     ('CWS', 'chiller_condenser', 'chiller', condenser_heat),
                                     ('FWS', 'pump', 'fws_pump', plant_heat),
                                     ('CWS', 'pump', 'cws_pump', condenser_heat),
                                     ('CWS', 'cooling_tower', 'tower', condenser_heat)]:
        items = kinds[(service, kind)]
        if not items:
            continue
        installed = len(items); spares = int(_get(config, stem + '_spares', 0)); duty_count = installed - spares
        if duty_count < 1:
            raise ValueError(stem + ' spare count must be below the number of modeled units')
        total_flow = family_totals[service]
        for edge in items:
            cid = edge['component_id']; prescribed[edge['id']] = total_flow / installed
            duty_flows[(cid, service)] = total_flow / duty_count
            duties.setdefault(cid, {}).update({service + '_all_online_m3_s': total_flow / installed,
                service + '_duty_m3_s': total_flow / duty_count, service + '_duty_heat_W': heat / duty_count,
                'duty_units': duty_count, 'installed_units': installed})
    extra = defaultdict(dict)
    if _get(config, 'plant_type', 'boundary') == 'boundary':
        for key, sign in [('fws_source', 1), ('fws_sink', -1)]:
            node = graph.get('metadata', {}).get(key)
            if node:
                extra['FWS'][node] = sign * fws_total
    signed, unknown = _passive_flows(edges, prescribed, extra)
    warnings += [{'code': 'FLOW_ASSIGNMENT_UNRESOLVED', **item} for item in unknown]
    if kinds[('CWS', 'cooling_tower')] and cop is None:
        warnings.append({'code': 'CONDENSER_HEAT_LOWER_BOUND', 'detail': 'CWS flow uses evaporator heat only; compressor and pump heat are missing. Enter chiller_cop before calling this a tower duty.'})
    # Uniform families deliberately avoid suggesting unintended bore changes at
    # every pipe segment. Fitting/pipe families are changed only at reducers.
    families = {}; estimates = {}; pending = []
    for edge in edges:
        eid, service, circuit, cid = edge['id'], edge['service'], edge['_circuit'], edge['component_id']
        if service not in fluids:
            pending.append({'edge_id': eid, 'reason': 'Fluid properties not provided for ' + service}); continue
        if eid not in signed:
            estimates[eid] = {'edge_id': eid, 'component_id': cid, 'circuit_id': circuit, 'status': 'NOT_EVALUABLE',
                             'flow_m3_s': None, 'design_flow_m3_s': None, 'total_dp_Pa': None}
            continue
        flow = abs(signed[eid]); level = edge.get('level', 'main'); comp = components[cid]
        family = _family(edge)
        if (cid, service) in duty_flows:
            envelope = duty_flows[(cid, service)]
        elif edge.get('pipe_family')=='fws_air':
            envelope=max((prescribed[e['id']] for e in air_edges),default=flow)
        elif level == 'cdu' and comp.get('cdu'):
            envelope = duty_flows.get(('CDU-%02d' % comp['cdu'], service), flow)
        elif service == 'TCS' and level in ('rack', 'row_branch'):
            envelope = max(flow, max((prescribed[e['id']] for e in rack_edges if e['_circuit'] == circuit), default=flow))
        elif service == 'TCS' and level == 'row':
            envelope = row_flows.get((circuit, edge.get('row') or comp.get('row')), flow)
        else:
            envelope = family_totals.get(circuit, flow)
        design_flow = max(flow, envelope)
        cap = edge.get('velocity_cap_m_s')
        if not cap:
            cap = _get(config, 'tcs_branch_velocity_cap_m_s', 1.5) if family == 'rack' else _get(config, 'tcs_header_velocity_cap_m_s', 2.7) if service == 'TCS' else _get(config, 'fws_velocity_cap_m_s', 3.)
        if type(cap) not in (int, float) or not isfinite(cap) or cap <= 0:
            raise ValueError('Velocity cap must be positive: ' + eid)
        material = edge.get('material')
        fkey = family + ':' + str(material)
        entry = families.setdefault(fkey, {'family': family, 'parameter': family + '_nominal_in', 'material': material,
            'design_flow_m3_s': 0., 'velocity_cap_m_s': cap, 'edge_ids': []})
        entry['design_flow_m3_s'] = max(entry['design_flow_m3_s'], design_flow)
        entry['velocity_cap_m_s'] = min(entry['velocity_cap_m_s'], cap); entry['edge_ids'].append(eid)
        estimates[eid] = {'edge_id': eid, 'component_id': cid, 'circuit_id': circuit, 'service': service,
                         'status': 'SCREENING_ESTIMATE', 'flow_m3_s': flow, 'flow_L_min': flow * 60000,
                         'signed_all_online_flow_m3_s': signed[eid], 'design_flow_m3_s': design_flow,
                         'size_family': fkey, 'flow_basis': 'Prescribed equipment sharing; continuity on passive trees. Design flow is an independent sizing envelope.'}
    for family in families.values():
        try:
            family['selection'] = select_size(family['design_flow_m3_s'], family['material'], family['velocity_cap_m_s'])
            family['status'] = 'CATALOGUE_RECOMMENDATION'
        except ValueError as exc:
            family['selection'] = None; family['status'] = 'NO_CATALOGUE_SIZE'; family['reason'] = str(exc)
            family['diagnostic']=getattr(exc,'diagnostic',{})
            pending.append({'family': family['family'], 'reason': str(exc)})
    # Set every recommendation before evaluating reducers; the smaller adjacent
    # bore must not depend on iteration order in the component list.
    for result in estimates.values():
        family = families.get(result.get('size_family'))
        if family and family['selection']:
            result['selected_size'] = dict(family['selection'])
    valves = []
    for eid, result in estimates.items():
        if result['status'] == 'NOT_EVALUABLE':
            continue
        edge = edge_by_id[eid]; fluid = fluids[edge['service']]; family = families[result['size_family']]
        size = family['selection']
        if size is None:
            result.update(status='NOT_EVALUABLE', total_dp_Pa=None, reason=family['reason']); continue
        result['selected_size'] = dict(size)
        diameter = size['id_m']; flow = result['design_flow_m3_s']; velocity = flow / (pi * diameter ** 2 / 4)
        roughness = edge.get('roughness_m', {'copper_type_l': 1.5e-6, 'stainless_sch10': 15e-6}.get(edge['material'], 45.72e-6))
        if roughness < 0:
            raise ValueError('Roughness must be nonnegative: ' + eid)
        reynolds = fluid['rho_kg_m3'] * velocity * diameter / fluid['mu_Pa_s']
        factor = friction_factor(reynolds, roughness / diameter)
        length = edge.get('length_m', 0.)
        if not isfinite(length) or length < 0:
            raise ValueError('Pipe length must be finite and nonnegative: ' + eid)
        dynamic = fluid['rho_kg_m3'] * velocity ** 2 / 2
        straight = factor['darcy_factor'] * length / diameter * dynamic if edge['kind'] == 'pipe' else 0.
        kind = edge['kind']; k = k_values.get(kind, 0.); equipment_dp = allocations.get(kind, 0.) if flow else 0.
        if kind in allocations:
            k = 0.  # An allocated valve/equipment dp is not counted twice as K.
        reference_diameter = diameter
        if kind == 'reducer':
            connected = [r['selected_size']['id_m'] for other, r in estimates.items()
                         if other != eid and r.get('selected_size') and
                         {edge['from_node'], edge['to_node']} & {edge_by_id[other]['from_node'], edge_by_id[other]['to_node']}]
            reference_diameter = min([diameter] + connected)
        k_velocity = flow / (pi * reference_diameter ** 2 / 4)
        fitting = k * fluid['rho_kg_m3'] * k_velocity ** 2 / 2
        if kind not in {'pipe', 'pump', 'cooling_tower'} | set(k_values) | set(allocations):
            pending.append({'edge_id': eid, 'reason': 'No declared loss assumption for component kind ' + kind})
            result.update(status='NOT_EVALUABLE', total_dp_Pa=None); continue
        result.update(velocity_m_s=velocity, velocity_cap_m_s=family['velocity_cap_m_s'],
                      velocity_cap_pass=velocity <= family['velocity_cap_m_s'] + 1e-9,
                      Reynolds=reynolds, roughness_m=roughness, friction_factor=factor['darcy_factor'],
                      flow_regime=factor['regime'], friction_method=factor['method'],
                      straight_dp_Pa=straight, fitting_dp_Pa=fitting, equipment_dp_Pa=equipment_dp,
                      total_dp_Pa=straight + fitting + equipment_dp,
                      loss_K=k, K_reference_id_m=reference_diameter,
                      loss_basis='Routed length plus declared project K/pressure allocations; manufacturer curves unassigned')
        if kind in ('balancing_valve', 'control_valve'):
            valves.append({'component_id': edge['component_id'], 'edge_id': eid, 'flow_m3_s': flow,
                           **valve_capacity(flow, fluid['rho_kg_m3'], valve_dp)})
    pumps = []
    by_circuit = defaultdict(list)
    for edge in edges:
        by_circuit[edge['_circuit']].append(edge)
    for circuit, circuit_edges in by_circuit.items():
        service = circuit_edges[0]['service']
        source_kind = 'cdu_secondary' if service == 'TCS' else 'pump'
        for pump in (e for e in circuit_edges if e['kind'] == source_kind):
            path = _longest_directed_path(circuit_edges, estimates, signed, pump['to_node'], pump['from_node'], {source_kind})
            item = {'component_id': pump['component_id'], 'circuit_id': circuit,
                    'basis': 'Maximum directed passive route with prescribed sharing and independent design-flow envelopes; branch balancing and pump curves not solved.', **path}
            if path['status'] != 'NOT_EVALUABLE':
                fluid = fluids[service]; flow = duty_flows.get((pump['component_id'], service), abs(signed.get(pump['id'], 0.)))
                internal = allocations['cdu_secondary'] if service == 'TCS' else 0.
                friction_dp = path['passive_dp_Pa'] + internal
                static_dp = 0.; static_status = 'Closed-loop elevation cancels; fill pressure, NPSH and expansion remain unassigned'
                complete = True
                if service == 'CWS':
                    lift = _get(config, 'cws_static_lift_m', _get(config, 'tower_static_lift_m', None))
                    nozzle = _get(config, 'tower_nozzle_dp_kPa', None)
                    if lift is None or nozzle is None:
                        static_status = 'OPEN tower loop: basin-to-discharge static lift and nozzle pressure are unassigned; reported head/power are friction-only lower-bound screens'
                        complete = False
                    else:
                        if type(lift) not in (int, float) or type(nozzle) not in (int, float) or not isfinite(lift) or not isfinite(nozzle) or lift < 0 or nozzle < 0:
                            raise ValueError('Tower static lift and nozzle pressure must be finite and nonnegative')
                        static_dp = fluid['rho_kg_m3'] * G * lift + nozzle * 1000.
                        static_status = 'Open tower circuit; user-entered basin-to-discharge lift and nozzle pressure included'
                    if cop is None:
                        complete = False
                dp = (friction_dp + static_dp) * (1 + margin)
                item.update(status='SCREENING_ESTIMATE' if complete else 'INCOMPLETE_LOWER_BOUND',
                    design_flow_m3_s=flow, passive_dp_Pa=path['passive_dp_Pa'], internal_cdu_dp_Pa=internal,
                    static_dp_Pa=static_dp, static_head_basis=static_status, head_margin_fraction=margin,
                    pump_dp_Pa=dp, pump_head_m=dp / (fluid['rho_kg_m3'] * G), hydraulic_power_W=flow * dp,
                    estimated_input_power_W=flow * dp / efficiency, efficiency=efficiency,
                    efficiency_basis='Assumed overall wire-to-water efficiency; use a matching efficiency when interpreting input power')
            pumps.append(item)
    unresolved = pending + warnings
    suggested_config = {}
    for family in families.values():
        if family['selection']:
            key = family['parameter']
            suggested_config[key] = max(suggested_config.get(key, 0.), family['selection']['nominal_size_in'])
    return {'schema_version': '1.0', 'status': 'PRELIMINARY_ESTIMATES',
            'network_pressure_solve_performed': False, 'geometry_modified': False, 'sizing_ready':all(f.get('selection') for f in families.values()),
            'flow_input_mode': mode, 'flow_lpm_per_liquid_kw': ratio if mode == 'lpm_per_kw' else None,
            'fluid_properties': fluids, 'rack_and_equipment_duties': duties,
            'thermal_flows': {'liquid_heat_W': total_heat,'air_heat_W':air_heat,'plant_heat_W':plant_heat,'FWS_air_m3_s':heat_flow(air_heat,'FWS'), 'TCS_m3_s': sum(flow_by_pod.values()),
                'TCS_L_min': sum(flow_by_pod.values()) * 60000., 'FWS_m3_s': fws_total,
                'FWS_L_min': fws_total * 60000., 'CWS_m3_s': cws_total if kinds[('CWS', 'cooling_tower')] else None,
                'condenser_heat_W': condenser_heat if kinds[('CWS', 'cooling_tower')] else None,
                'condenser_heat_basis': 'Evaporator plus compressor heat from entered COP; pump heat excluded' if cop else 'Evaporator-only lower bound; compressor and pump heat unassigned',
                'pod_flows_m3_s': dict(flow_by_pod), 'pod_liquid_heat_W': dict(heat_by_pod),
                'effective_TCS_delta_K': total_heat / (fluids['TCS']['rho_kg_m3'] * fluids['TCS']['cp_J_kg_K'] * sum(flow_by_pod.values())) if sum(flow_by_pod.values()) else None},
            'suggested_config': suggested_config,
            'size_families': list(families.values()), 'edge_estimates': list(estimates.values()),
            'pump_screens': pumps, 'valve_capacities': valves, 'unresolved': unresolved,
            'assumptions': {'K_by_kind': k_values, 'allocated_dp_Pa_by_kind': allocations,
                'K_reference': 'Selected local bore; reducer uses smaller connected recommended bore',
                'flow_sharing': 'All modeled units share equally within their assigned pod or plant bank; installed spare units are included in all-online flows',
                'sizing_envelope': 'Rack and row demands, full circuit main flow, and equipment duty division by installed-minus-spares. These maxima do not represent one solved operating network.',
                'equipment': 'CDU and chiller allocations apply independently to each fluid side; rack allocation represents aggregate IT-side loss',
                'flexibility': 'Default hose K=0 is an explicit unverified placeholder; hose/QD vendor curves remain required',
                'scope': 'No pump-curve intersection, pressure balancing, controls stability, operating redundancy, NPSH, cavitation, transient, or certified capacity assessment'},
            'sources': SOURCES}
