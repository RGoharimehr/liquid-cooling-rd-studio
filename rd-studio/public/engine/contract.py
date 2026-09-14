"""Versioned physical connection contract shared by rendering and all adapters."""
import hashlib,json,math
from collections import defaultdict
from dataclasses import asdict
from model import canonical_digest

def finalize_equipment(g,c):
    from layout import effective_clearance
    byid={x['id']:x for x in g['components']}
    for load in list(g['components']):
        if load['kind']!='rack_load' or not load.get('host_equipment'):continue
        box=byid[load['host_equipment']]
        box.update({k:v for k,v in load.items() if k not in ('id','tag','kind','center_m','size_m','abstract','host_equipment','mesh','assumptions')})
        box.update(hydraulic_element=True,functions=['aggregate_rack_load'])
        for e in g['edges']:
            if e['component_id']==load['id']:e['component_id']=box['id'];e['id']=box['id']+':load'
        g['components'].remove(load)
    existing={x['id'] for x in g['layout']['equipment_envelopes']}
    for comp in g['components']:
        if comp.get('size_m') and comp['id'] not in existing and not comp.get('attachment'):
            g['layout']['equipment_envelopes'].append(comp)
            if comp['kind'] in ('cdu','chiller','cooling_tower','pump'):
                clearance=effective_clearance(c,'cdu' if comp['kind']=='cdu' else 'chiller')
                x,y,z=comp['center_m'];sx,sy,sz=comp['size_m']
                if comp.get('zone_rotation_deg',comp.get('pod_rotation_deg',0))%180:
                    for side in (-1,1):g['layout']['clearance_zones'].append({'id':comp['id']+':service:'+str(side),'host':comp['id'],'kind':'service_clearance','center_m':[x+side*(sx+clearance)/2,y,.02],'size_m':[clearance,sy,.04],'source':'Project allowance; vendor minimum not yet selected'})
                    continue
                for side in (-1,1):g['layout']['clearance_zones'].append({'id':comp['id']+':service:'+str(side),'host':comp['id'],'kind':'service_clearance','center_m':[x,y+side*(sy+clearance)/2,.02],'size_m':[sx,clearance,.04],'source':'Project allowance; vendor minimum not yet selected'})

def attach_contract(g,c):
    nodes={n['id']:n for n in g['nodes']};owners=defaultdict(list);edges=defaultdict(list)
    for e in g['edges']:edges[e['component_id']].append(e)
    for comp in g['components']:
        for i,nid in enumerate(comp.get('ports',[])):
            if not comp.get('attachment'):owners[nid].append((comp['id'],i))
    rename={nid:'J:'+min(cid+':P'+str(i+1) for cid,i in refs) for nid,refs in owners.items()}
    for n in g['nodes']:n['id']=rename.get(n['id'],n['id'])
    for e in g['edges']:
        e['from_node']=rename.get(e['from_node'],e['from_node']);e['to_node']=rename.get(e['to_node'],e['to_node'])
    for coupling in g['couplings']:
        for k in ('primary_ports','secondary_ports'):
            if k in coupling:coupling[k]=[rename.get(p,p) for p in coupling[k]]
    for k in ('fws_source','fws_sink'):g['metadata'][k]=rename.get(g['metadata'].get(k),g['metadata'].get(k))
    for comp in g['components']:
        original=list(comp.get('ports',[]));pts=[nodes[n]['xyz_m'] for n in original];details=[]
        for i,nid in enumerate(original):
            direction=comp.get('port_directions',{}).get(nid)
            center=comp.get('center_m')
            if direction is None:
                other=center if comp['kind'] in ('tee','elbow') else pts[1-i] if len(pts)==2 else None
                direction=[pts[i][k]-other[k] for k in range(3)] if other else [0,0,1]
            norm=math.sqrt(sum(v*v for v in direction));direction=[v/norm for v in direction] if norm else [0,0,1]
            es=[e for e in edges[comp['id']] if rename.get(nid,nid) in (e['from_node'],e['to_node'])]
            edge=es[0] if es else next((e for e in g['edges'] if rename.get(nid,nid) in (e['from_node'],e['to_node'])),{});service=edge.get('service',comp['service']);circuit=edge.get('circuit_id',comp.get('circuit_id',service))
            details.append({'id':comp['id']+':P'+str(i+1),'node_id':rename.get(nid,nid),'xyz_m':pts[i],'outward':direction,'service':service,'circuit_id':circuit,
                'nominal_size_in':comp.get('port_sizes_in',{}).get(nid,edge.get('nominal_size_in',comp.get('nominal_size_in'))),
                'od_m':comp.get('port_od_m',{}).get(nid,edge.get('od_m',comp.get('od_m'))),'id_m':comp.get('port_id_m',{}).get(nid,edge.get('id_m',comp.get('id_m')))})
        comp['ports']=[rename.get(n,n) for n in original];comp['port_details']=details
        for key in ('port_directions','port_sizes_in','port_od_m','port_id_m'):
            if key in comp:comp[key]={rename.get(k,k):v for k,v in comp[key].items()}
    g['metadata']['schema_version']='2.0';g['metadata']['config_hash']=canonical_digest(asdict(c))
    g['metadata']['units']={'coordinates':'m','length':'m','diameters':'m','nominal_size':'in','temperature':'C','heat':'W'}

def transform_layout(g,c):
    angle=math.radians(c.layout_rotation_deg);co,si=math.cos(angle),math.sin(angle)
    def point(p):return [p[0]*co-p[1]*si+c.layout_origin_x_m,p[0]*si+p[1]*co+c.layout_origin_y_m,p[2]]
    def vector(p):return [p[0]*co-p[1]*si,p[0]*si+p[1]*co,p[2]]
    g['layout']['world_transform']={'origin_m':[c.layout_origin_x_m,c.layout_origin_y_m,0.],
                                  'rotation_deg':c.layout_rotation_deg,
                                  'description':'All generated zones use this layout frame; site footprint remains in world coordinates.'}
    for n in g['nodes']:n['xyz_m']=point(n['xyz_m']);n['route_hint_m']=n['xyz_m'].copy()
    for comp in g['components']:
        if comp.get('center_m'):comp['center_m']=point(comp['center_m'])
        if comp.get('xyz_m'):comp['xyz_m']=point(comp['xyz_m'])
        for p in comp.get('port_details',[]):p['xyz_m']=point(p['xyz_m']);p['outward']=vector(p['outward'])
        if comp.get('port_directions'):comp['port_directions']={key:vector(value) for key,value in comp['port_directions'].items()}
        if comp.get('mesh'):comp['mesh']['vertices']=[point(p) for p in comp['mesh']['vertices']]
        comp['rotation_deg']=c.layout_rotation_deg
    for z in g['layout']['clearance_zones']:z['center_m']=point(z['center_m']);z['rotation_deg']=c.layout_rotation_deg
    for zone in g['layout'].get('editable_zones',[]):
        zone['anchor_layout_m']=list(zone['anchor_m']);zone['anchor_m']=point(zone['anchor_m']);zone['coordinate_frame']='world'
        bounds=zone.get('bounds_m')
        if bounds:
            corners=[point([x,y,0]) for x in (bounds['min'][0],bounds['max'][0]) for y in (bounds['min'][1],bounds['max'][1])]
            zone['bounds_m']={'min':[min(p[k] for p in corners) for k in range(3)],'max':[max(p[k] for p in corners) for k in range(3)]}
