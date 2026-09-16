"""Geometric arrangement parameters; no hydraulic solver dependencies."""

def effective_clearance(c, kind):
    project = getattr(c, {'rack_front':'rack_front_clearance_m', 'rack_rear':'rack_rear_clearance_m',
                         'cdu':'cdu_service_clearance_m', 'chiller':'plant_service_clearance_m'}[kind])
    vendor = getattr(c, {'rack_front':'vendor_rack_front_clearance_m', 'rack_rear':'vendor_rack_rear_clearance_m',
                        'cdu':'vendor_cdu_service_clearance_m', 'chiller':'vendor_chiller_service_clearance_m'}[kind], 0.)
    return max(project, vendor)

def assignments(count, pods, explicit):
    """Which pod each row, or each CDU, belongs to."""
    return explicit or [min(pods, i*pods//count+1) for i in range(count)]


def cdu_gallery(c, row_y):
    """Where each CDU stands, in order.

    A central gallery is centred on the rows it serves, and with independent
    cooling pods that means each pod's own rows. Centring one column on the whole
    hall lets a pod's CDUs come to rest beside another pod's racks - on RD113
    with the pods assigned in the opposite order to the rows, both galleries sit
    on the wrong half and every rack branch pays for the crossing.

    An end gallery is a deliberate choice to stand the CDUs off the hall, so it
    keeps its single column at the end, and a custom origin is left alone.
    """
    pitch = c.cdu_pitch_m
    if c.cdu_placement == 'custom':
        base = c.cdu_origin_y_m
    elif c.cdu_placement == 'central_gallery':
        rows = assignments(c.rows, c.pod_count, c.row_pod_assignments)
        cdus = assignments(c.cdu_count, c.pod_count, c.cdu_pod_assignments)
        y = {}
        for pod in sorted(set(cdus)):
            served = [row_y[i] for i, value in enumerate(rows) if value == pod] or row_y
            mine = [i for i, value in enumerate(cdus) if value == pod]
            start = (min(served)+max(served))/2-(len(mine)-1)*pitch/2
            for offset, index in enumerate(mine):
                y[index] = start+offset*pitch
        return [y[i] for i in range(c.cdu_count)]
    else:
        base = -2-(c.cdu_count-1)*pitch
    return [base+i*pitch for i in range(c.cdu_count)]


def arrangement(c):
    pitch=c.rack_depth_m+c.aisle_width_m
    access=max(effective_clearance(c,'rack_front'),effective_clearance(c,'rack_rear'))
    network_band=(max(0,c.network_rows-1)*(c.network_rack_depth_m+c.network_aisle_m)
                  +c.network_rack_depth_m+2*access) if c.network_rows else 0
    split=max(1,c.rows//2)
    extra=network_band if c.layout_style=='central_network' else (2*c.aisle_width_m if c.layout_style=='split_banks' else 0)
    row_y=[i*pitch+(extra if i>=split else 0) for i in range(c.rows)]
    if c.layout_style=='central_network':
        net_base=(row_y[split-1]+c.rack_depth_m/2+access+c.network_rack_depth_m/2)
    else: net_base=(row_y[-1]+pitch+access)
    net_span=(max(0,c.network_racks_per_row-1))*c.network_rack_pitch_m
    comp_span=(c.racks_per_row-1)*c.rack_pitch_m
    net_x=c.first_rack_x_m+(comp_span-net_span)/2+c.network_offset_x_m
    cdu_y=cdu_gallery(c,row_y)
    return {'compute_row_y_m':row_y,'network_origin_m':[net_x,net_base+c.network_offset_y_m,0],
            'cdu_origin_m':[c.cdu_origin_x_m,cdu_y[0],0],'cdu_y_m':cdu_y,'network_band_m':network_band,
            'style':c.layout_style,'cdu_placement':c.cdu_placement}


def equipment(g,c):
    a=arrangement(c);boxes=[];zones=[]
    def add(id,kind,center,size,**kw):
        box={'id':id,'tag':id,'kind':kind,'center_m':center,'size_m':size,'ports':[],
             'service':'AIR' if kind in ('compute_rack','network_rack') else 'EQUIPMENT',
             'level':'equipment','hydraulic_element':False,'attachment':False,'status':'conceptual',
             'assumptions':['Project equipment envelope; vendor dimensions require confirmation'],**kw}
        boxes.append(box);g['components'].append(box)
    for r,y in enumerate(a['compute_row_y_m'],1):
        for j in range(1,c.racks_per_row+1):
            x=c.first_rack_x_m+(j-1)*c.rack_pitch_m
            add(f'IT-R{r:02d}-{j:02d}','compute_rack',[x,y,c.rack_height_m/2],[c.rack_width_m,c.rack_depth_m,c.rack_height_m],
                row=r,rack=j,cdu=None,power_W=c.rack_power_W,liquid_fraction=c.liquid_fraction,schematic_group='equipment-compute')
        width=(c.racks_per_row-1)*c.rack_pitch_m+c.rack_width_m
        for side,clear in [(-1,effective_clearance(c,'rack_front')),(1,effective_clearance(c,'rack_rear'))]:
            zones.append({'id':f'IT-R{r:02d}-'+('front' if side<0 else 'rear'),'host':f'IT-R{r:02d}','kind':'service_clearance',
                'center_m':[c.first_rack_x_m+(c.racks_per_row-1)*c.rack_pitch_m/2,y+side*(c.rack_depth_m+clear)/2,.02],
                'size_m':[width,clear,.04],'source':'Larger of project allowance and declared vendor minimum; OEM requirements govern'})
    nx,ny,_=a['network_origin_m'];index=0
    for r in range(1,c.network_rows+1):
        for j in range(1,c.network_racks_per_row+1):
            high_per_row=c.network_high_power_count//max(1,c.network_rows)+(1 if r<=c.network_high_power_count%max(1,c.network_rows) else 0)
            p=c.network_high_power_W if j>c.network_racks_per_row-high_per_row else c.network_rack_power_W;index+=1
            add(f'NET-R{r:02d}-{j:02d}','network_rack',[nx+(j-1)*c.network_rack_pitch_m,ny+(r-1)*(c.network_rack_depth_m+c.network_aisle_m),c.network_rack_height_m/2],
                [c.network_rack_width_m,c.network_rack_depth_m,c.network_rack_height_m],row=r,rack=j,cdu=None,power_W=p,liquid_fraction=0.,schematic_group='equipment-network')
            center=boxes[-1]['center_m']
            for side,clear in [(-1,effective_clearance(c,'rack_front')),(1,effective_clearance(c,'rack_rear'))]:
                zones.append({'id':f'NET-R{r:02d}-{j:02d}:service:{side}','host':boxes[-1]['id'],'kind':'service_clearance',
                              'center_m':[center[0],center[1]+side*(c.network_rack_depth_m+clear)/2,.02],
                              'size_m':[c.network_rack_width_m,clear,.04],
                              'source':'Project rack allowance / declared rack vendor minimum; network OEM requirements must be confirmed'})
    from zone_geometry import transform_zone_geometry
    network_boxes=[box for box in boxes if box['kind']=='network_rack']
    network_zones=[zone for zone in zones if zone['host'].startswith('NET-')]
    transform_zone_geometry([],network_boxes+network_zones,a['network_origin_m'],
                            getattr(c,'network_rotation_deg',0),getattr(c,'network_flip_x',False),getattr(c,'network_flip_y',False))
    ox=a['cdu_origin_m'][0]
    for i in ([] if any(x['kind']=='cdu' for x in g['components']) else range(1,c.cdu_count+1)):
        oy=a['cdu_y_m'][i-1]
        add(f'CDU-ENC-{i:02d}','cdu_enclosure',[ox+.15,oy,1.1],[1.8,1.0,2.2],row=None,rack=None,cdu=i,schematic_group='equipment-cdu')
        clear=effective_clearance(c,'cdu')
        for side in (-1,1):
            zones.append({'id':f'CDU-{i:02d}-service-{side}','host':f'CDU-ENC-{i:02d}','kind':'service_clearance','center_m':[ox+.15+side*(1.8+clear)/2,oy,.02],'size_m':[clear,1.0,.04],'source':'Project CDU service allowance; OEM requirements govern'})
    g['layout']={**a,'equipment_envelopes':boxes,'clearance_zones':zones,
        'network_cooling':'Air-cooled; no invented TCS branches. RD113 R0 diagram-reconciled interpretation.',
        'network_power_W':sum(b.get('power_W',0) for b in boxes if b['kind']=='network_rack')}
    return g['layout']
