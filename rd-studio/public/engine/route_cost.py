"""What a routed network costs, assembled from fields the graph already carries.

Nothing here is new physics. Lengths come from `route_graph()`, bores from
`hydraulics.select_size()`, pressure drops from `hydraulics.loss()`, fitting
counts from the components themselves. This module only prices them, so that a
router has a single number to minimise and a reviewer has a breakdown to argue
with.

Two tiers, deliberately kept apart:

* Priced terms - pipe, fittings, supports and the present value of pump energy.
  These have no weights. If the rate table is right, they are simply money.
* Preference terms - supply/return pairing and the number of corridors opened.
  These carry weights because no rate card prices them, and they are the only
  numbers anyone should be tuning.

The rate table is an ASSUMPTION. This repository holds no pipe, fitting or
labour cost data, so the defaults below are order-of-magnitude placeholders
carrying the same status field the rest of the generator uses for unsourced
values. Replace them with project rates before quoting a saving in currency;
until then the ratios are meaningful and the absolute figures are not.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, asdict
from math import dist

# Installed cost per metre by nominal size, in project currency units.
# Welded carbon steel, insulated, overhead on trapeze - material, fabrication,
# erection and insulation combined. The shape that matters is the exponent: the
# implied cost/diameter exponent across 2-12 in is about 0.94, so cost rises
# slower than bore. Because bore goes as the square root of flow at a fixed
# velocity cap, a trunk carrying n branches costs about n**0.47 rather than n,
# and merging pays. Any exponent below 2.0 preserves that.
PIPE_RATE_PER_M = {
    1.0: 75., 1.25: 85., 1.5: 95., 2.0: 115., 2.5: 140., 3.0: 165., 3.5: 185.,
    4.0: 205., 5.0: 250., 6.0: 295., 8.0: 400., 10.0: 510., 12.0: 620.,
    14.0: 700., 16.0: 800.,
}

# Fitting cost as a multiple of one metre of the same-size pipe, plus a fixed
# make-up charge per joint. Elbows are cheap; branch fittings are not.
FITTING_FACTOR = {
    'elbow': 0.9, 'tee': 2.2, 'reducer': 1.1, 'isolation_valve': 3.2,
    'balancing_valve': 4.0, 'check_valve': 3.6, 'strainer': 5.5,
    'quick_disconnect': 2.0, 'flex_connector': 1.6, 'air_separator': 6.0,
}
FITTING_FIXED = 45.

# Maximum hanger spacing for water service by nominal size, metres.
# ASME B31.1 Table 121.5-1 shape; project spacing governs.
HANGER_SPACING_M = {
    1.0: 2.1, 1.5: 2.7, 2.0: 3.0, 3.0: 3.7, 4.0: 4.3, 6.0: 5.2, 8.0: 5.8,
    10.0: 6.4, 12.0: 7.0, 16.0: 8.2,
}


@dataclass
class Rates:
    """Every price the cost model uses, in one overridable place."""
    pipe_per_m: dict = field(default_factory=lambda: dict(PIPE_RATE_PER_M))
    fitting_factor: dict = field(default_factory=lambda: dict(FITTING_FACTOR))
    fitting_fixed: float = FITTING_FIXED
    hanger_spacing_m: dict = field(default_factory=lambda: dict(HANGER_SPACING_M))
    hanger_base: float = 60.
    hanger_per_inch: float = 25.
    corridor_fixed: float = 900.      # opening a new overhead lane: rail, penetrations, coordination
    electricity_per_kWh: float = 0.11
    operating_hours_per_year: float = 8000.
    horizon_years: int = 10
    discount_rate: float = 0.07
    pump_efficiency: float = 0.70
    weight_unpaired_per_m: float = 40.   # preference, not a price
    status: str = ('ASSUMPTION: placeholder rates. No pipe, fitting or labour cost '
                   'data exists in this repository; replace before quoting currency.')

    def npv_factor(self) -> float:
        r, n = self.discount_rate, self.horizon_years
        if r <= 0:
            return float(n)
        return (1 - (1 + r) ** -n) / r

    def pipe_rate(self, nominal_in: float | None) -> float:
        return _lookup(self.pipe_per_m, nominal_in, default=205.)

    def hanger_spacing(self, nominal_in: float | None) -> float:
        return _lookup(self.hanger_spacing_m, nominal_in, default=4.3)


def _lookup(table: dict, nominal_in: float | None, default: float) -> float:
    if nominal_in is None:
        return default
    keys = sorted(table)
    for k in keys:
        if nominal_in <= k + 1e-9:
            return table[k]
    return table[keys[-1]]


# ---------------------------------------------------------------------------

def _is_transport(comp: dict, services, levels) -> bool:
    return (comp.get('service') in services and comp.get('level') in levels
            and not comp.get('attachment'))


def evaluate(g: dict, rates: Rates | None = None, *,
             services=('FWS', 'CWS', 'TCS'), levels=('main',)) -> dict:
    """Price a graph. Returns a breakdown, never a single unexplained number."""
    rates = rates or Rates()
    nodes = {n['id']: (n.get('xyz_m') or n.get('route_hint_m')) for n in g['nodes']}
    edges_by_comp = defaultdict(list)
    for e in g['edges']:
        edges_by_comp[e['component_id']].append(e)

    per_service = defaultdict(lambda: {'length_m': 0., 'pipe': 0., 'fittings': 0.,
                                       'supports': 0., 'energy_W': 0., 'elbows': 0,
                                       'tees': 0})
    for comp in g['components']:
        if not _is_transport(comp, services, levels):
            continue
        svc = comp['service']
        bucket = per_service[svc]
        nominal = comp.get('nominal_size_in')
        rate = rates.pipe_rate(nominal)
        kind = comp['kind']
        if kind == 'pipe':
            ports = comp.get('ports', [])
            if len(ports) == 2 and all(p in nodes for p in ports):
                length = dist(nodes[ports[0]], nodes[ports[1]])
                bucket['length_m'] += length
                bucket['pipe'] += length * rate
                spacing = rates.hanger_spacing(nominal)
                hangers = max(1, int(length / spacing + 0.999))
                bucket['supports'] += hangers * (rates.hanger_base +
                                                 rates.hanger_per_inch * (nominal or 4.))
        elif kind in rates.fitting_factor:
            bucket['fittings'] += rate * rates.fitting_factor[kind] + rates.fitting_fixed
            if kind == 'elbow':
                bucket['elbows'] += 1
            if kind == 'tee':
                bucket['tees'] += 1
        for e in edges_by_comp[comp['id']]:
            dp = (e.get('straight_dp_Pa') or 0.) + (e.get('fitting_dp_Pa') or 0.)
            q = e.get('design_flow_m3_s') or 0.
            bucket['energy_W'] += dp * q / max(rates.pump_efficiency, 1e-6)

    npv = rates.npv_factor()
    total = {'pipe': 0., 'fittings': 0., 'supports': 0., 'energy_npv': 0.,
             'length_m': 0., 'elbows': 0, 'tees': 0, 'energy_W': 0.}
    services_out = {}
    for svc, b in per_service.items():
        energy_npv = (b['energy_W'] / 1000. * rates.operating_hours_per_year
                      * rates.electricity_per_kWh * npv)
        row = {**b, 'energy_npv': energy_npv,
               'capex': b['pipe'] + b['fittings'] + b['supports']}
        row['total'] = row['capex'] + energy_npv
        services_out[svc] = row
        for k in ('pipe', 'fittings', 'supports', 'length_m', 'elbows', 'tees', 'energy_W'):
            total[k] += b[k]
        total['energy_npv'] += energy_npv
    total['capex'] = total['pipe'] + total['fittings'] + total['supports']
    total['total'] = total['capex'] + total['energy_npv']

    pairing = pairing_report(g, services=services, levels=levels)
    unpaired = sum(v['unpaired_m'] for v in pairing.values())
    total['unpaired_m'] = unpaired
    total['preference_pairing'] = unpaired * rates.weight_unpaired_per_m

    return {
        'rates_status': rates.status,
        'horizon_years': rates.horizon_years,
        'npv_factor': round(npv, 4),
        'by_service': services_out,
        'total': total,
        'pairing': pairing,
        'basis': ('Priced terms use graph lengths, bores and Darcy-Weisbach drops '
                  'already computed by the generator. Energy is zero in manual '
                  'sizing mode because no flow is assigned.'),
    }


def _chains(g, svc, levels):
    """Maximal pipe+elbow runs between real fittings, with their endpoints."""
    nodes = {n['id']: (n.get('xyz_m') or n.get('route_hint_m')) for n in g['nodes']}
    terminals = set()
    for comp in g['components']:
        if comp['kind'] not in ('pipe', 'elbow'):
            terminals.update(comp.get('ports', []))
    parts = [c for c in g['components']
             if c.get('service') == svc and c.get('level') in levels
             and c['kind'] in ('pipe', 'elbow') and len(c.get('ports', [])) == 2
             and all(p in nodes for p in c['ports'])]
    adj = defaultdict(list)
    for c in parts:
        a, b = c['ports']
        adj[a].append((b, c))
        adj[b].append((a, c))
    is_node = lambda p: len(adj[p]) != 2 or p in terminals
    seen, chains = set(), []
    for start in list(adj):
        if not is_node(start):
            continue
        for nxt, first in adj[start]:
            if first['id'] in seen:
                continue
            seen.add(first['id'])
            path, cur = [first], nxt
            while not is_node(cur):
                nxts = [(q, c) for q, c in adj[cur] if c['id'] not in seen]
                if not nxts:
                    break
                q, c = nxts[0]
                seen.add(c['id'])
                path.append(c)
                cur = q
            chains.append((start, cur, path, nodes))
    return chains


def pairing_report(g: dict, *, services=('FWS', 'CWS'), levels=('main',),
                   tolerances=(1.0, 2.0, 3.0), sample_m=0.25) -> dict:
    """How much supply main has its return running alongside it.

    A run is classified as supply or return by the elevation of its own
    endpoints, not segment by segment: the generator offsets the return header by
    `return_elevation_offset_m` throughout, and a run that climbs to cross
    another service is still the run it started as.
    """
    cfg = g.get('metadata', {}).get('config', {})
    z_supply = cfg.get('header_elevation_m', 4.0)
    z_return = z_supply + cfg.get('return_elevation_offset_m', 0.4)
    out = {}
    for svc in services:
        supply, ret = [], []
        for a, b, path, nodes in _chains(g, svc, levels):
            ends = (nodes[a][2], nodes[b][2])
            score = sum(abs(z - z_return) - abs(z - z_supply) for z in ends)
            target = ret if score < 0 else supply
            target.extend((nodes[c['ports'][0]], nodes[c['ports'][1]]) for c in path)
        if not supply or not ret:
            continue
        total = sum(dist(a, b) for a, b in supply)
        paired = {t: 0. for t in tolerances}
        for a, b in supply:
            length = dist(a, b)
            if length < 1e-9:
                continue
            steps = max(2, int(length / sample_m))
            for i in range(steps):
                t = (i + .5) / steps
                p = [a[k] + t * (b[k] - a[k]) for k in range(3)]
                d = min((_point_segment(p, u, v) for u, v in ret), default=1e9)
                for tol in paired:
                    if d <= tol:
                        paired[tol] += length / steps
        out[svc] = {
            'supply_m': round(total, 3),
            'paired_fraction': {str(t): round(paired[t] / total, 4) if total else 0.
                                for t in paired},
            'unpaired_m': round(total - paired[min(tolerances)], 3),
            'tolerance_m': min(tolerances),
        }
    return out


def chain_report(g: dict, *, services=('FWS', 'CWS', 'TCS'), levels=('main',)) -> dict:
    """Routed length against the rectilinear bound, per transport chain.

    The bound is Manhattan distance between the chain's own endpoints. It ignores
    obstacles and the axial approach a collector forces, so it is a floor no
    router can reach, not a target. Reporting it keeps the optimizer honest about
    its own gap instead of letting it claim optimality.
    """
    out = {}
    for svc in services:
        routed = bound = 0.
        rows = []
        for a, b, path, nodes in _chains(g, svc, levels):
            length = sum(dist(nodes[c['ports'][0]], nodes[c['ports'][1]]) for c in path)
            lb = sum(abs(nodes[a][k] - nodes[b][k]) for k in range(3))
            routed += length
            bound += lb
            rows.append({'routed_m': round(length, 3), 'bound_m': round(lb, 3),
                         'elbows': sum(1 for c in path if c['kind'] == 'elbow'),
                         'from_m': [round(x, 2) for x in nodes[a]],
                         'to_m': [round(x, 2) for x in nodes[b]]})
        if rows:
            rows.sort(key=lambda r: -r['routed_m'])
            out[svc] = {'routed_m': round(routed, 2), 'bound_m': round(bound, 2),
                        'excess_m': round(routed - bound, 2),
                        'excess_fraction': round(routed / bound - 1, 4) if bound else 0.,
                        'chains': rows}
    return out


def _point_segment(p, a, b) -> float:
    """Distance from a point to a finite segment; used by the pairing metric."""
    d = [b[k] - a[k] for k in range(3)]
    denom = sum(x * x for x in d)
    t = 0. if denom == 0 else max(0., min(1., sum((p[k] - a[k]) * d[k]
                                                  for k in range(3)) / denom))
    return dist(p, [a[k] + t * d[k] for k in range(3)])
