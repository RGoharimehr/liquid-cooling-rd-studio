"""Bore per run, not per family: size a pipe for what it actually carries.

One bore per family gave every main the same size, so the RD113 facility-water
header ran NPS 16 from the plant to the last CDU tee even where it carried one
CDU's duty, and a NPS 2 branch teed straight into it. This partitions the network
into runs - maximal stretches that must share a bore - sizes each from what
passes through it, and reports the reduction each fitting now makes.

A run is broken only at a reducer or a tee, because those are the two fittings
that can change a bore: a concentric or eccentric reducer between two runs, and
an ASME B16.9 reducing tee, designated run x run x branch. Everything else - pipe,
elbow, valve, strainer, quick disconnect, flexible connector - carries one bore
from end to end, so its ports are welded into the same run.

A run's duty is the duty envelope `preliminary_sizing` derived for its own edges,
which already carries the redundancy uplift a main section takes when a unit it
shares a header with goes offline, the cap at its own circuit total, and the
branch envelopes that stop a rack branch being sized for one rack while its
neighbour is offline. This module decides which edges share a bore, not what
that bore has to carry.

A node between two fittings is not a run: it has no pipe of its own. It takes the
larger of the bores either side, so the step happens inside the fitting built to
make it rather than in the gap between two of them.
"""
from collections import defaultdict
from hydraulics import CATALOGUES, NoCatalogueSize, select_size

# Fittings that may hold two bores at once. Everything else is one bore end to
# end: an elbow cannot reduce, and neither can a valve.
REDUCING = ('reducer', 'tee')


def _classes(graph):
    """Union the ports that have to share a bore, and return root per node."""
    parent = {}

    def find(node):
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for comp in graph['components']:
        if comp.get('attachment') or comp.get('size_m'):
            continue
        ports = comp.get('ports', [])
        for node in ports:
            find(node)
        if comp['kind'] in REDUCING:
            continue
        for node in ports[1:]:
            a, b = find(ports[0]), find(node)
            if a != b:
                parent[a] = b
    return find


def resolve(graph, config, estimates, families):
    """Return {edge_id: nominal}, {component_id: {node: nominal}} and the runs.

    `estimates` is preliminary_sizing's per-edge result and `families` its
    per-family selection, which stays the fallback wherever a run cannot be
    sized from the catalogue.
    """
    find = _classes(graph)
    by_edge = {item['edge_id']: item for item in estimates}
    components = {comp['id']: comp for comp in graph['components']}
    # Each circuit's own envelope, for reporting what the runs were bounded by.
    circuit_cap = defaultdict(float)
    for item in estimates:
        circuit_cap[item.get('circuit_id')] = max(circuit_cap[item.get('circuit_id')],
                                                  item.get('design_flow_m3_s') or 0.)
    runs = defaultdict(lambda: {'flow_m3_s': 0., 'cap_m_s': [], 'materials': set(), 'edge_ids': []})
    transitions = defaultdict(list)

    def demand(item):
        """What passes through this edge. preliminary_sizing owns the envelope,
        including the redundancy uplift a main section carries."""
        return abs(item.get('flow_m3_s') or 0.)

    for edge in graph['edges']:
        item = by_edge.get(edge['id'])
        if edge.get('internal') or not item or item.get('flow_m3_s') is None:
            continue
        a, b = find(edge['from_node']), find(edge['to_node'])
        through = demand(item)
        if a != b:
            # A transition edge says what passes through the fitting, and nothing
            # about the level on either side of it.
            for side in (a, b):
                run = runs[side]
                run['flow_m3_s'] = max(run['flow_m3_s'], through)
                run['cap_m_s'].append(edge.get('velocity_cap_m_s') or 3.)
                run['materials'].add(edge.get('material'))
            transitions[edge['component_id']].append(edge['id'])
            continue
        run = runs[a]
        # A run's own edges bring their level's duty envelope; a transition edge
        # carries continuity across a fitting and nothing about the other side.
        through = max(through, item.get('design_flow_m3_s') or 0.)
        run['flow_m3_s'] = max(run['flow_m3_s'], through)
        run['cap_m_s'].append(edge.get('velocity_cap_m_s') or 3.)
        run['materials'].add(edge.get('material'))
        run['edge_ids'].append(edge['id'])

    neighbours = defaultdict(set)
    for comp in graph['components']:
        if comp['kind'] not in REDUCING:
            continue
        roots = [find(node) for node in comp.get('ports', [])]
        for one in roots:
            for other in roots:
                if one != other:
                    neighbours[one].add(other)

    bore = {}
    unsized = []
    for root, run in runs.items():
        if not run['edge_ids']:
            continue
        material = next(iter(run['materials']), None)
        try:
            bore[root] = select_size(run['flow_m3_s'], material, min(run['cap_m_s']))['nominal_size_in']
        except (NoCatalogueSize, KeyError) as exc:
            unsized.append({'run': root, 'reason': str(exc), 'flow_m3_s': run['flow_m3_s']})
    # Fitting-to-fitting nodes have no pipe of their own; they follow the larger
    # side so the step stays inside the fitting that was built to make it.
    for _ in range(len(runs)):
        settled = True
        for root, run in runs.items():
            if run['edge_ids'] or root in bore:
                continue
            near = [bore[other] for other in neighbours[root] if other in bore]
            if near:
                bore[root] = max(near)
                settled = False
        if settled:
            break

    material_of = {root: next(iter(run['materials']), None) for root, run in runs.items()}

    def dimensions(root):
        """The run's bore in the run's own material, so a port is never quoted a
        size its own catalogue does not list."""
        size, material = bore.get(root), material_of.get(root)
        table = CATALOGUES.get(material, (None, None))[0]
        match = next((x for x in table if x[0] == size), None) if table else None
        if not match:
            return None
        nominal, od, wall = match
        return {'nominal_size_in': nominal, 'od_m': od * .0254, 'id_m': (od - 2 * wall) * .0254,
                'wall_m': wall * .0254, 'material': material}

    fallback = {}
    for item in estimates:
        family = families.get(item.get('size_family'))
        if family and family.get('selection'):
            fallback[item['edge_id']] = family['selection']['nominal_size_in']
    per_edge = {}
    per_port = defaultdict(dict)
    for comp in graph['components']:
        for node in comp.get('ports', []):
            dims = dimensions(find(node))
            if dims:
                per_port[comp['id']][node] = dims
    for edge in graph['edges']:
        if edge.get('internal') or edge['id'] not in by_edge:
            continue
        table = CATALOGUES.get(edge.get('material'), (None, None))[0]
        listed = {x[0] for x in table} if table else set()
        sizes = [bore.get(find(node)) for node in (edge['from_node'], edge['to_node'])]
        # A transition edge is reported at its larger end, but only at a size its
        # own material is made in: a copper branch off a steel header is quoted in
        # copper, and the two bores live on the reducer's ports.
        choices = [size for size in sizes if size in listed]
        if choices:
            per_edge[edge['id']] = max(choices)
        elif edge['id'] in fallback:
            per_edge[edge['id']] = fallback[edge['id']]
    report = [{'run': root, 'flow_m3_s': run['flow_m3_s'], 'nominal_size_in': bore.get(root),
               'velocity_cap_m_s': min(run['cap_m_s']) if run['cap_m_s'] else None,
               'material': next(iter(run['materials']), None), 'edges': len(run['edge_ids'])}
              for root, run in runs.items() if run['edge_ids']]
    return {'edge_sizes': per_edge, 'port_sizes': dict(per_port), 'runs': report, 'unsized': unsized,
            'circuit_envelope_m3_s': dict(circuit_cap),
            'basis': 'One bore per run, from the largest duty envelope on the run. A run is broken only '
                     'at a reducer or a tee, the two fittings that can hold two bores.',
            'scope': 'Screening bores on prescribed flows. No balanced network solution, and no check '
                     'that a listed reducing tee exists in the selected run x run x branch combination.'}
