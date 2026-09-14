"""Worker lifetime and direct-manipulation regressions for the actual Python API."""
from dataclasses import replace
from pathlib import Path
import base64,io,json,sys,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import web_api
from model import Config, canonical_digest
from parameters import PRESETS

class BrowserSession(unittest.TestCase):
 def setUp(self):
  self.applied=json.loads(web_api.preview(json.dumps(PRESETS['compact']['config'])))
  self.digest=self.applied['config_hash']
 def test_click_without_movement_preserves_automatic_arrays_and_hash(self):
  before=web_api._session
  r=json.loads(web_api.apply_zone_edit(self.digest,json.dumps({'zone_id':'pod-1','anchor_m':[0,0,0]})))
  self.assertTrue(r['no_change']);self.assertIs(web_api._session,before)
  self.assertEqual(web_api._session[0]['metadata']['config']['pod_origins_m'],[])
 def test_two_consecutive_moves_apply_without_separate_preview(self):
  digest=self.digest
  for x in (.25,.5):
   r=json.loads(web_api.apply_zone_edit(digest,json.dumps({'zone_id':'pod-1','anchor_m':[x,0,0]})))
   self.assertTrue(r['valid'],r.get('checks'));self.assertTrue(r['result']['exportable'])
   digest=r['result']['config_hash'];self.assertEqual(web_api._session[2],digest)
   zone=next(z for z in r['result']['graph']['layout']['editable_zones'] if z['id']=='pod-1')
   self.assertEqual(zone['anchor_m'][0],x)
   # JavaScript JSON.stringify removes the .0 on integral-valued floats.
   def browser_numbers(value):
    if isinstance(value,dict):return {k:browser_numbers(v) for k,v in value.items()}
    if isinstance(value,list):return [browser_numbers(v) for v in value]
    return int(value) if type(value) is float and value.is_integer() else value
   config_json=json.dumps(browser_numbers(r['result']['config']))
   self.assertEqual(web_api.ensure_session(digest,config_json),digest)
   web_api._session=None
   self.assertEqual(web_api.ensure_session(digest,config_json),digest)
   self.assertTrue(web_api._session[0]['metadata']['equipment_requirements']['ready_for_matching'])
  self.assertNotEqual(digest,self.digest)
  self.assertEqual(json.loads(web_api.export_file('BOM.csv',digest))['config_hash'],digest)
 def test_overlap_rejection_preserves_model_and_exports(self):
  previous=web_api._session
  r=json.loads(web_api.apply_zone_edit(self.digest,json.dumps({'zone_id':'pod-1','anchor_m':[2,2,0]})))
  self.assertFalse(r['valid']);self.assertIs(web_api._session,previous)
  self.assertEqual(json.loads(web_api.export_file('BOM.csv',self.digest))['config_hash'],self.digest)
 def test_routing_exception_restores_previous_session(self):
  previous=web_api._session
  actual_preview=web_api.preview
  def broken_preview(config):
   actual_preview(config)
   raise ValueError('Test route cannot fit an explicit elbow')
  with patch.object(web_api,'preview',side_effect=broken_preview):
   r=json.loads(web_api.apply_zone_edit(self.digest,json.dumps({'zone_id':'plant','anchor_m':[-19.75,-16,0]})))
  self.assertFalse(r['valid']);self.assertIs(web_api._session,previous)
  self.assertIn('elbow',r['checks'][0]['detail'])
 def test_post_build_blocker_rolls_back_valid_applied_design(self):
  previous=web_api._session;actual_preview=web_api.preview
  def blocked_preview(config):
   result=json.loads(actual_preview(config));result['exportable']=False
   result['graph']['metadata']['blocking_findings']=[{'status':'FAIL','check':'Injected route clash'}]
   return json.dumps(result)
  with patch.object(web_api,'preview',side_effect=blocked_preview):
   r=json.loads(web_api.apply_zone_edit(self.digest,json.dumps({'zone_id':'plant','anchor_m':[-19.75,-16,0]})))
  self.assertFalse(r['valid']);self.assertIs(web_api._session,previous)
 def test_restarted_worker_recovers_export_and_finder_metadata(self):
  web_api._session=None
  report={'status':'unavailable','applied_config_hash':self.digest,'message':'Last checked catalogue was unavailable'}
  restored=web_api.ensure_session(self.digest,json.dumps(self.applied['config']),json.dumps(report))
  self.assertEqual(restored,self.digest)
  bundle=json.loads(web_api.export_file('BOM.csv',self.digest))
  with zipfile.ZipFile(io.BytesIO(base64.b64decode(bundle['base64']))) as z:
   self.assertEqual(json.loads(z.read('equipment_candidates.json')),report)
   self.assertEqual(json.loads(z.read('config_used.json')),self.applied['config'])
  before=web_api._session
  with self.assertRaisesRegex(ValueError,'do not match'):
   web_api.ensure_session(self.digest,json.dumps({**self.applied['config'],'rows':2}))
  self.assertIs(web_api._session,before)
