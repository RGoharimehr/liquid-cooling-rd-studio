"""Bounded design actions using the same generator and acceptance checks as Apply."""
from dataclasses import asdict, replace
from copy import deepcopy
import hashlib,json


def metrics(graph):
    components={c['id']:c for c in graph['components']}
    edges=[e for e in graph['edges'] if components[e['component_id']].get('zone')=='plant']
    length=sum(e.get('length_m',0) for e in edges if e['kind']=='pipe')
    bends=sum(c['kind']=='elbow' for c in components.values() if c.get('zone')=='plant')
    failures=graph['metadata'].get('geometry_diagnostics',{}).get('blocking_failures',0)
    return {'plant_pipe_length_m':round(length,3),'plant_elbows':bends,'blocking_findings':failures}


def optimize_routes(config):
    """Try a small declared set of route preferences; never invent an optimum."""
    from pipeline import build
    from verify import run
    if config.plant_type=='boundary':raise ValueError('Select an air-cooled or water-cooled plant before optimizing plant pipes.')
    original=asdict(config);baseline,profile=build(deepcopy(config));before=metrics(baseline)
    trials=[];winner=None;best=before['plant_pipe_length_m']
    for cost,discount in [(1.5,.35),(.5,.2),(3.,.5)]:
        candidate=replace(config,route_optimizer=True,route_bend_cost_m=cost,route_bundle_discount=discount)
        try:
            g,p=build(candidate);m=metrics(g);verification=run(g,candidate,p)['summary']
            feasible=verification['blocking_failures']==0
            trials.append({'bend_cost_m':cost,'bundle_discount':discount,**m,'accepted':feasible})
            if feasible and m['plant_pipe_length_m']<best-.01:
                best=m['plant_pipe_length_m'];winner=(candidate,g,m)
        except ValueError as exc:trials.append({'bend_cost_m':cost,'bundle_discount':discount,'accepted':False,'reason':str(exc)})
    if winner:
        candidate,g,after=winner
        return {'status':'IMPROVED','config':asdict(candidate),'before':before,'after':after,'trials':trials,
                'saved_pipe_m':round(before['plant_pipe_length_m']-after['plant_pipe_length_m'],3),
                'config_hash':g['metadata']['config_hash'],'components':len(g['components']),
                'summary':'Shorter plant routing found and checked. Review the measured change, then stage and Apply.',
                'scope':'Three deterministic corridor trials; equipment positions, duties and pipe families are retained. Global optimality and network hydraulic performance are not claimed.'}
    return {'status':'NO_IMPROVEMENT','config':original,'before':before,'after':before,'trials':trials,'saved_pipe_m':0,
            'summary':'No shorter route passed all generator checks in these trials. The current design is unchanged.',
            'scope':'Try moving the plant or clearing equipment conflicts before another route search. Three corridor trials are not an exhaustive optimizer.'}
