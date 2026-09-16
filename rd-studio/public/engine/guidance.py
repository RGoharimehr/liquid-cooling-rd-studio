"""Concise, scoped source guidance. No source books are distributed with the site."""
SOURCES=[
 {'id':'ASHRAE-2','title':'ASHRAE liquid cooling · facility systems','edition':'Datacom Encyclopedia, third edition; supplied 2026-09-05 capture','clause':'§2.1.5, §2.3','status':'guidance','applicability':'Equipment access, fluid distribution and serviceability','url':'https://datacom.ashrae.org','document':'ASHRAE_LiquidCooling_Ch02_Facility_Cooling_Systems.pdf'},
 {'id':'ASHRAE-5','title':'ASHRAE liquid cooling · FWS interfaces','edition':'Datacom Encyclopedia, supplied chapter 5','clause':'§5.1–5.2','status':'guidance','applicability':'Facility side of the CDU','url':'https://datacom.ashrae.org','document':'ASHRAE_LiquidCooling_Ch05_Infrastructure_Facility_Cooling_Systems.pdf'},
 {'id':'ASHRAE-6','title':'ASHRAE liquid cooling · TCS interfaces','edition':'Datacom Encyclopedia, chapter 6 v1.1 (2025)','clause':'§6.1, Table 6.1 footnote; §6.3','status':'guidance','applicability':'Technology coolant delivered to IT equipment','url':'https://datacom.ashrae.org','document':'ASHRAE_LiquidCooling_Ch06_Infrastructure_Technology_Cooling_Systems.pdf'},
 {'id':'ASHRAE-7','title':'ASHRAE liquid cooling · fluids and materials','edition':'Datacom Encyclopedia, supplied chapter 7','clause':'§7.4; Table 7.2 notes','status':'guidance','applicability':'Separate FWS and TCS wetted-material lists','url':'https://datacom.ashrae.org','document':'ASHRAE_LiquidCooling_Ch07_Fluids_and_Fluid_Quality.pdf'},
 {'id':'ASHRAE-8','title':'ASHRAE liquid cooling · external connections','edition':'Datacom Encyclopedia, supplied chapter 8','clause':'§8.3; §8.4.5','status':'guidance','applicability':'Rack/row quick disconnects and hoses','url':'https://datacom.ashrae.org','document':'ASHRAE_LiquidCooling_Ch08_Common_Components_Cold_Plates.pdf'},
 {'id':'PROJECT','title':'Project design input','edition':'Generator schema 2','clause':'','status':'assumption','applicability':'Selected reference design','url':''},
 {'id':'VENDOR','title':'Selected equipment vendor','edition':'Manufacturer data required','clause':'Installation and service requirements','status':'vendor_requirement','applicability':'Selected equipment model only','url':''}]

def source_register():
    return {'sources':SOURCES,'source_quality':{'duplicate_chapters':'Chapter 1/2/3 duplicate captures differ only in headings/footer or are text-identical; canonical unnumbered copies used.','tables':'Supplied table 5.1 and 6.1 have missing/displaced cells. Numeric W/S labels corroborated by ASHRAE published class nomenclature; infrastructure examples do not impose a fixed mapping.','figures':'Some captured figures are absent; no diagram geometry inferred from missing images.'},'legal_code_status':'No jurisdiction selected; these checks do not certify code compliance.'}

def evaluate_guidance(c,g=None):
    checks=[]
    def check(name,ok,actual,required,source,detail):checks.append({'check':name,'status':'NOT_EVALUABLE' if ok is None else 'PASS' if ok else 'FAIL','actual':actual,'required':required,'source':source,'detail':detail,'severity':'review'})
    check('TCS supply above room dew point + 2 K',c.tcs_supply_C>=c.room_dew_point_C+2,c.tcs_supply_C,c.room_dew_point_C+2,'ASHRAE-6 §6.1','Applies to the declared measured/design room dew point; no room humidity simulation.')
    allowed={'S20':20,'S25':25,'S30':30,'S35':35,'S40':40,'S45':45,'S50':50}
    check('TCS supply within selected class',c.tcs_supply_C<=allowed[c.tcs_class] if c.tcs_class in allowed else None,c.tcs_supply_C,allowed.get(c.tcs_class),'ASHRAE-6 §6.1','IT manufacturer must qualify the equipment for the selected class; this is a boundary input check.')
    check('CDU temperature approach is positive',c.tcs_supply_C>c.fws_supply_C,c.tcs_supply_C-c.fws_supply_C,'> 0 K','ASHRAE-5/6','Required approach/capacity must be checked using the actual CDU curve, fluids and flows.')
    fws={'W17':17,'W27':27,'W32':32,'W40':40,'W45':45}
    check('FWS supply within selected W-class',c.fws_supply_C<=fws[c.fws_class] if c.fws_class in fws else None,c.fws_supply_C,fws.get(c.fws_class,'W+ requires vendor qualification'),'ASHRAE-5 §5.1','FWS W-class is independent of TCS S-class; no fixed W-to-S conversion is applied.')
    check('CDU return-side temperature approach is positive',c.tcs_supply_C+c.tcs_delta_K>c.fws_supply_C+c.fws_delta_K,(c.tcs_supply_C+c.tcs_delta_K)-(c.fws_supply_C+c.fws_delta_K),'> 0 K','ASHRAE-5/6','Boundary temperatures must permit heat transfer at both ends. Actual heat exchanger approach remains vendor-specific.')
    from layout import effective_clearance
    effective_source='ASHRAE-2 §2.1.5'
    for label,actual,vendor in [('Rack front access',effective_clearance(c,'rack_front'),c.vendor_rack_front_clearance_m),('Rack rear access',effective_clearance(c,'rack_rear'),c.vendor_rack_rear_clearance_m),('CDU service access',effective_clearance(c,'cdu'),c.vendor_cdu_service_clearance_m),('Chiller service access',effective_clearance(c,'chiller'),c.vendor_chiller_service_clearance_m)]:
        check(label,actual>=vendor if vendor else None,actual,vendor or 'Vendor minimum required','ASHRAE-2 §2.1.5','Zero vendor input means missing data, not zero required clearance.')
    check('Hose minimum bend radius',None,c.vendor_hose_min_bend_radius_m or None,'Vendor hose geometry/rating required','ASHRAE-8 §8.4.5','Current rack connections are straight external interface envelopes; hose routing/qualification is unresolved.')
    check('Fluid and wetted-material compatibility',None,{'TCS':c.pg_volume_fraction,'FWS':c.fws_material},'Supplier-approved complete wetted-material list','ASHRAE-7 §7.4','Commonly used materials are not a compatibility endorsement.')
    check('CDU and plant capacity / minimum flow',None,None,'Manufacturer performance/controls','ASHRAE-5 §5.2','No pump head, pressure distribution, transient or hydraulic capacity is solved.')
    # Where a pod's CDUs stand relative to the rows they feed. Every rack branch
    # in the pod carries the gap, so it is worth a number rather than a look at
    # the plan. Standing the gallery off the hall is a legitimate choice, which
    # is why this reports and does not block.
    from layout import arrangement, assignments
    a=(g or {}).get('layout') or arrangement(c)
    rows=assignments(c.rows,c.pod_count,c.row_pod_assignments)
    units=assignments(c.cdu_count,c.pod_count,c.cdu_pod_assignments)
    for pod in sorted(set(units)):
        served=[a['compute_row_y_m'][i] for i,value in enumerate(rows) if value==pod]
        mine=[a['cdu_y_m'][i] for i,value in enumerate(units) if value==pod]
        if not served or not mine:continue
        gap=max(0.,min(mine)-max(served),min(served)-max(mine))
        check(f'Cooling pod {pod} CDUs stand with the rows they serve',gap<=c.cdu_pitch_m,round(gap,2),
              f'no more than {c.cdu_pitch_m:g} m clear of the rows',effective_source,
              'Clear distance along the hall between this pod\'s CDU gallery and the rows it feeds. '
              'cdu_placement selects the gallery: central_gallery stands each pod\'s CDUs alongside its own rows.')
    return {'checks':checks,'summary':{status:sum(x['status']==status for x in checks) for status in ('PASS','FAIL','NOT_EVALUABLE')},'scope':'Scoped guidance and declared-input review; not installation certification'}
