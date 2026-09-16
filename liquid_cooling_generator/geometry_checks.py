"""Connection-direction, finite fitting and 3D routed clearance diagnostics."""
from collections import defaultdict
from math import dist,sqrt,sin,cos,pi

def dot(a,b):return sum(x*y for x,y in zip(a,b))
def sub(a,b):return [x-y for x,y in zip(a,b)]
def segment_distance(p1,q1,p2,q2):
    # Closest points between finite segments (including parallel segments).
    d1=sub(q1,p1);d2=sub(q2,p2);r=sub(p1,p2);a=dot(d1,d1);e=dot(d2,d2);f=dot(d2,r)
    if a<1e-14 and e<1e-14:return dist(p1,p2)
    if a<1e-14:s=0;t=max(0,min(1,f/e))
    else:
        c=dot(d1,r)
        if e<1e-14:t=0;s=max(0,min(1,-c/a))
        else:
            b=dot(d1,d2);den=a*e-b*b;s=max(0,min(1,(b*f-c*e)/den)) if den else 0;t=(b*s+f)/e
            if t<0:t=0;s=max(0,min(1,-c/a))
            elif t>1:t=1;s=max(0,min(1,(b-c)/a))
    return dist([p1[k]+s*d1[k] for k in range(3)],[p2[k]+t*d2[k] for k in range(3)])

def diagnose(g,c):
    nodes={n['id']:n['xyz_m'] for n in g['nodes']};owners=defaultdict(list);checks=[]
    def add(name,issues,detail):checks.append({'check':name,'status':'FAIL' if issues else 'PASS','actual':issues,'required':[],'source':'Physical graph geometry','detail':detail})
    active=[x for x in g['components'] if not x.get('attachment') and x.get('hydraulic_element') is not False]
    for comp in active:
        for p in comp.get('port_details',[]):owners[p['node_id']].append((comp,p))
    turns=[];bores=[];dangling=[];mixed=[]
    for nid,refs in owners.items():
        if len(refs)==2:
            (a,p),(b,q)=refs
            if dot(p['outward'],q['outward'])>-.99999:turns.append({'node':nid,'components':[a['id'],b['id']]})
            if p.get('nominal_size_in') and q.get('nominal_size_in') and abs(p['nominal_size_in']-q['nominal_size_in'])>1e-6:bores.append({'node':nid,'components':[a['id'],b['id']],'bores':[p['nominal_size_in'],q['nominal_size_in']]})
            if p['circuit_id']!=q['circuit_id']:mixed.append(nid)
        elif len(refs)!=2:
            if len(refs)==1 and nid in [g['metadata'].get('fws_source'),g['metadata'].get('fws_sink')] and c.plant_type=='boundary':continue
            dangling.append({'node':nid,'owners':len(refs)})
    add('Connected ports face each other',turns,'Every direction change needs an explicit fitting or declared equipment port direction.')
    add('Connected nominal bores agree',bores,'Diameter changes must occur inside an explicit reducer.')
    # Sizing a run for what it carries puts two bores on one fitting. That is
    # ordinary where the fitting is built to hold them and wrong anywhere else,
    # and the pairing check above cannot see it: it only compares across a joint.
    steps=[]
    for comp in active:
        if comp.get('size_m'):continue
        sizes={p['nominal_size_in'] for p in comp.get('port_details',[]) if p.get('nominal_size_in')}
        if len(sizes)>1 and comp['kind'] not in ('reducer','tee'):
            steps.append({'component':comp['id'],'kind':comp['kind'],'bores':sorted(sizes)})
    add('Bore changes stay inside a reducing fitting',steps,
        'Only a concentric/eccentric reducer or an ASME B16.9 reducing tee may hold two bores. A pipe, elbow or valve is one size end to end.')
    add('Fluid circuits remain separate',mixed,'FWS, CWS and independent TCS pods cannot share a fluid connection.')
    add('Physical fluid ports have partners',dangling,'Only declared boundary interfaces may be open.')
    invalid=[];segments=[]
    for comp in active:
        if comp.get('size_m'):continue
        pts=[nodes[p] for p in comp.get('ports',[])];r=comp.get('od_m',0)/2+c.insulation_thickness_m
        if comp['kind'] in ('elbow','tee'):
            center=comp['center_m']
            if comp['kind']=='elbow' and min(dist(p,center) for p in pts)<=r:invalid.append(comp['id'])
            # Conservative construction legs; joins excluded only with immediate neighbors.
            if comp['kind']=='elbow':
                a,b=pts;origin=[a[k]+b[k]-center[k] for k in range(3)];r0=sub(center,b);r1=sub(center,a)
                arc=[[origin[k]+cos(pi*j/32)*r0[k]+sin(pi*j/32)*r1[k] for k in range(3)] for j in range(17)]
                legs=list(zip(arc,arc[1:]))
            else:legs=[(p,center) for p in pts]
        else:legs=[(pts[0],pts[1])] if len(pts)==2 else []
        for p,q in legs:
            axis=next((k for k in range(3) if abs(p[k]-q[k])>1e-9),0) if comp['kind']!='elbow' else -1
            lower=[min(p[k],q[k])-(r+c.pipe_clear_gap_m if k!=axis else 0) for k in range(3)]
            upper=[max(p[k],q[k])+(r+c.pipe_clear_gap_m if k!=axis else 0) for k in range(3)]
            if comp['kind']=='elbow' and comp.get('mesh',{}).get('vertices'):
                # Arc capsules otherwise extend beyond a fitting's flat tangent
                # faces and falsely collide with the next inline valve.
                vertices=comp['mesh']['vertices'];extra=c.insulation_thickness_m+c.pipe_clear_gap_m
                lower=[max(lower[k],min(v[k] for v in vertices)-extra) for k in range(3)]
                upper=[min(upper[k],max(v[k] for v in vertices)+extra) for k in range(3)]
            segments.append((comp,p,q,r,lower,upper))
    neighbors=defaultdict(set)
    byid={x['id']:x for x in active}
    for refs in owners.values():
        if len(refs)==2:
            a,b=refs[0][0]['id'],refs[1][0]['id'];neighbors[a].add(b);neighbors[b].add(a)
    clashes=set()
    for i,(a,p,q,ra,amin,amax) in enumerate(segments):
        for b,u,v,rb,bmin,bmax in segments[i+1:]:
            if a['id']==b['id'] or any(amax[k]<bmin[k] or bmax[k]<amin[k] for k in range(3)):continue
            shared=set(a['ports'])&set(b['ports'])
            if shared:continue # Joined components have already passed tangent/bore checks.
            joint_region=False
            for joint in neighbors[a['id']]&neighbors[b['id']]:
                fitting=byid[joint]
                if fitting['kind'] not in ('tee','elbow','reducer','isolation_valve','quick_disconnect','flex_connector','balancing_valve','check_valve','strainer'):continue
                center=fitting.get('center_m') or [sum(nodes[n][k] for n in fitting['ports'])/len(fitting['ports']) for k in range(3)]
                extent=max(dist(center,nodes[n]) for n in fitting['ports'])+max(ra,rb)+c.pipe_clear_gap_m
                overlap_lo=[max(amin[k],bmin[k]) for k in range(3)];overlap_hi=[min(amax[k],bmax[k]) for k in range(3)]
                if all(max(abs(overlap_lo[k]-center[k]),abs(overlap_hi[k]-center[k]))<=extent+1e-6 for k in range(3)):joint_region=True
            if joint_region:continue
            if segment_distance(p,q,u,v)<ra+rb+c.pipe_clear_gap_m-1e-6:clashes.add(tuple(sorted((a['id'],b['id']))))
    add('Bend takeoff exceeds insulated outer radius',invalid,'No miter replacement or silent radius reduction is permitted.')
    add('Routed pipe and fitting clearances',sorted(clashes),'Conservative finite centerline segments with OD, insulation and configured clear gap. Component bodies/vendor envelopes remain separately qualified.')
    body_clashes=set()
    def intersects(p,q,lo,hi):
        lower,upper=0.,1.
        for k in range(3):
            delta=q[k]-p[k]
            if abs(delta)<1e-12:
                if p[k]<=lo[k]+1e-7 or p[k]>=hi[k]-1e-7:return False
            else:
                a,b=(lo[k]-p[k])/delta,(hi[k]-p[k])/delta
                lower=max(lower,min(a,b));upper=min(upper,max(a,b))
                if lower>=upper-1e-7:return False
        return True
    boxes=[x for x in active if x.get('size_m')]
    for part,p,q,r,_,_ in segments:
        for box in boxes:
            if set(part.get('ports',[]))&set(box.get('ports',[])):continue
            center=box['center_m'];size=box['size_m']
            lo=[center[k]-size[k]/2-r for k in range(3)];hi=[center[k]+size[k]/2+r for k in range(3)]
            if intersects(p,q,lo,hi):body_clashes.add((part['id'],box['id']))
    add('Routes clear equipment envelopes',sorted(body_clashes),'Pipe and fitting envelopes include insulation. Contact at an explicitly connected equipment port is permitted; vendor service/transport requirements still require qualification.')
    return {'checks':checks,'blocking_failures':sum(x['status']=='FAIL' for x in checks),'clash_count':len(clashes)+len(body_clashes)}
