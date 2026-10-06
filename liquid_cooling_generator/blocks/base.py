"""Result types shared by every block."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class ElementResult:
    """One line of a block's pressure-loss table.

    `dp_Pa is None` means UNKNOWN (for example a rack whose vendor pressure
    drop has not been supplied). It is never silently treated as zero.
    """
    tag: str
    kind: str
    flow_m3_s: float
    dp_Pa: Optional[float]
    basis: str                       # how dp was obtained
    status: str                      # calculated | assumption | allocated | vendor | unknown
    bore_m: Optional[float] = None
    length_m: Optional[float] = None
    velocity_m_s: Optional[float] = None
    reynolds: Optional[float] = None
    regime: Optional[str] = None
    k: Optional[float] = None
    extra: dict = field(default_factory=dict)

    def row(self) -> dict:
        d = asdict(self)
        d['flow_L_min'] = self.flow_m3_s * 60000.
        d['dp_kPa'] = None if self.dp_Pa is None else self.dp_Pa / 1000.
        return d


@dataclass
class BlockResult:
    name: str
    kind: str                         # rack_branch | rack_row | ...
    heat_W: float
    mass_kg_s: float
    flow_m3_s: float
    supply_T_C: float
    return_T_C: float
    delta_T_K: float
    dp_Pa: float                      # critical-path total of the KNOWN parts
    dp_complete: bool                 # False if any part on the path is unknown
    unknowns: list
    head_m: float
    elements: list                    # ElementResult, critical path in flow order
    pipes: list                       # pipe schedule (one dict per sized run)
    valves: list                      # valve schedule (one dict per valve)
    accessories: list = field(default_factory=list)   # vents, drains: not in the loss path
    children: list = field(default_factory=list)      # BlockResult of contained blocks
    assumptions: list = field(default_factory=list)   # declared assumptions used
    checks: list = field(default_factory=list)        # pass/fail checks against limits
    notes: list = field(default_factory=list)

    @property
    def flow_L_min(self) -> float:
        return self.flow_m3_s * 60000.

    @property
    def dp_kPa(self) -> float:
        return self.dp_Pa / 1000.

    def connection(self) -> dict:
        """What this block asks of whatever feeds it. This is the interface
        used when blocks are connected: the feeder needs only these numbers."""
        return {'block': self.name, 'kind': self.kind,
                'mass_kg_s': self.mass_kg_s, 'flow_m3_s': self.flow_m3_s,
                'supply_T_C': self.supply_T_C, 'return_T_C': self.return_T_C,
                'required_dp_Pa': self.dp_Pa, 'required_head_m': self.head_m,
                'dp_complete': self.dp_complete,
                'unknowns': list(self.unknowns)}

    def element_rows(self) -> list:
        return [e.row() for e in self.elements]

    def summary(self) -> dict:
        return {'name': self.name, 'kind': self.kind,
                'heat_kW': self.heat_W / 1000., 'mass_kg_s': self.mass_kg_s,
                'flow_L_min': self.flow_L_min, 'supply_T_C': self.supply_T_C,
                'return_T_C': self.return_T_C, 'delta_T_K': self.delta_T_K,
                'dp_kPa': self.dp_kPa, 'head_m': self.head_m,
                'dp_complete': self.dp_complete, 'unknowns': list(self.unknowns),
                'failed_checks': [c['name'] for c in self.checks if c.get('passed') is False]}
