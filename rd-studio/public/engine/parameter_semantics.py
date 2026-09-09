"""One UI contract for each input: effect, dependency and where it is changed."""
PLANT=['air_cooled','water_cooled']
POD_ARRAYS=('pod_origins_m','pod_rotations_deg','pod_flip_x','pod_flip_y')

def describe(field):
    k=field['key']; active={}; effect='Changes generated geometry when you Apply design.'
    if k in ('layout_style','cdu_placement','return_topology'):
        field['group']='Arrangement'
        descriptions={
          'layout_style':('Rack arrangement','Side gallery: network racks beyond compute rows. Central network: network racks between compute banks. Split banks: an open corridor separates compute banks. This controls rack geometry only.'),
          'cdu_placement':('CDU gallery position','End gallery: automatic Y beyond the rows. Central gallery: automatic Y beside the row midpoint. Custom: use CDU X/Y. Cooling-pod assignments remain independent.'),
          'return_topology':('Return pipe order','Direct return pairs the nearest supply/return branches. Reverse return routes the row return around the far end. Equipment locations stay defined by the arrangement.')}
        field['label'],effect=descriptions[k]
    if k=='standards_profile':field.update(group='Checks & criteria',label='Reference checks');effect='Selects reference-specific diagnostic checks. Use Starting reference to load equipment counts and geometry; this control does not load a layout.'
    if k.startswith('layout_') and k!='layout_style':field['group']='Site placement';effect='Moves or rotates the complete model in world coordinates, including the plant. The plan origin marker and exported coordinates show the change.'
    if k.startswith('site_footprint'):field['group']='Site placement';effect='Defines the fixed world-coordinate boundary used by placement checks. Both dimensions must be positive; zero disables the boundary.'
    if k in POD_ARRAYS:field['group']='Cooling pods';effect='Explicit pod transforms; empty uses automatic placement. Plan → Arrange zones edits these same values.'
    if k.startswith('plant_') and k!='plant_type':active['plant_type']=PLANT
    if k.startswith(('chiller_','fws_pump_')):active['plant_type']=PLANT
    if k.startswith(('cws_','tower_')) or k=='chiller_cop':active['plant_type']='water_cooled'
    if k.startswith('network_') and k not in ('network_rows','network_racks_per_row'):
        field['requires_nonzero']=['network_rows','network_racks_per_row']
    if k=='network_high_power_W':field['requires_nonzero']=['network_high_power_count']
    if k.startswith('network_') and any(v in k for v in ('offset','rotation','flip')):effect='Transforms the network-rack zone; Plan → Arrange zones edits these same placement inputs.'
    if k in ('cdu_origin_x_m','cdu_origin_y_m','cdu_pitch_m'):
        effect='Controls the CDU gallery within each cooling pod. End and central galleries calculate Y automatically; custom gallery uses the entered X/Y.'
        if k=='cdu_origin_y_m':active['cdu_placement']='custom'
    if k.startswith('route_'):
        field['group']='Routing';active['plant_type']=PLANT
        if k!='route_optimizer':active['route_optimizer']=True
        effect='Controls the bounded plant corridor router. Design actions → Try shorter plant routes tests candidates and reports measured changes; it does not prove a global optimum.'
    if k.endswith('_nominal_in'):
        active['sizing_mode']='manual';effect='Sets this pipe family’s commercial nominal size in Manual mode. Preliminary mode calculates and rounds its size instead.'
    if 'velocity_cap' in k:active['sizing_mode']='preliminary';effect='Limits velocity for pipe-family sizing. The selected standard size changes only when the calculated bore crosses a catalogue-size threshold.'
    if k.endswith('_material'):effect='Selects commercial dimensions and roughness for this pipe family. Material compatibility remains subject to vendor review.'
    sizing=('flow_input_mode','flow_lpm_per_kw','pump_efficiency','pump_head_margin_fraction','valve_design_dp_kPa','cdu_design_dp_kPa','rack_design_dp_kPa','chiller_design_dp_kPa','air_unit_design_dp_kPa','chiller_cop','tower_nozzle_dp_kPa','cws_static_lift_m')
    if k in sizing or k.endswith(('density_kg_m3','specific_heat_J_kgK','viscosity_Pa_s')):
        active['sizing_mode']='preliminary';effect='Changes the prescribed-flow sizing report and downstream equipment requirements; it may not change equipment positions.'
    if k=='flow_lpm_per_kw':active['flow_input_mode']='lpm_per_kw'
    if k=='tcs_delta_K':
        effect='Design TCS temperature-rise criterion. In heat-balance mode it sets flow; in L/min per kW mode the calculated rise is reported separately.'
    if k=='tcs_specific_heat_J_kgK':effect='Used in heat balance and implied TCS temperature rise. L/min per kW mode sets TCS flow independently.'
    if k in ('tcs_supply_C','fws_supply_C','cws_supply_C','pg_volume_fraction'):
        effect='Sets declared operating conditions for temperature/compatibility checks and finder requirements. Enter fluid properties separately for the selected mixture and temperature; no automatic property interpolation is claimed.'
        field['source']['note']=effect
    if k in ('tcs_class','fws_class','room_dew_point_C'):
        field['group']='Checks & criteria';effect='Changes the temperature-class or condensation diagnostic. It does not overwrite supply temperature or calculate flow from the class.'
    if k.startswith('vendor_') and 'clearance' in k:
        field['group']='Installation';effect='Expands the service envelope to the larger of the project allowance and this vendor minimum, and checks obstructions. Zero means the vendor requirement is unassigned.'
    if k.endswith('_design_pressure_bar'):
        effect='Sets the minimum working-pressure rating used by equipment matching. It is separate from routed pressure loss and does not resize geometry.'
    if k=='include_flex_connectors':effect='Adds/removes abstract external flexible connections at each rack; vendor hose bends and internal server routing remain unresolved.'
    if k.startswith('include_') and k not in ('include_rack_balancing_valves','include_quick_disconnects','include_rack_isolation_valves','include_flex_connectors'):
        effect='Adds/removes installation accessories. Enable Accessories above the canvas to see them; they remain in the graph and exports.'
    if k in ('air_unit_count','additional_air_load_W','air_unit_design_dp_kPa'):
        field['group']='Air cooling';field['source']={'title':'Project air-cooling design input','edition':'Project input','clause':'Residual compute + network + additional room load','status':'assumption','applicability':'Aggregate water-cooled CRAH/wall coils; manufacturer performance unresolved','url':'','note':'Residual compute and network heat are counted once in plant duty. Additional load excludes those rack loads. Coils must be selected for the declared water/air operating conditions.'}
        if k=='air_unit_count':field.update(min=1,max=16,step=1);effect='Changes the number of connected aggregate CRAH/wall-coil units and divides the air load between them.'
        if k=='additional_air_load_W':field.update(min=0,max=10000000,step=1000);effect='Adds room/auxiliary heat to the air-unit and chiller duty. Compute residual heat and network racks are already counted automatically.'
    if k=='fitting_arm_m':field['label']='Tee takeoff length';effect='Sets the straight takeoff envelope of tees. Elbow bend radius is a separate fitting dimension.'
    if k=='bend_radius_m':field['label']='Elbow centreline radius';effect='Sets elbow geometry and required straight takeoffs. Insufficient space produces component-specific routing diagnostics.'
    if k in ('pod_elevation_spacing_m',):field['requires_multiple']=['pod_count']
    if k.endswith('rotation_deg'):field.update(min=-360,max=360,step=90 if k!='layout_rotation_deg' else 1)
    if active:field['active_when']=active
    else:field.pop('active_when',None)
    field['effect']=effect
    return field
