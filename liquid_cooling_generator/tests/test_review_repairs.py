"""Regression checks for actionable sizing, air heat, and world-coordinate editing."""
from dataclasses import replace
import base64,csv,io,json,unittest,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Config
from parameters import PRESETS,catalog
from pipeline import build
from zone_editing import propose_zone_edit,footprint_check
from hydraulics import select_size
from air_cooling import heat_ledger

class ReviewRepairs(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.c=Config(**PRESETS['compact']['config']);cls.g,_=build(cls.c)
 def test_air_heat_is_counted_once_and_air_coils_connected(self):
  c=replace(self.c,sizing_mode='preliminary',additional_air_load_W=12000);g,_=build(c)
  h=g['metadata']['heat_ledger'];s=g['metadata']['preliminary_sizing'];self.assertEqual(h['chiller_W'],c.rows*c.racks_per_row*c.rack_power_W+h['network_air_W']+12000)
  self.assertEqual(sum(x.get('heat_W',0) for x in g['components'] if x['kind']=='air_unit'),h['air_W'])
  self.assertEqual(s['thermal_flows']['plant_heat_W'],h['chiller_W']);self.assertEqual(g['metadata']['geometry_diagnostics']['blocking_failures'],0)
  self.assertTrue(all(x['ports'] and len(x['ports'])==2 for x in g['components'] if x['kind']=='air_unit'))
  self.assertAlmostEqual(sum(v['FWS_duty_heat_W']/v['installed_units']*v['duty_units'] for k,v in s['rack_and_equipment_duties'].items() if k.startswith('CHILLER')),h['chiller_W'])
  self.assertFalse(any(x.get('code')=='FLOW_ASSIGNMENT_UNRESOLVED' for x in s['unresolved']))
 def test_reported_size_limit_uses_verified_larger_commercial_size(self):
  size=select_size(.27400255055565675,'carbon_steel_sch40',3);self.assertEqual(size['nominal_size_in'],16)
 def test_all_ui_fields_have_effect_provenance_and_distinct_identity(self):
  fields=catalog();self.assertEqual(len(fields),len({f['key'] for f in fields}))
  for f in fields:self.assertTrue(f['effect'] and f['source']['title'] and f['source']['status'],f['key'])
  keys={f['key'] for f in fields};self.assertNotIn('velocity_cap_m_s',keys);self.assertNotIn('vendor_hose_min_bend_radius_m',keys)
  cws=next(f for f in fields if f['key']=='cws_density_kg_m3');self.assertEqual(cws['active_when'],{'plant_type':'water_cooled','sizing_mode':'preliminary'})
 def test_overlap_move_is_rejected_without_mutation(self):
  before=json.dumps(self.g,sort_keys=True)
  r=propose_zone_edit(self.g,self.c,'pod-1',anchor_m=[2,2]);self.assertFalse(r['valid']);self.assertTrue(r['checks'])
  self.assertEqual(before,json.dumps(self.g,sort_keys=True))
 def test_world_origin_and_local_rotation_remain_distinct(self):
  c=replace(self.c,layout_origin_x_m=40,layout_origin_y_m=20,layout_rotation_deg=30);g,_=build(c)
  z=next(z for z in g['layout']['editable_zones'] if z['id']=='plant')
  r=propose_zone_edit(g,c,'plant',rotation_deg=90,flip_x=True)
  self.assertEqual(r['config']['plant_rotation_deg'],90);self.assertTrue(r['config']['plant_flip_x']);self.assertAlmostEqual(r['config']['plant_origin_x_m'],c.plant_origin_x_m)
  self.assertAlmostEqual(z['anchor_layout_m'][0],c.plant_origin_x_m)
 def test_vendor_minimum_expands_service_geometry(self):
  g,_=build(replace(self.c,vendor_rack_front_clearance_m=2.5))
  zone=next(z for z in g['layout']['clearance_zones'] if z['id']=='IT-R01-front');self.assertEqual(zone['size_m'][1],2.5)
  self.assertGreater(g['metadata']['geometry_diagnostics']['blocking_failures'],0)
 def test_network_rotation_applies_once(self):
  c=replace(self.c,network_rotation_deg=90,network_offset_y_m=10);g,_=build(c)
  a=next(x for x in g['components'] if x['id']=='NET-R01-01');b=next(x for x in g['components'] if x['id']=='NET-R01-02')
  self.assertAlmostEqual(a['center_m'][0],b['center_m'][0]);self.assertAlmostEqual(b['center_m'][1]-a['center_m'][1],c.network_rack_pitch_m)
 def test_footprint_reserves_service_access_after_rotation(self):
  c=replace(self.c,site_footprint_origin_x_m=0,site_footprint_origin_y_m=0,site_footprint_width_m=10,site_footprint_depth_m=10)
  g={'components':[{'id':'EQUIPMENT-1','center_m':[5,5,1],'size_m':[1,1,2]}],
     'layout':{'clearance_zones':[{'id':'EQUIPMENT-1-service','host':'EQUIPMENT-1','center_m':[8.5,5,1],'size_m':[1,4,2],'rotation_deg':90}]}}
  result=footprint_check(g,c)
  self.assertEqual(result['status'],'FAIL')
  self.assertTrue(any('access' in check['check'] and check.get('components')==['EQUIPMENT-1'] for check in result['checks']))
  g['layout']['clearance_zones'][0]['center_m'][0]=7.5
  self.assertEqual(footprint_check(g,c)['status'],'PASS')
 def test_unavailable_size_keeps_bound_review_export_and_can_be_repaired(self):
  import web_api
  c=replace(self.c,sizing_mode='preliminary',fws_velocity_cap_m_s=.01)
  applied=json.loads(web_api.preview(json.dumps(c.__dict__)))
  self.assertFalse(applied['exportable'])
  sizing=applied['graph']['metadata']['preliminary_sizing']
  self.assertFalse(sizing['geometry_modified'])
  self.assertTrue(any(f.get('diagnostic',{}).get('actions') for f in sizing['size_families'] if not f.get('selection')))
  for format_name in ('zip','network.ifc','graph.json','revit_handoff.json'):
   with self.assertRaisesRegex(ValueError,'blocking geometry'):web_api.export_file(format_name,applied['config_hash'])
  with self.assertRaisesRegex(ValueError,'different design'):web_api.export_file('review','0'*64)
  result=json.loads(web_api.export_file('review',applied['config_hash']))
  self.assertEqual(result['config_hash'],applied['config_hash'])
  with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['base64']))) as archive:
   names=set(archive.namelist())
   self.assertTrue({'REVIEW_ONLY.txt','config_used.json','graph-review-only.json','geometry_diagnostics.json','preliminary_sizing.json','BOM.csv','connection_schedule.csv','source_register.json','import_status.json'}<=names)
   self.assertFalse(any(n.endswith(('.ifc','.pcf','.fnm')) or n=='revit_handoff.json' for n in names))
   self.assertEqual(json.loads(archive.read('graph-review-only.json'))['metadata']['config_hash'],applied['config_hash'])
   self.assertEqual(json.loads(archive.read('config_used.json'))['fws_velocity_cap_m_s'],.01)
   self.assertTrue(list(csv.DictReader(io.StringIO(archive.read('connection_schedule.csv').decode()))))
  repaired=json.loads(web_api.preview(json.dumps(replace(c,fws_velocity_cap_m_s=3).__dict__)))
  self.assertTrue(repaired['exportable'])
  self.assertNotEqual(applied['config_hash'],repaired['config_hash'])
  with self.assertRaisesRegex(ValueError,'different design'):web_api.export_file('review',applied['config_hash'])
