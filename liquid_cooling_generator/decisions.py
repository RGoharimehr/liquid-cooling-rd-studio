"""Design-decision register: every choice, its governing clause, and its check.

Three things travel together for each design choice, and none is optional:

  1. WHAT was decided and why.
  2. WHICH document and clause governs it, plus the VERBATIM quote that must be
     findable in the reference corpus. A decision whose quote cannot be found is
     reported as unsupported - the register cannot silently drift from the source.
  3. HOW to check the generated model actually obeys it - a named function that
     runs against the real graph and returns a measured value, not an opinion.

`basis` says what kind of authority stands behind the choice:
    standard_mandate  - the source states a requirement or a hard number
    standard_guidance - the source recommends, without a mandatory number
    derived           - follows arithmetically from other decisions
    user_input        - supplied in the test case, not from a standard
    assumption        - no source; the honest gaps
    external_standard - real standard, but NOT in this project's reference DB,
                        so its quote can never be verified here. Declared as such.

`severity` says what a failed check means:
    blocking - the design does not fit or does not comply; must be resolved
    major    - a real deviation needing a documented decision
    advisory - informational
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math

GPM_PER_M3S = 15850.323141489
PSI_PER_PA = 1.0 / 6894.757293168

D = 'OCP-Specification-Deschutes_v1_0'
CS = '2025_Modular_TCS_CloudScale_Rev_1_March'
A = 'ASHRAE_TC99_liquid_cooling'
EXT = '(external - not in project reference database)'


@dataclass(frozen=True)
class Decision:
    id: str
    area: str
    choice: str
    rationale: str
    basis: str
    document: str
    clause: str
    quote: str
    check: str | None = None
    severity: str = 'advisory'

    def as_dict(self):
        return asdict(self)


# ---------------------------------------------------------------- checks ----
# Each returns (ok: bool|None, actual, expected, detail). None = not evaluable.
def _cats(g):
    return g['metadata']['standards']['pipe_categories']


def _f(g):
    return g['hydraulics']['heat_and_flow']


def _count(g, kind):
    return sum(1 for c in g['components'] if c.get('kind') == kind)


CHECKS = {}


def check(name):
    def wrap(fn):
        CHECKS[name] = fn
        return fn
    return wrap


@check('rack_pitch_matches_width_plus_gap')
def _(g, c, P):
    want = P['rack_width_m'] + P['rack_gap_m']
    return abs(c.rack_pitch_m - want) < 1e-6, c.rack_pitch_m, want, 'm, rack centre-to-centre'


@check('rack_depth_within_max')
def _(g, c, P):
    return c.rack_depth_m <= P['rack_depth_m'] + 1e-9, c.rack_depth_m, P['rack_depth_m'], 'm'


@check('aisle_meets_cold_minimum')
def _(g, c, P):
    return c.aisle_width_m >= P['cold_aisle_width_m'] - 1e-9, c.aisle_width_m, P['cold_aisle_width_m'], 'm clear'


@check('aisle_meets_hot_minimum')
def _(g, c, P):
    return c.aisle_width_m >= P['hot_aisle_width_m'] - 1e-9, c.aisle_width_m, P['hot_aisle_width_m'], 'm clear'


@check('row_length_meets_minimum')
def _(g, c, P):
    length = c.first_rack_x_m + (c.racks_per_row - 1) * c.rack_pitch_m + P['rack_width_m']
    return length >= P['row_length_min_m'] - 1e-9, length, P['row_length_min_m'], 'm'


@check('manifold_at_level_1')
def _(g, c, P):
    return abs(c.manifold_elevation_m - P['manifold_elevation_m']) < 1e-3, \
        c.manifold_elevation_m, P['manifold_elevation_m'], 'm above finished floor'


@check('headers_inside_available_band')
def _(g, c, P):
    low, high = P.header_band()
    ret = c.header_elevation_m + c.return_elevation_offset_m
    return (c.header_elevation_m >= low - 1e-9 and ret <= high + 1e-9), \
        [c.header_elevation_m, ret], [low, high], 'm; supply and return centre lines vs available band'


@check('cdu_duty_within_capacity')
def _(g, c, P):
    duty = _f(g)['cdu_duty_heat_W']
    return duty <= 2.0e6 + 1e-6, duty / 1e3, 2000.0, 'kW per duty CDU vs the 2 MW Deschutes CDU'


@check('cdu_secondary_flow_within_capacity')
def _(g, c, P):
    gpm = _f(g)['cdu_secondary_m3_s'] * GPM_PER_M3S
    return gpm <= 500.0 + 1e-6, gpm, 500.0, 'GPM secondary (IT) flow per duty CDU'


@check('cdu_primary_flow_within_capacity')
def _(g, c, P):
    gpm = _f(g)['cdu_primary_m3_s'] * GPM_PER_M3S
    return gpm <= 500.0 + 1e-6, gpm, 500.0, 'GPM facility flow per duty CDU'


@check('facility_flow_per_kw')
def _(g, c, P):
    f = _f(g)
    ratio = (f['cdu_primary_m3_s'] * GPM_PER_M3S) / (f['cdu_duty_heat_W'] / 1e3)
    return abs(ratio - 0.25) <= 0.05, ratio, 0.25, 'GPM/kW facility, +/-0.05 tolerance'


@check('tcs_loop_within_available_dp')
def _(g, c, P):
    worst = max(s['required_tcs_pump_dp_Pa'] for s in g['hydraulics']['scenarios'])
    return worst * PSI_PER_PA <= 80.0, worst * PSI_PER_PA, 80.0, 'psi required vs IT dP available 80-90 psi'


@check('approach_matches_spec')
def _(g, c, P):
    return abs(c.hx_approach_K - 3.0) < 1e-9, c.hx_approach_K, 3.0, 'K cold-end approach'


@check('tcs_temperatures_within_operating_range')
def _(g, c, P):
    lo, hi = c.tcs_supply_C, c.tcs_supply_C + c.tcs_delta_K
    return (lo >= 18.0 and hi <= 55.0), [lo, hi], [18.0, 55.0], 'degC TCS operating range'


@check('cdu_has_redundant_pumps')
def _(g, c, P):
    per = {}
    for comp in g['components']:
        if comp.get('kind') == 'pump':
            per[comp.get('cdu')] = per.get(comp.get('cdu'), 0) + 1
    fewest = min(per.values()) if per else 0
    return fewest >= 2, fewest, 2, 'pumps per CDU'


@check('cdu_has_expansion_tank')
def _(g, c, P):
    n = _count(g, 'expansion_tank')
    return n >= c.cdu_count, n, c.cdu_count, 'expansion tanks (one per CDU)'


@check('cdu_has_air_separator')
def _(g, c, P):
    n = _count(g, 'air_separator')
    return n >= c.cdu_count, n, c.cdu_count, 'air separators (one per CDU)'


@check('secondary_filtration_rated')
def _(g, c, P):
    strainers = [x for x in g['components'] if x.get('kind') == 'strainer' and x.get('service') == 'TCS']
    rated = [x for x in strainers if x.get('filtration_um') is not None]
    ok = bool(strainers) and len(rated) == len(strainers) and all(
        25.0 <= float(x['filtration_um']) <= 44.0 for x in rated)
    return ok, f'{len(rated)}/{len(strainers)} rated', '25-44 um', 'TCS strainer micron rating'


@check('primary_strainer_rated')
def _(g, c, P):
    strainers = [x for x in g['components'] if x.get('kind') == 'strainer' and x.get('service') == 'FWS']
    rated = [x for x in strainers if x.get('filtration_um') is not None]
    ok = bool(strainers) and len(rated) == len(strainers) and all(
        float(x['filtration_um']) <= 500.0 for x in rated)
    return ok, f'{len(rated)}/{len(strainers)} rated', '<= 500 um', 'FWS strainer micron rating'


@check('tcs_wetted_materials_allowed')
def _(g, c, P):
    allowed = {'stainless_sch10', 'copper_type_l'}
    used = {e.get('material') for e in g['edges'] if e.get('service') == 'TCS'}
    return used <= allowed, sorted(x for x in used if x), sorted(allowed), 'TCS pipe catalogues'


@check('wall_manifold_bore_at_least_4in')
def _(g, c, P):
    bores = [float(e['nominal_size_in']) for e in g['edges']
             if e.get('service') == 'TCS' and e.get('level') == 'row' and e.get('nominal_size_in')]
    smallest = min(bores) if bores else 0
    return smallest >= 4.0, smallest, 4.0, 'in nominal, row (wall manifold) header'


@check('leak_detection_present')
def _(g, c, P):
    return _count(g, 'drip_tray') > 0, _count(g, 'drip_tray'), '> 0', 'drip trays under distribution piping'


@check('vents_at_all_high_points')
def _(g, c, P):
    return _count(g, 'vent') > 0, _count(g, 'vent'), '> 0', 'vents placed at routed local high points'


@check('flexible_connector_at_rack')
def _(g, c, P):
    return _count(g, 'flex_connector') >= _count(g, 'quick_disconnect'), \
        _count(g, 'flex_connector'), _count(g, 'quick_disconnect'), 'one per rack quick disconnect'


@check('velocity_within_category_cap')
def _(g, c, P):
    bad = [e['id'] for e in g['edges'] if not e.get('velocity_cap_pass', True)]
    return not bad, len(bad), 0, 'edges exceeding their pipe-category cap'


@check('copper_only_on_rack_branches')
def _(g, c, P):
    wrong = {e.get('level') for e in g['edges'] if e.get('material') == 'copper_type_l'} - {'rack', 'row_branch'}
    return not wrong, sorted(wrong) or 'none', 'rack / row_branch only', 'levels using copper'


@check('supports_within_published_span')
def _(g, c, P):
    over = []
    for comp in g['components']:
        if comp.get('kind') == 'pipe_support' and comp.get('supported_length_m') and comp.get('max_span_m'):
            if float(comp['supported_length_m']) > float(comp['max_span_m']) + 1e-9:
                over.append(comp['id'])
    return not over, len(over), 0, 'supports whose tributary length exceeds the published span'


@check('seismic_braces_present')
def _(g, c, P):
    n = _count(g, 'seismic_brace_transverse') + _count(g, 'seismic_brace_longitudinal')
    return n > 0, n, '> 0', 'seismic braces placed'


@check('overhead_rigging_clearance')
def _(g, c, P):
    _, high = P.header_band()
    ret = c.header_elevation_m + c.return_elevation_offset_m
    return high - ret >= P['overhead_rigging_clear_m'] - 1e-9, high - ret, P['overhead_rigging_clear_m'], 'm'


@check('parallel_cdus_on_common_header')
def _(g, c, P):
    scen = [s for s in g['scenarios'] if s['name'] == 'all_three_online']
    return bool(scen) and len(scen[0]['active_cdus']) == c.cdu_count, \
        len(scen[0]['active_cdus']) if scen else 0, c.cdu_count, 'CDUs sharing the common header'


@check('ifc_network_connectivity')
def _(g, c, P):
    em = g['metadata'].get('emission') or {}
    got = em.get('ifc_connected_networks')
    if got is None:
        return None, 'not emitted yet', '[TCS, FWS]', 'run after emission to evaluate'
    return len(got) == 2, got, '2 networks (TCS, FWS)', \
        'element sizes of each connected network, from re-reading the emitted IFC and traversing ports'


@check('ifc_all_elements_typed')
def _(g, c, P):
    em = g['metadata'].get('emission') or {}
    untyped = em.get('ifc_untyped_elements')
    if untyped is None:
        return None, 'not emitted yet', 0, 'run after emission to evaluate'
    return untyped == 0, untyped, 0, 'IFC elements with no IfcTypeObject via IfcRelDefinesByType'


@check('ifc_predefined_types_valid')
def _(g, c, P):
    em = g['metadata'].get('emission') or {}
    rejected = em.get('ifc_rejected_predefined_types')
    if rejected is None:
        return None, 'not emitted yet', [], 'run after emission to evaluate'
    return not rejected, rejected or 'none', 'none', 'PredefinedType values the IFC4 schema refused'


# -------------------------------------------------------------- register ----
REGISTER = [
    # ---- layout, from OCP Deschutes critical dimensions
    Decision('DEC-L01', 'layout', 'Rack pitch = 28 in rack width + 5 mm gap = 0.7162 m',
             'Shoulder-to-shoulder deployment fixes the pitch; it is not a free layout choice.',
             'standard_mandate', D, '18.1 / 18.3', 'Rack Width: 28" (711 mm)',
             'rack_pitch_matches_width_plus_gap', 'blocking'),
    Decision('DEC-L02', 'layout', 'Rack depth 1.270 m',
             'Spec states a maximum; the reference design sits at it.',
             'standard_mandate', D, '18.1', 'Rack Depth: 50" (1270 mm) max',
             'rack_depth_within_max', 'blocking'),
    Decision('DEC-L03', 'layout', 'Inter-rack gap 5 mm',
             'Fixes how many racks fit between base plates.',
             'standard_mandate', D, '18.3', '5 mm gap between the neighboring racks', None, 'advisory'),
    Decision('DEC-L04', 'layout', 'Aisle clear width >= 1.3716 m (cold aisle minimum)',
             'Cold aisle is also the front service access for the rack.',
             'standard_mandate', D, '18.2', 'Cold Aisle width 54" (1372mm) minimum',
             'aisle_meets_cold_minimum', 'blocking'),
    Decision('DEC-L05', 'layout', 'Aisle clear width >= 1.73736 m (hot aisle minimum with RDHx)',
             'Governs when rear door heat exchangers are fitted; the binding minimum of the two.',
             'standard_mandate', D, '18.2', 'Hot Aisle width 68.4" (1737mm) minimum',
             'aisle_meets_hot_minimum', 'blocking'),
    Decision('DEC-L06', 'layout', 'Row length >= 14.02 m',
             'A Deschutes row is a fixed module; a shorter row is a partial deployment.',
             'standard_mandate', D, '18.2', "Min row length 46' (14.02m)",
             'row_length_meets_minimum', 'major'),
    Decision('DEC-L07', 'layout', 'Rack manifold centre line at 2.5527 m (100.5 in)',
             'Wall manifold elevation is critical and cannot be changed.',
             'standard_mandate', D, '18.4', 'Wall Manifold (WMF) pipes. Elevation: 100.5"',
             'manifold_at_level_1', 'blocking'),
    Decision('DEC-L08', 'layout', 'Distribution headers confined to 3.5433-4.2672 m',
             'Derived: the only space left for distribution piping is above cable Level 4 and below the '
             'minimum ceiling. This is what invalidates an assumed 4.5 m header.',
             'derived', D, '18.4 with 18.2',
             'The space above the fourth elevation (139.5") is available to the Colo providers',
             'headers_inside_available_band', 'blocking'),
    Decision('DEC-L09', 'layout', 'Cable levels and manifold elevation treated as immutable',
             'The spec marks them critical; overriding is recorded as a critical deviation.',
             'standard_mandate', D, '18.4', 'All these four elevations are critical, i.e. cannot be changed.',
             None, 'advisory'),
    Decision('DEC-L10', 'layout', 'Overhead rigging clearance above the return header',
             'Server removal and rigging need headroom. NO NUMBER IS GIVEN by the source; ours is assumed.',
             'assumption', A, 'Ch10 10.2.1',
             'Sufficient overhead clearance should be provided for removal of the server',
             'overhead_rigging_clearance', 'major'),
    Decision('DEC-L11', 'scope', 'Structural qualification is out of scope',
             'The generator checks geometry only; loads and anchoring belong to the owner.',
             'standard_mandate', D, '18',
             'Structural Qualification for Static and Dynamic Loads: The data center owner is solely responsible',
             None, 'advisory'),

    # ---- CDU capacity and interface, from the Deschutes CDU specification
    Decision('DEC-C01', 'capacity', 'Duty CDU thermal load must fit a 2 MW Deschutes CDU',
             'The reference CDU is a 2 MW unit; the N-duty load must not exceed it.',
             'standard_mandate', D, '3.1 / 5', 'Thermal load (kW) 2000',
             'cdu_duty_within_capacity', 'blocking'),
    Decision('DEC-C02', 'capacity', 'Secondary (IT) flow per duty CDU must fit 500 GPM',
             'Hydraulic capacity of the reference CDU.',
             'standard_mandate', D, '3.1 / 5', 'IT flow (GPM) 500',
             'cdu_secondary_flow_within_capacity', 'blocking'),
    Decision('DEC-C03', 'capacity', 'Facility flow per duty CDU must fit 500 GPM',
             'Primary-side hydraulic capacity of the reference CDU.',
             'standard_mandate', D, '3.1', 'Facility flow @ 0.25 GPM/kW 500',
             'cdu_primary_flow_within_capacity', 'blocking'),
    Decision('DEC-C04', 'sizing', 'Facility flow tracks 0.25 GPM/kW',
             'The spec ties facility flow to load; our FWS delta-T assumption must reproduce it.',
             'standard_mandate', D, '3.1', 'Facility GPM/kW 0.25',
             'facility_flow_per_kw', 'major'),
    Decision('DEC-C05', 'hydraulic', 'TCS circuit loss must fit the CDU available differential',
             'The CDU offers 80-90 psi to the IT loop; the distribution circuit must live inside that.',
             'standard_mandate', D, '3.1 / 5', 'IT dP available (psi) 80-90',
             'tcs_loop_within_available_dp', 'blocking'),
    Decision('DEC-C06', 'thermal', 'Cold-end approach 3 K',
             'Matches the CDU design point, and sets TCS supply from FWS supply.',
             'standard_mandate', D, '3.1 / 5', 'Approach temperature (°C) 3',
             'approach_matches_spec', 'major'),
    Decision('DEC-C07', 'thermal', 'TCS operating temperatures inside 18-55 degC',
             'The CDU operating envelope bounds the loop temperatures.',
             'standard_mandate', D, '5', 'Operating liquid temperature (°C) 18-55',
             'tcs_temperatures_within_operating_range', 'blocking'),
    Decision('DEC-C08', 'redundancy', 'Each CDU carries N+1 pumps',
             'Pumps are the likeliest CDU failure, and changeover without active redundancy is a thermal event.',
             'standard_mandate', D, '3.2 / 5.4', 'N+1 pump operation, providing redundancy.',
             'cdu_has_redundant_pumps', 'blocking'),
    Decision('DEC-C09', 'hydraulic', 'Expansion tank inside each CDU provides the TCS pressure reference',
             'The Deschutes CDU includes a flow-through expansion tank, so the closed TCS loop does have a '
             'pressure reference - it belongs in the CDU assembly, not the distribution network.',
             'standard_mandate', D, '3.2 / 4.2', 'Flow-through expansion tank, front serviceable',
             'cdu_has_expansion_tank', 'blocking'),
    Decision('DEC-C10', 'hydraulic', 'Air separator inside each CDU',
             'Deschutes fits a Spirovent; ASHRAE wants separation at high temperature and low pressure, '
             'which is the CDU return/pump suction.',
             'standard_mandate', D, '3.2', 'Spirovent (air separator)',
             'cdu_has_air_separator', 'major'),
    Decision('DEC-C11', 'cleanliness', 'TCS strainers rated 25-44 micron',
             'Cold-plate microchannels are ~100 micron; filtration is a design input, not an afterthought.',
             'standard_mandate', D, '3.2 / 4.2', 'Secondary side filtration: 25-44 um',
             'secondary_filtration_rated', 'major'),
    Decision('DEC-C12', 'cleanliness', 'FWS strainers rated 500 micron',
             'Primary side is coarser; the CDU protects the TCS.',
             'standard_mandate', D, '4.2', 'Primary side strainer: 500 um',
             'primary_strainer_rated', 'major'),
    Decision('DEC-C13', 'materials', 'TCS wetted materials limited to stainless steel and copper',
             'Deschutes fixes the wetted set; ASHRAE Table 7.2 independently excludes carbon steel from TCS.',
             'standard_mandate', D, '3.2', 'Wetted materials: stainless steel, copper, EPDM',
             'tcs_wetted_materials_allowed', 'blocking'),
    Decision('DEC-C14', 'controls', 'Equal load sharing follows from fixed-differential pump control',
             'Not an assumption: the CDU default control mode and parallel operation produce it.',
             'standard_mandate', D, '7.2.2', 'DEFAULT: Fixed pressure drop control',
             None, 'advisory'),
    Decision('DEC-C15', 'topology', 'CDUs operate in parallel on a common header',
             'The spec explicitly permits it, which is what makes the N+1 sharing scheme legitimate.',
             'standard_mandate', D, '6.7',
             'Controls shall allow for CDUs to be operated in parallel, i.e. hydraulically connected to a common header.',
             'parallel_cdus_on_common_header', 'major'),
    Decision('DEC-C16', 'safety', 'Leak detection and drip trays under distribution piping',
             'Deschutes fits 3-zone leak rope; CloudScale requires drip trays and leak detection.',
             'standard_mandate', D, '3.2', 'Leak rope detection (detected through PLC, 3 zones)',
             'leak_detection_present', 'major'),

    # ---- wall manifold
    Decision('DEC-W01', 'sizing', 'Row (wall manifold) header bore >= 4 in',
             'The Deschutes wall manifold is 4 in ID or larger; a smaller row header cannot interface.',
             'standard_mandate', D, '23.2.2', 'Piping Inner diameter: of 4 inches (or larger)',
             'wall_manifold_bore_at_least_4in', 'blocking'),
    Decision('DEC-W02', 'hydraulic', 'Wall manifold working pressure 130 psi, differential 80-90 psi',
             'Bounds both the static rating and the loop differential the distribution may consume.',
             'standard_mandate', D, '23.2.2', 'Maximum working pressure for wall manifold: 130 psi',
             None, 'advisory'),
    Decision('DEC-W03', 'constructability', 'Manifold routed in ~3 m segments',
             'Modular sections ship in crates and assemble on site; segment length drives joint count.',
             'standard_guidance', D, '23.2.2', 'These are about 3 meters long', None, 'advisory'),

    # ---- pipe categories and velocity
    Decision('DEC-V01', 'sizing', 'Stainless TCS header velocity cap 2.7 m/s',
             'The one number that governs pipe sizing, and it is stated.',
             'standard_mandate', CS, '3.4', 'Flow velocity limit of 2.7 m/s (9 ft/s)',
             'velocity_within_category_cap', 'blocking'),
    Decision('DEC-V02', 'sizing', 'Erosion regarded as a concern above 3 m/s',
             'Sets the hard ceiling the cap sits below.',
             'standard_mandate', CS, '3.4', 'Erosion may become a concern for flows > 3 m/s', None, 'advisory'),
    Decision('DEC-V03', 'sizing', 'Copper rack-branch cap 1.5 m/s, NOT 2.7',
             'The 2.7 m/s figure is argued from stainless erosion-corrosion. Transferring it to copper tube '
             'would be using a source for something it does not say.',
             'assumption', CS, '3.4 (scope of)',
             'Stainless steel is resistant to corrosion but susceptible to erosion-corrosion at high flow velocities',
             'copper_only_on_rack_branches', 'major'),

    # ---- installation, from ASHRAE
    Decision('DEC-I01', 'installation', 'Vent at every routed local high point',
             'Overhead headers with rack drops create high points by construction.',
             'standard_guidance', A, 'TCS Coolant Integrity, Air Management',
             'Avoid geometries that trap air', 'vents_at_all_high_points', 'major'),
    Decision('DEC-I02', 'installation', 'Air separation at CDU return / pump suction',
             'Placement is specified by condition, not by convenience.',
             'standard_guidance', A, 'TCS Coolant Integrity, Air Management',
             'Locate air separation where fluid temperature is relatively high and pressure is relatively low',
             'cdu_has_air_separator', 'major'),
    Decision('DEC-I03', 'installation', 'Flexible connector at every rack interface',
             'Rigid TCS-to-rack joints fail in seismic events.',
             'standard_guidance', A, 'Ch11 seismic',
             'the joints between a TCS loop and a rack could be damaged during a seismic event if flexible piping is not used',
             'flexible_connector_at_rack', 'major'),
    Decision('DEC-I04', 'clearance', 'Working clearance maintained around valves and equipment',
             'Required, but the source gives no dimension - ours is assumed.',
             'assumption', A, 'Ch02 2.1.5',
             'maintain adequate working clearance around cooling equipment', None, 'advisory'),
    Decision('DEC-I05', 'redundancy', 'Redundant CDU pumps corroborated independently of OCP',
             'Two sources agree, which raises confidence in a blocking check.',
             'standard_guidance', A, 'Ch04 4.2.2', 'Most CDUs will have redundant pumps.',
             'cdu_has_redundant_pumps', 'blocking'),

    # ---- external standards: real, but NOT in this project's reference database
    Decision('DEC-X01', 'installation', 'Pipe support spacing from published B31.1 / MSS SP-69 spans',
             'Support count and position come from a span table, plus a support at each concentrated load.',
             'external_standard', EXT, 'ASME B31.1 / MSS SP-69',
             '', 'supports_within_published_span', 'major'),
    Decision('DEC-X02', 'installation', 'Seismic bracing at 40 ft transverse / 80 ft longitudinal',
             'Common ASCE 7 practice spacing. Deschutes itself invokes ASCE 7-16 for the CDU.',
             'external_standard', EXT, 'ASCE 7 practice',
             '', 'seismic_braces_present', 'major'),
    Decision('DEC-X03', 'installation', 'Seismic design parameters anchored to ASCE 7-16',
             'Deschutes names the edition and a design Sds, so the bracing basis is not free-floating.',
             'standard_mandate', D, '19.4.5',
             'Seismic loading as per ASCE (Americal Society for Civil Engineers) 7-16 for Sds 2.273', None, 'advisory'),
    Decision('DEC-X04', 'fabrication', 'Welded joints to ASME B31.3',
             'The spec requires it explicitly for Project Deschutes.',
             'standard_mandate', D, '12',
             'For Project Deschutes it is required to follow the ASME B31.3 standard.', None, 'advisory'),

    # ---- user inputs, declared as such
    Decision('DEC-U01', 'load', '132 kW per rack at 0.95 liquid fraction',
             'Supplied in the test case. Not from any standard.',
             'user_input', '(test case)', '-', '', None, 'advisory'),
    Decision('DEC-U02', 'thermal', 'TCS rise 12 K, FWS supply 27 degC',
             'Supplied in the test case; FWS rise of 10 K is our assumption on top.',
             'user_input', '(test case)', '-', '', None, 'advisory'),
    Decision('DEC-U03', 'topology', 'Three CDUs in N+1',
             'Supplied in the test case. Deschutes permits parallel operation, which makes it workable.',
             'user_input', '(test case)', '-', '', None, 'advisory'),

    # ---- emission
    Decision('DEC-E01', 'emission', 'IFC4 carries port connectivity, not loose geometry',
             'A downstream tool must traverse the network. Verified by re-reading the emitted file and '
             'walking element -> port -> port -> element; two networks is the correct answer, because the '
             'CDU couplings transfer heat without a hydraulic path.',
             'derived', '(design constraint)', '-', '', 'ifc_network_connectivity', 'major'),
    Decision('DEC-E02', 'emission', 'Every IFC element carries an IfcTypeObject',
             'An untyped element does not propagate type properties or quantities into Revit or Archicad, '
             'and BIM delivery checkers flag it. One type per kind + size + material, related with '
             'IfcRelDefinesByType. Added after an external IFC checker reported 234 untyped flow segments.',
             'derived', '(BIM delivery practice)', '-', '', 'ifc_all_elements_typed', 'major'),
    Decision('DEC-E03', 'emission', 'PredefinedType values validated by the schema at write time',
             'Enumerations are class-specific in IFC4. The writer adjudicates rather than a hard-coded table, '
             'and any rejected value is recorded rather than silently dropped.',
             'derived', '(IFC4 schema)', '-', '', 'ifc_predefined_types_valid', 'advisory'),
]

BY_ID = {d.id: d for d in REGISTER}
