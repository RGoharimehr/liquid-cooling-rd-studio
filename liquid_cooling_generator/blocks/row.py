"""Building block 2: one rack row = supply header + return header + N rack branches.

Every rack receives its prescribed design flow. Under that condition the
header flows follow from continuity alone (no network solve):

    supply header segment feeding tee i carries the flow of racks i..N-1.

Each rack has one supply/return path through the headers. The path with the
largest pressure drop is the CRITICAL path; its balancing valve keeps the
minimum allocation. Every other branch's balancing valve takes the difference,
so all paths need the same pressure difference at the row connection.

Arrangements:
  direct_return   return header leaves at the same end as the supply enters.
                  The farthest rack has the longest path.
  reverse_return  return header leaves at the far end and a return leg brings
                  it back to the connection end, so the row still connects at
                  one end. Path lengths are nearly equal.

Header styles:
  constant  every header segment uses the size needed for the full row flow.
  stepped   each segment is sized for its own flow, with reducers between sizes.

Tee losses use preliminary_sizing.DEFAULT_K (screening assumptions):
tee_branch at the branch bore and branch flow where a rack leaves/joins the
header, tee_run at the downstream segment bore and flow where a path passes a
tee. Reducers use the smaller bore. Elevation is ignored: in a closed loop the
supply and return columns cancel; static fill pressure is a separate check.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from standards import CATEGORIES, D, LAYOUT, Param

from blocks.base import BlockResult, ElementResult
from blocks.components import Fitting, Pipe
from blocks.fluid import Fluid
from blocks.rack_branch import RackBranchSpec, build_rack_branch
from blocks.sizing import flow_from_heat, head_m, size_pipe

PSI = 6894.757293168

# OCP Deschutes section 3.1 summary table: "IT dP available (psi) 80-90" at
# 500 GPM IT flow. Applies to a Deschutes CDU only; the lower bound is used.
DESCHUTES_IT_DP_AVAILABLE = Param(80 * PSI, 'Pa', D, '3.1 Technical specification Summary Table',
                                  'recommended',
                                  'IT dP available 80-90 psi at 500 GPM; lower bound used. Deschutes CDU only.')

DEFAULT_PITCH_M = LAYOUT['rack_width_m'].value + LAYOUT['rack_gap_m'].value   # 0.7162 m, OCP Deschutes 18.1/18.3


@dataclass(frozen=True)
class RowSpec:
    branch: RackBranchSpec                 # identical racks along the row
    n_racks: int
    arrangement: str = 'direct_return'     # direct_return | reverse_return
    header: str = 'constant'               # constant | stepped
    category: str = 'tcs_row_header'
    velocity_cap_m_s: Optional[float] = None
    rack_pitch_m: float = DEFAULT_PITCH_M
    feed_length_m: float = 5.0             # ASSUMPTION: row connection to first tee
    header_isolation_valves: bool = True
    available_dp: Optional[Param] = None   # e.g. DESCHUTES_IT_DP_AVAILABLE
    name: str = 'Row A'

    def validate(self):
        if type(self.n_racks) is not int or self.n_racks < 1:
            raise ValueError('n_racks must be a positive integer')
        if self.arrangement not in ('direct_return', 'reverse_return'):
            raise ValueError(f'Unknown arrangement {self.arrangement!r}')
        if self.header not in ('constant', 'stepped'):
            raise ValueError(f'Unknown header style {self.header!r}')
        if self.rack_pitch_m <= 0 or self.feed_length_m < 0:
            raise ValueError('rack_pitch_m must be positive and feed_length_m nonnegative')


def _segments(spec: RowSpec, q: float):
    """Header segments as (id, length, flow). Supply S0..S{N-1}; return R*."""
    n, p = spec.n_racks, spec.rack_pitch_m
    seg = {}
    seg['S0'] = (spec.feed_length_m, n * q)
    for i in range(1, n):
        seg[f'S{i}'] = (p, (n - i) * q)
    if spec.arrangement == 'direct_return':
        seg['R0'] = (spec.feed_length_m, n * q)               # tee 0 -> row return connection
        for i in range(1, n):
            seg[f'R{i}'] = (p, (n - i) * q)                   # tee i -> tee i-1
    else:
        for i in range(n - 1):
            seg[f'R{i}'] = (p, (i + 1) * q)                   # tee i -> tee i+1
        seg['RL'] = (spec.feed_length_m + (n - 1) * p, n * q)  # far end back to connection end
    return seg


def _paths(spec: RowSpec):
    """For rack k: supply segments, return segments, supply run tees, return run tees.
    Run tees are given as the segment downstream of the tee (its flow and bore)."""
    n = spec.n_racks
    out = []
    for k in range(n):
        sup = [f'S{i}' for i in range(k + 1)]
        sup_run = [f'S{i+1}' for i in range(k)]                # passing tees 0..k-1
        if spec.arrangement == 'direct_return':
            ret = [f'R{i}' for i in range(k, -1, -1)]
            ret_run = [f'R{i}' for i in range(k - 1, -1, -1)]  # passing tees k-1..0
        else:
            ret = [f'R{i}' for i in range(k, n - 1)] + ['RL']
            ret_run = [f'R{j}' if j < n - 1 else 'RL' for j in range(k + 1, n)]  # passing tees k+1..N-1
        out.append((sup, ret, sup_run, ret_run))
    return out


def build_row(spec: RowSpec, fluid: Fluid) -> BlockResult:
    spec.validate()
    n = spec.n_racks
    rack = flow_from_heat(spec.branch.heat_W, spec.branch.delta_T_max_K, fluid)
    q = rack.flow_m3_s
    row = rack.scaled(n)
    rough = CATEGORIES[spec.category].roughness_m.value
    seg = _segments(spec, q)

    # ---- header sizing
    full = size_pipe(row.flow_m3_s, spec.category, spec.velocity_cap_m_s)
    size = {sid: (full if spec.header == 'constant' else size_pipe(f, spec.category, spec.velocity_cap_m_s))
            for sid, (_, f) in seg.items()}
    bore = {sid: s['id_m'] for sid, s in size.items()}

    # ---- loss of each shared header element, evaluated once
    cache: dict = {}

    def pipe(sid):
        key = ('pipe', sid)
        if key not in cache:
            length, flow = seg[sid]
            cache[key] = Pipe(f'{spec.name}-{sid}', length, rough).evaluate(flow, fluid, bore[sid])
        return cache[key]

    def run_tee(side, sid):
        key = ('run', side, sid)
        if key not in cache:
            cache[key] = Fitting(f'{spec.name}-{side}TEE-run@{sid}', 'tee_run').evaluate(seg[sid][1], fluid, bore[sid])
        return cache[key]

    def reducer(a, b):
        key = ('red', a, b)
        if key not in cache:
            small = a if bore[a] < bore[b] else b
            cache[key] = Fitting(f'{spec.name}-RED {a}/{b}', 'reducer').evaluate(seg[small][1], fluid, bore[small])
        return cache[key]

    def iv_segment(side):
        return 'S0' if side == 'S' else ('R0' if spec.arrangement == 'direct_return' else 'RL')

    def header_iv(side):
        key = ('iv', side)
        if key not in cache:
            sid = iv_segment(side)
            cache[key] = Fitting(f'{spec.name}-IV-{side}', 'isolation_valve').evaluate(seg[sid][1], fluid, bore[sid])
        return cache[key]

    # Branch geometry is identical for every rack; size it once for its bore.
    probe = build_rack_branch(replace(spec.branch, tag='probe'), fluid)
    b_bore = probe.pipes[0]['id_m']

    def branch_tee(side, k):
        return Fitting(f'{spec.name}-{side}TEE{k+1:02d}-branch', 'tee_branch').evaluate(q, fluid, b_bore)

    def path_header(k, sup, ret, sup_run, ret_run):
        before, after = [], []
        if spec.header_isolation_valves:
            before.append(header_iv('S'))
        for i, sid in enumerate(sup):
            before.append(pipe(sid))
            if i + 1 < len(sup) and bore[sup[i + 1]] != bore[sid]:
                before.append(reducer(sid, sup[i + 1]))
        before += [run_tee('S', sid) for sid in sup_run]
        before.append(branch_tee('S', k))
        after.append(branch_tee('R', k))
        after += [run_tee('R', sid) for sid in ret_run]
        for i, sid in enumerate(ret):
            after.append(pipe(sid))
            if i + 1 < len(ret) and bore[ret[i + 1]] != bore[sid]:
                after.append(reducer(sid, ret[i + 1]))
        if spec.header_isolation_valves:
            after.append(header_iv('R'))
        return before, after

    paths = _paths(spec)
    headers = [path_header(k, *paths[k]) for k in range(n)]
    header_dp = [sum(e.dp_Pa for e in b + a) for b, a in headers]
    base = [h + probe.dp_Pa for h in header_dp]          # identical known branch part
    critical = max(range(n), key=lambda k: base[k])
    target = base[critical]

    branches = [build_rack_branch(replace(spec.branch, tag=f'{spec.name}-R{k+1:02d}'), fluid,
                                  balancing_extra_Pa=target - base[k]) for k in range(n)]
    path_totals = [header_dp[k] + branches[k].dp_Pa for k in range(n)]
    unknowns = sorted({u for b in branches for u in b.unknowns})
    crit_elements = headers[critical][0] + branches[critical].elements + headers[critical][1]

    # ---- schedules
    pipes = []
    for sid, (length, flow) in seg.items():
        s = size[sid]
        pipes.append({'run': f'{spec.name} header {sid}', 'length_m': length, 'flow_L_min': flow * 60000.,
                      'nominal_size_in': s['nominal_size_in'], 'id_m': s['id_m'],
                      'velocity_m_s': flow / (3.141592653589793 * s['id_m'] ** 2 / 4),
                      'velocity_cap_m_s': s['velocity_cap_m_s'], 'velocity_cap_status': s['velocity_cap_status'],
                      'catalogue': s['catalogue'], 'category': spec.category})
    pipes.append({**probe.pipes[0], 'run': f'{spec.name} rack branches (x{n})'})
    valves = []
    if spec.header_isolation_valves:
        for side in ('S', 'R'):
            e = header_iv(side)
            valves.append({'tag': e.tag, 'kind': 'isolation_valve',
                           'size_nominal_in': size[iv_segment(side)]['nominal_size_in'],
                           'flow_L_min': e.flow_m3_s * 60000., 'dp_kPa': e.dp_Pa / 1000., 'basis': e.basis,
                           'Kv_m3_h': None, 'Cv_US': None})
    for b in branches:
        valves += b.valves

    tees = 2 * n
    accessories = [
        {'item': 'air vent', 'where': 'supply header high point (far end)', 'basis': 'standards.INSTALL vent_at_high_point'},
        {'item': 'air vent', 'where': 'return header high point', 'basis': 'standards.INSTALL vent_at_high_point'},
        {'item': 'drain valve', 'where': 'supply header low point', 'basis': 'project practice; location after routing'},
        {'item': 'drain valve', 'where': 'return header low point', 'basis': 'project practice; location after routing'},
        {'item': 'tee', 'where': f'{tees} header tees (one supply, one return per rack)', 'basis': 'row topology'},
    ]

    checks = []
    for p_ in pipes:
        checks.append({'name': f"velocity {p_['run']}", 'value': p_['velocity_m_s'], 'limit': p_['velocity_cap_m_s'],
                       'unit': 'm/s', 'passed': p_['velocity_m_s'] <= p_['velocity_cap_m_s'] + 1e-12})
    spread = max(path_totals) - min(path_totals)
    checks.append({'name': 'balanced: every path needs the same dp', 'value': spread, 'limit': 1e-6,
                   'unit': 'Pa', 'passed': spread <= 1e-6})
    if spec.available_dp is not None:
        lim = spec.available_dp.value
        complete = not unknowns
        passed = (target <= lim) if complete else (False if target > lim else None)
        checks.append({'name': 'row dp within available CDU differential', 'value': target, 'limit': lim,
                       'unit': 'Pa', 'passed': passed,
                       'source': f'{spec.available_dp.source} {spec.available_dp.clause} ({spec.available_dp.status})',
                       'note': '' if complete else 'Known parts only; rack pressure drop unknown, so a pass cannot be confirmed.'})

    excess = [target - base[k] for k in range(n)]
    assumptions = list(spec.branch.assumptions()) + [
        f'Row feed length {spec.feed_length_m:g} m from the row connection to the first tee (project assumption).',
        f'Rack pitch {spec.rack_pitch_m:.4f} m.',
        'Tee, reducer and isolation-valve K values are preliminary_sizing.DEFAULT_K screening assumptions.',
        'Every rack receives its design flow (prescribed); balancing valves are allocated to make that so.',
    ]
    return BlockResult(
        name=spec.name, kind='rack_row', heat_W=row.heat_W, mass_kg_s=row.mass_kg_s, flow_m3_s=row.flow_m3_s,
        supply_T_C=spec.branch.supply_T_C, return_T_C=spec.branch.supply_T_C + row.delta_T_K,
        delta_T_K=row.delta_T_K, dp_Pa=target, dp_complete=not unknowns, unknowns=unknowns,
        head_m=head_m(target, fluid), elements=crit_elements, pipes=pipes, valves=valves,
        accessories=accessories, children=branches, assumptions=assumptions, checks=checks,
        notes=[f'{spec.arrangement}, {spec.header} header, {n} racks.',
               f'Critical path: rack {critical+1}. Largest balancing excess {max(excess)/1000:.2f} kPa '
               f'(rack {excess.index(max(excess))+1}).',
               'Row return temperature equals the rack return temperature because every rack has the same rise.'])
