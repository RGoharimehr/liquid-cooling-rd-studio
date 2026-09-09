"""Independent arithmetic and graph-failure checks for prescribed-flow sizing."""
from copy import deepcopy
from dataclasses import asdict
from math import pi, sqrt
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import Config
from pipeline import build
from preliminary_sizing import evaluate, friction_factor, valve_capacity, G


def options(config, **changes):
    values = asdict(config); values.update(changes)
    return SimpleNamespace(**values)


class PreliminarySizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Config(rows=1, racks_per_row=1, rack_power_W=140000., liquid_fraction=1.,
                            cdu_count=2, redundancy=1, plant_type='air_cooled')
        cls.graph, _ = build(cls.config)
        cls.inputs = options(cls.config, flow_input_mode='lpm_per_kw', flow_lpm_per_kw=1.2)
        cls.result = evaluate(cls.graph, cls.inputs)

    def test_140_liquid_kw_times_1_2_is_168_litres_per_minute(self):
        self.assertAlmostEqual(self.result['thermal_flows']['TCS_L_min'], 168.)
        rack = next(e for e in self.graph['edges'] if e['kind'] == 'rack_load')
        duty = self.result['rack_and_equipment_duties'][rack['component_id']]
        self.assertAlmostEqual(duty['TCS_m3_s'], .0028)
        self.assertAlmostEqual(duty['TCS_L_min'], 168.)

    def test_heat_balance_uses_user_fluid_properties_and_liquid_heat(self):
        result = evaluate(self.graph, options(self.config, flow_input_mode='heat_balance',
            tcs_density_kg_m3=1000., tcs_specific_heat_J_kgK=4000., tcs_delta_K=10.))
        self.assertAlmostEqual(result['thermal_flows']['TCS_m3_s'], 140000. / (1000. * 4000. * 10.))
        self.assertAlmostEqual(result['thermal_flows']['effective_TCS_delta_K'], 10.)
        self.assertIsNone(result['flow_lpm_per_liquid_kw'])

    def test_catalogue_rounding_uses_inner_diameter_and_uniform_families(self):
        # At 168 L/min and 1.5 m/s the required ID is 48.753 mm.
        # Type-L 1.5-in ID=38.227 mm fails; 2-in ID=50.419 mm passes.
        required = sqrt(4 * .0028 / (pi * 1.5))
        self.assertLess((1.625 - 2 * .060) * .0254, required)
        self.assertGreater((2.125 - 2 * .070) * .0254, required)
        self.assertEqual(self.result['suggested_config']['rack_nominal_in'], 2)
        estimates = {e['edge_id']: e for e in self.result['edge_estimates']}
        for family in self.result['size_families']:
            for eid in family['edge_ids']:
                self.assertEqual(estimates[eid]['selected_size'], family['selection'])
                self.assertTrue(estimates[eid]['velocity_cap_pass'])

    def test_prescribed_flow_conserves_every_internal_node(self):
        residual = {node['id']: 0. for node in self.graph['nodes']}
        results = {e['edge_id']: e for e in self.result['edge_estimates']}
        for edge in self.graph['edges']:
            flow = results[edge['id']]['signed_all_online_flow_m3_s']
            residual[edge['from_node']] -= flow; residual[edge['to_node']] += flow
        self.assertLess(max(map(abs, residual.values())), 1e-10)
        self.assertFalse(any(x.get('code') == 'FLOW_ASSIGNMENT_UNRESOLVED' for x in self.result['unresolved']))

    def test_darcy_factor_and_pipe_loss_match_independent_equations(self):
        self.assertAlmostEqual(friction_factor(1000., .0001)['darcy_factor'], .064)
        self.assertEqual(friction_factor(5000., .0001)['regime'], 'transitional_uncertain')
        turbulent = friction_factor(100000., .0001)['darcy_factor']
        self.assertAlmostEqual(turbulent, .018513866, places=8)
        edge_by_id = {e['id']: e for e in self.graph['edges']}
        result = next(r for r in self.result['edge_estimates'] if edge_by_id[r['edge_id']]['kind'] == 'pipe' and r['design_flow_m3_s'] > 0)
        edge = edge_by_id[result['edge_id']]
        rho = self.result['fluid_properties'][edge['service']]['rho_kg_m3']
        diameter = result['selected_size']['id_m']
        expected = result['friction_factor'] * edge['length_m'] / diameter * rho * result['velocity_m_s'] ** 2 / 2
        self.assertAlmostEqual(result['straight_dp_Pa'], expected)
        self.assertEqual(result['fitting_dp_Pa'], 0.)

    def test_valve_pressure_budget_is_not_double_counted_as_k(self):
        sized = valve_capacity(10. / 3600., 1000., 100000.)
        self.assertAlmostEqual(sized['Kv_m3_h'], 10.)
        self.assertAlmostEqual(sized['Cv_US'], 11.56)
        edge_by_id = {e['id']: e for e in self.graph['edges']}
        result = next(r for r in self.result['edge_estimates'] if edge_by_id[r['edge_id']]['kind'] == 'balancing_valve')
        self.assertEqual(result['equipment_dp_Pa'], 20000.)
        self.assertEqual(result['fitting_dp_Pa'], 0.)
        self.assertTrue(self.result['valve_capacities'])

    def test_pump_power_and_closed_loop_static_head(self):
        for pump in self.result['pump_screens']:
            self.assertEqual(pump['status'], 'SCREENING_ESTIMATE', pump)
            self.assertEqual(pump['static_dp_Pa'], 0.)
            self.assertAlmostEqual(pump['hydraulic_power_W'], pump['design_flow_m3_s'] * pump['pump_dp_Pa'])
            self.assertAlmostEqual(pump['estimated_input_power_W'], pump['hydraulic_power_W'] / .7)
            self.assertAlmostEqual(pump['pump_dp_Pa'], (pump['passive_dp_Pa'] + pump['internal_cdu_dp_Pa']) * 1.15)

    def test_passive_ring_is_unresolved_instead_of_silently_balanced(self):
        graph = deepcopy(self.graph)
        pipe = next(e for e in graph['edges'] if e['kind'] == 'pipe' and e['service'] == 'FWS')
        duplicate = dict(pipe, id=pipe['id'] + ':parallel'); graph['edges'].append(duplicate)
        result = evaluate(graph, self.inputs)
        failures = [x for x in result['unresolved'] if x.get('code') == 'FLOW_ASSIGNMENT_UNRESOLVED']
        self.assertTrue(any('loop' in x['reason'] for x in failures))
        affected = next(e for e in result['edge_estimates'] if e['edge_id'] == duplicate['id'])
        self.assertIsNone(affected['flow_m3_s'])
        self.assertIsNone(affected['total_dp_Pa'])

    def test_disconnected_pipe_has_no_assigned_balanced_flow(self):
        graph = deepcopy(self.graph)
        pipe = next(e for e in graph['edges'] if e['kind'] == 'pipe' and e.get('level') == 'rack')
        graph['edges'].remove(pipe)
        result = evaluate(graph, self.inputs)
        self.assertTrue(any('not conserved' in x.get('reason', '') for x in result['unresolved']))

    def test_separate_pods_use_their_own_loads_and_cdu_assignments(self):
        config = Config(rows=4, racks_per_row=1, pod_count=2, cdu_count=4, redundancy=1,
                        row_pod_assignments=[1, 1, 1, 2], cdu_pod_assignments=[1, 1, 2, 2], ceiling_height_m=6.5)
        graph, _ = build(config); result = evaluate(graph, options(config, flow_lpm_per_kw=1.2))
        flows = result['thermal_flows']['pod_flows_m3_s']
        self.assertAlmostEqual(flows['TCS-P01'], flows['TCS-P02'] * 3)
        duties = result['rack_and_equipment_duties']
        self.assertAlmostEqual(duties['CDU-01']['all_online_heat_W'], duties['CDU-03']['all_online_heat_W'] * 3)

    def test_open_tower_load_includes_compressor_heat_and_separate_static_input(self):
        config = Config(rows=1, racks_per_row=1, plant_type='water_cooled')
        graph, _ = build(config)
        result = evaluate(graph, options(config, chiller_cop=5., cws_static_lift_m=3., tower_nozzle_dp_kPa=15.))
        thermal = result['thermal_flows']
        self.assertAlmostEqual(thermal['condenser_heat_W'], thermal['plant_heat_W'] * 1.2)
        self.assertAlmostEqual(thermal['CWS_m3_s'], thermal['condenser_heat_W'] / (998. * 4180. * 5.))
        cws = [p for p in result['pump_screens'] if p['circuit_id'] == 'CWS']
        self.assertTrue(cws)
        for pump in cws:
            self.assertEqual(pump['status'], 'SCREENING_ESTIMATE')
            self.assertAlmostEqual(pump['static_dp_Pa'], 998. * G * 3. + 15000.)
        incomplete = evaluate(graph, options(config, chiller_cop=None, cws_static_lift_m=None))
        self.assertTrue(all(p['status'] == 'INCOMPLETE_LOWER_BOUND' for p in incomplete['pump_screens'] if p['circuit_id'] == 'CWS'))
        self.assertTrue(any(x.get('code') == 'CONDENSER_HEAT_LOWER_BOUND' for x in incomplete['unresolved']))

    def test_no_catalogue_size_returns_explicit_unresolved_result(self):
        result = evaluate(self.graph, options(self.config, flow_lpm_per_kw=100000.))
        self.assertTrue(any(f['status'] == 'NO_CATALOGUE_SIZE' for f in result['size_families']))
        self.assertTrue(result['unresolved'])
        self.assertNotIn('tcs_main_nominal_in',result['suggested_config'])
        self.assertNotIn('rack_nominal_in',result['suggested_config'])
        json.dumps(result, allow_nan=False)

    def test_validation_and_input_immutability(self):
        before = json.dumps(self.graph, sort_keys=True, allow_nan=False)
        evaluate(self.graph, self.inputs)
        self.assertEqual(before, json.dumps(self.graph, sort_keys=True, allow_nan=False))
        for invalid in ({'flow_lpm_per_kw': -1}, {'pump_efficiency': 0}, {'pump_efficiency': 1.1},
                        {'tcs_viscosity_Pa_s': 0}, {'tcs_density_kg_m3': float('nan')},
                        {'valve_design_dp_kPa': 0}, {'chiller_cop': -1}, {'flow_input_mode': 'solve'}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                evaluate(self.graph, options(self.config, **invalid))


if __name__ == '__main__':
    unittest.main()
