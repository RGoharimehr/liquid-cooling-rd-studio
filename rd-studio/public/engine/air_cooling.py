"""Residual air heat and conceptual two-port CRAH/wall-coil water branches.

The air units share the declared FWS supply/return in this initial template.
That connection is an architectural assumption, not a claim that a warm-water
CDU supply can meet the air coil duty. Airflow and coil selection remain open.
"""
from math import isfinite

AIR_SOURCE = 'https://handbook.ashrae.org/Handbooks/A23/SI/A23_Ch20/a23_ch20_si.aspx'


def _get(config, name, default=0):
    return config.get(name, default) if isinstance(config, dict) else getattr(config, name, default)


def heat_ledger(config):
    compute = _get(config, 'rows') * _get(config, 'racks_per_row') * _get(config, 'rack_power_W')
    liquid = compute * _get(config, 'liquid_fraction', 1.)
    network = (_get(config, 'network_rows') * _get(config, 'network_racks_per_row') * _get(config, 'network_rack_power_W')
               + _get(config, 'network_high_power_count') * (_get(config, 'network_high_power_W') - _get(config, 'network_rack_power_W')))
    other = _get(config, 'additional_air_load_W', 0.)
    if type(other) not in (float, int) or not isfinite(other) or other < 0:
        raise ValueError('additional_air_load_W must be finite and nonnegative')
    air = compute - liquid + network + other
    return {'liquid_W': liquid, 'compute_air_W': compute-liquid, 'network_air_W': network,
            'additional_air_W': other, 'air_W': air, 'chiller_W': liquid + air,
            'basis': 'Coincident declared IT heat, with no diversity: liquid to CDUs; residual compute, network and additional room/fan heat to air units. Each load is counted once.',
            'unassigned': 'Envelope, ventilation, latent and fan/motor gains are excluded unless entered in additional_air_load_W. Air coil performance and FWS temperature compatibility require selection.',
            'source_refs': [{'source': AIR_SOURCE, 'edition': 'ASHRAE Handbook 2023 HVAC Applications',
                             'chapter': '20 Data Centers and Telecommunication Facilities',
                             'classification': 'guidance', 'applicability': 'Combined air/liquid cooling system architecture; unit geometry and loss allocations are project assumptions'}]}


def add_air_cooling(b):
    """Add a parallel FWS load bank, preserving explicit ports and fittings."""
    c=b.c; ledger=heat_ledger(c); heat=ledger['air_W']
    b.g['metadata']['heat_ledger']=ledger
    if heat <= 1e-9:
        b.g['metadata']['air_cooling']={'status':'NO_AIR_LOAD', 'heat_W':0., 'equipment_ids':[]}
        return
    count=getattr(c,'air_unit_count',2)
    if type(count) is not int or count < 1:
        raise ValueError('air_unit_count must be at least one when residual air heat is present')
    start_nodes=len(b.g['nodes']);start_components=len(b.g['components']);start_edges=len(b.g['edges'])
    basis=b.fixed(0);group=(None,None,None);source=b.g['metadata']['fws_source'];sink=b.g['metadata']['fws_sink']
    source_pt=b.xyz(source);sink_pt=b.xyz(sink)
    # The north wall/service strip follows the actual moved pod routes and the
    # configured network footprint. It is deliberately outside the IT envelope.
    net_y=b.layout['network_origin_m'][1]+max(0,c.network_rows-1)*(c.network_rack_depth_m+c.network_aisle_m)+c.network_rack_depth_m/2
    north=max(net_y,max(p['route_hint_m'][1] for p in b.g['nodes']))+4
    sy=north;ry=north+2;uy=north+5
    z=max(source_pt[2],3.6);zr=max(sink_pt[2],z+c.return_elevation_offset_m)
    arm=c.fitting_arm_m
    def hub(old,y,height,split):
        """Tee the air branch off the facility interface where the interface is.

        This used to put the tee on the north wall and hand back its common port
        as the new fws_source, so the whole facility's connection point moved to
        wherever the air units sat. On RD113 that put the interface at y=+20.3
        while the plant and pod 1 are at y=-16..-10, and every circuit - all
        18,571 L/min of it - ran north and back to reach it.

        The tee now sits beside the existing interface and only the air branch,
        which carries 489 L/min, travels to the wall.
        """
        x,oy,_=b.xyz(old)
        common,other,branch=b.junction([x,oy+2*arm,height],[0,-1,0],[1,0,0],'FWS','main',[basis,basis],group,split=split)
        if split:b.route_path(other,old,[[x,oy,height]],'FWS','main',basis,group)
        else:b.route_path(old,other,[[x,oy,height]],'FWS','main',basis,group)
        # The tee's branch port faces east, the wall is north and the spine then
        # runs east again, so the branch needs both turns as explicit elbows and
        # has to clear the interface riser it just left.
        bx=x+2.
        spine=b.node([bx+.6,y,height],'FWS')
        legs=[[bx,oy+2*arm,height],[bx,y,height]]
        if split:b.route_path(branch,spine,legs,'FWS','main',basis,group)
        else:b.route_path(spine,branch,legs[::-1],'FWS','main',basis,group)
        return common,spine
    new_source,supply=hub(source,sy,z,True);new_sink,ret=hub(sink,ry,zr,False)
    b.g['metadata'].update(fws_source=new_source,fws_sink=new_sink)
    first_x=max(c.first_rack_x_m, source_pt[0]+4, sink_pt[0]+4)
    equipment=[]
    def branch(start,x,y,height,unit_port,incoming):
        # Diameter changes remain coaxial, then each top connection has a
        # separate finite-radius turn. No pipe is drawn through the air unit.
        before=len(b.g['edges']);px=x
        if incoming:
            red,_=b.part(start,[px,y+.5,height],'reducer','FWS','cdu',basis,group)
            stop,_=b.part(red,[px,y+.85,height],'isolation_valve','FWS','cdu',basis,group)
            clean,_=b.part(stop,[px,y+1.15,height],'strainer','FWS','cdu',basis,group)
            b.route_path(clean,unit_port,[[px,uy,height]],'FWS','cdu',basis,group)
        else:
            stop=b.node([px,y+1.15,height],'FWS')
            b.route_path(unit_port,stop,[[px,uy,height]],'FWS','cdu',basis,group)
            control,_=b.part(stop,[px,y+.85,height],'control_valve','FWS','cdu',basis,group)
            isolate,_=b.part(control,[px,y+.5,height],'isolation_valve','FWS','cdu',basis,group)
            b.component('reducer',[isolate,start],'FWS','main',basis,group)
        # The outlet reducer belongs to the main side; remaining branches have
        # an independent air-unit sizing family instead of reusing CDU inputs.
        for edge in b.g['edges'][before:]:
            if edge['level']=='cdu':edge['pipe_family']='fws_air'
            edge['load_group']='air_cooling'
    for i in range(count):
        x=first_x+i*4;cid=f'AIR-UNIT-{i+1:02}'
        inlet=b.node([x-.5,uy,2.2],'FWS','equipment_port');outlet=b.node([x+.5,uy,2.2],'FWS','equipment_port')
        comp={'id':cid,'tag':cid,'kind':'air_unit','service':'FWS','circuit_id':'FWS','level':'cdu',
              'ports':[inlet,outlet],'row':None,'rack':None,'cdu':None,'pod':None,
              'center_m':[x,uy,1.1],'size_m':[3.,1.2,2.2],'schematic_group':'AIR-COOLING','zone':'air_cooling',
              'hydraulic_element':True,'status':'conceptual','functions':['aggregate_air_cooling_load'],
              'heat_W':heat/count,'duty_role':'duty','port_directions':{inlet:[0,0,1],outlet:[0,0,1]},
              'source_refs':ledger['source_refs'],
              'assumptions':['Conceptual CRAH/wall-unit envelope and shared FWS connection; no manufacturer selected.',
                             'Coil capacity at entering water/air conditions and air distribution remain unverified.']}
        b.g['components'].append(comp);edge=b.edge(comp,inlet,outlet,'air_coil',basis)
        edge.update(internal=True,pipe_family='fws_air',load_group='air_cooling');equipment.append(cid)
        for line,label,xx,yy,hh,split in [(supply,'supply',x-.5,sy,z,True),(ret,'return',x+.5,ry,zr,False)]:
            common,other,tap=b.junction([xx,yy,hh],[1,0,0],[0,1,0],'FWS','main',[basis,basis],group,split=split,last=i==count-1)
            if split:b.route(line,common,'FWS','main',basis,group)
            else:b.route(common,line,'FWS','main',basis,group)
            branch(tap,xx,yy,hh,inlet if split else outlet,split)
            if label=='supply':supply=other
            else:ret=other
    for comp in b.g['components'][start_components:]:comp['zone']='air_cooling'
    for edge in b.g['edges'][start_edges:]:
        edge.setdefault('load_group','air_cooling')
    b.g['metadata']['air_cooling']={
        'status':'CONCEPTUAL_CONNECTED', 'heat_W':heat,'equipment_ids':equipment,
        'architecture':'Parallel two-port CRAH/wall-coil branches on FWS; aggregate air-side heat only.',
        'temperature_status':'UNRESOLVED: selected FWS temperature may be too warm for the required air supply; select a compatible coil or design a separate chilled-water circuit.',
        'source_refs':ledger['source_refs']}
