"""Regression and acceptance checks for connected reference layouts (no solver)."""
from dataclasses import replace
from pathlib import Path
import sys,json,math,csv,tempfile,unittest,subprocess
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Config,build_profile
from topology import route_graph
from sizing import apply_sizes
from pipeline import build,run
from parameters import PRESETS,catalog
from placement import place_installation,installation_diagnostics

class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=Config(rows=2,racks_per_row=3,cdu_count=3,redundancy=1)
        cls.g,cls.p=build(cls.c)
    def test_networks_and_rack_types(self):
        g=self.g;used={s:set() for s in ('TCS','FWS')}
        for e in g['edges']:used[e['service']].update((e['from_node'],e['to_node']))
        self.assertFalse(used['TCS']&used['FWS'])
        for c in g['components']:
            if c['kind']=='network_rack':self.assertEqual(c['ports'],[]);self.assertEqual(c['liquid_fraction'],0)
        self.assertEqual(sum(c['kind']=='compute_rack' for c in g['components']),6)
        self.assertEqual(sum(c['kind']=='cdu' and 'secondary_pump' in c['functions'] for c in g['components']),3)
        self.assertFalse(any(c['kind']=='pump' for c in g['components']))
    def test_manual_sizes_and_no_pressure_solver(self):
        self.assertEqual(self.g['hydraulics']['mode'],'manual')
        self.assertFalse(self.g['hydraulics']['network_pressure_solve_performed'])
        for e in self.g['edges']:
            self.assertGreaterEqual(e['design_flow_m3_s'],0)
            self.assertNotIn('dp_Pa',e)
            self.assertGreater(e['od_m'],e['id_m'])
        self.assertTrue(any(e['design_flow_m3_s']>0 for e in self.g['edges']))
        e=next(e for e in self.g['edges'] if e['level']=='rack')
        self.assertEqual(e['nominal_size_in'],2)
        self.assertAlmostEqual(e['id_m'],1.985*.0254)
    def test_route_length_and_explicit_junction_ownership(self):
        g=self.g;n={n['id']:n['xyz_m'] for n in g['nodes']};owners={}
        for c in g['components']:
            if not c.get('attachment'):
                for p in c['ports']:owners.setdefault(p,[]).append(c['id'])
        self.assertLessEqual(max(map(len,owners.values())),2)
        for e in g['edges']:
            if e['kind']=='pipe':self.assertAlmostEqual(e['length_m'],math.dist(n[e['from_node']],n[e['to_node']]))
    def test_general_redundancy_and_prescribed_flow_conservation(self):
        for redundancy in (0,1,2):
            c=replace(self.c,redundancy=redundancy,sizing_mode='preliminary');g,_=build(c)
            self.assertEqual(sum(s['kind']=='design' for s in g['scenarios']),math.comb(3,redundancy))
            sizing=g['metadata']['preliminary_sizing']
            self.assertFalse([x for x in sizing['unresolved'] if x.get('code')=='FLOW_ASSIGNMENT_UNRESOLVED'])
            edges={e['id']:e for e in g['edges']}
            residual={n['id']:0. for n in g['nodes']}
            for item in sizing['edge_estimates']:
                q=item.get('signed_all_online_flow_m3_s')
                if q is None:continue
                e=edges[item['edge_id']];residual[e['from_node']]-=q;residual[e['to_node']]+=q
            for n in (g['metadata']['fws_source'],g['metadata']['fws_sink']):residual.pop(n)
            self.assertLess(max(map(abs,residual.values())),1e-9)
            # One design flow per circuit: the graph block and the sizing block
            # are derived the same way and must not drift apart again.
            flows=g['hydraulics']['heat_and_flow'];thermal=sizing['thermal_flows']
            self.assertAlmostEqual(flows['tcs_total_m3_s'],thermal['TCS_m3_s'],places=12)
            self.assertAlmostEqual(flows['fws_total_m3_s'],thermal['FWS_m3_s'],places=12)
    def test_topology_and_placement_knobs_change_geometry(self):
        base=self.g
        for changes in ({'layout_style':'central_network'},{'layout_style':'split_banks'},{'return_topology':'reverse_return'},{'cdu_placement':'custom','cdu_origin_x_m':-8.,'cdu_origin_y_m':-12.}):
            g,p=build(replace(self.c,**changes))
            self.assertNotEqual([n['xyz_m'] for n in g['nodes']],[n['xyz_m'] for n in base['nodes']])
            self.assertEqual(sum(c['kind']=='compute_rack' and len(c['ports'])==2 for c in g['components']),6)
    def test_inline_toggles_and_installation_controls(self):
        c=replace(self.c,include_quick_disconnects=False,include_flex_connectors=False,include_leak_detection=False,include_rack_isolation_valves=False,include_supports=False)
        g,p=build(c);kinds=[x['kind'] for x in g['components']]
        self.assertNotIn('quick_disconnect',kinds);self.assertNotIn('flex_connector',kinds);self.assertNotIn('leak_detector',kinds);self.assertNotIn('pipe_support',kinds)
        self.assertIn('drip_tray',kinds)
        g['components']=[x for x in self.g['components'] if x['kind']!='leak_detector']
        diagnostics=installation_diagnostics(g,self.c,self.p)
        self.assertTrue(any(x['status']=='FAIL' and 'Leak sensors' in x['check'] for x in diagnostics['checks']))
    def test_extrema_coverage_and_idempotence(self):
        g,p=build(self.c);before=len(g['components']);place_installation(g,p)
        self.assertEqual(before,len(g['components']))
        g['components']=[x for x in g['components'] if x['kind']!='vent']
        d=installation_diagnostics(g,self.c,p)
        self.assertTrue(any(x['status']=='FAIL' and 'vent' in x['check'] for x in d['checks']))
    def test_export_accounting_metadata_and_stale_failure(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';g=run(self.c,out)
            saved=json.loads((out/'graph.json').read_text());self.assertIn('emission',saved['metadata']);self.assertIn('verification',saved['metadata'])
            m=json.loads((out/'geometry_export_manifest.json').read_text());emitted={x['parent_component_id'] for x in m['emitted']}
            self.assertEqual(emitted,{e['component_id'] for e in g['edges']})
            bom=list(csv.DictReader((out/'BOM.csv').read_text().splitlines()));self.assertEqual(len(bom),len(g['components']))
            old=(out/'network.ifc').read_bytes()
            with patch('ifc4.emit_ifc',side_effect=ValueError('injected export failure')):
                with self.assertRaises(ValueError):run(self.c,out)
            self.assertEqual(old,(out/'network.ifc').read_bytes())
            run(replace(self.c,rows=1,racks_per_row=1),out)
            owned=json.loads((out/'sha256_manifest.json').read_text());self.assertFalse(any('ROW-02' in x for x in owned))
    def test_parameter_catalog_and_invalid_controls(self):
        for field in catalog():self.assertIn(field['key'],self.c.__dict__);self.assertTrue(field['source']['note'])
        for changes in ({'rows':0},{'rows':1.5},{'include_vents':'no'},{'standards_overrides':{'unknown':2}},{'sizing_mode':'heat_balance','pg_volume_fraction':.1},{'rack_nominal_in':-2}):
            with self.assertRaises((ValueError,TypeError)):replace(self.c,**changes).validate()
    def test_clearance_and_rd_reference(self):
        g,p=build(replace(self.c,ceiling_height_m=4.1));self.assertGreater(g['metadata']['layout_compliance']['fail_count'],0)
        rd=Config(**PRESETS['rd113']['config']);g,p=build(rd)
        self.assertEqual(sum(c['kind']=='compute_rack' for c in g['components']),64)
        # RD113 R1: 32 networking racks, 880 kW (8 SMN + 8 N/S at 15 kW,
        # 8 CME at 35 kW, 8 CIN at 45 kW). R0 had 24 racks and 640 kW.
        self.assertEqual(sum(c['kind']=='network_rack' for c in g['components']),32)
        self.assertEqual(g['layout']['network_power_W'],880000)
        ys=g['layout']['compute_row_y_m'];ny=g['layout']['network_origin_m'][1];self.assertLess(ys[1],ny);self.assertLess(ny,ys[2])
    def test_corpus_ids_and_partial_evidence(self):
        from verify import canonical_document_id,load_corpus
        self.assertEqual(canonical_document_id('OCP-Specification-Deschutes v1_0.pdf'),'OCP-Specification-Deschutes_v1_0')
        self.assertEqual(canonical_document_id('2025 Modular TCS CloudScale Design Delivery Selection Guidance Rev 1 March.pdf'),'2025_Modular_TCS_CloudScale_Rev_1_March')
        docs,meta=load_corpus();self.assertTrue(docs);self.assertTrue(all(m['partial'] for m in meta.values()))

    def test_cli_nonconforming_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);c=replace(self.c,rows=1,racks_per_row=1,ceiling_height_m=4.1);conf=td/'c.json';conf.write_text(json.dumps(c.__dict__))
            cmd=[sys.executable,str(Path(__file__).resolve().parents[1]/'run.py'),'--config',str(conf),'--out',str(td/'out')]
            self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,2)
            self.assertEqual(subprocess.run(cmd+['--allow-nonconforming'],capture_output=True).returncode,0)
if __name__=='__main__':unittest.main()
