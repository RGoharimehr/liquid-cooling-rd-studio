from pathlib import Path
from dataclasses import replace
import base64,copy,io,json,sys,tempfile,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Config
from parameters import PRESETS,catalog
from pipeline import build,emit
from verify import run
from geometry_checks import diagnose
from contract import attach_contract
from handoff import emit_handoff

class ContractV2Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.c=Config(**PRESETS['compact']['config']);cls.g,cls.p=build(cls.c)
 def test_presets_and_water_have_no_blocking_geometry(self):
  for name,values in [(k,v['config']) for k,v in PRESETS.items()]+[('water',{**PRESETS['compact']['config'],'plant_type':'water_cooled'})]:
   with self.subTest(name=name):
    c=Config(**values);g,p=build(c);self.assertEqual(run(g,c,p)['blocking_failures'],[])
    self.assertEqual(g['metadata']['connectivity_scenarios']['scenarios'][0]['tcs_path_status'],'PASS')
 def test_cdu_reducer_connections_are_coaxial_with_explicit_elbows(self):
  refs={}
  for c in self.g['components']:
   if c.get('attachment'):continue
   for p in c.get('port_details',[]):refs.setdefault(p['node_id'],[]).append((c,p))
  cdus=[c for c in self.g['components'] if c['kind']=='cdu'];self.assertEqual(len(cdus),3)
  for c in cdus:
   self.assertEqual(len(c['port_details']),4)
   self.assertEqual({p['service'] for p in c['port_details']},{'TCS','FWS'})
  for c in self.g['components']:
   if c['kind']!='reducer' or c.get('cdu') is None:continue
   normals=[p['outward'] for p in c['port_details']];self.assertAlmostEqual(sum(a*b for a,b in zip(*normals)),-1)
   for p in c['port_details']:
    others=[(a,q) for a,q in refs[p['node_id']] if a['id']!=c['id']]
    self.assertEqual(len(others),1)
    self.assertAlmostEqual(sum(a*b for a,b in zip(p['outward'],others[0][1]['outward'])),-1)
    self.assertAlmostEqual(p['id_m'],others[0][1]['id_m'])
  self.assertTrue(any(c['kind']=='elbow' and c.get('cdu') is not None for c in self.g['components']))
 def test_crossings_and_broken_turn_are_detected(self):
  # Six spatially separated crossing pairs: detection cannot rely on graph adjacency.
  g={'metadata':{},'nodes':[],'components':[]}
  for i in range(6):
   for j,points in enumerate(([[i*5,0,4],[i*5+2,0,4]],[[i*5+1,-1,4],[i*5+1,1,4]])):
    cid=f'cross-{i}-{j}';ports=[]
    for k,xyz in enumerate(points):nid=cid+str(k);g['nodes'].append({'id':nid,'xyz_m':xyz});ports.append(nid)
    g['components'].append({'id':cid,'kind':'pipe','ports':ports,'port_details':[],'od_m':.1})
  d=diagnose(g,self.c);self.assertEqual(d['clash_count'],6)
  changed=copy.deepcopy(self.g);p=next(c for c in changed['components'] if c['kind']=='reducer')['port_details'][0];p['outward']=[0,0,1]
  self.assertTrue(any(x['status']=='FAIL' and 'face' in x['check'] for x in diagnose(changed,self.c)['checks']))
 def test_pods_and_plant_circuits(self):
  c=replace(self.c,pod_count=2,cdu_count=4,ceiling_height_m=6.5,plant_type='water_cooled');g,p=build(c)
  for comp in g['components']:
   if comp['kind']=='cdu':self.assertEqual(len({x['circuit_id'] for x in comp['port_details']}),2)
   if comp['kind']=='chiller':self.assertEqual({x['circuit_id'] for x in comp['port_details']},{'FWS','CWS'})
  self.assertEqual({e['circuit_id'] for e in g['edges']},{'FWS','CWS','TCS-P01','TCS-P02'})
  self.assertEqual(run(g,c,p)['blocking_failures'],[])
  assignments=[2,1,2,1];changed,_=build(replace(c,row_pod_assignments=assignments,cdu_pod_assignments=assignments))
  self.assertEqual(changed['metadata']['pod_assignments']['rows'],assignments)
 def test_active_generator_expands_redundancy_scenarios(self):
  c=replace(self.c,cdu_count=4,redundancy=2,ceiling_height_m=6.5,plant_type='water_cooled');g,_=build(c)
  self.assertEqual(g['metadata']['redundancy']['duty_units'],2)
  self.assertEqual(g['metadata']['redundancy']['capacity_per_cdu_W'],g['couplings'][0]['design_capacity_W'])
  design=[s for s in g['scenarios'] if s['kind']=='design']
  self.assertEqual(len(design),6)
  self.assertEqual({tuple(s['active_cdus']) for s in design},{(1,2),(1,3),(1,4),(2,3),(2,4),(3,4)})
  for scenario in design:
  offline=sorted(set(range(1,c.cdu_count+1))-set(scenario['active_cdus']))
  disabled={x for index in offline for x in g['couplings'][index-1]['component_ids']}
  closed={x for index in offline for x in g['couplings'][index-1]['isolation_components']}
  self.assertEqual(set(scenario['disabled_components']),disabled)
  self.assertEqual(set(scenario['closed_components']),closed)
  for index,coupling in enumerate(g['couplings'],1):
  self.assertEqual(coupling['scenario_heat_W']['all_online'],coupling['heat_W'])
  self.assertEqual(sum(value>0 for name,value in coupling['scenario_heat_W'].items() if name!='all_online'),3)
  self.assertEqual(max(coupling['scenario_heat_W'].values()),g['metadata']['redundancy']['capacity_per_cdu_W'])
 def test_migration_stable_identity_and_parameter_effects(self):
  self.assertEqual(Config.from_dict({'rows':2}).plant_type,'boundary')
  changed,p=build(replace(self.c,rack_pitch_m=.95,layout_rotation_deg=30))
  a={x['id'] for x in self.g['components'] if not x.get('attachment')};b={x['id'] for x in changed['components'] if not x.get('attachment')};self.assertEqual(a,b)
  self.assertNotEqual(changed['metadata']['config_hash'],self.g['metadata']['config_hash'])
  self.assertNotEqual(changed['nodes'][0]['xyz_m'],self.g['nodes'][0]['xyz_m'])
  for field in catalog():
   self.assertTrue(field['source']['title']);self.assertTrue(field['source']['edition']);self.assertTrue(field['source']['applicability']);self.assertIn(field['source']['status'],['assumption','guidance','reference','vendor_requirement'])
 def test_handoff_pcf_and_on_demand_bundle(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td);emit(self.g,self.p,out);handoff=json.loads((out/'revit_handoff.json').read_text())
   self.assertEqual(handoff['config_hash'],self.g['metadata']['config_hash']);self.assertTrue((out/'revit/ImportCommand.cs').exists())
   self.assertEqual(handoff['import_status']['revit'],'NOT_TESTED_IN_TARGET_APPLICATION')
   self.assertFalse((out/'network_EQUIPMENT.pcf').exists())
   text=(out/'network_FWS.pcf').read_text();self.assertIn('FWS-PUMP-01',text);self.assertIn('CHILLER-01',text)
  import web_api
  result=json.loads(web_api.preview(json.dumps(self.c.__dict__)))
  self.assertTrue(result['exportable'])
  with self.assertRaises(ValueError):web_api.export_file('network.ifc','stale')
  data=json.loads(web_api.export_file('network.ifc',result['config_hash']))
  with zipfile.ZipFile(io.BytesIO(base64.b64decode(data['base64']))) as archive:
   for name in ['network.ifc','config_used.json','BOM.csv','connection_schedule.csv','source_register.json','geometry_diagnostics.json','import_status.json']:self.assertIn(name,archive.namelist())
   self.assertEqual(json.loads(archive.read('revit_handoff.json'))['config_hash'],result['config_hash'])
  with self.assertRaises(ValueError):web_api.preview(json.dumps({**self.c.__dict__,'rows':0}))
  self.assertEqual(json.loads(web_api.export_file('graph.json',result['config_hash']))['config_hash'],result['config_hash'])
if __name__=='__main__':unittest.main()
