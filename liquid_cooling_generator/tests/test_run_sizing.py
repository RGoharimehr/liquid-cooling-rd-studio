"""A bore per run: what a pipe carries, not what its family is called."""
from pathlib import Path
from dataclasses import replace
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collections import defaultdict
from model import Config
from parameters import PRESETS
from pipeline import build
from geometry_checks import diagnose
from verify import run

REDUCING = ('reducer', 'tee')


class RunSizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Config(**PRESETS['rd113']['config'])
        cls.g, cls.p = build(cls.c)

    def mains(self, graph=None):
        return [e for e in (graph or self.g)['edges']
                if e['kind'] == 'pipe' and e['service'] == 'FWS' and e['level'] == 'main']

    def test_a_header_steps_down_instead_of_carrying_one_bore_to_its_last_tee(self):
        sizes = {e['nominal_size_in'] for e in self.mains()}
        # One bore per family gave the whole facility-water header the circuit's
        # size; carried duty gives the trunk that size and the ends far less.
        self.assertGreater(len(sizes), 1)
        envelope = self.g['metadata']['preliminary_sizing']['suggested_config']['fws_main_nominal_in']
        self.assertEqual(max(sizes), envelope)
        self.assertLess(min(sizes), envelope)

    def test_every_bore_change_sits_inside_a_fitting_built_to_hold_two(self):
        checks = {x['check']: x for x in diagnose(self.g, self.c)['checks']}
        for name in ('Connected nominal bores agree', 'Bore changes stay inside a reducing fitting'):
            self.assertEqual(checks[name]['status'], 'PASS', checks[name]['actual'])
        self.assertEqual(run(self.g, self.c, self.p)['blocking_failures'], [])
        for comp in self.g['components']:
            if comp.get('reducing'):
                self.assertIn(comp['kind'], REDUCING)

    def test_a_valve_given_two_bores_is_reported(self):
        import copy
        broken = copy.deepcopy(self.g)
        valve = next(x for x in broken['components']
                     if x['kind'] == 'isolation_valve' and len(x.get('port_details', [])) == 2)
        valve['port_details'][0]['nominal_size_in'] = valve['port_details'][1]['nominal_size_in'] + 2
        checks = {x['check']: x for x in diagnose(broken, self.c)['checks']}
        self.assertEqual(checks['Bore changes stay inside a reducing fitting']['status'], 'FAIL')

    def test_a_reducing_tee_is_designated_run_by_run_by_branch(self):
        tees = [x for x in self.g['components'] if x.get('reducing_designation')]
        self.assertTrue(tees)
        for tee in tees:
            self.assertEqual(tee['kind'], 'tee')
            parts = [float(v) for v in tee['reducing_designation'].split(' x ')]
            self.assertEqual(len(parts), 3)
            run_a, run_b, branch = parts
            self.assertEqual([run_a, run_b, branch],
                             [tee['port_sizes_in'][n] for n in tee['ports']])
            # A tee cannot enlarge what passes through it.
            self.assertLessEqual(branch, max(run_a, run_b))

    def test_no_run_is_sized_above_its_own_circuit_or_below_its_duty(self):
        estimates = {x['edge_id']: x for x in self.g['metadata']['preliminary_sizing']['edge_estimates']}
        caps = self.g['metadata']['run_sizing']['circuit_envelope_m3_s']
        for edge in self.g['edges']:
            item = estimates.get(edge['id'])
            if not item or item.get('design_flow_m3_s') is None or not edge.get('id_m'):
                continue
            self.assertLessEqual(item['design_flow_m3_s'], caps[item['circuit_id']] + 1e-12)
        self.assertEqual([e for e in self.g['edges'] if e.get('velocity_cap_pass') is False], [])

    def test_manual_sizing_still_takes_one_bore_per_family(self):
        manual = replace(self.c, sizing_mode='manual')
        g, p = build(manual)
        self.assertEqual(run(g, manual, p)['blocking_failures'], [])
        self.assertNotIn('run_sizing', g['metadata'])
        byfamily = defaultdict(set)
        for edge in g['edges']:
            if edge['kind'] == 'pipe' and edge.get('nominal_size_in'):
                # Air-unit branches sit at CDU level with a family of their own.
                key = edge.get('pipe_family') or (edge['service'], edge['level'])
                byfamily[key].add(edge['nominal_size_in'])
        for key, sizes in byfamily.items():
            self.assertEqual(len(sizes), 1, (key, sizes))


if __name__ == '__main__':
    unittest.main()
