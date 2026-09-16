"""What needs a human's eye, anchored to the component it belongs to.

Every diagnostic in this generator already knows which component it concerns,
but they are scattered across geometry checks, sizing findings, connectivity
scenarios and equipment requirements. That is fine for a report and useless for
a model you are looking at: you cannot see which box in the 3D view is the one
missing a pressure rating, or the one whose pipe is undersized.

This module rolls those findings up per component, in categories a reviewer can
act on, so the viewer can colour the object rather than the reader hunting
through JSON:

    missing_information  a required input or vendor datum is unassigned
    undersized           the requirement exceeds what has been selected
    oversized            a smaller listed size would still meet the criterion
    clash                geometry overlaps something it must not
    unserved             a load loses its path or its duty cannot be allocated

Nothing here computes anything new. A flag that appears in this module must
already exist as a finding somewhere else, or it would be an opinion.
"""
from collections import defaultdict

SEVERITY_ORDER = {'blocking': 0, 'review': 1, 'information': 2}
# Sizing findings, mapped to what a reviewer should do about them.
SIZING_CODES = {
    'MANUAL_VELOCITY_LIMIT_EXCEEDED': ('undersized', 'review'),
    'NO_CATALOGUE_SIZE': ('undersized', 'blocking'),
    'K_REFERENCE_IMPLAUSIBLE': ('missing_information', 'review'),
    'CDU_RATING_EXCEEDED': ('undersized', 'review'),
    'POD_SPARES_UNRESOLVED': ('unserved', 'blocking'),
    'FLOW_ASSIGNMENT_UNRESOLVED': ('unserved', 'review'),
    'AIR_COIL_PERFORMANCE_UNRESOLVED': ('missing_information', 'information'),
    'CONDENSER_HEAT_LOWER_BOUND': ('missing_information', 'information'),
    'NO_RACK_DEMAND': ('unserved', 'review'),
    'AIR_LOAD_UNROUTED': ('unserved', 'review'),
}
# Equipment-requirement gaps worth showing in the model. The rest are contract
# boilerplate that would flag every component and so tell a reviewer nothing.
REQUIREMENT_CODES = {
    'PRESSURE_RATING_UNASSIGNED', 'FILTRATION_UNASSIGNED', 'THROTTLING_DUTY_UNASSIGNED',
    'THERMAL_DUTY_UNASSIGNED', 'FLOW_UNASSIGNED', 'QD_MATING_INTERFACE_UNASSIGNED',
    'POD_UNAVAILABLE_IN_REQUESTED_OUTAGE',
}


def _smaller_size_would_fit(family, catalogues):
    """True when a smaller listed bore still meets the family's velocity cap."""
    selection = family.get('selection')
    if not selection or not family.get('design_flow_m3_s'):
        return None
    table, _ = catalogues[family['material']]
    smaller = [row for row in table if row[0] < selection['nominal_size_in']]
    if not smaller:
        return None
    from math import pi
    nominal, od, wall = smaller[-1]
    bore = (od - 2 * wall) * .0254
    velocity = 4 * family['design_flow_m3_s'] / (pi * bore ** 2)
    return (nominal, velocity) if velocity <= family['velocity_cap_m_s'] + 1e-9 else None


# Findings that describe a pipe family rather than any one fitting in it.
FAMILY_CODES = ('MANUAL_VELOCITY_LIMIT_EXCEEDED', 'K_REFERENCE_IMPLAUSIBLE')


def collect(graph, config=None):
    from hydraulics import CATALOGUES
    metadata = graph.get('metadata', {})
    sizing = metadata.get('preliminary_sizing') or {}
    components = {c['id'] for c in graph.get('components', [])}
    owner = {e['id']: e['component_id'] for e in graph.get('edges', [])}
    flags = defaultdict(list)
    systemic = []

    def add(component_id, code, category, severity, detail, source, resolved_by=None):
        if component_id in components:
            entry = {'code': code, 'category': category, 'severity': severity,
                     'detail': detail, 'source': source}
            if resolved_by:
                entry['resolved_by'] = resolved_by
            flags[component_id].append(entry)

    # A finding that names a pipe family belongs to the family, not to each of
    # its segments: one nominal size clears every one of them at once. A velocity
    # exceedance is the obvious case; an implausible K reference is the same gap
    # seen from the fitting side, and on a water-cooled RD113 in manual mode it
    # was landing on 106 elbows, tees and valves individually.
    by_family = defaultdict(list)
    for item in sizing.get('unresolved', []):
        code = item.get('code')
        if code not in SIZING_CODES:
            continue
        category, severity = SIZING_CODES[code]
        target = item.get('component_id') or owner.get(item.get('edge_id', ''))
        if code in FAMILY_CODES and item.get('family'):
            by_family[(code, item['family'])].append((target, item))
        elif target:
            add(target, code, category, severity, item.get('detail') or item.get('reason', ''), 'preliminary_sizing')
    families = {f['family']: f for f in sizing.get('size_families', [])}
    for (code, name), items in by_family.items():
        ids = sorted({t for t, _ in items if t in components})
        family = families.get(name, {})
        category, severity = SIZING_CODES[code]
        systemic.append({'code': code, 'category': category,
            'severity': severity, 'scope': f'pipe family {name}', 'components': len(ids),
            'component_ids': ids, 'detail': items[0][1]['detail'],
            'clears_when': f"{family.get('parameter', name + '_nominal_in')} is increased, "
                           f"or Preliminary sizing selects the bore."})

    for item in sizing.get('cdu_selection', []):
        for row in item['checks']:
            if row['status'] == 'SHORT':
                add(item['component_id'], 'CDU_RATING_SHORT', 'undersized', 'review',
                    f"Required {row['quantity']} {row['required']:,.0f} exceeds the published "
                    f"{row['published']:,.0f} by {-row['margin_fraction']:.1%}.", 'cdu_selection')
            elif row['status'] == 'UNASSIGNED':
                add(item['component_id'], 'CDU_RATING_UNASSIGNED', 'missing_information', 'information',
                    f"No published {row['quantity']} entered for the selected unit, so it cannot be "
                    f"checked against the required {row['required'] or 0:,.0f}.", 'cdu_selection')

    # Oversizing belongs to the pipe family, not to each of its 300 segments.
    # It is only possible where a bore was chosen by hand; the catalogue
    # recommendation is the smallest that fits by construction.
    if sizing.get('dimension_basis') == 'manual_catalogue':
        from math import pi
        for family in sizing.get('size_families', []):
            smaller = _smaller_size_would_fit(family, CATALOGUES)
            if not smaller:
                continue
            nominal, velocity = smaller
            actual = 4 * family['design_flow_m3_s'] / (pi * family['selection']['id_m'] ** 2)
            systemic.append({'code': 'OVERSIZED_FOR_CRITERION', 'category': 'oversized',
                'severity': 'information', 'scope': f"pipe family {family['family']}",
                'components': len(family['edge_ids']),
                'component_ids': sorted({owner[e] for e in family['edge_ids'] if e in owner}),
                'detail': f"NPS {family['selection']['nominal_size_in']:g} carries this duty at {actual:.2f} m/s; "
                          f"NPS {nominal:g} would still meet the {family['velocity_cap_m_s']:g} m/s limit at "
                          f"{velocity:.2f} m/s.",
                'clears_when': f"{family['parameter']} is reduced, or Preliminary sizing selects the bore."})

    for check in metadata.get('geometry_diagnostics', {}).get('checks', []):
        if check.get('status') != 'FAIL':
            continue
        # `actual` carries whatever the check measured: a list of component ids,
        # a list of {node, components} records, or a bare number for a check that
        # is about a quantity rather than an object.
        actual = check.get('actual')
        for entry in actual if isinstance(actual, (list, tuple)) else []:
            names = [entry] if isinstance(entry, str) else \
                    list(entry) if isinstance(entry, (list, tuple)) else \
                    list(entry.get('components', [])) if isinstance(entry, dict) else []
            for name in names:
                add(name, 'GEOMETRY_FINDING', 'clash', 'blocking', check['check'], 'geometry_diagnostics')

    for scenario in metadata.get('connectivity_scenarios', {}).get('scenarios', []):
        if not scenario.get('required_design_check'):
            continue
        for rack in scenario.get('unconnected_compute_racks', []):
            add(rack, 'NO_CDU_PATH', 'unserved', 'blocking',
                f"Loses its path to an active CDU in scenario {scenario['name']}.", 'connectivity_scenarios')

    for requirement in metadata.get('equipment_requirements', {}).get('requirements', []):
        for issue in requirement.get('unresolved', []):
            if issue['code'] in REQUIREMENT_CODES:
                add(requirement['component_id'], issue['code'], 'missing_information', 'information',
                    issue['detail'], 'equipment_requirements', issue.get('resolved_by'))

    for screen in sizing.get('pump_screens', []):
        if str(screen.get('status', '')).startswith('INCOMPLETE'):
            add(screen['component_id'], screen['status'], 'missing_information', 'review',
                screen.get('outage_limitation') or screen.get('static_head_basis', ''), 'pump_screens')

    # A finding that lands on every component of its kind is one project-level
    # gap, not N component problems. Flagging 500 objects for a single missing
    # input buries the handful that are genuinely specific.
    kinds = defaultdict(set)
    for component in graph.get('components', []):
        kinds[component['kind']].add(component['id'])
    kind_of = {cid: k for k, ids in kinds.items() for cid in ids}
    hits = defaultdict(set)
    for cid, items in flags.items():
        for item in items:
            hits[(item['code'], kind_of.get(cid))].add(cid)
    blanket = set()
    for (code, kind), found in hits.items():
        population = kinds.get(kind, set())
        if len(population) > 1 and found >= population:
            blanket.add((code, kind))
            # Take the representative in sorted order. Iterating the set directly
            # picked an arbitrary component, and because a detail string can carry
            # that component's own numbers the same design serialised differently
            # from run to run.
            sample = flags[min(found)]
            item = next(x for x in sample if x['code'] == code)
            detail, category, severity = item['detail'], item['category'], item['severity']
            # Where the finding named the input that closes it, say so. "One
            # project input resolves all of them" is true and useless: a reviewer
            # looking at a flagged object needs the name of the thing to set.
            clears_when = item.get('resolved_by') or 'One project input or vendor datum resolves all of them.'
            systemic.append({'code': code, 'category': category, 'severity': severity,
                'scope': f'every {kind}', 'components': len(found), 'representative': min(found),
                'component_ids': sorted(found), 'detail': detail,
                'clears_when': clears_when})
    for cid in list(flags):
        flags[cid] = [x for x in flags[cid] if (x['code'], kind_of.get(cid)) not in blanket]
        if not flags[cid]:
            del flags[cid]

    ranked = {}
    for cid, items in flags.items():
        items.sort(key=lambda x: (SEVERITY_ORDER[x['severity']], x['category']))
        ranked[cid] = {'worst_severity': items[0]['severity'],
                       'categories': sorted({x['category'] for x in items}),
                       'flags': items}
    counts = defaultdict(int)
    for entry in ranked.values():
        for category in entry['categories']:
            counts[category] += 1
    systemic.sort(key=lambda x: (SEVERITY_ORDER[x['severity']], -x['components']))
    return {'components': ranked, 'systemic': systemic,
            'summary': {'flagged_components': len(ranked), 'systemic_findings': len(systemic),
                        'by_category': dict(sorted(counts.items())),
                        'by_severity': {s: sum(1 for e in ranked.values() if e['worst_severity'] == s)
                                        for s in SEVERITY_ORDER}},
            'categories': {'missing_information': 'A required input or vendor datum is unassigned.',
                           'undersized': 'The requirement exceeds what has been selected.',
                           'oversized': 'A smaller listed size would still meet the criterion.',
                           'clash': 'Geometry overlaps something it must not.',
                           'unserved': 'A load loses its path, or its duty cannot be allocated.'},
            'scope': 'A roll-up of findings this model already produces, anchored to the component each '
                     'concerns. It computes nothing new and adds no judgement of its own.'}
