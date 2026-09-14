"""Applied RD duties for a headless equipment shortlist; no catalogue selection.

The RD owns flow, diameter rounding, pressure-loss budgets and throttling Kv/Cv.
This contract preserves those decisions, the separate fluid sides of equipment,
and missing requirements. A hydraulic pressure drop is never a working-pressure
rating. Pipe material and nominal NPS are not proof of a compatible connection.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from json import dumps
from math import isfinite
from model import canonical_digest


SCHEMA_VERSION = '1.0'
KINDS = {
    'isolation_valve': ('valve', 'shutoff_valve', True),
    'balancing_valve': ('valve', 'balancing_valve', True),
    'control_valve': ('valve', 'control_valve', True),
    'check_valve': ('valve', 'check_valve', True),
    'quick_disconnect': ('quick_disconnect', None, True),
    'strainer': ('strainer', 'line_strainer', True),
    'cdu': ('cdu', None, True),
    'chiller': ('chiller', None, True),
    'pump': ('pump', None, False),
    'air_unit': ('air_unit', None, False),
    'cooling_tower': ('cooling_tower', None, False),
    'air_separator': ('air_separator', None, False),
    'expansion_tank': ('expansion_tank', None, False),
    'flex_connector': ('hose', None, False),
    'vent': ('vent', None, False),
    'drain': ('drain', None, False),
}
THROTTLING = {'balancing_valve', 'control_valve'}


def _digest(value):
    return canonical_digest(value)


def _number(value, name, positive=False):
    if value is None:
        return None
    if type(value) not in (int, float) or not isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(name + ' must be a finite ' + ('positive' if positive else 'nonnegative') + ' number')
    return float(value)


def _temperature(value, name):
    if value is None:
        return None
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(name + ' must be a finite temperature')
    return float(value)


def _issue(code, detail):
    return {'code': code, 'detail': detail}


def build_requirements(graph, config=None, sizing=None):
    """Return hash-bound requirements from an applied, rounded graph.

    Normally call ``build_requirements(graph)`` after ``pipeline.build``. Optional
    config/sizing arguments must match the applied graph; they cannot substitute
    draft parameters or a sizing file from another Apply. Manual models can be
    matched when duties were evaluated at their verified, retained pipe sizes.
    """
    metadata = graph.get('metadata', {})
    applied = metadata.get('config')
    if not isinstance(applied, dict) or not metadata.get('config_hash'):
        raise ValueError('Equipment requirements need an applied graph with config and config_hash')
    if _digest(applied) != metadata['config_hash']:
        raise ValueError('Applied configuration hash does not match the graph')
    if config is not None:
        supplied = asdict(config) if is_dataclass(config) else dict(config)
        if _digest(supplied) != metadata['config_hash']:
            raise ValueError('Draft parameters do not match the applied graph')
    config = applied
    stored_sizing = metadata.get('preliminary_sizing')
    if sizing is not None and _digest(sizing) != _digest(stored_sizing):
        raise ValueError('Sizing must match the preliminary results embedded in this applied graph')
    sizing = stored_sizing if sizing is None else sizing
    calculated = isinstance(sizing, dict) and sizing.get('status') == 'PRELIMINARY_ESTIMATES' and config.get('sizing_mode') in ('preliminary', 'manual')
    sizing = sizing if calculated else {}
    estimates = {row['edge_id']: row for row in sizing.get('edge_estimates', [])}
    coefficients = {row['component_id']: row for row in sizing.get('valve_capacities', [])}
    duties = sizing.get('rack_and_equipment_duties', {})
    pump_screens = {(row['component_id'], row['circuit_id']): row for row in sizing.get('pump_screens', [])}
    edges = graph.get('edges', [])
    by_component = defaultdict(list); by_node = defaultdict(list)
    for edge in edges:
        by_component[edge['component_id']].append(edge)
        by_node[edge['from_node']].append(edge); by_node[edge['to_node']].append(edge)
    dimensions_mismatch = []
    for edge in edges:
        selection = estimates.get(edge['id'], {}).get('selected_size')
        if not selection:
            continue
        for key in ('nominal_size_in', 'id_m', 'od_m'):
            if edge.get(key) is None or abs(edge[key] - selection[key]) > 1e-8:
                dimensions_mismatch.append({'edge_id': edge['id'], 'field': key,
                                            'actual': edge.get(key), 'calculated': selection[key]})
    manual_retained = calculated and config.get('sizing_mode') == 'manual' and sizing.get('dimension_basis') == 'manual_catalogue' and sizing.get('sizing_ready') is True
    rounded = calculated and (sizing.get('geometry_modified') is True or manual_retained) and not dimensions_mismatch
    digest = metadata['config_hash']
    requirements = []
    for component in graph.get('components', []):
        kind = component.get('kind')
        if kind not in KINDS:
            continue
        cid = component['id']; category, subtype, supported = KINDS[kind]
        if kind == 'chiller':
            subtype = config.get('plant_type', '') + '_chiller'
        unresolved = []; ports = []; sides = []
        physical = not component.get('attachment', False)
        own_edges = by_component[cid]
        if manual_retained:
            for issue in sizing.get('unresolved', []):
                if issue.get('component_id') == cid and issue.get('code') == 'MANUAL_VELOCITY_LIMIT_EXCEEDED':
                    unresolved.append(_issue(issue['code'], issue['detail']))
        for port in component.get('port_details', []):
            nid = port['node_id']
            neighbors = [e for e in by_node[nid] if e['component_id'] != cid]
            local = neighbors[0] if len(neighbors) == 1 else next((e for e in own_edges if nid in (e['from_node'], e['to_node'])), {})
            # Preserve both designation and actual dimensions. There is deliberately
            # no NPS*25.4 "DN" field or inferred threaded/flanged connection.
            ports.append({'id': port['id'], 'node_id': nid, 'circuit_id': port.get('circuit_id'),
                'service': port.get('service'), 'nominal_nps_in': _number(port.get('nominal_size_in'), cid + ' NPS', True),
                'pipe_id_m': _number(local.get('id_m', port.get('id_m')), cid + ' pipe ID', True),
                'pipe_od_m': _number(local.get('od_m', port.get('od_m')), cid + ' pipe OD', True),
                'pipe_material': local.get('material'), 'pipe_dimension_standard': local.get('size_standard'),
                'connection_type': port.get('connection_type'), 'connection_standard': port.get('connection_standard'),
                'role': port.get('role'), 'direction_outward': deepcopy(port.get('outward'))})
        circuit_groups = defaultdict(list)
        for port in ports:
            circuit_groups[(port['circuit_id'], port['service'])].append(port)
        for (circuit, service), side_ports in sorted(circuit_groups.items(), key=lambda x: str(x[0])):
            prefix = service.lower() if service else ''
            side_edges = [e for e in own_edges if e.get('circuit_id') == circuit and e.get('service') == service]
            selected = [estimates[e['id']] for e in side_edges if e['id'] in estimates]
            assigned = bool(selected) and len(selected) == len(side_edges) and all(
                x.get('status') == 'SCREENING_ESTIMATE' and x.get('design_flow_m3_s') is not None for x in selected)
            flow = max((_number(x.get('design_flow_m3_s'), cid + ' flow') for x in selected), default=None) if assigned else None
            supply = _temperature(config.get(prefix + '_supply_C'), cid + ' supply temperature')
            delta = _number(config.get(prefix + '_delta_K'), cid + ' temperature difference', True)
            declared_return = supply + delta if supply is not None and delta is not None else None
            effective_delta = sizing.get('thermal_flows', {}).get('effective_TCS_delta_K') if service == 'TCS' else None
            estimated_return = supply + effective_delta if supply is not None and effective_delta is not None else None
            temperatures = [x for x in (supply, declared_return, estimated_return) if x is not None]
            pressure = _number(config.get(prefix + '_design_pressure_bar'), cid + ' design pressure') or None
            if pressure is None:
                unresolved.append(_issue('PRESSURE_RATING_UNASSIGNED', circuit + ': maximum design working pressure including fill/static/transient allowances is not supplied. Hydraulic dp is not a pressure rating.'))
            fluid = {'name': 'water / propylene glycol' if service == 'TCS' and config.get('pg_volume_fraction', 0) else 'water',
                     'pg_volume_fraction': config.get('pg_volume_fraction', 0.) if service == 'TCS' else 0.,
                     'cooling_phase': 'single_phase',
                     'properties': deepcopy(sizing.get('fluid_properties', {}).get(service, {})),
                     'formulation': None, 'compatibility_status': 'SUPPLIER_APPROVAL_REQUIRED'}
            losses = [{'edge_id': x['edge_id'], 'assumed_K': x.get('loss_K'),
                       'reference_pipe_id_m': x.get('K_reference_id_m'), 'estimated_dp_Pa': x.get('total_dp_Pa'),
                       'basis': x.get('loss_basis')} for x in selected]
            sides.append({'circuit_id': circuit, 'service': service, 'port_ids': [p['id'] for p in side_ports],
                'design_flow_m3_s': flow, 'flow_status': 'PRESCRIBED_RD_DUTY' if assigned else 'UNASSIGNED',
                'fluid': fluid, 'temperature': {'supply_C': supply, 'declared_return_C': declared_return,
                    'estimated_return_C': estimated_return, 'required_max_temperature_C': max(temperatures) if temperatures else None,
                    'basis': 'Maximum declared or estimated operating temperature; no design-temperature margin, freeze/startup or transient limit inferred'},
                'minimum_pressure_rating_Pa': pressure * 100000. if pressure is not None else None,
                'pressure_basis': 'Explicit design-pressure input only; independent of pump head and component dp',
                'connected_pipe_materials': sorted({p['pipe_material'] for p in side_ports if p.get('pipe_material')}),
                'required_wetted_materials': None, 'screening_losses': losses})
            if not assigned:
                unresolved.append(_issue('FLOW_UNASSIGNED', circuit + ': complete assigned preliminary flow is required.'))
        throttling = None
        if kind in THROTTLING:
            coeff = coefficients.get(cid)
            if coeff and calculated:
                cv = _number(coeff.get('Cv_US'), cid + ' required Cv', True)
                kv = _number(coeff.get('Kv_m3_h'), cid + ' required Kv', True)
                dp = _number(coeff.get('allocated_dp_Pa'), cid + ' allocated valve dp', True)
                throttling = {'required_Cv_US': cv, 'required_Kv_m3_h': kv, 'allocated_dp_Pa': dp,
                    'flow_m3_s': _number(coeff.get('flow_m3_s'), cid + ' valve flow', True),
                    'source_edge_id': coeff.get('edge_id'),
                    'basis': 'RD calculated liquid throttling duty. Manufacturer trim, authority, rangeability and cavitation checks remain required.'}
            if throttling is None or any(throttling.get(k) is None for k in ('required_Cv_US', 'required_Kv_m3_h', 'allocated_dp_Pa')):
                unresolved.append(_issue('THROTTLING_DUTY_UNASSIGNED', 'No complete calculated Kv/Cv at an allocated pressure drop.'))
        duty = duties.get(cid, {}); thermal = None
        if kind == 'cdu':
            thermal = {'required_capacity_W': duty.get('screening_duty_heat_W'), 'all_online_heat_W': duty.get('all_online_heat_W'),
                'heat_transfer_type': 'liquid_to_liquid', 'cooling_phase': 'single_phase',
                'basis': 'Independent CDU duty envelope for the assigned pod; not nameplate capacity at arbitrary temperatures',
                'TCS_supply_C': config.get('tcs_supply_C'), 'FWS_supply_C': config.get('fws_supply_C'),
                'required_approach_K': config.get('tcs_supply_C', 0) - config.get('fws_supply_C', 0),
                'vendor_performance_map_required': True}
        elif kind in ('chiller', 'cooling_tower','air_unit'):
            key = 'FWS_duty_heat_W' if kind in ('chiller','air_unit') else 'CWS_duty_heat_W'
            thermal = {'required_capacity_W': duty.get(key), 'condenser_heat_W': duty.get('CWS_duty_heat_W'),
                'plant_type': config.get('plant_type'), 'basis': 'RD duty per installed-minus-spare units; ratings must match fluid and inlet/outlet conditions',
                'condenser_heat_basis': sizing.get('thermal_flows', {}).get('condenser_heat_basis'),
                'ambient_dry_bulb_C': config.get('design_ambient_dry_bulb_C'),
                'ambient_wet_bulb_C': config.get('design_ambient_wet_bulb_C'), 'vendor_performance_map_required': True}
        if thermal and thermal.get('required_capacity_W') is None:
            unresolved.append(_issue('THERMAL_DUTY_UNASSIGNED', 'Calculated equipment duty is missing.'))
        if kind == 'chiller':
            unresolved.append(_issue('CHILLER_RATING_CONDITIONS_REQUIRED', 'Capacity shortlist requires vendor rating at the specified water temperatures/flow and air or condenser-water condition.'))
        if kind == 'strainer' and not component.get('filtration_um'):
            unresolved.append(_issue('FILTRATION_UNASSIGNED', 'Required mesh/particle rating and clean/dirty loss budgets are not specified.'))
        if kind == 'quick_disconnect':
            unresolved.append(_issue('QD_MATING_INTERFACE_UNASSIGNED', 'Mating series, connector halves, shutoff arrangement and spill/leak limits require an equipment interface specification.'))
        if not physical or not ports:
            unresolved.append(_issue('CONCEPT_INTERFACE_ONLY', 'Installation marker or provision has no complete physical port contract.'))
        if any(not p.get('connection_type') or not p.get('connection_standard') for p in ports):
            unresolved.append(_issue('CONNECTION_STANDARD_UNASSIGNED', 'Exact NPS and pipe bore do not establish flange, thread, groove, weld or quick-coupling compatibility.'))
        unresolved.append(_issue('WETTED_MATERIAL_APPROVAL_REQUIRED', 'Connected pipe material is context, not a required equipment-body material or proof of complete coolant/seal compatibility.'))
        if not supported:
            unresolved.append(_issue('FINDER_CATEGORY_UNSUPPORTED', 'Retain this RD requirement; the current finder has no qualified category workflow for ' + kind + '.'))
        ready = bool(rounded and physical and ports and sides and supported and
                     all(s['design_flow_m3_s'] is not None for s in sides) and
                     all(p['nominal_nps_in'] is not None and p['pipe_id_m'] is not None for p in ports) and
                     (kind not in THROTTLING or throttling is not None) and
                     (thermal is None or thermal.get('required_capacity_W') is not None))
        requirements.append({'id': 'REQ:' + cid, 'component_id': cid, 'tag': component.get('tag', cid),
            'kind': kind, 'category': category, 'subtype': subtype, 'quantity': 1,
            'pod': component.get('pod'), 'circuit_ids': sorted({p['circuit_id'] for p in ports if p.get('circuit_id')}),
            'ports': ports, 'fluid_sides': sides, 'throttling': throttling, 'thermal_duty': thermal,
            'pump_duty': [deepcopy(pump_screens[(cid, s['circuit_id'])]) for s in sides if (cid, s['circuit_id']) in pump_screens],
            'filtration_um': component.get('filtration_um'), 'functions': deepcopy(component.get('functions', [])),
            'required_material': None, 'required_wetted_materials': None,
            'equipment_envelope_m': deepcopy(component.get('size_m')), 'duty_role': component.get('duty_role'),
            'supported_by_finder': supported, 'ready_for_matching': ready,
            'selection_status': 'CONDITIONAL_SHORTLIST_ONLY' if ready else 'UNRESOLVED',
            'unresolved': unresolved,
            'provenance': {'config_hash': digest, 'component_id': cid, 'edge_ids': [e['id'] for e in own_edges],
                'sizing_schema_version': sizing.get('schema_version'), 'sizing_status': sizing.get('status'),
                'flow_and_size_owner': 'RD generator', 'dimension_basis': sizing.get('dimension_basis'),
                'source_refs': list(sizing.get('sources', {}).values()),
                'component_assumptions': deepcopy(component.get('assumptions', []))}})
    # Candidate decisions can compare requirements independently of coordinates,
    # while the enclosing document remains strictly bound to one applied model.
    for requirement in requirements:
        engineering = {k: v for k, v in requirement.items() if k not in ('provenance', 'tag', 'id', 'component_id')}
        engineering['ports'] = [{k: v for k, v in p.items() if k not in ('direction_outward', 'node_id')}
                                for p in requirement['ports']]
        requirement['duty_fingerprint'] = _digest(engineering)
    return {'schema_version': SCHEMA_VERSION, 'contract': 'rd-equipment-requirements',
        'config_hash': digest, 'graph_schema_version': metadata.get('schema_version'),
        'sizing_hash': _digest(sizing) if calculated else None,
        'ready_for_matching': bool(rounded),
        'preconditions': {'applied_hash_verified': True, 'preliminary_sizing_present': bool(calculated),
            'standard_sizes_applied': bool(rounded), 'dimension_mismatches': dimensions_mismatch,
            'manual_dimensions_preserved': bool(manual_retained and not dimensions_mismatch),
            'dimension_basis': sizing.get('dimension_basis'),
            'geometry_blocking_findings': metadata.get('geometry_diagnostics', {}).get('blocking_failures')},
        'requirements': requirements,
        'summary': {'total': len(requirements), 'ready_for_matching': sum(r['ready_for_matching'] for r in requirements),
            'unsupported': sum(not r['supported_by_finder'] for r in requirements)},
        'scope': 'Headless catalogue requirements after RD duty calculations at applied commercial pipe dimensions. Manual sizes are retained; preliminary mode rounds sizes for the velocity criterion. No catalogue choice, material approval, connection-fit approval, pressure-rating approval or procurement authorization is made here.'}
