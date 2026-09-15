"""Declared handover points: where each pod meets the facility, and which one it uses."""
from pathlib import Path
from dataclasses import replace
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from math import dist
from model import Config
from parameters import PRESETS
from pipeline import build
from network_v2 import assign_connections


class AssignmentTests(unittest.TestCase):
    def points(self):
        return [{'id': 'near', 'point_m': [0., 0., 0.], 'capacity_m3_s': .10},
                {'id': 'far', 'point_m': [100., 0., 0.], 'capacity_m3_s': 1.}]

    def test_every_zone_takes_the_nearest_point_that_has_room(self):
        zones = [{'id': 'pod-1', 'point_m': [1., 0., 0.], 'flow_m3_s': .06},
                 {'id': 'pod-2', 'point_m': [2., 0., 0.], 'flow_m3_s': .06}]
        rows = assign_connections(zones, self.points())
        self.assertEqual(rows[0]['connection_point'], 'near')
        self.assertNotIn('status', rows[0])
        # 0.06 + 0.06 exceeds the near point, so the second pod spills to the far one
        # whole rather than sending half its duty somewhere else.
        self.assertEqual(rows[1]['connection_point'], 'far')
        self.assertTrue(rows[1]['status'].startswith('SPILLED'))
        self.assertAlmostEqual(rows[1]['distance_m'], 98.)

    def test_a_zone_no_point_can_take_is_reported_not_hidden(self):
        zones = [{'id': 'pod-1', 'point_m': [1., 0., 0.], 'flow_m3_s': 4.}]
        rows = assign_connections(zones, self.points())
        self.assertTrue(rows[0]['status'].startswith('OVERSUBSCRIBED'))
        self.assertEqual(rows[0]['connection_point'], 'near')

    def test_an_undeclared_capacity_never_blocks_an_assignment(self):
        zones = [{'id': 'pod-1', 'point_m': [1., 0., 0.], 'flow_m3_s': 9.}]
        rows = assign_connections(zones, [{'id': 'open', 'point_m': [0., 0., 0.], 'capacity_m3_s': None}])
        self.assertEqual(rows[0]['connection_point'], 'open')
        self.assertNotIn('status', rows[0])


class DeclaredPointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Config(**PRESETS['rd113']['config'])
        cls.g, cls.p = build(cls.c)

    def declared(self, graph=None):
        return (graph or self.g)['metadata']['connection_points']

    def test_each_pod_declares_one_point_and_the_facility_can_carry_them_all(self):
        declared = self.declared()
        self.assertEqual([z['id'] for z in declared['zones']], ['pod-1', 'pod-2'])
        capacity = declared['facility'][0]['capacity_m3_s']
        self.assertGreaterEqual(capacity, sum(z['flow_m3_s'] for z in declared['zones']))
        for row in declared['assignments']:
            self.assertEqual(row['connection_point'], 'facility-fws')
            self.assertNotIn('status', row)

    def test_the_interface_sits_on_the_side_the_plant_is_on(self):
        nodes = {n['id']: n['xyz_m'] for n in self.g['nodes']}
        facility = self.declared()['facility'][0]
        cdus = [c['center_m'][1] for c in self.g['components'] if c['kind'] == 'cdu']
        # Every pod reaches the plant without first travelling past the far end
        # of the CDU line, which is what the single north-exit collector did.
        self.assertLess(facility['point_m'][1], min(cdus))
        self.assertEqual(facility['outward_dir'], [0, -1, 0])
        for zone in self.declared()['zones']:
            self.assertGreater(nodes[zone['supply_node']][1], facility['point_m'][1])

    def test_the_pod_beside_the_plant_has_the_shorter_connection(self):
        by = {z['id']: z for z in self.declared()['zones']}
        rows = {r['zone']: r for r in self.declared()['assignments']}
        self.assertLess(by['pod-1']['point_m'][1], by['pod-2']['point_m'][1])
        self.assertLess(rows['pod-1']['distance_m'], rows['pod-2']['distance_m'])

    def test_a_boundary_design_keeps_the_north_interface(self):
        c = replace(self.c, plant_type='boundary')
        g, _ = build(c)
        facility = self.declared(g)['facility'][0]
        cdus = [comp['center_m'][1] for comp in g['components'] if comp['kind'] == 'cdu']
        self.assertGreater(facility['point_m'][1], max(cdus))
        self.assertEqual(facility['kind'], 'boundary')


if __name__ == '__main__':
    unittest.main()
