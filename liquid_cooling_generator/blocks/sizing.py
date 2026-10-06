"""The sizing chain for one section.

    heat + max temperature rise -> mass flow -> volume flow
    -> minimum bore at the category velocity cap -> next catalogue size
    -> actual velocity, Reynolds number, friction factor -> pressure loss -> head

Pipe dimensions, velocity caps and roughness come from `hydraulics` and
`standards.CATEGORIES`; the friction factor comes from
`preliminary_sizing.friction_factor`. Nothing is duplicated here.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, pi, sqrt

from hydraulics import select_size
from preliminary_sizing import G, friction_factor
from standards import CATEGORIES

from blocks.fluid import Fluid


def _check(value, label, *, positive=False, nonnegative=False):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f'{label} must be a finite number, got {value!r}')
    if positive and value <= 0:
        raise ValueError(f'{label} must be positive')
    if nonnegative and value < 0:
        raise ValueError(f'{label} must be nonnegative')
    return float(value)


@dataclass(frozen=True)
class FlowDemand:
    heat_W: float
    delta_T_K: float
    mass_kg_s: float
    flow_m3_s: float

    @property
    def flow_L_min(self) -> float:
        return self.flow_m3_s * 60000.

    def scaled(self, count: int) -> 'FlowDemand':
        """`count` identical demands in parallel: heat and flow add, rise stays."""
        return FlowDemand(self.heat_W * count, self.delta_T_K,
                          self.mass_kg_s * count, self.flow_m3_s * count)


def flow_from_heat(heat_W: float, delta_T_K: float, fluid: Fluid) -> FlowDemand:
    """Rate form of the heat balance: m = Q / (cp * dT), V = m / rho."""
    heat = _check(heat_W, 'heat_W', nonnegative=True)
    rise = _check(delta_T_K, 'delta_T_K', positive=True)
    mass = heat / (fluid.cp_J_kgK * rise)
    return FlowDemand(heat, rise, mass, mass / fluid.rho_kg_m3)


def size_pipe(flow_m3_s: float, category: str, velocity_cap_m_s: float | None = None) -> dict:
    """Smallest catalogue bore whose velocity stays at or below the cap.

    The cap and the catalogue belong to the pipe CATEGORY (standards.py). An
    override is allowed but is recorded as a project deviation.
    Raises hydraulics.NoCatalogueSize when the catalogue is exhausted.
    """
    if category not in CATEGORIES:
        raise ValueError(f'Unknown pipe category {category!r}; known: {sorted(CATEGORIES)}')
    cat = CATEGORIES[category]
    cap_param = cat.velocity_cap_m_s
    cap = cap_param.value if velocity_cap_m_s is None else _check(velocity_cap_m_s, 'velocity cap', positive=True)
    flow = _check(flow_m3_s, 'flow_m3_s', nonnegative=True)
    chosen = select_size(flow, cat.catalogue, cap)
    area = pi * chosen['id_m'] ** 2 / 4
    chosen.update({
        'category': category, 'catalogue': cat.catalogue,
        'flow_m3_s': flow, 'velocity_m_s': flow / area,
        'velocity_cap_m_s': cap,
        'velocity_cap_status': cap_param.status if velocity_cap_m_s is None else 'project_override',
        'velocity_cap_source': (f'{cap_param.source} {cap_param.clause}'.strip()
                                if velocity_cap_m_s is None else 'project override of category cap'),
        'roughness_m': cat.roughness_m.value,
        'roughness_status': cat.roughness_m.status,
    })
    return chosen


def velocity(flow_m3_s: float, bore_m: float) -> float:
    return flow_m3_s / (pi * bore_m ** 2 / 4)


def straight_loss(flow_m3_s: float, fluid: Fluid, bore_m: float, length_m: float, roughness_m: float) -> dict:
    """Darcy-Weisbach loss in a straight run at a known (prescribed) flow."""
    flow = _check(flow_m3_s, 'flow_m3_s', nonnegative=True)
    bore = _check(bore_m, 'bore_m', positive=True)
    length = _check(length_m, 'length_m', nonnegative=True)
    v = velocity(flow, bore)
    re = fluid.rho_kg_m3 * v * bore / fluid.mu_Pa_s
    ff = friction_factor(re, roughness_m / bore)
    dp = ff['darcy_factor'] * (length / bore) * fluid.rho_kg_m3 * v * v / 2
    return {'velocity_m_s': v, 'reynolds': re, 'darcy_factor': ff['darcy_factor'],
            'regime': ff['regime'], 'friction_method': ff['method'], 'dp_Pa': dp}


def k_loss(flow_m3_s: float, fluid: Fluid, bore_m: float, k: float) -> dict:
    """Minor loss K * rho v^2 / 2 at the stated reference bore."""
    v = velocity(_check(flow_m3_s, 'flow_m3_s', nonnegative=True), _check(bore_m, 'bore_m', positive=True))
    return {'velocity_m_s': v, 'reynolds': fluid.rho_kg_m3 * v * bore_m / fluid.mu_Pa_s,
            'dp_Pa': _check(k, 'K', nonnegative=True) * fluid.rho_kg_m3 * v * v / 2}


def head_m(dp_Pa: float, fluid: Fluid) -> float:
    return dp_Pa / (fluid.rho_kg_m3 * G)
