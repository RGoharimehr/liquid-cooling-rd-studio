"""Design-flow sizing and path losses. This is not a nonlinear network/pump solver."""
import math
from collections import defaultdict

FLUIDS = {
 'TCS': {'rho_kg_m3': 1017.5632747528, 'cp_J_kg_K': 3952.5072241237, 'mu_Pa_s': .00157,
         'temperature_C': 36.0, 'source': 'Dynalene PG 2020 tables, 25 vol%, interpolate 90/100 F at 96.8 F',
         'status': 'sourced/interpolated; ASSUMPTION: this inhibited formulation represents selected coolant'},
 'FWS': {'rho_kg_m3': 995.0, 'cp_J_kg_K': 4178.0, 'mu_Pa_s': .00077,
         'temperature_C': 32.0, 'source': 'ASSUMPTION: rounded water properties near 32 C', 'status': 'assumed'}
}
# Commercial dimensions in inches. Copper Development Association Type L table;
# carbon steel ASME B36.10M Schedule 40 dimensions as reproduced by manufacturer.
COPPER = [(1,1.125,.050),(1.25,1.375,.055),(1.5,1.625,.060),(2,2.125,.070),
          (2.5,2.625,.080),(3,3.125,.090),(3.5,3.625,.100),(4,4.125,.110),
          (5,5.125,.125),(6,6.125,.140)]
STEEL = [(2,2.375,.154),(2.5,2.875,.203),(3,3.5,.216),(3.5,4,.226),
         (4,4.5,.237),(5,5.563,.258),(6,6.625,.280),(8,8.625,.322),
         (10,10.75,.365),(12,12.75,.406),(14,14,.438),
         (16,16,.500),(18,18,.562),(20,20,.594),(24,24,.688)]
# NPS 16–24 are cross-checked against Weldbend's Schedule 40 reducer
# dimensions (OD, ID and wall). These dimensions do not establish pressure rating.
STEEL_DIMENSION_SOURCE = 'https://weldbend.com/catalog.pdf'
# ASME B36.19M Schedule 10S stainless, the TCS header material CloudScale 3.4/3.5
# frames its erosion-corrosion and pipe-selection discussion around.
STAINLESS = [(1,1.315,.109),(1.25,1.66,.109),(1.5,1.9,.109),(2,2.375,.109),
             (2.5,2.875,.120),(3,3.5,.120),(3.5,4,.120),(4,4.5,.120),
             (5,5.563,.134),(6,6.625,.134),(8,8.625,.148),(10,10.75,.165),
             (12,12.75,.180),(14,14,.188),(16,16,.188)]
CATALOGUES = {'copper_type_l':(COPPER,'ASTM B88 Type L (CDA dimensions)'),
              'carbon_steel_sch40':(STEEL,'ASME B36.10M Schedule 40 (manufacturer dimensions)'),
              'stainless_sch10':(STAINLESS,'ASME B36.19M Schedule 10S')}


def heat_flows(c):
    from air_cooling import heat_ledger
    ledger=heat_ledger(c)
    heat_rack=c.rack_power_W*c.liquid_fraction
    heat_total=heat_rack*c.rows*c.racks_per_row
    t=FLUIDS['TCS']; f=FLUIDS['FWS']
    t_mass=heat_total/(t['cp_J_kg_K']*c.tcs_delta_K)
    f_mass=heat_total/(f['cp_J_kg_K']*c.fws_delta_K)
    plant_mass=ledger['chiller_W']/(f['cp_J_kg_K']*c.fws_delta_K)
    return {'rack_heat_W':heat_rack,'row_heat_W':heat_rack*c.racks_per_row,
            'total_heat_W':heat_total,'air_heat_W':ledger['air_W'],'chiller_heat_W':ledger['chiller_W'],
            'cdu_duty_heat_W':heat_total/(c.cdu_count-c.redundancy),
            'tcs_total_mass_kg_s':t_mass,'tcs_total_m3_s':t_mass/t['rho_kg_m3'],
            'fws_total_mass_kg_s':plant_mass,'fws_total_m3_s':plant_mass/f['rho_kg_m3'],
            'fws_cdu_total_m3_s':f_mass/f['rho_kg_m3'],
            'rack_mass_kg_s':t_mass/(c.rows*c.racks_per_row),
            'rack_m3_s':t_mass/t['rho_kg_m3']/(c.rows*c.racks_per_row),
            'row_mass_kg_s':t_mass/c.rows,'row_m3_s':t_mass/t['rho_kg_m3']/c.rows,
            'cdu_secondary_mass_kg_s':t_mass/(c.cdu_count-c.redundancy),
            'cdu_secondary_m3_s':t_mass/t['rho_kg_m3']/(c.cdu_count-c.redundancy),
            'cdu_primary_mass_kg_s':f_mass/(c.cdu_count-c.redundancy),
            'cdu_primary_m3_s':f_mass/f['rho_kg_m3']/(c.cdu_count-c.redundancy)}


class NoCatalogueSize(ValueError):
    """A recoverable design limit with enough information to change inputs."""
    def __init__(self, flow, material, cap):
        table, standard = CATALOGUES[material]
        nominal, od, wall = table[-1]
        bore = (od - 2 * wall) * .0254
        maximum = math.pi * bore * bore / 4 * cap
        required = math.sqrt(4 * flow / (math.pi * cap))
        self.diagnostic = {
            'code': 'NO_CATALOGUE_SIZE', 'material': material,
            'flow_m3_s': flow, 'flow_L_min': flow * 60000,
            'velocity_cap_m_s': cap, 'required_id_m': required,
            'largest_supported_nominal_in': nominal, 'largest_supported_id_m': bore,
            'largest_supported_capacity_m3_s': maximum,
            'minimum_parallel_runs_at_largest_size': max(1, math.ceil(flow / maximum)),
            'actions': [
                'Check rack count, heat load and flow-per-kW or temperature-difference inputs for this circuit.',
                'Split the affected circuit into separately routed headers or cooling pods; adding CDUs alone does not reduce shared-main flow.',
                'Select a compatible pipe family with a larger supported bore, or extend the verified dimension catalogue.',
                'Only raise the velocity limit after the project material, erosion, noise and pressure-loss criteria have been reviewed.'],
            'scope': 'Preview retains the previous/manual bore for this family; it is not a valid sized pipe.'}
        super().__init__(f'{flow*60000:,.0f} L/min needs at least {required*1000:.1f} mm inside diameter at {cap:g} m/s. '
            f'{material} currently supports up to NPS {nominal:g} ({bore*1000:.1f} mm ID, {maximum*60000:,.0f} L/min). '
            'Reduce the circuit demand, split its headers, or choose a compatible larger-bore catalogue. The design remains editable.')


def select_size(flow,material,cap):
    """Round up to a commercial bore. `cap` is the CATEGORY velocity cap, not a
    global one: see standards.PipeCategory.velocity_cap_m_s."""
    if material not in CATALOGUES:
        raise ValueError(f'No dimension catalogue for {material!r}')
    if type(flow) not in (int,float) or not math.isfinite(flow) or flow < 0:
        raise ValueError('Pipe sizing flow must be finite and nonnegative')
    if type(cap) not in (int,float) or not math.isfinite(cap) or cap <= 0:
        raise ValueError('Pipe sizing velocity limit must be finite and positive')
    table,std=CATALOGUES[material]
    required=math.sqrt(4*flow/(math.pi*cap))
    for nominal,od,wall in table:
        inner=(od-2*wall)*.0254
        if inner+1e-12 >= required:
            return {'nominal_size_in':nominal,'od_m':od*.0254,'id_m':inner,
                    'wall_m':wall*.0254,'required_id_m':required,'size_standard':std}
    raise NoCatalogueSize(flow,material,cap)


def scenario_flow(edge, active):
    b=edge['flow_basis']; base=b['total_m3_s']
    if b['type']=='fixed': return base
    if b['type']=='cdu': return base/len(active) if b['cdu'] in active else 0.
    if b['type']=='collector': return base*len(set(b['cdus']) & set(active))/len(active)
    raise ValueError(b)


def friction(re,relrough):
    if re<=0:return 0.
    if re<2300:return 64/re
    # EPA EPANET 2.2 Swamee-Jain turbulent approximation.
    turbulent=lambda r: .25/math.log10(relrough/3.7+5.74/r**.9)**2
    if re >= 4000: return turbulent(re)
    # ASSUMPTION: linear transition blend; flag transitional results for review.
    weight=(re-2300)/(4000-2300)
    return (1-weight)*64/re+weight*turbulent(4000)


def loss(edge, flow):
    f=FLUIDS[edge['service']]; d=edge['id_m']; area=math.pi*d*d/4
    v=flow/area; re=f['rho_kg_m3']*v*d/f['mu_Pa_s']
    rough=edge.get('roughness_m') or (1.5e-6 if edge['material']=='copper_type_l' else 45.72e-6)
    ff=friction(re,rough/d)
    dynamic=f['rho_kg_m3']*v*v/2
    pipe=ff*edge['length_m']/d*dynamic if edge['kind']=='pipe' else 0.
    kd=edge.get('K_reference_id_m',d)
    kv=4*flow/(math.pi*kd*kd)
    fitting=edge['K']*f['rho_kg_m3']*kv*kv/2
    ref=edge['reference_flow_m3_s']
    equipment=edge['reference_dp_Pa']*(flow/ref)**2 if ref else 0.
    return {'velocity_m_s':v,'Re':re,'friction_factor':ff,'straight_dp_Pa':pipe,
            'fitting_dp_Pa':fitting,'equipment_dp_Pa':equipment,'dp_Pa':pipe+fitting+equipment}


def size_graph(g,c):
    scenarios=[s for s in g['scenarios'] if s['kind']=='design']
    for e in g['edges']:
        e['design_flow_m3_s']=max(scenario_flow(e,s['active_cdus']) for s in scenarios)
        e['flow_m3_s']=scenario_flow(e,list(range(1,c.cdu_count+1)))
        # Keep full-level bore within a pipe family; local segments can have smaller flow.
        family=max(e['design_flow_m3_s'],e.get('sizing_flow_m3_s',0))
        cap=e.get('velocity_cap_m_s',c.velocity_cap_m_s)
        e.update(select_size(family,e['material'],cap))
        e.update(loss(e,e['design_flow_m3_s']))
        e['velocity_cap_pass']=e['velocity_m_s']<=cap+1e-9
    bycomp=defaultdict(list)
    for e in g['edges']:bycomp[e['component_id']].append(e)
    for comp in g['components']:
        es=bycomp[comp['id']]
        largest=max(es,key=lambda x:x['id_m'])
        comp.update({k:largest[k] for k in ('nominal_size_in','id_m','od_m','material')})
        comp['port_sizes_in']={}
        for e in es:
            for n in (e['from_node'],e['to_node']):
                comp['port_sizes_in'][n]=max(comp['port_sizes_in'].get(n,0),e['nominal_size_in'])
    # Reducer inlet inherits immediately upstream bore; outlet is its sized flow family.
    incoming=defaultdict(list)
    for e in g['edges']:incoming[e['to_node']].append(e)
    for comp in g['components']:
        if comp['kind']=='reducer':
            e=bycomp[comp['id']][0]; prev=incoming[e['from_node']]
            if prev:
                comp['port_sizes_in'][e['from_node']]=prev[0]['nominal_size_in']
                comp['inlet_nominal_size_in']=prev[0]['nominal_size_in']
                comp['outlet_nominal_size_in']=e['nominal_size_in']
                e['inlet_id_m']=prev[0]['id_m']
                e['K_reference_id_m']=min(prev[0]['id_m'],e['id_m'])
                e['provenance']['K_reference']='ASSUMPTION: reducer/expander K uses smaller connected inside diameter'
    for e in g['edges']:
        e.update(loss(e,e['design_flow_m3_s']))
        e['hydraulic_result_basis']='design_flow_m3_s; maxima over N-duty scenarios, not one simultaneous operating network'
        e['operating_results']={'basis':'all_three_online','flow_m3_s':e['flow_m3_s'],**loss(e,e['flow_m3_s'])}


def longest_path(g,start,end,active,service,exclude=()):
    adj=defaultdict(list)
    for e in g['edges']:
        if e['service']!=service or e['kind'] in exclude:continue
        q=scenario_flow(e,active)
        if q>0:adj[e['from_node']].append((e,loss(e,q)['dp_Pa']))
    visiting=set(); cache={end:(0.,[])}
    def walk(n):
        if n in cache:return cache[n]
        if n in visiting:raise ValueError('Unexpected cycle in passive network')
        visiting.add(n);best=(-math.inf,[])
        for e,dp in adj[n]:
            score,path=walk(e['to_node'])
            if dp+score>best[0]:best=(dp+score,[e['id']]+path)
        visiting.remove(n);cache[n]=best;return best
    score,ids=walk(start)
    if not math.isfinite(score):raise ValueError(f'No path {start}->{end}')
    ed={e['id']:e for e in g['edges']}
    breakdown={k:0. for k in ('straight_dp_Pa','fitting_dp_Pa','equipment_dp_Pa')}
    for i in ids:
        e=ed[i]; l=loss(e,scenario_flow(e,active))
        for k in breakdown:breakdown[k]+=l[k]
    return {'start_node':start,'end_node':end,'dp_Pa':score,'edge_ids':ids,
            'pipe_length_m':sum(ed[i]['length_m'] for i in ids if ed[i]['kind']=='pipe'),**breakdown}


def analyze(g,c):
    size_graph(g,c)
    report=[]
    for s in g['scenarios']:
        active=s['active_cdus']; paths=[]
        for i in active:
            ports=g['metadata']['cdu_pump_nodes'][str(i)]
            p=longest_path(g,ports['discharge'],ports['suction'],active,'TCS',('pump',))
            p['cdu']=i;paths.append(p)
        worst=max(paths,key=lambda x:x['dp_Pa'])
        fws=longest_path(g,g['metadata']['fws_source'],g['metadata']['fws_sink'],active,'FWS')
        nodes={n['id']:n for n in g['nodes']}
        src=nodes[g['metadata']['fws_source']];snk=nodes[g['metadata']['fws_sink']]
        elevation=(snk['xyz_m'] or snk['route_hint_m'])[2]-(src['xyz_m'] or src['route_hint_m'])[2]
        static=FLUIDS['FWS']['rho_kg_m3']*9.80665*elevation
        # Shared collector junctions enforce equal pressure. Select a common duty
        # sufficient for every active pump; individual pump/control curves remain gaps.
        report.append({'name':s['name'],'active_cdus':active,'tcs_pump_paths':paths,
            'worst_tcs_path':worst,'required_tcs_pump_dp_Pa':worst['dp_Pa']*(1+c.pump_margin_fraction),
            'required_tcs_pump_head_m':worst['dp_Pa']*(1+c.pump_margin_fraction)/(FLUIDS['TCS']['rho_kg_m3']*9.80665),
            'fws_path':fws,'fws_boundary_elevation_m':elevation,'fws_static_dp_Pa':static,
            'required_fws_available_dp_Pa':fws['dp_Pa']*(1+c.pump_margin_fraction)+static,
            'fws_pressure_basis':'source minus sink static pressure; friction plus margin + elevation; equal boundary bores/velocities'})
    violations=[e['id'] for e in g['edges'] if not e['velocity_cap_pass']]
    continuity=[]
    for s in g['scenarios']:
        balance=defaultdict(float)
        for e in g['edges']:
            q=scenario_flow(e,s['active_cdus']);balance[e['from_node']]-=q;balance[e['to_node']]+=q
        boundary={g['metadata']['fws_source'],g['metadata']['fws_sink']}
        bad={n:q for n,q in balance.items() if n not in boundary and abs(q)>1e-10}
        if bad:raise ValueError(f'Mass conservation failed in {s["name"]}: {bad}')
        continuity.append({'scenario':s['name'],'max_internal_residual_m3_s':max((abs(q) for n,q in balance.items() if n not in boundary),default=0.)})
    return {'fluid_properties':FLUIDS,'heat_and_flow':heat_flows(c),'scenarios':report,
        'velocity_violations':violations,'continuity_checks':continuity,
        'method':'Demand-based Darcy-Weisbach/Swamee-Jain path calculation. Assumed balanced parallel branches, NOT solved pump curves.',
        'static_head_note':'Closed TCS elevation cancels in circulating head; fill pressure, NPSH and expansion vessel are unresolved.'}
