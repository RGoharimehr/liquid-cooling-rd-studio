"""Building block 1: one rack branch.

Flow path, supply tee on the row header to return tee on the row header:

    isolation valve (S) -> strainer -> supply pipe + elbows -> quick disconnect (S)
    -> rack internal loop -> quick disconnect (R) -> return pipe + elbows
    -> balancing valve -> [control valve] -> isolation valve (R)

The tees themselves belong to the row header and are counted by the row block.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from standards import CATEGORIES

from blocks.base import BlockResult
from blocks.components import AllocatedValve, Equipment, Fitting, Pipe
from blocks.fluid import Fluid
from blocks.sizing import flow_from_heat, head_m, size_pipe


@dataclass(frozen=True)
class RackBranchSpec:
    heat_W: float                         # liquid heat into the coolant at this rack
    delta_T_max_K: float                  # maximum coolant rise across the rack
    supply_T_C: float                     # coolant supply temperature at the rack
    category: str = 'tcs_rack_branch'     # pipe category -> catalogue, cap, roughness
    velocity_cap_m_s: Optional[float] = None   # None = category cap
    supply_length_m: float = 3.0          # ASSUMPTION: header tee to rack, straight length
    return_length_m: float = 3.0          # ASSUMPTION
    supply_elbows: int = 2                # ASSUMPTION
    return_elbows: int = 2                # ASSUMPTION
    strainer: bool = True                 # filtration at the rack (CloudScale App. G guidance)
    rack_dp_Pa: Optional[float] = None    # rack internal loop at rated flow; None = UNKNOWN
    rack_rated_flow_m3_s: Optional[float] = None
    rack_dp_source: str = ''
    balancing_valve_min_dp_Pa: float = 10_000.   # ASSUMPTION: allocation at the critical branch
    control_valve_dp_Pa: Optional[float] = None  # None = no control valve in the branch
    tag: str = 'R01'

    def assumptions(self) -> list:
        out = [f'Branch straight lengths {self.supply_length_m:g} m supply / {self.return_length_m:g} m return '
               f'with {self.supply_elbows}/{self.return_elbows} elbows (project assumption until routed).',
               f'Balancing valve minimum allocation {self.balancing_valve_min_dp_Pa/1000:g} kPa at the critical '
               'branch (project assumption; vendor minimum measuring/signal differential to be confirmed).']
        if self.control_valve_dp_Pa is not None:
            out.append(f'Control valve allocation {self.control_valve_dp_Pa/1000:g} kPa (project input; '
                       'authority to be reviewed against the branch).')
        if self.rack_dp_Pa is None:
            out.append('Rack internal pressure drop not supplied: branch total is incomplete.')
        return out


def build_rack_branch(spec: RackBranchSpec, fluid: Fluid, *, balancing_extra_Pa: float = 0.) -> BlockResult:
    """Size the branch from heat and rise, then evaluate every loss at the
    design flow. `balancing_extra_Pa` is added to the balancing valve by the
    row block so that every parallel path needs the same pressure difference."""
    if balancing_extra_Pa < 0:
        raise ValueError('balancing_extra_Pa must be nonnegative')
    demand = flow_from_heat(spec.heat_W, spec.delta_T_max_K, fluid)
    q = demand.flow_m3_s
    pipe = size_pipe(q, spec.category, spec.velocity_cap_m_s)
    bore = pipe['id_m']
    rough = CATEGORIES[spec.category].roughness_m.value
    t = spec.tag

    path = [Fitting(f'{t}-IV-S', 'isolation_valve')]
    if spec.strainer:
        path.append(Fitting(f'{t}-STR', 'strainer'))
    path.append(Pipe(f'{t}-P-S', spec.supply_length_m, rough))
    path += [Fitting(f'{t}-EL-S{i+1}', 'elbow') for i in range(spec.supply_elbows)]
    path.append(Fitting(f'{t}-QD-S', 'quick_disconnect'))
    path.append(Equipment(f'{t}-RACK', 'rack_load', spec.rack_dp_Pa, spec.rack_rated_flow_m3_s, spec.rack_dp_source))
    path.append(Fitting(f'{t}-QD-R', 'quick_disconnect'))
    path.append(Pipe(f'{t}-P-R', spec.return_length_m, rough))
    path += [Fitting(f'{t}-EL-R{i+1}', 'elbow') for i in range(spec.return_elbows)]
    bal_dp = spec.balancing_valve_min_dp_Pa + balancing_extra_Pa
    path.append(AllocatedValve(f'{t}-BV', 'balancing_valve', bal_dp,
                               'Allocated: minimum allocation + row balancing excess'))
    if spec.control_valve_dp_Pa is not None:
        path.append(AllocatedValve(f'{t}-CV', 'control_valve', spec.control_valve_dp_Pa,
                                   'Allocated control-valve pressure drop (project input)'))
    path.append(Fitting(f'{t}-IV-R', 'isolation_valve'))

    elements = [c.evaluate(q, fluid, bore) for c in path]
    known = sum(e.dp_Pa for e in elements if e.dp_Pa is not None)
    unknowns = [e.tag for e in elements if e.dp_Pa is None]
    valves = [{'tag': e.tag, 'kind': e.kind, 'size_nominal_in': pipe['nominal_size_in'],
               'flow_L_min': e.flow_m3_s * 60000., 'dp_kPa': e.dp_Pa / 1000.,
               'basis': e.basis, 'Kv_m3_h': e.extra.get('Kv_m3_h'), 'Cv_US': e.extra.get('Cv_US')}
              for e in elements if 'valve' in e.kind]
    rise = demand.delta_T_K
    return BlockResult(
        name=f'Rack branch {t}', kind='rack_branch', heat_W=demand.heat_W,
        mass_kg_s=demand.mass_kg_s, flow_m3_s=q, supply_T_C=spec.supply_T_C,
        return_T_C=spec.supply_T_C + rise, delta_T_K=rise,
        dp_Pa=known, dp_complete=not unknowns, unknowns=unknowns, head_m=head_m(known, fluid),
        elements=elements,
        pipes=[{'run': f'{t} branch (supply and return)', 'flow_L_min': q * 60000., **pipe}],
        valves=valves,
        assumptions=spec.assumptions(),
        notes=['Flow is prescribed by heat and maximum rise; this is not a solved operating point.'])
