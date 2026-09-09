"""IFC exchange regressions: native schema, geometry, identity and graph ports.

Stdlib tests run without IfcOpenShell. Optional native tests run when it is
installed; full EXPRESS validation additionally requires pytest (an IfcOpenShell
validator dependency). No native dependency is imported by the exporter itself.
"""
from collections import Counter
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ifc4 import component_mesh, emit_ifc, stable_guid

try:
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.validate
except ImportError:
    ifcopenshell = None


def fixture():
    graph = {'metadata': {'graph_id': 'ifc-regression', 'name': "O'Brien liquid cooling °C 😀"},
             'nodes': [], 'components': [], 'edges': [], 'couplings': []}
    xyzs = {'a': [0, 0, 1], 'b': [1, 0, 1], 'c': [1.5, 0, 1], 'd': [1.25, .25, 1],
            'e': [2, 0, 1], 'f': [1.25, .6, 1], 'g': [2.3, .3, 1], 'h': [2.3, .8, 1],
            'i': [2.3, 1.2, 1], 'j': [3, 0, 1], 'k': [3, .5, 1]}
    graph['nodes'] = [{'id': key, 'xyz_m': p, 'service': 'FWS' if key in ('j', 'k') else 'TCS'}
                      for key, p in xyzs.items()]

    def add(cid, kind, ports, **extra):
        comp = {'id': cid, 'tag': cid, 'kind': kind, 'service': 'TCS', 'ports': ports,
                'od_m': .06, 'id_m': .05, 'material': 'stainless_steel', **extra}
        graph['components'].append(comp)
        if len(ports) == 2:
            graph['edges'].append({'id': 'edge/' + cid, 'component_id': cid,
                                   'from_node': ports[0], 'to_node': ports[1],
                                   'design_flow_m3_s': 0., 'flow_status': 'unassigned'})
        return comp

    add('pipe1', 'pipe', ['a', 'b'])
    add('tee1', 'tee', ['b', 'c', 'd'], center_m=[1.25, 0, 1])
    graph['edges'].extend([{'id': 'tee_run', 'component_id': 'tee1', 'from_node': 'b', 'to_node': 'c'},
                           {'id': 'tee_branch', 'component_id': 'tee1', 'from_node': 'b', 'to_node': 'd'}])
    add('pipe2', 'pipe', ['c', 'e'])
    add('valve1', 'isolation_valve', ['d', 'f'])
    add('bend1', 'elbow', ['e', 'g'], center_m=[2.3, 0, 1])
    add('pump1', 'pump', ['g', 'h'])
    add('hx_tcs', 'cdu_secondary', ['h', 'i'])
    add('hx_fws', 'cdu_primary', ['j', 'k'], service='FWS')
    add('rack1', 'compute_rack', [], center_m=[5, 0, 1.1], size_m=[.8, 1.2, 2.2], service='', hydraulic_element=False)
    add('network1', 'network_rack', [], center_m=[6, 0, 1.1], size_m=[.6, 1.2, 2.2], service='', hydraulic_element=False)
    add('cdu1', 'cdu_enclosure', [], center_m=[7, 0, 1.1], size_m=[1., 1.2, 2.2], service='', hydraulic_element=False)
    add('support1', 'pipe_support', ['b'], attachment=True, hydraulic_element=False)
    graph['couplings'] = [{'id': 'HX1', 'primary_component': 'hx_fws',
                          'secondary_component': 'hx_tcs', 'mass_transfer_kg_s': 0}]
    return graph


class StdlibIfcTests(unittest.TestCase):
    def test_deterministic_step_and_stable_component_identity_after_rerouting(self):
        graph = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            first = emit_ifc(graph, out)
            original = (out / 'network.ifc').read_bytes()
            emit_ifc(graph, out)
            self.assertEqual(original, (out / 'network.ifc').read_bytes())
            graph['nodes'][0]['xyz_m'][0] -= 1
            changed = emit_ifc(graph, out)
            self.assertEqual({c['component_id']: c['guid'] for c in first['ifc_components']},
                             {c['component_id']: c['guid'] for c in changed['ifc_components']})
            self.assertNotEqual(original, (out / 'network.ifc').read_bytes())

    def test_geometry_helper_accepts_envelopes_and_reports_tight_bend(self):
        graph = fixture()
        rack = next(c for c in graph['components'] if c['id'] == 'rack1')
        mesh = component_mesh(graph, rack)
        self.assertEqual(mesh['geometry_basis'], 'declared_envelope')
        for axis, expected in enumerate(rack['size_m']):
            values = [p[axis] for p in mesh['vertices']]
            self.assertAlmostEqual(max(values) - min(values), expected)
        bend = next(c for c in graph['components'] if c['id'] == 'bend1')
        bend['od_m'] = .8
        rough = component_mesh(graph, bend)
        self.assertTrue(rough['geometry_basis'].startswith('rough_miter_fallback'))
        self.assertTrue(rough['warnings'])

    def test_reject_invalid_mesh_and_cross_service_shared_node(self):
        graph = fixture()
        pipe = graph['components'][0]
        pipe['mesh'] = {'vertices': [[0, 0, 0], [1, 0, 0], [2, 0, 0]], 'faces': [[0, 1, 2]]}
        with self.assertRaisesRegex(ValueError, 'zero-area'):
            component_mesh(graph, pipe)
        graph = fixture()
        graph['components'][0]['service'] = 'FWS'
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, 'fluid services'):
            emit_ifc(graph, Path(tmp))

    def test_no_component_or_geometry_is_silently_omitted(self):
        graph = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = emit_ifc(graph, Path(tmp))
        self.assertEqual(manifest['ifc_element_count'], len(graph['components']))
        self.assertEqual(manifest['ifc_skipped_count'], 0)
        self.assertEqual(manifest['ifc_port_count'], 17)
        self.assertEqual(manifest['ifc_port_connections'], 6)
        self.assertEqual(manifest['ifc_thermal_coupling_groups'], 1)
        self.assertTrue(all(c['mesh_closed'] for c in manifest['ifc_components']))


@unittest.skipUnless(ifcopenshell is not None, 'Optional IfcOpenShell validation dependency is absent')
class NativeIfcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.graph = fixture()
        # A supplied polygon mesh must survive the exact same exchange path.
        cdu = next(c for c in cls.graph['components'] if c['id'] == 'cdu1')
        cdu['mesh'] = component_mesh(cls.graph, cdu)
        cls.manifest = emit_ifc(cls.graph, cls.out)
        cls.model = ifcopenshell.open(str(cls.out / 'network.ifc'))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_ifc_schema_and_type_property_assignments(self):
        logger = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(self.model, logger)
        self.assertEqual(logger.statements, [])
        for typ in self.model.by_type('IfcTypeObject'):
            self.assertTrue(typ.HasPropertySets)
        for relation in self.model.by_type('IfcRelDefinesByProperties'):
            self.assertFalse(any(obj.is_a('IfcTypeObject') for obj in relation.RelatedObjects))
        expected = {'IfcPipeSegment': 2, 'IfcPipeFitting': 2, 'IfcValve': 1, 'IfcPump': 1,
                    'IfcHeatExchanger': 2, 'IfcBuildingElementProxy': 3, 'IfcDiscreteAccessory': 1}
        self.assertEqual({kind: len(self.model.by_type(kind)) for kind in expected}, expected)

    def test_full_express_rules(self):
        try:
            import _pytest
        except ImportError:
            self.skipTest('Full EXPRESS validator additionally requires pytest')
        logger = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(self.model, logger, express_rules=True)
        self.assertEqual(logger.statements, [])

    def test_populated_systems_and_exact_component_port_connectivity(self):
        systems = {system.Name: {e.Tag for rel in system.IsGroupedBy for e in rel.RelatedObjects}
                   for system in self.model.by_type('IfcDistributionSystem')}
        for service in ('TCS', 'FWS'):
            expected = {c['id'] for c in self.graph['components'] if c['service'] == service and not c.get('attachment')}
            self.assertEqual(systems[service], expected)
        owner = {}
        for relation in self.model.by_type('IfcRelNests'):
            for port in relation.RelatedObjects:
                self.assertNotIn(port.GlobalId, owner)
                owner[port.GlobalId] = relation.RelatingObject.Tag
        self.assertEqual(len(owner), 17)
        graph_nodes = {}
        for comp in self.graph['components']:
            if comp.get('attachment'):
                continue
            for node in comp['ports']:
                graph_nodes.setdefault(node, set()).add(comp['id'])
        expected_pairs = {frozenset(items) for items in graph_nodes.values() if len(items) == 2}
        actual_pairs = {frozenset([owner[r.RelatingPort.GlobalId], owner[r.RelatedPort.GlobalId]])
                        for r in self.model.by_type('IfcRelConnectsPorts')}
        self.assertEqual(actual_pairs, expected_pairs)
        self.assertNotIn(frozenset(['hx_tcs', 'hx_fws']), actual_pairs)
        self.assertEqual({r.RelatingPort.FlowDirection for r in self.model.by_type('IfcRelConnectsPorts')}, {'SOURCE'})
        self.assertEqual({r.RelatedPort.FlowDirection for r in self.model.by_type('IfcRelConnectsPorts')}, {'SINK'})

    def test_return_tee_directions_follow_graph_edges_with_unassigned_zero_flows(self):
        graph = fixture()
        for edge in graph['edges']:
            edge['from_node'], edge['to_node'] = edge['to_node'], edge['from_node']
        with tempfile.TemporaryDirectory() as tmp:
            emit_ifc(graph, Path(tmp))
            model = ifcopenshell.open(str(Path(tmp) / 'network.ifc'))
        ports = {p.Name: p.FlowDirection for p in model.by_type('IfcDistributionPort')}
        self.assertEqual(ports['tee1:b'], 'SOURCE')
        self.assertEqual(ports['tee1:c'], 'SINK')
        self.assertEqual(ports['tee1:d'], 'SINK')
        self.assertTrue(all(r.RelatingPort.FlowDirection == 'SOURCE' and r.RelatedPort.FlowDirection == 'SINK'
                            for r in model.by_type('IfcRelConnectsPorts')))

    def test_tessellation_bounds_and_non_ascii_strings_round_trip(self):
        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)
        bounds = {}
        for element in self.model.by_type('IfcElement'):
            shape = ifcopenshell.geom.create_shape(settings, element)
            self.assertTrue(shape.geometry.verts)
            self.assertTrue(shape.geometry.faces)
            v = shape.geometry.verts
            bounds[element.Tag] = [(min(v[i::3]), max(v[i::3])) for i in range(3)]
        self.assertEqual(self.model.by_type('IfcProject')[0].Name, self.graph['metadata']['name'])
        # The branch center must fall within the tee body, not outside a run-only tube.
        branch = [1.25, .25, 1]
        self.assertTrue(all(lo-1e-6 <= x <= hi+1e-6 for x, (lo, hi) in zip(branch, bounds['tee1'])))
        self.assertAlmostEqual(bounds['rack1'][2][0], 0.)
        self.assertAlmostEqual(bounds['rack1'][2][1], 2.2)
        self.assertAlmostEqual(bounds['cdu1'][0][1]-bounds['cdu1'][0][0], 1.)

    def test_ifc_guid_encoding_matches_native_library(self):
        namespace = uuid.UUID('8a9201a1-f6ef-534f-bb32-26a071f14fbf')
        for i in range(100):
            raw = uuid.uuid5(namespace, 'liquid-cooling-reference/' + str(i))
            self.assertEqual(stable_guid(str(i)), ifcopenshell.guid.compress(raw.hex))


if __name__ == '__main__':
    unittest.main()
