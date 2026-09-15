"""Bounded design actions using the same generator and acceptance checks as Apply."""
from dataclasses import asdict, replace
from copy import deepcopy
import hashlib,json


def metrics(graph):
    """Measure every routed pipe, not only the plant's own.

    Scoring zone=='plant' alone left 56% of the routed length outside the
    objective in the compact preset - the CDU-to-plant mains and the whole air
    spine among it. A trial could send a return the long way round the hall and
    still score as an improvement, because the detour was not in the plant.
    """
    components={c['id']:c for c in graph['components']}
    pipes=[e for e in graph['edges'] if e['kind']=='pipe']
    plant=[e for e in pipes if components[e['component_id']].get('zone')=='plant']
    length=sum(e.get('length_m',0) for e in pipes)
    bends=sum(c['kind']=='elbow' for c in components.values())
    failures=graph['metadata'].get('geometry_diagnostics',{}).get('blocking_failures',0)
    return {'routed_pipe_length_m':round(length,3),'elbows':bends,
            'plant_pipe_length_m':round(sum(e.get('length_m',0) for e in plant),3),
            'plant_elbows':sum(c['kind']=='elbow' for c in components.values() if c.get('zone')=='plant'),
            'blocking_findings':failures}


def optimize_routes(config):
    """Try a small declared set of route preferences; never invent an optimum."""
    from pipeline import build
    from verify import run
    if config.plant_type=='boundary':raise ValueError('Select an air-cooled or water-cooled plant before optimizing plant pipes.')
    original=asdict(config);baseline,profile=build(deepcopy(config));before=metrics(baseline)
    trials=[];winner=None;best=before['routed_pipe_length_m']
    for cost,discount in [(1.5,.35),(.5,.2),(3.,.5)]:
        candidate=replace(config,route_optimizer=True,route_bend_cost_m=cost,route_bundle_discount=discount)
        try:
            g,p=build(candidate);m=metrics(g);verification=run(g,candidate,p)['summary']
            feasible=verification['blocking_failures']==0
            trials.append({'bend_cost_m':cost,'bundle_discount':discount,**m,'accepted':feasible})
            if feasible and m['routed_pipe_length_m']<best-.01:
                best=m['routed_pipe_length_m'];winner=(candidate,g,m)
        except ValueError as exc:trials.append({'bend_cost_m':cost,'bundle_discount':discount,'accepted':False,'reason':str(exc)})
    if winner:
        candidate,g,after=winner
        return {'status':'IMPROVED','config':asdict(candidate),'before':before,'after':after,'trials':trials,
                'saved_pipe_m':round(before['routed_pipe_length_m']-after['routed_pipe_length_m'],3),
                'config_hash':g['metadata']['config_hash'],'components':len(g['components']),
                'summary':'Shorter plant routing found and checked. Review the measured change, then stage and Apply.',
                'scope':'Three deterministic corridor trials; equipment positions, duties and pipe families are retained. Global optimality and network hydraulic performance are not claimed.'}
    return {'status':'NO_IMPROVEMENT','config':original,'before':before,'after':before,'trials':trials,'saved_pipe_m':0,
            'summary':'No shorter route passed all generator checks in these trials. The current design is unchanged.',
            'scope':'Try moving the plant or clearing equipment conflicts before another route search. Three corridor trials are not an exhaustive optimizer.'}
