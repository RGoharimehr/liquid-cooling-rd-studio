"""Standards-derived parameter registry — the tuning surface of the generator.

Every layout, clearance, category and installation number the generator uses is
declared here as a Param carrying its value, unit, source document, clause and
STATUS. Status is the whole point:

    'critical'    - the source marks it as a critical dimension. Changing it
                    breaks physical interoperability. Overriding is allowed but
                    is recorded and reported as a declared deviation.
    'recommended' - sourced guidance; tune freely, deviation is recorded.
    'assumption'  - not found in any source available to this project. These
                    are the honest gaps and are listed as such in the report.

Nothing in this module is a performance/solver input. The generator needs no
pump curve, HX map or cold-plate resistance to lay out a reference design.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Any

IN = 0.0254
FT = 0.3048


@dataclass(frozen=True)
class Param:
    value: Any
    unit: str
    source: str
    clause: str
    status: str            # critical | recommended | assumption
    note: str = ''

    def __post_init__(self):
        if self.status not in ('critical', 'recommended', 'assumption'):
            raise ValueError(f'bad status {self.status}')


D = 'OCP-Specification-Deschutes v1_0'
CS = '2025 Modular TCS / CloudScale Design Delivery Selection Guidance Rev 1 March'
A2 = 'ASHRAE Liquid Cooling Ch02 Facility Cooling Systems'
A7 = 'ASHRAE Liquid Cooling Ch07 Fluids and Fluid Quality'
A8 = 'ASHRAE Liquid Cooling Ch08 Common Components / Cold Plates'
A10 = 'ASHRAE Liquid Cooling Ch10 Transitioning to Liquid Cooling'
A11 = 'ASHRAE Liquid Cooling Ch11 Additional Considerations'
TCSI = 'ASHRAE TC 9.9 TCS Coolant Integrity and System Readiness Best Practices'
B311 = 'ASME B31.1 (via published support-span tables)'
SP69 = 'MSS SP-69 (via published support-span tables)'
ASCE = 'ASCE 7 seismic bracing practice for distribution systems'


# ---------------------------------------------------------------- layout ----
# OCP Deschutes 18.1-18.4. Every dimension the spec marks critical is critical
# here. The spec itself distinguishes critical from fungible; we preserve that.
LAYOUT = {
    'rack_width_m':            Param(28 * IN,     'm', D, '18.1', 'critical'),
    'rack_depth_m':            Param(50 * IN,     'm', D, '18.1', 'critical', 'maximum'),
    'rack_height_min_m':       Param(80.7 * IN,   'm', D, '18.1', 'critical'),
    'rack_height_max_m':       Param(90.55 * IN,  'm', D, '18.1', 'critical'),
    'rack_gap_m':              Param(0.005,       'm', D, '18.3', 'critical', 'gap between neighbouring racks'),
    'cold_aisle_width_m':      Param(54 * IN,     'm', D, '18.2', 'critical', 'minimum'),
    'hot_aisle_width_m':       Param(68.4 * IN,   'm', D, '18.2', 'critical', 'minimum, with RDHx, rear RHx face to face'),
    'hot_aisle_max_m':         Param(102 * IN,    'm', D, '18.2', 'critical',
                                     'DISCREPANCY: spec prints 102 in AND 2210 mm; 102 in = 2590.8 mm. Inch value used.'),
    'bay_width_min_m':         Param(121 * IN,    'm', D, '18.2', 'critical', 'minimum'),
    'row_length_min_m':        Param(46 * FT,     'm', D, '18.2', 'critical', 'minimum'),
    'transport_aisle_a_m':     Param(6 * FT,      'm', D, '18.2', 'critical', 'at least one transport row'),
    'transport_aisle_b_m':     Param(10 * FT,     'm', D, '18.2', 'critical', 'the other transport row'),
    'ceiling_height_min_m':    Param(14 * FT,     'm', D, '18.2/18.4', 'critical', 'Redmond HAC overall height 168 in'),
    'manifold_elevation_m':    Param(100.5 * IN,  'm', D, '18.4', 'critical', 'Level 1 wall manifold pipe elevation'),
    'cable_level_2_m':         Param(115.5 * IN,  'm', D, '18.4', 'critical'),
    'cable_level_3_m':         Param(127.5 * IN,  'm', D, '18.4', 'critical'),
    'cable_level_4_m':         Param(139.5 * IN,  'm', D, '18.4', 'critical',
                                     'space ABOVE this elevation is available for distribution piping'),
    'racks_per_bay_side':      Param(4,           '-', D, '18.3', 'critical'),
    'post_size_m':             Param(5 * IN,      'm', D, '18.3', 'critical', 'vertical post 5 in x 5 in'),
}

# The distribution-header band is fully determined by Deschutes: above the top
# cable level, below the minimum ceiling. This is a derived constraint, not a
# free parameter, and it is what invalidates a 4.5 m header assumption.
# NOTE: the band's upper bound is NOT a separate parameter. It is the ceiling
# height in LAYOUT. Duplicating it would let a caller tune one and not the other.
HEADER_BAND = {
    'header_band_low_m':   Param(139.5 * IN, 'm', D, '18.4', 'critical', 'top of cable Level 4'),
    'header_supply_elevation_m': Param(3.75, 'm', D, '18.4 derived', 'recommended',
                                       'TUNABLE within the band; default centres supply in the available zone'),
    'return_elevation_offset_m': Param(0.30, 'm', '-', '-', 'assumption',
                                       'vertical separation of return above supply header'),
    'header_half_separation_m':  Param(0.25, 'm', '-', '-', 'assumption',
                                       'lateral half-separation of supply/return centre lines'),
}

# --------------------------------------------------------- clearances ------
CLEARANCE = {
    'pipe_to_rack_clear_m':      Param(0.30, 'm', CS, 'App. F "Rack, Cable and Equipment Clearance"', 'assumption',
                                       'source requires adequate clearance but states no number'),
    'valve_service_clear_m':     Param(0.60, 'm', A2, '2.1.5', 'assumption',
                                       'source requires access to operate valves/controls; number not given'),
    'cdu_service_clear_m':       Param(1.00, 'm', A2, '2.1.5', 'assumption',
                                       'manufacturer working clearance is the governing value; unknown here'),
    'rack_front_service_m':      Param(54 * IN, 'm', D, '18.2', 'critical', 'cold aisle doubles as front service access'),
    'rack_rear_service_m':       Param(68.4 * IN, 'm', D, '18.2', 'critical', 'hot aisle'),
    'overhead_rigging_clear_m':  Param(0.50, 'm', A10, '10.2.1', 'assumption',
                                       'source requires sufficient overhead clearance for server removal/rigging'),
}

# ------------------------------------------------------ pipe categories ----
# Each category owns its own limits. Velocity caps are NOT global.
@dataclass(frozen=True)
class PipeCategory:
    name: str
    service: str
    catalogue: str                  # key into hydraulics size tables
    velocity_cap_m_s: Param
    roughness_m: Param
    insulation_thickness_m: Param
    support_span: dict              # NPS(in) -> max span (m)
    support_span_source: str
    min_bend_radius_d: Param        # centre-line radius in pipe diameters
    seismic_brace_min_nps_in: Param


# ASME B31.1 water service, published span tables.
STEEL_SPAN = {1: 2.1, 2: 3.0, 3: 3.7, 4: 4.3, 6: 5.2, 8: 5.8, 12: 7.0}
# MSS SP-69 copper tube, water service.
COPPER_SPAN = {1: 1.8, 2: 2.4, 3: 3.0, 4: 3.7, 6: 4.3}

_CAP_TCS = Param(2.7, 'm/s', CS, '3.4', 'recommended',
                 'stated limit; erosion concern above 3 m/s. Argued from stainless erosion-corrosion.')
_CAP_CU = Param(1.5, 'm/s', '-', '-', 'assumption',
                'CloudScale 3.4 argues 2.7 m/s from stainless erosion-corrosion; not transferable to copper tube. '
                'Conservative copper erosion limit assumed pending a cited source.')
_CAP_FWS = Param(3.0, 'm/s', '-', '-', 'assumption',
                 'FWS is outside the TCS erosion argument; conventional chilled-water practice assumed.')

CATEGORIES = {
    'tcs_rack_branch': PipeCategory(
        'tcs_rack_branch', 'TCS', 'copper_type_l', _CAP_CU,
        Param(1.5e-6, 'm', '-', '-', 'assumption', 'new/clean drawn tube'),
        Param(0.0, 'm', A10, '10.2.2', 'assumption', 'insulation subject to dewpoint control strategy'),
        COPPER_SPAN, SP69,
        Param(3.0, 'D', '-', '-', 'assumption', 'long-radius'),
        Param(1.0, 'in', ASCE, 'Ip=1.5 threshold', 'recommended')),
    'tcs_row_header': PipeCategory(
        'tcs_row_header', 'TCS', 'stainless_sch10', _CAP_TCS,
        Param(15e-6, 'm', '-', '-', 'assumption', 'passivated stainless, clean'),
        Param(0.0, 'm', A10, '10.2.2', 'assumption'),
        STEEL_SPAN, B311,
        Param(3.0, 'D', '-', '-', 'assumption'),
        Param(1.0, 'in', ASCE, 'Ip=1.5 threshold', 'recommended')),
    'tcs_main': PipeCategory(
        'tcs_main', 'TCS', 'stainless_sch10', _CAP_TCS,
        Param(15e-6, 'm', '-', '-', 'assumption'),
        Param(0.0, 'm', A10, '10.2.2', 'assumption'),
        STEEL_SPAN, B311,
        Param(3.0, 'D', '-', '-', 'assumption'),
        Param(1.0, 'in', ASCE, 'Ip=1.5 threshold', 'recommended')),
    'fws_cdu': PipeCategory(
        'fws_cdu', 'FWS', 'carbon_steel_sch40', _CAP_FWS,
        Param(45.72e-6, 'm', 'EPA EPANET 2.2 Table 3.2', '3.1', 'recommended'),
        Param(0.038, 'm', A10, '10.2.1/10.2.2', 'assumption', '1.5 in cited in the raised-floor space example'),
        STEEL_SPAN, B311,
        Param(3.0, 'D', '-', '-', 'assumption'),
        Param(1.0, 'in', ASCE, 'Ip=1.5 threshold', 'recommended')),
    'fws_main': PipeCategory(
        'fws_main', 'FWS', 'carbon_steel_sch40', _CAP_FWS,
        Param(45.72e-6, 'm', 'EPA EPANET 2.2 Table 3.2', '3.1', 'recommended'),
        Param(0.038, 'm', A10, '10.2.1/10.2.2', 'assumption'),
        STEEL_SPAN, B311,
        Param(3.0, 'D', '-', '-', 'assumption'),
        Param(1.0, 'in', ASCE, 'Ip=1.5 threshold', 'recommended')),
}

# Which category serves which (service, level). This is the only mapping the
# topology builder needs; adding a category does not touch topology code.
CATEGORY_OF = {
    ('TCS', 'rack'): 'tcs_rack_branch',
    ('TCS', 'row_branch'): 'tcs_rack_branch',
    ('TCS', 'row'): 'tcs_row_header',
    ('TCS', 'main'): 'tcs_main',
    ('TCS', 'cdu'): 'tcs_main',
    ('FWS', 'main'): 'fws_main',
    ('FWS', 'cdu'): 'fws_cdu',
}


# ------------------------------------------------------- installation ------
INSTALL = {
    'seismic_transverse_spacing_m': Param(40 * FT, 'm', ASCE, 'common practice', 'recommended'),
    'seismic_longitudinal_spacing_m': Param(80 * FT, 'm', ASCE, 'common practice', 'recommended'),
    'seismic_brace_of_turn_m':     Param(24 * IN, 'm', ASCE, 'common practice', 'recommended',
                                         'brace within this distance of an elbow or branch'),
    'seismic_hanger_exempt_m':     Param(12 * IN, 'm', ASCE, 'common practice', 'recommended',
                                         'pipe suspended within this distance of structure is exempt'),
    'support_at_fitting':          Param(True, '-', B311, 'span note', 'recommended',
                                         'published spans are invalid where a concentrated load (flange, valve) sits in the span'),
    'flexible_connection_at_rack': Param(True, '-', A11, 'seismic', 'recommended',
                                         'TCS-to-rack joints require flexible piping / service loop'),
    'vent_at_high_point':          Param(True, '-', TCSI, 'Air Management', 'recommended',
                                         'avoid localised high points without venting'),
    'air_separator_at_pump_suction': Param(True, '-', TCSI, 'Air Management', 'recommended',
                                           'locate where temperature is high and pressure low'),
    'tcs_filtration_um':           Param(25.0, 'um', CS, 'App. G', 'recommended'),
    'tcs_filtration_um_alt':       Param(50.0, 'um', A7, '7.1', 'recommended', 'general cold-plate guideline'),
    'drip_tray_under_piping':      Param(True, '-', CS, 'App. A / leak detection', 'recommended'),
}


# ------------------------------------------------------ design profiles ----
# Which body actually governs this design, and which parameters it mandates.
#
# Before this existed, `Profile.default()` merged every parameter from every
# cited source into one set and handed it to every design. A Schneider RD113
# layout was built on 23 OCP Deschutes dimensions, each still stamped 'critical'
# and attributed to a document that does not govern it. The values were right
# because the configuration overrode them; the provenance was not.
#
# A profile does two things: it names the parameters its body genuinely mandates
# and supplies their values, and it demotes every other critical dimension to an
# assumption, because a mandate from a document you did not select is guidance at
# best. Nothing is hidden - the original source stays on the Param as provenance.


@dataclass(frozen=True)
class DesignProfile:
    name: str
    label: str
    body: str
    document: str              # corpus document id; empty when no document governs
    governs: frozenset         # parameter keys this body mandates for this design
    values: dict               # the values it mandates, for keys it governs
    clause: str = ''
    note: str = ''


PROFILES = {
    'project': DesignProfile(
        name='project', label='Project design', body='This project', document='',
        governs=frozenset(), values={},
        note='No reference module governs this design. Every dimension is a project assumption, '
             'informed by the cited guidance but not bound by it.'),
    'deschutes_module': DesignProfile(
        name='deschutes_module', label='OCP Deschutes module', body=D,
        document='OCP-Specification-Deschutes_v1_0',
        # The spec itself marks these critical: change one and a Deschutes module
        # no longer physically interoperates.
        governs=frozenset({'rack_width_m', 'rack_depth_m', 'rack_height_min_m', 'rack_height_max_m',
                           'rack_gap_m', 'racks_per_bay_side', 'bay_width_min_m', 'row_length_min_m',
                           'post_size_m', 'cold_aisle_width_m', 'hot_aisle_width_m', 'hot_aisle_max_m',
                           'transport_aisle_a_m', 'transport_aisle_b_m', 'rack_front_service_m',
                           'rack_rear_service_m', 'manifold_elevation_m', 'header_band_low_m',
                           'ceiling_height_min_m', 'cable_level_2_m', 'cable_level_3_m',
                           'cable_level_4_m'}),
        values={}, clause='18.1-18.4',
        note='The OCP Deschutes module specification governs rack, aisle and header-band geometry.'),
    'rd113_r1': DesignProfile(
        name='rd113_r1', label='Schneider RD113 R1', body='Schneider Electric EcoStruxure RD113',
        document='',
        # RD113 lists pipe diameters, clearances and elevations under project or
        # OEM inputs. What it does publish is the rack it uses and the AI hot
        # aisle, so those are all it governs here.
        governs=frozenset({'rack_width_m', 'rack_depth_m', 'hot_aisle_width_m'}),
        values={'rack_width_m': 0.600, 'rack_depth_m': 1.200, 'hot_aisle_width_m': 1.8288},
        clause='RD113_4.2 R1 equipment list; RD113DS R0 p5',
        note='RD113 publishes its rack and its AI hot aisle. It lists dimensions, clearances and pipe '
             'sizes as project or OEM inputs, so nothing else here is governed by it.'),
}


# ----------------------------------------------------------- profile -------
@dataclass
class Profile:
    """A resolved, tunable set of standards parameters.

    `overrides` is the tuning mechanism: a flat {key: value} dict, normally
    loaded from config.json. Every override is recorded with the status of the
    parameter it replaced, so a report can list deviations from critical
    dimensions separately from ordinary tuning.
    """
    params: dict = field(default_factory=dict)
    categories: dict = field(default_factory=lambda: dict(CATEGORIES))
    deviations: list = field(default_factory=list)
    design: 'DesignProfile' = PROFILES['project']

    def for_design(self, design: DesignProfile) -> 'Profile':
        """Restamp every parameter against the body that actually governs it."""
        for key, param in list(self.params.items()):
            if key in design.governs:
                self.params[key] = replace(param, value=design.values.get(key, param.value),
                    status='critical', source=design.body, clause=design.clause or param.clause,
                    note=(param.note + f' [governed by {design.label}]').strip())
            elif param.status == 'critical':
                self.params[key] = replace(param, status='assumption',
                    note=(param.note + f' [{param.source} marks this critical, but {design.label} does not '
                          f'govern it here, so it is a project assumption]').strip())
        self.design = design
        return self

    @classmethod
    def default(cls) -> 'Profile':
        merged = {}
        for group in (LAYOUT, HEADER_BAND, CLEARANCE, INSTALL):
            merged.update(group)
        return cls(params=dict(merged))

    def tune(self, overrides: dict) -> 'Profile':
        for key, value in (overrides or {}).items():
            if key in self.params:
                old = self.params[key]
                self.params[key] = replace(old, value=value, note=(old.note + ' [OVERRIDDEN]').strip())
                self.deviations.append({'key': key, 'from': old.value, 'to': value, 'status': old.status,
                                        'source': old.source, 'clause': old.clause, 'note': old.note})
            elif '.' in key:                      # category tuning: "tcs_main.velocity_cap_m_s"
                cat, attr = key.split('.', 1)
                if cat not in self.categories:
                    raise KeyError(f'unknown pipe category {cat!r}')
                target = self.categories[cat]
                old = getattr(target, attr)
                new = replace(old, value=value, note=(old.note + ' [OVERRIDDEN]').strip()) if isinstance(old, Param) else value
                self.categories[cat] = replace(target, **{attr: new})
                self.deviations.append({'key': key, 'from': getattr(old, 'value', old), 'to': value,
                                        'status': getattr(old, 'status', 'recommended'),
                                        'source': getattr(old, 'source', '-'), 'clause': getattr(old, 'clause', '-')})
            else:
                raise KeyError(f'unknown tuning parameter {key!r}')
        return self

    def __getitem__(self, key):
        return self.params[key].value

    def param(self, key) -> Param:
        return self.params[key]

    def header_band(self) -> tuple:
        """Available distribution-header band: above the top cable level, below
        the ceiling. The upper bound is `ceiling_height_min_m`, deliberately not
        a second parameter, so tuning the ceiling moves the band."""
        return self['header_band_low_m'], self['ceiling_height_min_m']

    def cap(self, category: str) -> float:
        return self.categories[category].velocity_cap_m_s.value

    def category_for(self, service: str, level: str) -> PipeCategory:
        return self.categories[CATEGORY_OF[(service, level)]]

    def support_span_m(self, category: str, nps_in: float) -> float:
        table = self.categories[category].support_span
        keys = sorted(k for k in table if k <= nps_in)
        return table[keys[-1]] if keys else min(table.values())

    def critical_deviations(self) -> list:
        return [d for d in self.deviations if d['status'] == 'critical']

    def assumptions(self) -> list:
        out = [{'key': k, 'value': p.value, 'unit': p.unit, 'note': p.note}
               for k, p in sorted(self.params.items()) if p.status == 'assumption']
        for name, cat in sorted(self.categories.items()):
            for attr in ('velocity_cap_m_s', 'roughness_m', 'insulation_thickness_m',
                         'min_bend_radius_d', 'seismic_brace_min_nps_in'):
                p = getattr(cat, attr)
                if isinstance(p, Param) and p.status == 'assumption':
                    out.append({'key': f'{name}.{attr}', 'value': p.value, 'unit': p.unit, 'note': p.note})
        return out

    def manifest(self) -> dict:
        return {
            'critical_deviations': self.critical_deviations(),
            'design_profile': {'name': self.design.name, 'label': self.design.label,
                               'body': self.design.body, 'document': self.design.document,
                               'governs': sorted(self.design.governs), 'clause': self.design.clause,
                               'note': self.design.note,
                               'scope': 'Parameters outside `governs` are project assumptions under this '
                                        'profile, whatever document they were sourced from.'},
            'parameters': {k: {'value': p.value, 'unit': p.unit, 'source': p.source,
                               'clause': p.clause, 'status': p.status, 'note': p.note}
                           for k, p in sorted(self.params.items())},
            'pipe_categories': {n: {'service': c.service, 'catalogue': c.catalogue,
                                    'velocity_cap_m_s': c.velocity_cap_m_s.value,
                                    'velocity_cap_status': c.velocity_cap_m_s.status,
                                    'velocity_cap_source': f'{c.velocity_cap_m_s.source} {c.velocity_cap_m_s.clause}'.strip(),
                                    'roughness_m': c.roughness_m.value,
                                    'insulation_thickness_m': c.insulation_thickness_m.value,
                                    'support_span_source': c.support_span_source,
                                    'support_span_m_by_nps_in': c.support_span,
                                    'seismic_brace_min_nps_in': c.seismic_brace_min_nps_in.value}
                                for n, c in sorted(self.categories.items())},
            'category_assignment': {f'{s}/{l}': c for (s, l), c in sorted(CATEGORY_OF.items())},
            'deviations': self.deviations,
            'critical_deviations': self.critical_deviations(),
            'declared_assumptions': self.assumptions(),
            'scope_note': 'Layout and connectivity generator. No pump curve, heat-exchanger map or '
                          'component resistance curve is required to produce this reference design; '
                          'those belong to the downstream flow-network model.',
        }
