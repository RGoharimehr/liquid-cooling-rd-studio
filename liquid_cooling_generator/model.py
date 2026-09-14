"""SI graph contract. Coordinates describe routing centre-lines, not fabrication envelopes."""
from dataclasses import dataclass, asdict, field
from typing import Any
import standards

def canonical_digest(value):
    """Stable across browser JSON round trips (for example 0.0 becomes 0)."""
    import hashlib, json
    def normalized(item):
        if isinstance(item, dict):
            return {key: normalized(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalized(val) for val in item]
        if type(item) is float and item.is_integer():
            return int(item)
        return item
    return hashlib.sha256(json.dumps(normalized(value), sort_keys=True, allow_nan=False).encode()).hexdigest()


@dataclass
class Config:
    rows: int = 4
    racks_per_row: int = 8
    rack_power_W: float = 132000.0
    liquid_fraction: float = .95
    network_rows: int = 2
    network_racks_per_row: int = 4
    network_rack_power_W: float = 20000.0
    network_high_power_count: int = 0
    network_high_power_W: float = 40000.0
    layout_style: str = 'side_gallery'
    return_topology: str = 'direct_return'
    cdu_placement: str = 'end_gallery'
    cdu_count: int = 3
    redundancy: int = 1
    cdu_origin_x_m: float = -4.1
    cdu_origin_y_m: float = -6.0
    cdu_pitch_m: float = 2.0
    rack_width_m: float = .7112
    rack_height_m: float = 2.2
    rack_pitch_m: float = .8
    rack_depth_m: float = 1.27
    aisle_width_m: float = 1.8288
    first_rack_x_m: float = 2.0
    network_rack_width_m: float = .6
    network_rack_depth_m: float = 1.2
    network_rack_height_m: float = 2.2
    network_rack_pitch_m: float = .8
    network_aisle_m: float = 1.2
    network_offset_x_m: float = 0.0
    network_offset_y_m: float = 0.0
    header_elevation_m: float = 4.0
    return_elevation_offset_m: float = .4
    manifold_elevation_m: float = 1.5
    header_half_separation_m: float = .35
    ceiling_height_m: float = 5.0
    rack_front_clearance_m: float = 1.2
    rack_rear_clearance_m: float = 1.0
    cdu_service_clearance_m: float = 1.0
    overhead_clearance_m: float = .2
    pipe_clear_gap_m: float = .05
    fitting_arm_m: float = .18
    bend_radius_m: float = .18
    include_rack_balancing_valves: bool = True
    include_quick_disconnects: bool = True
    include_rack_isolation_valves: bool = True
    include_supports: bool = True
    include_vents: bool = True
    include_drains: bool = True
    include_flex_connectors: bool = True
    include_leak_detection: bool = True
    include_drip_trays: bool = True
    include_seismic_braces: bool = False
    sizing_mode: str = 'manual'
    rack_nominal_in: float = 2.0
    row_nominal_in: float = 5.0
    tcs_main_nominal_in: float = 10.0
    tcs_cdu_nominal_in: float = 8.0
    fws_main_nominal_in: float = 10.0
    fws_cdu_nominal_in: float = 8.0
    tcs_header_material: str = 'stainless_sch10'
    tcs_branch_material: str = 'copper_type_l'
    fws_material: str = 'carbon_steel_sch40'
    tcs_header_velocity_cap_m_s: float = 2.7
    tcs_branch_velocity_cap_m_s: float = 1.5
    fws_velocity_cap_m_s: float = 3.0
    pg_volume_fraction: float = .25
    tcs_supply_C: float = 30.0
    tcs_delta_K: float = 12.0
    fws_supply_C: float = 27.0
    hx_approach_K: float = 3.0
    fws_delta_K: float = 10.0
    velocity_cap_m_s: float = 2.7
    standards_profile: str = 'project'
    standards_overrides: dict = field(default_factory=dict)
    pump_margin_fraction: float = .2
    initial_pipe_length_m: float = 1.0
    rack_load_dp_Pa: float = 50000.0
    manifold_dp_Pa: float = 5000.0
    qd_dp_Pa: float = 10000.0
    cdu_secondary_dp_Pa: float = 60000.0
    cdu_primary_dp_Pa: float = 50000.0
    strainer_dp_Pa: float = 15000.0

    cdu_width_m: float = 2.4
    cdu_depth_m: float = 1.0
    cdu_height_m: float = 2.2
    chiller_width_m: float = 4.0
    chiller_depth_m: float = 2.0
    chiller_height_m: float = 2.5
    plant_pump_width_m: float = 1.8
    plant_pump_depth_m: float = 1.0
    plant_pump_height_m: float = 1.0
    tower_width_m: float = 4.0
    tower_depth_m: float = 3.0
    tower_height_m: float = 3.0
    pod_elevation_spacing_m: float = 1.0
    pod_origins_m: list = field(default_factory=list)
    pod_rotations_deg: list = field(default_factory=list)
    pod_flip_x: list = field(default_factory=list)
    pod_flip_y: list = field(default_factory=list)
    network_rotation_deg: float = 0.0
    network_flip_x: bool = False
    network_flip_y: bool = False
    site_footprint_width_m: float = 0.0
    site_footprint_depth_m: float = 0.0
    site_footprint_origin_x_m: float = -45.0
    site_footprint_origin_y_m: float = -40.0
    flow_input_mode: str = 'lpm_per_kw'
    flow_lpm_per_kw: float = 1.2
    pump_efficiency: float = 0.7
    pump_head_margin_fraction: float = 0.15
    valve_design_dp_kPa: float = 20.0
    cdu_design_dp_kPa: float = 50.0
    cdu_available_head_kPa: float = 0.0
    rack_design_dp_kPa: float = 30.0
    chiller_design_dp_kPa: float = 50.0
    chiller_cop: float = 5.0
    tower_nozzle_dp_kPa: float = 30.0
    cws_static_lift_m: float = 0.0
    tcs_density_kg_m3: float = 1025.0
    tcs_specific_heat_J_kgK: float = 3900.0
    tcs_viscosity_Pa_s: float = 0.002
    fws_density_kg_m3: float = 998.0
    fws_specific_heat_J_kgK: float = 4180.0
    fws_viscosity_Pa_s: float = 0.001
    cws_density_kg_m3: float = 998.0
    cws_specific_heat_J_kgK: float = 4180.0
    cws_viscosity_Pa_s: float = 0.001
    schema_version: int = 2
    plant_type: str = 'boundary'
    pod_count: int = 1
    row_pod_assignments: list = field(default_factory=list)
    cdu_pod_assignments: list = field(default_factory=list)
    layout_origin_x_m: float = 0.0
    layout_origin_y_m: float = 0.0
    layout_rotation_deg: float = 0.0
    plant_origin_x_m: float = -20.0
    plant_origin_y_m: float = -16.0
    plant_elevation_m: float = 0.0
    plant_rotation_deg: float = 0.0
    plant_flip_x: bool = False
    plant_flip_y: bool = False
    air_unit_count: int = 2
    additional_air_load_W: float = 0.0
    air_unit_design_dp_kPa: float = 35.0
    fws_air_nominal_in: float = 2.0
    plant_header_elevation_m: float = 4.0
    plant_equipment_pitch_m: float = 6.0
    plant_service_clearance_m: float = 1.5
    route_optimizer: bool = False
    route_bend_cost_m: float = 1.5
    route_bundle_discount: float = .35
    route_corridor_m: float = 1.2
    route_pipe_clearance_m: float = .20
    route_equipment_clearance_m: float = 1.0
    route_avoid_overfly: bool = True
    chiller_count: int = 2
    chiller_spares: int = 1
    fws_pump_count: int = 2
    fws_pump_spares: int = 1
    cws_pump_count: int = 2
    cws_pump_spares: int = 1
    tower_count: int = 2
    tower_spares: int = 1
    cws_main_nominal_in: float = 10.0
    cws_material: str = 'carbon_steel_sch40'
    cws_supply_C: float = 30.0
    cws_delta_K: float = 5.0
    room_dew_point_C: float = 15.0
    tcs_class: str = 'S30'
    fws_class: str = 'W27'
    insulation_thickness_m: float = 0.0
    vendor_hose_min_bend_radius_m: float = 0.0
    vendor_rack_front_clearance_m: float = 0.0
    vendor_rack_rear_clearance_m: float = 0.0
    vendor_cdu_service_clearance_m: float = 0.0
    vendor_chiller_service_clearance_m: float = 0.0
    tcs_design_pressure_bar: float = 0.0
    fws_design_pressure_bar: float = 0.0
    cws_design_pressure_bar: float = 0.0

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict): raise ValueError('Expected a parameter object')
        values = dict(data)
        version = values.pop('schema_version', 1)
        if version not in (1, 2): raise ValueError('Unsupported parameter schema version')
        if version == 1: values.setdefault('plant_type', 'boundary')
        # The retired heat-balance mode produced a design with no pressure,
        # pump or valve results at all. Migrate it rather than rebuilding one.
        if values.get('sizing_mode') == 'heat_balance': values['sizing_mode'] = 'preliminary'
        return cls(schema_version=2, **values)

    def validate(self):
        import math
        for key in ('tcs_design_pressure_bar','fws_design_pressure_bar','cws_design_pressure_bar'):
            if type(getattr(self,key)) not in (int,float) or not math.isfinite(getattr(self,key)) or getattr(self,key)<0:
                raise ValueError(key+' must be a finite nonnegative design-envelope pressure; zero means unassigned')
        if self.schema_version != 2: raise ValueError('Use Config.from_dict to migrate legacy parameters')
        if self.plant_type not in ('boundary','air_cooled','water_cooled'): raise ValueError('Unknown plant type')
        if type(self.pod_count) is not int or not 1 <= self.pod_count <= min(self.rows,self.cdu_count): raise ValueError('Each pod needs at least one row and one CDU')
        for name,count in [('row_pod_assignments',self.rows),('cdu_pod_assignments',self.cdu_count)]:
            items=getattr(self,name)
            if not isinstance(items,list) or (items and (len(items)!=count or any(type(x) is not int or not 1<=x<=self.pod_count for x in items) or set(items)!=set(range(1,self.pod_count+1)))): raise ValueError(f'{name}: enter exactly {count} pod numbers between 1 and {self.pod_count}, including every pod, or use Balance pod assignments to restore automatic grouping.')
        if type(self.air_unit_count) is not int or not 1<=self.air_unit_count<=16:raise ValueError('Air cooling units: use 1–16 units. Each represents an aggregate CRAH/wall coil with external water connections.')
        for key in ('additional_air_load_W','air_unit_design_dp_kPa'):
            if type(getattr(self,key)) not in (int,float) or not math.isfinite(getattr(self,key)) or getattr(self,key)<0:raise ValueError(key+' must be finite and nonnegative')
        for key in ('pod_flip_x','pod_flip_y'):
            values=getattr(self,key)
            if not isinstance(values,list) or (values and (len(values)!=self.pod_count or any(type(v) is not bool for v in values))):raise ValueError(key+' must be empty or one true/false value per pod')
        for key in ('plant_flip_x','plant_flip_y','network_flip_x','network_flip_y','route_optimizer','route_avoid_overfly'):
            if type(getattr(self,key)) is not bool:raise ValueError(key+' must be true or false')
        for key in ('plant_rotation_deg','network_rotation_deg'):
            value=getattr(self,key)
            if type(value) not in (int,float) or not math.isfinite(value) or value%90:raise ValueError(key+': use multiples of 90 degrees so equipment ports stay orthogonal')
        for stem in ('chiller','fws_pump','cws_pump','tower'):
            count=getattr(self,stem+'_count');spares=getattr(self,stem+'_spares')
            if type(count) is not int or type(spares) is not int or not 1<=count<=8 or not 0<=spares<count: raise ValueError(stem+': use 1–8 units and fewer spares than units')
        for key in ('insulation_thickness_m','plant_service_clearance_m','vendor_hose_min_bend_radius_m','vendor_rack_front_clearance_m','vendor_rack_rear_clearance_m','vendor_cdu_service_clearance_m','vendor_chiller_service_clearance_m'):
            if getattr(self,key)<0: raise ValueError(key+' must be nonnegative')
        for key in ('cdu_width_m','cdu_depth_m','cdu_height_m','chiller_width_m','chiller_depth_m','chiller_height_m','plant_pump_width_m','plant_pump_depth_m','plant_pump_height_m','tower_width_m','tower_depth_m','tower_height_m'):
            if getattr(self,key)<=0: raise ValueError(key+' must be positive')
        if self.plant_equipment_pitch_m<5: raise ValueError('Plant equipment pitch requires at least 5 m for these concept envelopes')
        if not 0<=self.route_bundle_discount<.9: raise ValueError('route_bundle_discount must be in [0, 0.9): a full discount would make shared corridors free')
        for key in ('route_bend_cost_m','route_corridor_m','route_pipe_clearance_m','route_equipment_clearance_m'):
            if getattr(self,key)<0: raise ValueError(key+' must be nonnegative')
        if self.cws_delta_K<=0: raise ValueError('Condenser-water temperature difference must be positive')
        aliases={'header_supply_elevation_m':'header_elevation_m','vent_at_high_point':'include_vents',
                 'support_at_fitting':'include_supports','flexible_connection_at_rack':'include_flex_connectors',
                 'drip_tray_under_piping':'include_drip_trays','rack_width_m':'rack_width_m',
                 'rack_depth_m':'rack_depth_m','header_half_separation_m':'header_half_separation_m',
                 'return_elevation_offset_m':'return_elevation_offset_m',
                 'tcs_main.velocity_cap_m_s':'tcs_header_velocity_cap_m_s',
                 'tcs_row_header.velocity_cap_m_s':'tcs_header_velocity_cap_m_s',
                 'tcs_rack_branch.velocity_cap_m_s':'tcs_branch_velocity_cap_m_s',
                 'fws_main.velocity_cap_m_s':'fws_velocity_cap_m_s','fws_cdu.velocity_cap_m_s':'fws_velocity_cap_m_s'}
        if not isinstance(self.standards_overrides,dict):raise ValueError('standards_overrides must be an object')
        for k,v in self.standards_overrides.items():
            if k not in aliases: raise ValueError(f'Unsupported override {k!r}; use an advertised parameter. No override is silently ignored.')
            setattr(self,aliases[k],v)
        for k in ('rows','racks_per_row','network_rows','network_racks_per_row','network_high_power_count','cdu_count','redundancy'):
            if type(getattr(self,k)) is not int: raise ValueError(f'{k} must be an integer')
        if not 1<=self.rows<=16 or not 1<=self.racks_per_row<=40: raise ValueError('Compute layout supports 1–16 rows and 1–40 racks per row')
        if not 0<=self.network_rows<=8 or not 0<=self.network_racks_per_row<=40: raise ValueError('Invalid network-rack counts')
        if not 0<=self.network_high_power_count<=self.network_rows*self.network_racks_per_row: raise ValueError('High-power network count exceeds total network racks')
        if not 1<=self.cdu_count<=8 or not 0<=self.redundancy<self.cdu_count: raise ValueError('CDUs must be 1–8 with fewer spares than installed units')
        if math.comb(self.cdu_count,self.redundancy)>70: raise ValueError('Too many redundancy scenarios')
        if self.layout_style not in ('side_gallery','central_network','split_banks'): raise ValueError('Unknown layout style')
        if self.return_topology not in ('direct_return','reverse_return'): raise ValueError('Unknown return topology')
        if self.cdu_placement not in ('end_gallery','central_gallery','custom'): raise ValueError('Unknown CDU placement')
        if self.sizing_mode == 'heat_balance': raise ValueError("The heat_balance sizing mode is retired because it produced no pressure, pump or valve results; use 'preliminary' (Config.from_dict migrates it automatically)")
        if self.sizing_mode not in ('manual','preliminary'): raise ValueError('Select manual or preliminary sizing')
        if self.standards_profile not in ('project','deschutes_module','rd113_r0'): raise ValueError('Unknown standards profile')
        if self.pod_elevation_spacing_m<=0:raise ValueError('Pod elevation spacing must be positive')
        if self.flow_input_mode not in ('lpm_per_kw','heat_balance'):raise ValueError('Unknown flow input basis')
        for key in ('flow_lpm_per_kw','chiller_cop','tcs_density_kg_m3','tcs_specific_heat_J_kgK','tcs_viscosity_Pa_s','fws_density_kg_m3','fws_specific_heat_J_kgK','fws_viscosity_Pa_s','cws_density_kg_m3','cws_specific_heat_J_kgK','cws_viscosity_Pa_s'):
            if getattr(self,key)<=0:raise ValueError(key+' must be positive')
        if not 0<self.pump_efficiency<=1:raise ValueError('Pump total efficiency must be between 0 and 1')
        for key in ('pump_head_margin_fraction','valve_design_dp_kPa','cdu_design_dp_kPa','cdu_available_head_kPa','rack_design_dp_kPa','chiller_design_dp_kPa','cws_static_lift_m','tower_nozzle_dp_kPa','site_footprint_width_m','site_footprint_depth_m'):
            if getattr(self,key)<0:raise ValueError(key+' must be nonnegative')
        if bool(self.site_footprint_width_m)!=bool(self.site_footprint_depth_m):raise ValueError('Provide both footprint dimensions, or set both to zero for unrestricted placement')
        if not isinstance(self.pod_origins_m,list) or (self.pod_origins_m and (len(self.pod_origins_m)!=self.pod_count or any(not isinstance(p,list) or len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in self.pod_origins_m))):raise ValueError('Pod origins must be empty or one [x,y] pair per pod')
        if not isinstance(self.pod_rotations_deg,list) or (self.pod_rotations_deg and (len(self.pod_rotations_deg)!=self.pod_count or any(type(v) not in (int,float) or not math.isfinite(v) or v%90 for v in self.pod_rotations_deg))):raise ValueError('Pod rotations must be empty or one multiple of 90 degrees per pod')
        defaults=asdict(Config())
        for k,v in asdict(self).items():
            if isinstance(defaults[k],(int,float)) and not isinstance(defaults[k],bool) and type(v) not in (int,float):raise ValueError(f'{k} must be numeric')
            if isinstance(v,(int,float)) and not isinstance(v,bool) and not math.isfinite(v): raise ValueError(f'{k} must be finite')
            if k.startswith('include_') and type(v) is not bool: raise ValueError(f'{k} must be boolean')
        for k in ('rack_width_m','rack_height_m','rack_depth_m','network_rack_width_m','network_rack_depth_m','network_rack_height_m',
                  'ceiling_height_m','fitting_arm_m','bend_radius_m','rack_power_W','tcs_delta_K','fws_delta_K',
                  'tcs_header_velocity_cap_m_s','tcs_branch_velocity_cap_m_s','fws_velocity_cap_m_s','rack_nominal_in','row_nominal_in','tcs_main_nominal_in','tcs_cdu_nominal_in','fws_main_nominal_in','fws_cdu_nominal_in'):
            if getattr(self,k)<=0: raise ValueError(f'{k} must be positive')
        if not 0<=self.pg_volume_fraction<=.6:raise ValueError('PG volume fraction must be 0–0.6')
        for k in ('network_rack_power_W','network_high_power_W','manifold_elevation_m','network_aisle_m','rack_front_clearance_m','rack_rear_clearance_m','cdu_service_clearance_m','overhead_clearance_m','pipe_clear_gap_m'):
            if getattr(self,k)<0: raise ValueError(f'{k} must be nonnegative')
        if self.rack_pitch_m<self.rack_width_m or self.network_rack_pitch_m<self.network_rack_width_m: raise ValueError('Rack pitch must accommodate rack width')
        if self.cdu_pitch_m<1.0 or self.aisle_width_m<.6 or self.first_rack_x_m<1: raise ValueError('Layout is too small for reference equipment')
        if self.header_elevation_m-self.manifold_elevation_m<1.05: raise ValueError('Rack-drop assembly needs at least 1.05 m')
        if not 0<self.header_half_separation_m or self.return_elevation_offset_m<0: raise ValueError('Supply/return separation must be positive')
        if not 0<self.liquid_fraction<=1 or not 0<=self.pg_volume_fraction<1: raise ValueError('Invalid liquid or glycol fraction')
        if not .04<=self.fitting_arm_m<=.24 or not .04<=self.bend_radius_m<=.35: raise ValueError('Reference fitting envelopes support 0.04–0.24 m arms and 0.04–0.35 m bends; check diagnostics')


@dataclass
class Node:
    id: str
    kind: str
    route_hint_m: list[float]
    xyz_m: list[float] | None = None
    service: str = ''
    # A shared node is a hydraulic connection; never shared across TCS and FWS.


@dataclass
class Component:
    id: str
    tag: str
    kind: str
    service: str
    level: str
    ports: list[str]
    row: int | None = None
    rack: int | None = None
    cdu: int | None = None
    schematic_group: str = ''
    status: str = 'conceptual'
    assumptions: list[str] = field(default_factory=list)


@dataclass
class Edge:
    id: str
    component_id: str
    from_node: str
    to_node: str
    service: str
    level: str
    kind: str
    flow_m3_s: float
    design_flow_m3_s: float
    flow_basis: dict[str, Any]
    length_m: float = 0.0
    material: str = ''
    K: float = 0.0
    reference_dp_Pa: float = 0.0
    reference_flow_m3_s: float = 0.0
    row: int | None = None
    rack: int | None = None
    cdu: int | None = None
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass
class RoutedSizedEdge(Edge):
    """Stage 2/3 extension; all top-level loss results use design_flow_m3_s."""
    sizing_flow_m3_s: float = 0.0
    nominal_size_in: float = 0.0
    id_m: float = 0.0
    od_m: float = 0.0
    wall_m: float = 0.0
    required_id_m: float = 0.0
    size_standard: str = ''
    velocity_m_s: float = 0.0
    Re: float = 0.0  # dimensionless
    friction_factor: float = 0.0  # dimensionless Darcy factor
    straight_dp_Pa: float = 0.0
    fitting_dp_Pa: float = 0.0
    equipment_dp_Pa: float = 0.0
    dp_Pa: float = 0.0
    velocity_cap_pass: bool = False
    inlet_id_m: float | None = None  # reducers only
    K_reference_id_m: float | None = None  # smaller connected reducer bore
    hydraulic_result_basis: str = 'design_flow_m3_s'
    operating_results: dict[str, Any] = field(default_factory=dict)


@dataclass
class HeatExchangerCoupling:
    """Thermal link only: it must never create a hydraulic connection."""
    id: str
    primary_component: str
    secondary_component: str
    heat_W: float  # actual heat at all-three-online operation
    design_capacity_W: float  # installed capacity at N duty
    heat_basis: str
    mass_transfer_kg_s: float
    isolation_components: list[str]
    nonreturn_component: str
    component_ids: list[str]
    scenario_heat_W: dict[str, float]


@dataclass
class Graph:
    metadata: dict[str, Any]
    nodes: list[Node]
    components: list[Component]
    edges: list[Edge | RoutedSizedEdge]
    couplings: list[HeatExchangerCoupling]
    scenarios: list[dict[str, Any]]
    hydraulics: dict[str, Any]
    provenance: dict[str, Any]


def empty_graph(config: Config) -> dict:
    return {'metadata': {'schema_version': '2.0', 'units': 'SI; temperature C; nominal sizes in inches',
            'status': 'ENGINEERING CONCEPT - NOT FOR CONSTRUCTION', 'config': asdict(config),
            'graph_is_source_of_truth': True}, 'nodes': [], 'components': [], 'edges': [],
            'couplings': [], 'scenarios': [], 'hydraulics': {}, 'provenance': {}}


def build_profile(config: 'Config'):
    """Resolve the standards profile for this configuration."""
    from dataclasses import replace
    p=standards.Profile.default()
    p.config=config
    mapping={'rack_width_m':'rack_width_m','rack_depth_m':'rack_depth_m','header_supply_elevation_m':'header_elevation_m','return_elevation_offset_m':'return_elevation_offset_m','header_half_separation_m':'header_half_separation_m','manifold_elevation_m':'manifold_elevation_m','ceiling_height_min_m':'ceiling_height_m','rack_front_service_m':'rack_front_clearance_m','rack_rear_service_m':'rack_rear_clearance_m','cdu_service_clear_m':'cdu_service_clearance_m','overhead_rigging_clear_m':'overhead_clearance_m','vent_at_high_point':'include_vents','drain_at_low_point':'include_drains','support_at_fitting':'include_supports','flexible_connection_at_rack':'include_flex_connectors','leak_detection_at_rack':'include_leak_detection','drip_tray_under_piping':'include_drip_trays'}
    for key,field in mapping.items():
        if key in p.params:p.params[key]=replace(p.params[key],value=getattr(config,field))
    for name,cat in list(p.categories.items()):
        branch=name in ('tcs_rack','tcs_row_branch') or ('branch' in name)
        material=config.fws_material if cat.service=='FWS' else (config.tcs_branch_material if branch else config.tcs_header_material)
        cap=config.fws_velocity_cap_m_s if cat.service=='FWS' else (config.tcs_branch_velocity_cap_m_s if branch else config.tcs_header_velocity_cap_m_s)
        p.categories[name]=replace(cat,catalogue=material,velocity_cap_m_s=replace(cat.velocity_cap_m_s,value=cap,status='assumption',source='Project cap; final OCP Modular TCS 2025 discusses tradeoffs, not a universal numeric limit',clause='§3.5'))
    return p
