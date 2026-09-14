"""Applied-model integrity and engineering distinctions in catalogue requirements."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import Config, canonical_digest
from pipeline import build
from equipment_requirements import build_requirements


class EquipmentRequirementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Config(rows=2, racks_per_row=2, rack_power_W=140000., liquid_fraction=1.,
            cdu_count=4, redundancy=1, pod_count=2, plant_type='water_cooled',
            ceiling_height_m=8., sizing_mode='preliminary')
        cls.graph, _ = build(cls.config)
        cls.document = build_requirements(cls.graph)
        cls.requirements = {r['component_id']: r for r in cls.document['requirements']}

    def test_contract_is_bound_to_applied_config_and_rounded_sizes(self):
        self.assertTrue(self.document['ready_for_matching'])
        self.assertTrue(self.document['preconditions']['standard_sizes_applied'])
        self.assertEqual(self.document['config_hash'], self.graph['metadata']['config_hash'])
        for row in self.document['requirements']:
            self.assertEqual(row['provenance']['config_hash'], self.document['config_hash'])
        altered = deepcopy(self.graph)
        next(e for e in altered['edges'] if e['kind'] == 'pipe')['id_m'] *= 1.05
        invalid = build_requirements(altered)
        self.assertFalse(invalid['ready_for_matching'])
        self.assertTrue(invalid['preconditions']['dimension_mismatches'])
        self.assertTrue(all(not r['ready_for_matching'] for r in invalid['requirements']))

    def test_manual_models_match_at_retained_bores_with_calculated_duties(self):
        config = replace(self.config, sizing_mode='manual', rack_nominal_in=1.)
        graph, _ = build(config); result = build_requirements(graph)
        sizing = graph['metadata']['preliminary_sizing']
        self.assertTrue(result['ready_for_matching'])
        self.assertTrue(result['preconditions']['manual_dimensions_preserved'])
        self.assertEqual(sizing['dimension_basis'], 'manual_catalogue')
        self.assertFalse(sizing['geometry_modified'])
        self.assertEqual(sizing['suggested_config'], {})
        qd = next(row for row in result['requirements'] if row['kind'] == 'quick_disconnect')
        self.assertTrue(qd['ready_for_matching'])
        self.assertAlmostEqual(qd['fluid_sides'][0]['design_flow_m3_s'], .0028)
        self.assertTrue(all(port['nominal_nps_in'] == 1. for port in qd['ports']))
        self.assertTrue(any(x['code'] == 'MANUAL_VELOCITY_LIMIT_EXCEEDED' for x in qd['unresolved']))
        self.assertTrue(any(row['throttling'] for row in result['requirements']))
        self.assertTrue(any(row['pump_duty'] for row in result['requirements']))
        altered = deepcopy(graph)
        next(edge for edge in altered['edges'] if edge['kind'] == 'pipe')['id_m'] *= 1.05
        self.assertFalse(build_requirements(altered)['ready_for_matching'])

    def test_every_relevant_physical_component_is_retained(self):
        kinds = {'isolation_valve', 'balancing_valve', 'control_valve', 'check_valve',
                 'strainer', 'quick_disconnect', 'cdu', 'chiller', 'pump', 'cooling_tower'}
        expected = {c['id'] for c in self.graph['components'] if c['kind'] in kinds}
        self.assertTrue(expected <= set(self.requirements))
        self.assertEqual(len(self.requirements), len(self.document['requirements']))
        self.assertTrue(all(row['quantity'] == 1 for row in self.requirements.values()))

    def test_exact_nominal_designation_is_separate_from_actual_pipe_bore(self):
        valve = next(row for row in self.requirements.values() if row['kind'] == 'quick_disconnect')
        for port in valve['ports']:
            self.assertEqual(port['nominal_nps_in'], 2.)
            self.assertAlmostEqual(port['pipe_id_m'], (2.125 - 2 * .070) * .0254)
            self.assertAlmostEqual(port['pipe_od_m'], 2.125 * .0254)
            self.assertNotIn('minimum_size_mm', port)
            self.assertNotIn('nominal_dn', port)
            self.assertIsNone(port['connection_standard'])
        self.assertIsNone(valve['required_material'])
        self.assertIsNone(valve['required_wetted_materials'])
        self.assertEqual(valve['fluid_sides'][0]['connected_pipe_materials'], ['copper_type_l'])

    def test_throttling_coefficients_are_only_assigned_to_throttling_roles(self):
        original = {row['component_id']: row for row in self.graph['metadata']['preliminary_sizing']['valve_capacities']}
        for row in self.requirements.values():
            if row['kind'] in ('balancing_valve', 'control_valve'):
                expected = original[row['component_id']]
                self.assertEqual(row['throttling']['required_Cv_US'], expected['Cv_US'])
                self.assertEqual(row['throttling']['required_Kv_m3_h'], expected['Kv_m3_h'])
                self.assertEqual(row['throttling']['allocated_dp_Pa'], expected['allocated_dp_Pa'])
            else:
                self.assertIsNone(row['throttling'])

    def test_pressure_loss_never_becomes_pressure_rating(self):
        found_nonzero_dp = False
        for row in self.requirements.values():
            for side in row['fluid_sides']:
                self.assertIsNone(side['minimum_pressure_rating_Pa'])
                found_nonzero_dp |= any((loss['estimated_dp_Pa'] or 0) > 0 for loss in side['screening_losses'])
        self.assertTrue(found_nonzero_dp)
        valve = next(row for row in self.requirements.values() if row['throttling'])
        self.assertTrue(any(x['code'] == 'PRESSURE_RATING_UNASSIGNED' for x in valve['unresolved']))
        # Future explicit per-service design pressure is accepted as an input,
        # without borrowing any pressure number from sizing results.
        graph = deepcopy(self.graph)
        graph['metadata']['config']['fws_design_pressure_bar'] = 7.
        graph['metadata']['config_hash'] = canonical_digest(graph['metadata']['config'])
        document = build_requirements(graph)
        for row in document['requirements']:
            for side in row['fluid_sides']:
                self.assertEqual(side['minimum_pressure_rating_Pa'], 700000. if side['service'] == 'FWS' else None)

    def test_cdu_and_chiller_do_not_merge_fluid_sides_or_pods(self):
        first, second = self.requirements['CDU-01'], self.requirements['CDU-03']
        self.assertEqual(first['circuit_ids'], ['FWS', 'TCS-P01'])
        self.assertEqual(second['circuit_ids'], ['FWS', 'TCS-P02'])
        self.assertEqual(first['thermal_duty']['heat_transfer_type'], 'liquid_to_liquid')
        self.assertEqual(first['thermal_duty']['cooling_phase'], 'single_phase')
        self.assertEqual(len(first['ports']), 4)
        self.assertTrue(all(len(s['port_ids']) == 2 for s in first['fluid_sides']))
        chiller = self.requirements['CHILLER-01']
        self.assertEqual(chiller['subtype'], 'water_cooled_chiller')
        self.assertEqual(chiller['circuit_ids'], ['CWS', 'FWS'])
        self.assertGreater(chiller['thermal_duty']['condenser_heat_W'], chiller['thermal_duty']['required_capacity_W'])

    def test_temperature_retains_declared_and_estimated_conditions(self):
        expected_return = self.config.tcs_supply_C + self.graph['metadata']['preliminary_sizing']['thermal_flows']['effective_TCS_delta_K']
        side = next(s for s in self.requirements['CDU-01']['fluid_sides'] if s['service'] == 'TCS')
        self.assertEqual(side['temperature']['declared_return_C'], self.config.tcs_supply_C + self.config.tcs_delta_K)
        self.assertEqual(side['temperature']['estimated_return_C'], expected_return)
        self.assertEqual(side['temperature']['required_max_temperature_C'], max(expected_return, self.config.tcs_supply_C + self.config.tcs_delta_K))
        self.assertEqual(side['fluid']['pg_volume_fraction'], self.config.pg_volume_fraction)
        self.assertIsNone(side['fluid']['formulation'])

    def test_unsupported_pump_and_tower_duties_remain_visible(self):
        pump = self.requirements['CWS-PUMP-01']; tower = self.requirements['TOWER-01']
        for row in (pump, tower):
            self.assertFalse(row['supported_by_finder'])
            self.assertFalse(row['ready_for_matching'])
            self.assertTrue(any(x['code'] == 'FINDER_CATEGORY_UNSUPPORTED' for x in row['unresolved']))
        self.assertGreater(pump['pump_duty'][0]['pump_head_m'], 0)
        self.assertGreater(tower['thermal_duty']['required_capacity_W'], 0)

    def test_missing_component_estimate_does_not_borrow_a_neighbor_flow(self):
        graph = deepcopy(self.graph)
        target = next(row for row in self.requirements.values() if row['kind'] == 'quick_disconnect')
        graph['metadata']['preliminary_sizing']['edge_estimates'] = [e for e in graph['metadata']['preliminary_sizing']['edge_estimates'] if e['component_id'] != target['component_id']]
        result = build_requirements(graph)
        row = next(r for r in result['requirements'] if r['component_id'] == target['component_id'])
        self.assertFalse(row['ready_for_matching'])
        self.assertIsNone(row['fluid_sides'][0]['design_flow_m3_s'])

    def test_stale_config_or_sizing_is_rejected_and_inputs_are_immutable(self):
        before = json.dumps(self.graph, sort_keys=True, allow_nan=False)
        build_requirements(self.graph, self.config)
        self.assertEqual(before, json.dumps(self.graph, sort_keys=True, allow_nan=False))
        with self.assertRaisesRegex(ValueError, 'Draft parameters'):
            build_requirements(self.graph, replace(self.config, rack_power_W=150000.))
        stale = deepcopy(self.graph['metadata']['preliminary_sizing'])
        stale['valve_capacities'][0]['Cv_US'] *= 2
        with self.assertRaisesRegex(ValueError, 'Sizing must match'):
            build_requirements(self.graph, sizing=stale)
        damaged = deepcopy(self.graph); damaged['metadata']['config']['rows'] = 9
        with self.assertRaisesRegex(ValueError, 'hash'):
            build_requirements(damaged)
        json.dumps(self.document, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
