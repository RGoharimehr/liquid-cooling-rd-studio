"""Explicit CDU outage cases for independent pods; no capacity verification."""
from itertools import combinations


def attach(graph, config, row_pods, cdu_pods):
    units = list(range(1, config.cdu_count + 1))
    couplings = {int(x['id'].split('-')[-1]): x for x in graph['couplings']}
    pod_units = {pod: [unit for unit in units if cdu_pods[unit - 1] == pod]
                 for pod in range(1, config.pod_count + 1)}
    pod_heat = {pod: row_pods.count(pod) * config.racks_per_row * config.rack_power_W * config.liquid_fraction
                for pod in pod_units}

    def case(name, kind, offline):
        offline = set(offline)
        active = [unit for unit in units if unit not in offline]
        states = {}
        for pod, assigned in pod_units.items():
            surviving = [unit for unit in assigned if unit in active]
            states[f'TCS-P{pod:02}'] = {
                'pod': pod, 'installed_cdus': assigned, 'active_cdus': surviving,
                'offline_cdus': [unit for unit in assigned if unit in offline],
                'liquid_heat_W': pod_heat[pod],
                'allocated_heat_W': pod_heat[pod] if surviving else 0.,
                'unserved_heat_W': 0. if surviving else pod_heat[pod],
                'allocation_per_active_cdu_W': pod_heat[pod] / len(surviving) if surviving else None,
                'availability_status': 'AVAILABLE_UNVERIFIED' if surviving else 'UNAVAILABLE'}
        return {
            'name': name, 'kind': kind, 'active_cdus': active, 'offline_cdus': sorted(offline),
            'closed_components': sorted({cid for unit in offline for cid in couplings[unit]['isolation_components']}),
            'disabled_components': sorted({cid for unit in offline for cid in couplings[unit]['component_ids']}),
            'pod_states': states,
            'unavailable_pods': [state['pod'] for state in states.values() if not state['active_cdus']],
            'unserved_heat_W': sum(state['unserved_heat_W'] for state in states.values()),
            'capacity_status': 'NOT_EVALUABLE', 'operational_redundancy_proven': False,
            'control_assumption': 'Equal load allocation only within each surviving pod. No load transfer between independent pods; capacity, pressure and controls are unverified.'}

    alternatives = list(combinations(units, config.redundancy))
    # Keep the established design name for a deterministic representative case.
    # Prefer a balanced outage allocation that leaves a CDU in every pod where
    # possible. Every alternative remains a required design check below.
    nominal = min(alternatives, key=lambda offline: (
        sum(all(unit in offline for unit in assigned) for assigned in pod_units.values()),
        max(sum(unit in offline for unit in assigned) / len(assigned) for assigned in pod_units.values()),
        tuple(-unit for unit in offline)))
    scenarios = [case('all_online', 'operating', ())]
    for offline in [nominal] + [value for value in alternatives if value != nominal]:
        name = 'design' if offline == nominal else 'duty_' + '_'.join(map(str, offline))
        scenarios.append(case(name, 'design', offline))
    graph['scenarios'] = scenarios
    for unit, coupling in couplings.items():
        circuit = f'TCS-P{cdu_pods[unit - 1]:02}'
        coupling['scenario_heat_W'] = {
            scenario['name']: scenario['pod_states'][circuit]['allocation_per_active_cdu_W']
            if unit in scenario['active_cdus'] else 0. for scenario in scenarios}
        coupling['heat_basis'] = 'All-online heat allocation within the assigned pod; scenario_heat_W excludes offline CDUs. Unserved pod heat is reported on each scenario; capacity is unverified.'
    for component in graph['components']:
        if component['kind'] == 'cdu':
            unit = component['cdu']
            component['duty_role'] = 'duty' if unit in scenarios[1]['active_cdus'] else 'spare'
            component['duty_role_basis'] = 'Deterministic representative design scenario; every requested outage combination is evaluated.'
    graph['metadata']['redundancy'] = {
        'total_units': config.cdu_count, 'duty_units': config.cdu_count - config.redundancy,
        'spare_units': config.redundancy, 'requested_simultaneous_outages': config.redundancy,
        'outage_scope': 'global_across_independent_pods',
        'design_scenario_count': len(alternatives), 'nominal_design_scenario': 'design',
        'nominal_spare_cdus': list(nominal),
        'pods': {f'TCS-P{pod:02}': {'installed_cdus': assigned,
            'minimum_active_cdus': max(0, len(assigned) - config.redundancy),
            'connectivity_outage_limit': len(assigned) - 1} for pod, assigned in pod_units.items()},
        'scope': 'Requested simultaneous CDU outages across all independent pods. Not a per-pod N+R rating or proof of capacity/operational redundancy; common headers remain shared failure points.'}
