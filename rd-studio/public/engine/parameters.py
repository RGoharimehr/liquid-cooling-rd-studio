"""Active tuning controls, with explicit source scope rather than compliance claims."""
from dataclasses import asdict
from model import Config
from hydraulics import CATALOGUES
OCP='https://www.opencompute.org/documents/ocp-acf-reference-design-guidance-white-paper-pdf-1'
MANIFOLD='https://www.opencompute.org/documents/ocp-white-paper-rack-manifold-requirements-and-qualification-v3-pdf'
TCS='https://www.opencompute.org/documents/ocp-modular-tcs-rev-1-final-2025-pdf'
RD='https://www.se.com/sg/en/download/document/RD113DS/'
EXCLUDED={'standards_overrides','hx_approach_K','schema_version'}
OPTIONS={'layout_style':['side_gallery','central_network','split_banks'],'return_topology':['direct_return','reverse_return'],'cdu_placement':['end_gallery','central_gallery','custom'],'sizing_mode':['manual','preliminary'],'flow_input_mode':['lpm_per_kw','heat_balance'],'standards_profile':['project','deschutes_module','rd113_r1'],'plant_type':['boundary','air_cooled','water_cooled'],'tcs_class':['S20','S25','S30','S35','S40','S45','S50'],'fws_class':['W17','W27','W32','W40','W45','W+']}
RANGES={'rows':(1,16,1),'racks_per_row':(1,40,1),'network_rows':(0,8,1),'network_racks_per_row':(0,40,1),'network_high_power_count':(0,320,1),'cdu_count':(1,8,1),'redundancy':(0,7,1),'liquid_fraction':(.01,1,.01),'pg_volume_fraction':(0,.6,.01),'fitting_arm_m':(.04,.24,.01),'bend_radius_m':(.04,.35,.01),'rack_power_W':(1,1000000,1000),'network_rack_power_W':(0,1000000,1000),'network_high_power_W':(0,1000000,1000),'aisle_width_m':(.6,10,.05),'first_rack_x_m':(1,50,.1),'cdu_pitch_m':(1,20,.1)}
LABELS={'rows':'Compute rows','racks_per_row':'Compute racks per row','layout_style':'Layout arrangement','return_topology':'Return-pipe topology','cdu_placement':'CDU placement','rack_power_W':'Compute rack power','network_high_power_count':'High-power network racks','network_high_power_W':'High-power rack rating','standards_profile':'Reference comparison','pg_volume_fraction':'PG volume fraction'}

def catalog():
    result=[]
    for key,value in asdict(Config()).items():
        if key in EXCLUDED or key in ('manifold_elevation_m','vendor_hose_min_bend_radius_m'):continue
        group='Layout'
        if key.startswith('network_'):group='Network racks'
        elif key.startswith(('plant_','chiller_','fws_pump_','cws_','tower_')):group='Plant'
        elif key in ('pod_count','row_pod_assignments','cdu_pod_assignments','pod_origins_m','pod_rotations_deg','pod_elevation_spacing_m'):group='Cooling pods'
        elif key.startswith('cdu_') or key=='redundancy':group='CDUs'
        elif key.startswith('include_') or 'clearance' in key or 'clear_gap' in key:group='Installation'
        elif 'nominal' in key or 'material' in key or 'velocity_cap' in key or key=='sizing_mode':group='Piping'
        elif key.startswith(('tcs_','fws_','pg_')) or key in ('rack_power_W','liquid_fraction'):group='Design duty'
        sizing_keys={'flow_input_mode','flow_lpm_per_kw','pump_efficiency','pump_head_margin_fraction','valve_design_dp_kPa','cdu_design_dp_kPa','rack_design_dp_kPa','chiller_design_dp_kPa','chiller_cop','tower_nozzle_dp_kPa','cws_static_lift_m'}
        is_sizing=key in sizing_keys or key.endswith(('density_kg_m3','specific_heat_J_kgK','viscosity_Pa_s'))
        if is_sizing:group='Sizing estimates'
        unit='m' if key.endswith('_m') else ('in' if key.endswith('_in') else ('W' if key.endswith('_W') else ('°C' if key.endswith('_C') else ('K' if key.endswith('_K') else ('m/s' if key.endswith('_m_s') else '')))))
        label=LABELS.get(key,key.removeprefix('include_').removesuffix('_m_s').removesuffix('_m').removesuffix('_in').removesuffix('_W').removesuffix('_C').removesuffix('_K').replace('_',' ').replace('tcs','TCS').replace('fws','FWS').replace('cdu','CDU').capitalize())
        note='Configurable project assumption; no universal standard value is claimed.';title='Project design input';url='';clause='';status='assumption'
        if group=='Installation':
            title='OCP ACF layout guidance';url=OCP;clause='Layout Planning, p.9';note='Guidance calls for installation and operating clearance. The numeric allowance and accessory selection are project assumptions; verify equipment/vendor requirements.'
        if key in ('include_quick_disconnects','include_flex_connectors','include_rack_isolation_valves','include_rack_balancing_valves'):
            title='OCP rack manifold guidance';url=MANIFOLD;clause='Plumbing/serviceability, p.16';note='Guidance supports serviceable plumbing, local flow control and quick couplings. Component counts and hose envelopes are project assumptions.'
        if 'velocity_cap' in key:
            title='OCP Modular TCS, final 2025';url=TCS;clause='§3.5';note='Final guidance discusses velocity tradeoffs; these numeric caps are project assumptions, not mandatory OCP limits. Preliminary sizing rounds each pipe family up to them; Manual sizing keeps the entered bore and reports the exceedance.'
        if key=='aisle_width_m':
            title='RD113 R0, attached reference';url=RD;clause='p.5, hot aisle';note='Default 1.8288 m equals the 6 ft hot aisle in R0. Applied as a configurable shared aisle here; cold-aisle/service allowances require project review. Public page now serves a newer revision.';status='reference'
        if key.startswith('rack_') and key.endswith(('width_m','depth_m')):
            title='OCP Deschutes example';clause='§18.1, partial local extract';note='Default derives from one module example, not a universal rack dimension. The local excerpt is indicative; confirm the original module specification.'
        if 'nominal' in key or 'material' in key:
            title='Commercial pipe dimension catalogues';clause='ASME B36.19M/B36.10M; ASTM B88';note='Nominal selections are project inputs. OD/ID dimensions come from the selected catalogue; wetted-material compatibility and vendor connector sizes require verification.'
        if key in ('tcs_supply_C','tcs_delta_K','fws_supply_C','fws_delta_K','pg_volume_fraction'):
            note='Stored design condition. Enter the density, specific heat and viscosity that match this formulation at its mean temperature under Sizing estimates; they are used exactly as entered and are not checked against a property table.'
        if key=='cdu_origin_y_m':note='Used only with custom CDU placement. End and central galleries calculate their Y origin from the layout.'
        field={'key':key,'label':label,'group':group,'type':'boolean' if isinstance(value,bool) else ('select' if isinstance(value,str) else 'json' if isinstance(value,list) else 'number'),'unit':unit,'default':value,'source':{'title':title,'url':url,'clause':clause,'status':status,'note':note}}
        from guidance import SOURCES
        selected=None
        if key.startswith('vendor_'):selected=SOURCES[-1]
        elif key in ('room_dew_point_C','tcs_class','tcs_supply_C'):selected=SOURCES[2]
        elif key in ('fws_class','fws_supply_C'):selected=SOURCES[1]
        elif key in ('plant_type','pod_count','row_pod_assignments','cdu_pod_assignments') or group=='Plant':selected=SOURCES[0]
        if selected:
            field['source']={**selected,'status':'vendor_requirement' if key.startswith('vendor_') else 'assumption','note':'Tunable project value informed by the cited guidance; equipment model, site conditions and vendor limits determine applicability.'}
        field['source'].setdefault('edition','See cited source; project defaults are not universal limits')
        field['source'].setdefault('applicability','Selected reference design')
        if key=='cdu_origin_y_m':field['active_when']={'cdu_placement':'custom'}
        if key.startswith(('cws_','tower_')):field['active_when']={'plant_type':'water_cooled'}
        if key.startswith('plant_') and key!='plant_type':field['active_when']={'plant_type':['air_cooled','water_cooled']}
        if key in ('manifold_elevation_m','include_flex_connectors','vendor_hose_min_bend_radius_m'):field['source']['note']='Reserved rack interface/vendor input. Server manifolds and routed hoses are outside the aggregate rack representation.'
        if key.startswith(('chiller_','fws_pump_')) and not is_sizing:field['active_when']={'plant_type':['air_cooled','water_cooled']}
        if key.endswith('_nominal_in'):field['active_when']={'sizing_mode':'manual'}
        if is_sizing:
            field['active_when']={'sizing_mode':'preliminary'}
            field['source']={'title':'ASHRAE Fundamentals · flow and piping','edition':'2025 Handbook—Fundamentals','clause':'Ch. 3 Fluid Flow; Ch. 22 Pipe and Tube Design','status':'assumption','applicability':'Prescribed-flow screening with manual or automatically rounded pipe dimensions','url':'https://handbook.ashrae.org/Handbooks/F25/SI/F25_Ch22/F25_Ch22_si.aspx','note':'Method supported by the source; this numeric input is a project assumption. Fluid properties must match the selected formulation and mean temperature. Equipment losses and efficiency require vendor confirmation.'}
        if key=='flow_lpm_per_kw':
            field['unit']='L/min per liquid kW';field['source'].update(title='OCP OAI liquid-cooling example',edition='March 2023',clause='§1.3',url='https://www.opencompute.org/documents/oai-system-liquid-cooling-guidelines-in-ocp-template-mar-3-2023-update-pdf',note='The selected ratio is a project input. OAI PG25 guidance gives an example1.25–2.0 range, typical1.5 at10K; it is not a universal rack rule.140 liquid kW×1.2=168L/min.');field['active_when']={'sizing_mode':'preliminary','flow_input_mode':'lpm_per_kw'}
        if key.endswith('rotation_deg') or key=='pod_rotations_deg':field['unit']='°'
        if key.endswith('_kPa'):field['unit']='kPa'
        if key.endswith('density_kg_m3'):field['unit']='kg/m³'
        if key.endswith('specific_heat_J_kgK'):field['unit']='J/(kg·K)'
        if key.endswith('viscosity_Pa_s'):field['unit']='Pa·s'
        if key in ('pump_efficiency','pump_head_margin_fraction'):field['unit']='fraction'
        if key.startswith('site_footprint'):field['source']['note']='Project site boundary in world XY coordinates. Set width and depth to zero to leave the footprint unconstrained; this is not a property-line or code certification.'
        if isinstance(value,list):field['type']='json'
        elif isinstance(value,str):field['options']=OPTIONS.get(key,list(CATALOGUES))
        elif not isinstance(value,bool):
            low,high,step=RANGES.get(key,(-100,100,.1) if any(x in key for x in ('origin_','offset_','supply_C')) else (0,100,.05))
            field.update(min=low,max=high,step=step)
            if 'nominal' in key:field.update(min=1,max=16,step=.25)
        if (key.endswith(('_count','_spares')) and not key.startswith('network_')) or key=='pod_count':field.update(min=0 if key.endswith('_spares') else 1,max=8,step=1)
        if key.endswith('rotation_deg'):field.update(min=-360,max=360,step=90 if key=='plant_rotation_deg' else 1)
        if key.endswith('density_kg_m3'):field.update(min=1,max=2500,step=1)
        if key.endswith('specific_heat_J_kgK'):field.update(min=1,max=10000,step=10)
        if key.endswith('viscosity_Pa_s'):field.update(min=.000001,max=1,step=.0001)
        if key.endswith('_kPa'):field.update(min=0,max=1000,step=1)
        if key in ('pump_efficiency','pump_head_margin_fraction'):field.update(min=.01 if key=='pump_efficiency' else 0,max=1,step=.01)
        if key=='flow_lpm_per_kw':field.update(min=.01,max=10,step=.05)
        if key=='sizing_mode':field['source']['note']='Both modes calculate declared heat/flow duties, rough pressure loss, pump head/power and valve Kv/Cv. Manual retains selected commercial bores; Preliminary also rounds pipe families up for velocity limits. Neither mode balances or solves a fluid network.'
        if key.endswith('_design_pressure_bar'):
            field.update(group='Design duty',unit='bar',min=0,max=100,step=.5)
            field['label']=key[:3].upper()+' minimum equipment pressure rating'
            field['source']={'title':'RD project pressure envelope','edition':'Project input','clause':'Equipment working-pressure requirement','status':'assumption','applicability':'Selected fluid circuit; zero means unassigned','url':'','note':'Provide the required working-pressure rating from the project design envelope, including fill, static elevation, pump shutoff and transient allowances. RD owns this requirement; the finder only compares published ratings. Routed pressure loss alone cannot determine it. Zero leaves catalogue pressure qualification unresolved.'}
        if key.endswith('_nominal_in'):
            material_key='tcs_branch_material' if key in ('rack_nominal_in',) else 'tcs_header_material' if key.startswith('tcs_') or key=='row_nominal_in' else 'cws_material' if key.startswith('cws_') else 'fws_material'
            field['nominal_material_parameter']=material_key
            field['nominal_options']={name:[row[0] for row in values[0]] for name,values in CATALOGUES.items()}
            field.update(min=1,max=24)
        if key=='valve_design_dp_kPa':field['min']=.01
        if key in ('cdu_nominal_flow_L_min','cdu_rated_capacity_kW'):
            field['group']='CDUs'
            field['label']={'cdu_nominal_flow_L_min':'CDU nominal secondary flow','cdu_rated_capacity_kW':'CDU rated capacity'}[key]
            field['unit']={'cdu_nominal_flow_L_min':'L/min','cdu_rated_capacity_kW':'kW'}[key]
            field.update(min=0,max=100000 if key.endswith('_kW') else 20000,step=10)
            field['source']={'title':'Selected CDU published data','edition':'Manufacturer selection table','clause':'Nominal flowrate and rated cooling capacity','status':'vendor_requirement','applicability':'Acceptance limits for the CDU capacity screen','url':'','note':'The flow and duty the selected unit is published to carry, at the rating condition that matches this design. The screen reports whether the required head, flow and capacity all fit; any one short and the unit does not suit. Zero leaves that check unassigned.'}
        if key=='cdu_available_head_kPa':
            field['label']='CDU available secondary head'
            field['source']={'title':'Selected CDU published data','edition':'Manufacturer selection table','clause':'Nominal available pump head pressure','status':'vendor_requirement','applicability':'Acceptance limit for the TCS circuit pressure screen','url':'','note':'The head the selected CDU offers to the technology-cooling loop, from its own published data. The circuit screen is checked against this instead of a reference unit. Zero leaves the check on the reference figure. This is not the CDU internal pressure drop; that is cdu_design_dp_kPa.'}
        from parameter_semantics import describe
        result.append(describe(field))
    return result

DEFAULT=asdict(Config(plant_type='air_cooled',ceiling_height_m=8.0,bend_radius_m=.24,fitting_arm_m=.24,return_elevation_offset_m=.5))
PRESETS={
 'compact':{'label':'Compact reference','description':'32 compute + 8 air-cooled network racks. Shared CDU group and project clearance assumptions.','config':DEFAULT},
 'rd113':{'label':'RD113 R1 · equipment-list reference','description':'64 AI racks at the Max-Q 188 kW rack power, 32 networking racks totalling 880 kW, 8 Motivair MCDU-70 CDUs in two pods, 4 Uniflair fan walls. Counts, equipment and operating temperatures follow the supplied RD113 R1 documents; see references/rd113_r1. Pipe sizes, pump duties and valve coefficients are not published in that set and remain this generator\'s own estimates.','config':{**DEFAULT,'rows':4,'racks_per_row':16,'rack_power_W':188000.,'layout_style':'central_network',
  # The generic default bores belong to a 4 MW hall. Left on manual this preset
  # ships pipes far too small for its own load, so it selects its own sizes.
  'sizing_mode':'preliminary',
  # RD113_4.2 R1: NetShelter Open Architecture MGX, 600 mm wide, 1200 mm deep,
  # 48U - for both the AI and the networking racks. The preset previously
  # carried the 711 mm OCP Deschutes rack, which the profile now reports as a
  # deviation from the dimensions RD113 actually publishes.
  'rack_width_m':.6,'rack_depth_m':1.2,'cdu_count':8,'redundancy':2,'pod_count':2,'ceiling_height_m':6.5,'standards_profile':'rd113_r1','network_aisle_m':1.8288,
  # RD113_2.5 R1: 8 SMN + 8 N/S at 15 kW, 8 CME at 35 kW, 8 CIN at 45 kW = 32
  # racks, 880 kW. The generator supports one base power plus one high-power
  # band, so the 16 high racks carry their exact 40 kW average (8x35 + 8x45).
  'network_rows':2,'network_racks_per_row':16,'network_rack_power_W':15000.,
  'network_high_power_count':16,'network_high_power_W':40000.,
  # RD113_4.2 R1 and RD113_3.3: 4 fan walls, 2 chillers N+1, 6 adiabatic fluid
  # coolers N+1 (Dallas), CWP1-6 in two banks of three.
  # CWP1-6 are two banks of three. The generator lays a pump bank out along +Y
  # from the plant origin, and from the third unit the bank crosses the chiller
  # supply and return collectors at py+4 and py+6 at the same elevation, which
  # its own clearance check correctly rejects. Until the bank geometry is fixed
  # the preset carries two per bank; see references/benchmarks/rd113_r1.json.
  # Motivair MCDU-70 selection table: 38 psi available head, 991 GPM nominal
  # secondary flow, 2500 kW at primary 105.8 F / secondary PG25 113 F - which is
  # this design's own FWS 40 C and TCS 45 C.
  'cdu_available_head_kPa':262.,'cdu_nominal_flow_L_min':3750.,'cdu_rated_capacity_kW':2500.,
  'air_unit_count':4,'chiller_count':2,'chiller_spares':1,'tower_count':6,'tower_spares':1,
  'fws_pump_count':2,'fws_pump_spares':1,'cws_pump_count':2,'cws_pump_spares':1,
  # R0 p4/p9: compute 96% liquid, TCS 45/55 C, FWS 40/50 C. The preset carried
  # the generic 30/42 and 27/37 defaults until benchmark.py compared it with the
  # extracted source, which is a 15 K error in the design condition it claims.
  'liquid_fraction':.96,'tcs_supply_C':45.,'tcs_delta_K':10.,'fws_supply_C':40.,'fws_delta_K':10.,
  'hx_approach_K':5.,'tcs_class':'S45','fws_class':'W40',
  # R0 publishes no flow rate, so the preset derives it from the temperatures it
  # does publish rather than carrying a prescribed 1.2 L/min per kW that implies
  # a 12.5 K rise against the stated 10 K.
  'flow_input_mode':'heat_balance'}},
 'split':{'label':'Split banks · reverse return','description':'48 compute + 8 network racks. Wider center gap and reverse-return piping; project layout assumption.','config':{**DEFAULT,'rows':4,'racks_per_row':12,'layout_style':'split_banks','return_topology':'reverse_return','cdu_count':4,'redundancy':1,'ceiling_height_m':5.8}},
}
