"""Components that sit in a block's flow path, each with one pressure-loss model.

Each loss is counted once (SIZING_BASIS.md section 4): a valve is either a
generic K (isolation, check) or an ALLOCATED pressure drop (balancing,
control), never both.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from preliminary_sizing import DEFAULT_K, valve_capacity

from blocks.base import ElementResult
from blocks.fluid import Fluid
from blocks.sizing import k_loss, straight_loss, velocity

GENERIC_K_BASIS = ('preliminary_sizing.DEFAULT_K: explicit screening assumption, '
                   'not a universal fitting property')


@dataclass(frozen=True)
class Pipe:
    tag: str
    length_m: float
    roughness_m: float

    def evaluate(self, flow_m3_s: float, fluid: Fluid, bore_m: float) -> ElementResult:
        r = straight_loss(flow_m3_s, fluid, bore_m, self.length_m, self.roughness_m)
        return ElementResult(self.tag, 'pipe', flow_m3_s, r['dp_Pa'],
                             f"Darcy-Weisbach, {r['friction_method']}", 'calculated',
                             bore_m=bore_m, length_m=self.length_m, velocity_m_s=r['velocity_m_s'],
                             reynolds=r['reynolds'], regime=r['regime'],
                             extra={'darcy_factor': r['darcy_factor']})


@dataclass(frozen=True)
class Fitting:
    """Elbow, tee, reducer, strainer, quick disconnect, isolation or check valve.

    K comes from preliminary_sizing.DEFAULT_K unless a sourced value is given.
    """
    tag: str
    kind: str
    k: Optional[float] = None
    k_source: str = ''

    def evaluate(self, flow_m3_s: float, fluid: Fluid, bore_m: float) -> ElementResult:
        if self.k is None:
            if self.kind not in DEFAULT_K:
                raise ValueError(f'No default K for {self.kind!r}; supply k and k_source')
            k, basis, status = DEFAULT_K[self.kind], GENERIC_K_BASIS, 'assumption'
        else:
            if not self.k_source:
                raise ValueError(f'{self.tag}: a supplied K needs k_source')
            k, basis, status = self.k, self.k_source, 'vendor'
        r = k_loss(flow_m3_s, fluid, bore_m, k)
        return ElementResult(self.tag, self.kind, flow_m3_s, r['dp_Pa'], basis, status,
                             bore_m=bore_m, velocity_m_s=r['velocity_m_s'], reynolds=r['reynolds'], k=k)


@dataclass(frozen=True)
class AllocatedValve:
    """Balancing or control valve sized from an ALLOCATED pressure drop.

    The required effective Kv / Cv(US) follows from the allocation. It is a
    capacity requirement for a vendor shortlist, not a valve selection.
    """
    tag: str
    kind: str              # balancing_valve | control_valve
    dp_Pa: float
    allocation_basis: str

    def evaluate(self, flow_m3_s: float, fluid: Fluid, bore_m: float) -> ElementResult:
        if self.kind not in ('balancing_valve', 'control_valve'):
            raise ValueError(f'AllocatedValve kind must be balancing_valve or control_valve, got {self.kind!r}')
        cap = valve_capacity(flow_m3_s, fluid.rho_kg_m3, self.dp_Pa)
        return ElementResult(self.tag, self.kind, flow_m3_s, self.dp_Pa, self.allocation_basis, 'allocated',
                             bore_m=bore_m, velocity_m_s=velocity(flow_m3_s, bore_m),
                             extra={'Kv_m3_h': cap['Kv_m3_h'], 'Cv_US': cap['Cv_US'],
                                    'valve_basis': cap['basis']})


@dataclass(frozen=True)
class Equipment:
    """A load with its own pressure-drop data, e.g. the rack's internal loop
    (rack manifold + cold plates). Unknown data stays unknown.

    With a rated point, dp is scaled by (flow / rated_flow)^2, the usual
    turbulent screening assumption, and labelled as such.
    """
    tag: str
    kind: str = 'rack_load'
    rated_dp_Pa: Optional[float] = None
    rated_flow_m3_s: Optional[float] = None
    source: str = ''

    def evaluate(self, flow_m3_s: float, fluid: Fluid, bore_m: Optional[float] = None) -> ElementResult:
        if self.rated_dp_Pa is None:
            return ElementResult(self.tag, self.kind, flow_m3_s, None,
                                 'Equipment pressure drop not supplied: UNKNOWN, not zero', 'unknown')
        if not self.source:
            raise ValueError(f'{self.tag}: a supplied equipment pressure drop needs a source')
        if self.rated_flow_m3_s:
            dp = self.rated_dp_Pa * (flow_m3_s / self.rated_flow_m3_s) ** 2
            basis = f'{self.source}; scaled (Q/Q_rated)^2 from {self.rated_flow_m3_s*60000:.1f} L/min'
        else:
            dp = self.rated_dp_Pa
            basis = f'{self.source}; taken at design flow'
        return ElementResult(self.tag, self.kind, flow_m3_s, dp, basis, 'vendor')
