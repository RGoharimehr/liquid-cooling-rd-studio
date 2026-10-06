"""Coolant properties for one block, always with their provenance.

There is no built-in PG25 table on purpose (SIZING_BASIS.md section 2): the
properties depend on temperature, glycol fraction and formulation. They are
either entered explicitly with a source, or taken from the engine
configuration, where they are project inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Fluid:
    name: str
    rho_kg_m3: float
    cp_J_kgK: float
    mu_Pa_s: float
    source: str
    status: str = 'project_input'   # project_input | assumption | reviewed_table

    def __post_init__(self):
        for label in ('rho_kg_m3', 'cp_J_kgK', 'mu_Pa_s'):
            value = getattr(self, label)
            if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError(f'Fluid {label} must be a finite positive number, got {value!r}')
        if self.status not in ('project_input', 'assumption', 'reviewed_table'):
            raise ValueError(f'Unknown fluid property status {self.status!r}')
        if not self.source:
            raise ValueError('Fluid properties need a source description')

    @classmethod
    def from_config(cls, config, service: str = 'TCS') -> 'Fluid':
        """The same values the rest of the engine uses for this service."""
        prefix = service.lower()
        return cls(name=f'{service} coolant (engine configuration)',
                   rho_kg_m3=float(getattr(config, prefix + '_density_kg_m3')),
                   cp_J_kgK=float(getattr(config, prefix + '_specific_heat_J_kgK')),
                   mu_Pa_s=float(getattr(config, prefix + '_viscosity_Pa_s')),
                   source='Engine configuration (model.Config); project input at the intended '
                          'mean temperature. Formulation and manufacturer property curve require confirmation.',
                   status='project_input')

    def as_dict(self) -> dict:
        return {'name': self.name, 'rho_kg_m3': self.rho_kg_m3, 'cp_J_kgK': self.cp_J_kgK,
                'mu_Pa_s': self.mu_Pa_s, 'source': self.source, 'status': self.status}
