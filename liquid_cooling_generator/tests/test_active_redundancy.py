"""Regression tests must use the active public pipeline, not legacy topology."""
from dataclasses import replace
from itertools import combinations
from math import comb
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import Config
from pipeline import build
from verify import run
from parameters import catalog


class ActiveRedundancyTests(unittest.TestCase):
    def test_n0_n1_n2_remove_declared_units_and_conserve_assigned_heat(self):
        for redundancy in (0, 1, 2):
            with self.subTest(redundancy=redundancy):
                config = Config(rows=2, racks_per_row=1, cdu_count=3, redundancy=redundancy,
                                liquid_fraction=1., rack_power_W=140000.)
                graph, profile = build(config)
                scenarios = [case for case in graph['scenarios'] if case['kind']=='design']
                self.assertEqual(len(scenarios), comb(3, redundancy))
                self.assertEqual({tuple(case['offline_cdus']) for case in scenarios},
                                 set(combinations((1,2,3), redundancy)))
                self.assertEqual(scenarios[0]['name'], 'design')
                self.assertEqual(graph['scenarios'][0]['active_cdus'], [1,2,3])
                couplings = {int(item['id'].split('-')[1]): item for item in graph['couplings']}
                checked = {case['name']:case for case in graph['metadata']['connectivity_scenarios']['scenarios']}
                for case in scenarios:
                    self.assertEqual(len(case['active_cdus']), 3-redundancy)
                    self.assertEqual(set(case['active_cdus']) | set(case['offline_cdus']), {1,2,3})
                    self.assertEqual(set(case['active_cdus']) & set(case['offline_cdus']), set())
                    self.assertEqual(checked[case['name']]['active_cdus'], case['active_cdus'])
                    self.assertEqual(checked[case['name']]['tcs_path_status'], 'PASS')
                    self.assertFalse(checked[case['name']]['operational_redundancy_proven'])
                    self.assertEqual(checked[case['name']]['capacity_status'], 'NOT_EVALUABLE')
                    for unit in case['offline_cdus']:
                        self.assertIn(f'CDU-{unit:02}', case['disabled_components'])
                        self.assertTrue(set(couplings[unit]['isolation_components']) <= set(case['closed_components']))
                        self.assertEqual(couplings[unit]['scenario_heat_W'][case['name']], 0)
                    for unit in case['active_cdus']:
                        self.assertAlmostEqual(couplings[unit]['scenario_heat_W'][case['name']], 280000./(3-redundancy))
                    self.assertAlmostEqual(sum(item['scenario_heat_W'][case['name']] for item in couplings.values()), 280000.)
                nominal = next(case for case in scenarios if case['name']=='design')
                spare_ids = [comp['cdu'] for comp in graph['components'] if comp['kind']=='cdu' and comp['duty_role']=='spare']
                self.assertEqual(spare_ids, nominal['offline_cdus'])
                duties = graph['metadata']['preliminary_sizing']['rack_and_equipment_duties']
                self.assertAlmostEqual(duties['CDU-01']['screening_duty_heat_W'], 280000./(3-redundancy))
                self.assertEqual(graph['metadata']['connectivity_scenarios']['blocking_failures'], 0)
                # N+0 may still have diagnostic single-isolation cases, but
                # only the actual requested outage cases gate the design.
                self.assertFalse(any('CDU outage connectivity' in item['check'] for item in run(graph,config,profile)['blocking_failures']))

    def test_independent_pods_allocate_only_their_own_heat_after_outages(self):
        config = Config(rows=4, racks_per_row=1, cdu_count=4, redundancy=1, pod_count=2,
                        row_pod_assignments=[1,1,1,2], cdu_pod_assignments=[1,2,1,2], ceiling_height_m=8.)
        graph, _ = build(config)
        couplings = {int(item['id'].split('-')[1]): item for item in graph['couplings']}
        for case in graph['scenarios']:
            states = case['pod_states']
            self.assertEqual(states['TCS-P01']['installed_cdus'], [1,3])
            self.assertEqual(states['TCS-P02']['installed_cdus'], [2,4])
            self.assertAlmostEqual(states['TCS-P01']['liquid_heat_W'], 3*states['TCS-P02']['liquid_heat_W'])
            for state in states.values():
                self.assertAlmostEqual(sum(couplings[unit]['scenario_heat_W'][case['name']] for unit in state['installed_cdus']), state['liquid_heat_W'])
                self.assertEqual(state['unserved_heat_W'], 0)
        self.assertEqual(graph['metadata']['connectivity_scenarios']['blocking_failures'], 0)

    def test_global_n2_cannot_silently_borrow_capacity_across_two_cdu_pods(self):
        config = Config(rows=2, racks_per_row=1, cdu_count=4, redundancy=2,
                        pod_count=2, ceiling_height_m=8.)
        graph, profile = build(config)
        cases = [case for case in graph['scenarios'] if case['kind']=='design']
        self.assertEqual(len(cases), 6)
        self.assertEqual(sum(bool(case['unavailable_pods']) for case in cases), 2)
        # The representative case keeps both pods running, but the two
        # concentrated-outage alternatives must still block the requested N+2.
        self.assertEqual(next(case for case in cases if case['name']=='design')['unavailable_pods'], [])
        outage = next(case for case in cases if case['offline_cdus']==[1,2])
        self.assertEqual(outage['unavailable_pods'], [1])
        self.assertEqual(outage['pod_states']['TCS-P01']['allocation_per_active_cdu_W'], None)
        self.assertEqual(outage['unserved_heat_W'], config.rack_power_W*config.liquid_fraction)
        self.assertEqual(sum(item['scenario_heat_W'][outage['name']] for item in graph['couplings'])+outage['unserved_heat_W'], 2*config.rack_power_W*config.liquid_fraction)
        checks = graph['metadata']['connectivity_scenarios']
        checked = next(case for case in checks['scenarios'] if case['name']==outage['name'])
        self.assertEqual(checked['unconnected_compute_racks'], ['IT-R01-01'])
        self.assertEqual(checked['tcs_path_status'], 'UNAVAILABLE')
        self.assertEqual(checks['blocking_failures'], 2)
        self.assertEqual(sum('CDU outage connectivity' in item['check'] for item in run(graph,config,profile)['blocking_failures']), 2)
        sizing = graph['metadata']['preliminary_sizing']
        self.assertTrue(any(issue.get('code')=='POD_SPARES_UNRESOLVED' for issue in sizing['unresolved']))
        self.assertIsNone(sizing['rack_and_equipment_duties']['CDU-01']['screening_duty_heat_W'])
        self.assertTrue(all(pump['status']=='INCOMPLETE_OUTAGE_COVERAGE' for pump in sizing['pump_screens'] if pump['circuit_id'].startswith('TCS')))
        for requirement in graph['metadata']['equipment_requirements']['requirements']:
            if requirement['kind']=='cdu':
                self.assertFalse(requirement['ready_for_matching'])
                self.assertTrue(any(issue['code']=='POD_UNAVAILABLE_IN_REQUESTED_OUTAGE' for issue in requirement['unresolved']))
        json.dumps(graph, allow_nan=False)
        # Keep the diagnostic model editable: relaxing only the declared
        # outage count restores connectivity; it does not require a new preset.
        repaired, _ = build(replace(config,redundancy=1))
        self.assertEqual(repaired['metadata']['connectivity_scenarios']['blocking_failures'],0)

    def test_input_explains_global_outage_scope_and_scenario_bound(self):
        field = next(item for item in catalog() if item['key']=='redundancy')
        self.assertIn('across all independent pods', field['effect'])
        self.assertIn('not a per-pod', field['source']['note'])
        # Config bounds guarantee at most C(8,4)=70 design cases.
        Config(cdu_count=8,redundancy=4).validate()
        with self.assertRaises(ValueError):Config(cdu_count=9,redundancy=4).validate()


if __name__=='__main__':unittest.main()
