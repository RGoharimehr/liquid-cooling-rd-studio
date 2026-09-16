"""Offer a transport link to the lane router, and build whatever comes back.

The optimizer used to be reachable from one place, so on RD113 it saw two links
of 64 m in a 689 m network - the plant's own tie-ins - and every other run that
crosses open floor was a fixed lane it was never shown. This module is that entry
point, so anything which is genuinely "get from A to B around what is already
there" can be offered to it.

Nothing here decides geometry. The router proposes waypoints, `route_path` still
builds every pipe, elbow, node and tag, and a proposal that will not place
legally falls back to the lane the caller supplied.
"""
from math import dist


def _measure(points):
    length=sum(dist(p,q) for p,q in zip(points,points[1:]))
    return length,max(0,len(points)-2)


def plan(b,c,links,service):
    """Ask the lane router for better waypoints than the deterministic lanes.

    Returns {key: points} for the links it improved. A link is only replaced when
    the search actually beats the lane it would otherwise use, measured with the
    same cost, so enabling the optimizer can never lengthen a run. Anything it
    cannot place legally is left alone and reported.
    """
    from route_lanes import LaneRouter,Request,obstacles_from_graph,_collapse,_validate
    ends=[b.xyz(a) for _,a,d,_,_,_ in links]+[b.xyz(d) for _,a,d,_,_,_ in links]
    levels=sorted({round(p[2],3) for p in ends})
    levels+= [z+1.2 for z in levels]
    router=LaneRouter(
        obstacles_from_graph(b.g,b.xyz,pipe_half_m=c.route_pipe_clearance_m,
            equipment_pad_m=c.route_equipment_clearance_m,
            overfly_top_m=c.ceiling_height_m if c.route_avoid_overfly else None),
        bend_radius_m=c.bend_radius_m,bend_cost_m=c.route_bend_cost_m,
        bundle_discount=c.route_bundle_discount,corridor_m=c.route_corridor_m,
        z_levels=sorted(set(levels)))
    requests=[Request(key=key,start=tuple(b.xyz(a)),end=tuple(b.xyz(d)),
                      start_dir=adir,end_dir=ddir,lead_m=2.0,
                      clearance_m=c.route_pipe_clearance_m,service=service)
              for key,a,d,adir,ddir,_ in links]
    results=router.route(requests)
    report=b.g['metadata'].setdefault('route_optimizer',{}).setdefault('links',[])
    chosen={}
    for key,a,d,adir,ddir,fallback in links:
        res=results[key]
        base_pts=_collapse([tuple(b.xyz(a))]+[tuple(x) for x in fallback]+[tuple(b.xyz(d))])
        base_len,base_bends=_measure(base_pts)
        base_cost=base_len+base_bends*c.route_bend_cost_m
        row={'link':key,'service':service,'status':res.status,
             'lane_m':round(base_len,3),'lane_bends':base_bends,
             'bound_m':round(res.bound_m,3)}
        if res.status=='routed':
            cost=res.length_m+res.bends*c.route_bend_cost_m
            row.update(routed_m=round(res.length_m,3),routed_bends=res.bends,
                       shared_m=round(res.shared_m,3),
                       gap_over_bound=round(res.length_m/res.bound_m-1,4) if res.bound_m else None)
            if cost<base_cost-1e-6:
                chosen[key]=res.waypoints
                row['chosen']='optimized'
                row['saved_m']=round(base_len-res.length_m,3)
            else:
                row['chosen']='lane'
                row['reason']='deterministic lane already at or below the optimised cost'
        else:
            row['chosen']='lane'
            row['reason']=res.reason
        report.append(row)
    return chosen



def emit(b,c,links,service,level='main',group=(None,None,None),basis=None):
    """Route each link, preferring the optimizer's waypoints over the fixed lane."""
    basis=b.fixed(0) if basis is None else basis
    chosen=plan(b,c,links,service) if c.route_optimizer else {}
    for key,a,d,adir,ddir,fallback in links:
        points=chosen.get(key,fallback)
        try:
            b.route_path(a,d,points,service,level,basis,group)
        except ValueError:
            if key not in chosen:raise
            b.g['metadata']['route_optimizer'].setdefault('rejected',[]).append(key)
            b.route_path(a,d,fallback,service,level,basis,group)
