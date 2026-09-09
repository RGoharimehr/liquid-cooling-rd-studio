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
   edge=next(e for e in g['edges'] if e['kind']=='pipe' and e['service']=='FWS' and e['level']=='main')
   self.assertEqual(edge['nominal_size_in'],result['suggested_config']['fws_main_nominal_in'])
   self.assertTrue(any(p.get('pump_head_m',0)>0 for p in result['pump_screens']))
 def test_bad_zone_arrays_are_rejected(self):
  for change in ({'pod_origins_m':[[1]]},{'pod_rotations_deg':[45]},{'site_footprint_width_m':20}):
   with self.assertRaises(ValueError):replace(self.c,**change).validate()
if __name__=='__main__':unittest.main()
