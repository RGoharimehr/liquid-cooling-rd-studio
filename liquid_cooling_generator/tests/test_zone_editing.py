from dataclasses import replace
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Config
from pipeline import build
from parameters import PRESETS
from verify import run
class ZoneAndSizingIntegration(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.c=Config(**PRESETS['compact']['config']);cls.g,_=build(cls.c)
 def test_pod_move_preserves_assignment_and_reconnects_four_port_cdus(self):
  c=replace(self.c,pod_origins_m=[[2,0]]);g,p=build(c)
  self.assertEqual(run(g,c,p)['blocking_failures'],[])
  self.assertEqual(g['metadata']['pod_assignments'],self.g['metadata']['pod_assignments'])
  old=next(x for x in self.g['components'] if x['id']=='IT-R01-01');new=next(x for x in g['components'] if x['id']==old['id'])
  self.assertEqual(new['center_m'][:2],[old['center_m'][0]+2,old['center_m'][1]])
  self.assertEqual(g['metadata']['connectivity_scenarios']['scenarios'][0]['tcs_path_status'],'PASS')
  self.assertTrue(any(x['id']=='pod-1' for x in g['layout']['editable_zones']))
 def test_an_eight_cdu_pod_arranges_without_stacking_lanes_to_the_ceiling(self):
  # Each CDU used to get its own elevated lane back to a collector left behind,
  # stacked 0.8 m apart: the eighth sat at 11.76 m, through a 6.5 m ceiling, so
  # this pod could not be arranged at all. The collector travels with the pod now.
  c=Config(**PRESETS['rd113']['config']);base,_=build(c)
  anchors=[list(s['original_anchor_m'][:2]) for s in base['metadata']['pod_transforms']]
  self.assertEqual(len(anchors),2)
  anchors[0][1]-=4.
  moved,p=build(replace(c,pod_origins_m=anchors))
  self.assertEqual([s['moved'] for s in moved['metadata']['pod_transforms']],[True,False])
  top=lambda g:max(n['xyz_m'][2] for n in g['nodes'])
  self.assertLessEqual(top(moved),top(base)+.35)
  self.assertLess(top(moved),c.ceiling_height_m-c.overhead_clearance_m)
  self.assertEqual(run(moved,replace(c,pod_origins_m=anchors),p)['blocking_failures'],[])
  # The pod's own facility-water pieces went with it rather than being rebuilt.
  before={x['id']:x['center_m'] for x in base['components'] if x.get('cdu')==1 and x['service']=='FWS' and x.get('center_m')}
  after={x['id']:x['center_m'] for x in moved['components'] if x.get('cdu')==1 and x['service']=='FWS' and x.get('center_m')}
  self.assertTrue(before and set(before)<=set(after))
  for cid,centre in before.items():
   self.assertAlmostEqual(after[cid][1],centre[1]-4.)
 def test_a_central_gallery_stands_each_pods_cdus_on_its_own_rows(self):
  # The CDU collector shared the row distribution spine at x=0, which silently
  # required the gallery to stand clear of the rows in Y. Centring it on them -
  # what this placement is for - put the collector tees on the row takeoffs and
  # blocked the design. The collector has its own lane now.
  c=Config(**PRESETS['rd113']['config'])
  for order in ([1,1,2,2],[2,2,1,1]):
   with self.subTest(rows=order):
    changed=replace(c,cdu_placement='central_gallery',row_pod_assignments=order,
                    cdu_pod_assignments=[1,1,1,1,2,2,2,2])
    g,p=build(changed)
    self.assertEqual(run(g,changed,p)['blocking_failures'],[])
    rows=g['metadata']['pod_assignments']['rows'];units=g['metadata']['pod_assignments']['cdus']
    for pod in (1,2):
     served=[g['layout']['compute_row_y_m'][i] for i,v in enumerate(rows) if v==pod]
     mine=[g['layout']['cdu_y_m'][i] for i,v in enumerate(units) if v==pod]
     # Each pod's gallery overlaps the rows it feeds, whichever way round the
     # pods were assigned to them.
     self.assertLess(min(mine),max(served))
     self.assertGreater(max(mine),min(served))
    gaps=[x for x in g['metadata']['guidance']['checks'] if 'stand with the rows' in x['check']]
    self.assertEqual([x['status'] for x in gaps],['PASS','PASS'])
 def test_every_gallery_and_layout_combination_still_routes(self):
  # A gallery standing close to the first row it feeds left the link between
  # them a 0.115 m leg to fit two 0.24 m bends in, and split_banks with a custom
  # origin put it exactly there: the design stopped building at all.
  c=Config(**PRESETS['rd113']['config'])
  for style in ('side_gallery','central_network','split_banks'):
   for placement in ('end_gallery','central_gallery','custom'):
    with self.subTest(style=style,placement=placement):
     changed=replace(c,layout_style=style,cdu_placement=placement)
     g,_=build(changed)
     self.assertTrue(any(x['kind']=='cdu' for x in g['components']))
 def test_an_end_gallery_reports_how_far_it_stands_off_the_rows(self):
  c=Config(**PRESETS['rd113']['config']);g,p=build(c)
  gaps=[x for x in g['metadata']['guidance']['checks'] if 'stand with the rows' in x['check']]
  self.assertEqual(len(gaps),2)
  # Standing the gallery off the hall is a choice, so this reports and never blocks.
  self.assertEqual([x['status'] for x in gaps],['FAIL','FAIL'])
  self.assertTrue(all(x['actual']>0 for x in gaps))
  self.assertEqual(run(g,c,p)['blocking_failures'],[])
 def test_footprint_contains_or_rejects_actual_geometry(self):
  good=replace(self.c,site_footprint_width_m=100,site_footprint_depth_m=100)
  g,p=build(good);self.assertEqual(g['metadata']['footprint_diagnostics']['status'],'PASS')
  g,p=build(replace(good,site_footprint_width_m=1))
  self.assertEqual(g['metadata']['footprint_diagnostics']['status'],'FAIL');self.assertTrue(run(g,replace(good,site_footprint_width_m=1),p)['blocking_failures'])
 def test_preliminary_sizes_are_applied_and_water_circuit_is_checked(self):
  for plant in ('air_cooled','water_cooled'):
   c=replace(self.c,plant_type=plant,sizing_mode='preliminary');g,p=build(c)
   self.assertEqual(run(g,c,p)['blocking_failures'],[])
   result=g['metadata']['preliminary_sizing'];self.assertTrue(result['geometry_modified']);self.assertFalse(result['network_pressure_solve_performed'])
   # A main is sized for what its own run carries, so the family recommendation
   # is the envelope none of them exceeds rather than the size all of them take.
   mains=[e['nominal_size_in'] for e in g['edges'] if e['kind']=='pipe' and e['service']=='FWS' and e['level']=='main']
   envelope=result['suggested_config']['fws_main_nominal_in']
   self.assertTrue(mains);self.assertEqual(max(mains),envelope)
   self.assertLess(min(mains),envelope)
   self.assertTrue(any(x['kind']=='tee' and x.get('reducing_designation') for x in g['components']))
   self.assertTrue(any(p.get('pump_head_m',0)>0 for p in result['pump_screens']))
 def test_bad_zone_arrays_are_rejected(self):
  for change in ({'pod_origins_m':[[1]]},{'pod_rotations_deg':[45]},{'site_footprint_width_m':20}):
   with self.assertRaises(ValueError):replace(self.c,**change).validate()
if __name__=='__main__':unittest.main()
