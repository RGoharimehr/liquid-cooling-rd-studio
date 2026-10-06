"""Building blocks: independent arithmetic, honesty rules and balancing behaviour.

Expected numbers are written out by hand here, not produced by the code under
test. The straight-pipe fixture is the one in SIZING_BASIS.md section 5.
"""
from dataclasses import replace
from math import pi, sqrt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hydraulics import NoCatalogueSize
from model import Config
from preliminary_sizing import G
from blocks import (Fluid, RackBranchSpec, RowSpec, build_rack_branch, build_row,
                    flow_from_heat, head_m, size_pipe)
from blocks.components import Equipment, Fitting
from blocks.row import DESCHUTES_IT_DP_AVAILABLE, PSI
from blocks.sizing import straight_loss

WATER = Fluid('test water', 1000., 4000., 0.001, 'test fixture', 'assumption')
PG = Fluid('test PG25-like', 1025., 3900., 0.002, 'test fixture (engine Config defaults)', 'assumption')


class SizingChain(unittest.TestCase):
    def test_flow_from_heat_and_rise(self):
        d = flow_from_heat(100_000., 10., WATER)          # 100 kW, 10 K, cp 4000
        self.assertAlmostEqual(d.mass_kg_s, 2.5)          # 1e5 / (4000*10)
        self.assertAlmostEqual(d.flow_m3_s, 0.0025)       # 2.5 / 1000
        self.assertAlmostEqual(d.flow_L_min, 150.)

    def test_350_kW_rack_at_10_K(self):
        d = flow_from_heat(350_000., 10., PG)
        self.assertAlmostEqual(d.mass_kg_s, 350_000 / 39_000)            # 8.9744 kg/s
        self.assertAlmostEqual(d.flow_m3_s, 350_000 / 39_000 / 1025)     # 8.7555e-3 m3/s
        # Copper branch category cap 1.5 m/s: minimum bore 86.2 mm -> 3.5 in Type L (ID 3.425 in)
        p = size_pipe(d.flow_m3_s, 'tcs_rack_branch')
        self.assertAlmostEqual(p['required_id_m'], sqrt(4 * d.flow_m3_s / (pi * 1.5)))
        self.assertEqual(p['nominal_size_in'], 3.5)
        self.assertAlmostEqual(p['id_m'], (3.625 - 2 * .100) * .0254)
        self.assertLessEqual(p['velocity_m_s'], 1.5)
        self.assertEqual(p['velocity_cap_status'], 'assumption')
        # Stainless header category cap 2.7 m/s: 64.3 mm -> 2.5 in Sch 10S (ID 2.635 in)
        h = size_pipe(d.flow_m3_s, 'tcs_row_header')
        self.assertEqual(h['nominal_size_in'], 2.5)
        self.assertEqual(h['velocity_cap_status'], 'recommended')

    def test_zero_heat_is_zero_flow_not_an_error(self):
        d = flow_from_heat(0., 10., WATER)
        self.assertEqual(d.flow_m3_s, 0.)

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            flow_from_heat(1000., 0., WATER)
        with self.assertRaises(ValueError):
            Fluid('bad', -1., 4000., .001, 'x')
        with self.assertRaises(ValueError):
            size_pipe(.001, 'no_such_category')

    def test_sizing_basis_straight_pipe_fixture(self):
        r = straight_loss(0.0025, WATER, 0.050, 20., 0.000045)
        self.assertAlmostEqual(r['velocity_m_s'], 1.27323954, places=7)
        self.assertAlmostEqual(r['reynolds'], 63661.97724, places=3)
        self.assertAlmostEqual(r['darcy_factor'], 0.02298248, places=7)
        self.assertAlmostEqual(r['dp_Pa'], 7451.55721, places=3)
        self.assertEqual(r['regime'], 'turbulent')

    def test_head_from_pressure(self):
        self.assertAlmostEqual(head_m(98066.5, WATER), 98066.5 / (1000 * G))

    def test_catalogue_exhaustion_is_reported_not_capped(self):
        with self.assertRaises(NoCatalogueSize):
            size_pipe(5.0, 'tcs_rack_branch')

    def test_fluid_from_engine_config(self):
        f = Fluid.from_config(Config())
        self.assertEqual((f.rho_kg_m3, f.cp_J_kgK, f.mu_Pa_s), (1025., 3900., .002))
        self.assertEqual(f.status, 'project_input')


class Components(unittest.TestCase):
    def test_unknown_equipment_is_unknown_not_zero(self):
        e = Equipment('RACK').evaluate(.001, WATER)
        self.assertIsNone(e.dp_Pa)
        self.assertEqual(e.status, 'unknown')

    def test_supplied_equipment_dp_needs_a_source_and_scales_with_flow_squared(self):
        with self.assertRaises(ValueError):
            Equipment('RACK', rated_dp_Pa=50_000.).evaluate(.001, WATER)
        e = Equipment('RACK', rated_dp_Pa=50_000., rated_flow_m3_s=.002, source='vendor sheet X').evaluate(.001, WATER)
        self.assertAlmostEqual(e.dp_Pa, 12_500.)

    def test_fitting_k_fixture(self):
        # SIZING_BASIS fixture: K=3 at 0.05 m bore, 0.0025 m3/s -> 2431.70841 Pa
        e = Fitting('X', 'custom', k=3., k_source='test').evaluate(.0025, WATER, .05)
        self.assertAlmostEqual(e.dp_Pa, 2431.70841, places=3)


class RackBranch(unittest.TestCase):
    def spec(self, **kw):
        return RackBranchSpec(heat_W=350_000., delta_T_max_K=10., supply_T_C=30., **kw)

    def test_temperatures_flow_and_incomplete_without_rack_dp(self):
        r = build_rack_branch(self.spec(), PG)
        self.assertAlmostEqual(r.return_T_C, 40.)
        self.assertAlmostEqual(r.mass_kg_s, 350_000 / 39_000)
        self.assertFalse(r.dp_complete)
        self.assertEqual(r.unknowns, ['R01-RACK'])
        self.assertAlmostEqual(r.dp_Pa, sum(e.dp_Pa for e in r.elements if e.dp_Pa is not None))
        self.assertAlmostEqual(r.head_m, r.dp_Pa / (1025 * G))

    def test_supplying_rack_dp_completes_the_branch(self):
        q = 350_000 / 39_000 / 1025
        without = build_rack_branch(self.spec(), PG)
        with_dp = build_rack_branch(self.spec(rack_dp_Pa=100_000., rack_rated_flow_m3_s=q,
                                              rack_dp_source='test vendor value'), PG)
        self.assertTrue(with_dp.dp_complete)
        self.assertAlmostEqual(with_dp.dp_Pa - without.dp_Pa, 100_000.)

    def test_parts_list_has_isolation_balancing_and_optional_control_valves(self):
        kinds = [v['kind'] for v in build_rack_branch(self.spec(), PG).valves]
        self.assertEqual(kinds.count('isolation_valve'), 2)
        self.assertEqual(kinds.count('balancing_valve'), 1)
        self.assertNotIn('control_valve', kinds)
        cv = build_rack_branch(self.spec(control_valve_dp_Pa=30_000.), PG).valves
        self.assertIn('control_valve', [v['kind'] for v in cv])

    def test_balancing_valve_kv_matches_spirax_relation(self):
        r = build_rack_branch(self.spec(), PG)
        bv = next(v for v in r.valves if v['kind'] == 'balancing_valve')
        q_m3_h = 350_000 / 39_000 / 1025 * 3600
        self.assertAlmostEqual(bv['Kv_m3_h'], q_m3_h * sqrt(1.025 / 0.1))   # 10 kPa = 0.1 bar


class Row(unittest.TestCase):
    branch = RackBranchSpec(heat_W=350_000., delta_T_max_K=10., supply_T_C=30.)

    def row(self, **kw):
        return build_row(RowSpec(self.branch, 8, **kw), PG)

    def test_heat_and_flow_add_temperature_rise_does_not(self):
        r = self.row()
        self.assertAlmostEqual(r.heat_W, 8 * 350_000.)
        self.assertAlmostEqual(r.flow_m3_s, 8 * 350_000 / 39_000 / 1025)
        self.assertAlmostEqual(r.delta_T_K, 10.)
        self.assertAlmostEqual(r.return_T_C, 40.)

    def test_header_flow_follows_continuity(self):
        q = 350_000 / 39_000 / 1025
        flows = {p['run'].split()[-1]: p['flow_L_min'] / 60000. for p in self.row().pipes}
        for i in range(8):
            self.assertAlmostEqual(flows[f'S{i}'], (8 - i) * q)

    def test_every_path_is_balanced_and_valves_never_go_below_minimum(self):
        for arrangement in ('direct_return', 'reverse_return'):
            for header in ('constant', 'stepped'):
                r = self.row(arrangement=arrangement, header=header)
                check = next(c for c in r.checks if c['name'].startswith('balanced'))
                self.assertTrue(check['passed'], (arrangement, header))
                bv = [v['dp_kPa'] for v in r.valves if v['kind'] == 'balancing_valve']
                self.assertEqual(len(bv), 8)
                self.assertAlmostEqual(min(bv), 10.)
                self.assertTrue(all(c['passed'] for c in r.checks if c['name'].startswith('velocity')))

    def test_direct_return_critical_rack_is_the_farthest(self):
        r = self.row(arrangement='direct_return')
        bv = [v['dp_kPa'] for v in r.valves if v['kind'] == 'balancing_valve']
        self.assertAlmostEqual(bv[-1], 10.)
        self.assertEqual(bv, sorted(bv, reverse=True))

    def test_reverse_return_needs_less_balancing_than_direct(self):
        def spread(r):
            bv = [v['dp_kPa'] for v in r.valves if v['kind'] == 'balancing_valve']
            return max(bv) - min(bv)
        self.assertLess(spread(self.row(arrangement='reverse_return')), spread(self.row(arrangement='direct_return')))

    def test_stepped_header_never_grows_downstream(self):
        sizes = [p['nominal_size_in'] for p in self.row(header='stepped').pipes if p['run'].split()[-1].startswith('S')]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_single_rack_row_is_branch_plus_header_feed(self):
        r = build_row(RowSpec(self.branch, 1), PG)
        branch = build_rack_branch(self.branch, PG)
        header = sum(e.dp_Pa for e in r.elements if e.tag.startswith('Row A-') and '-R01-' not in e.tag)
        self.assertAlmostEqual(r.dp_Pa, branch.dp_Pa + header)

    def test_available_dp_check_cannot_pass_while_rack_dp_is_unknown(self):
        r = self.row(available_dp=DESCHUTES_IT_DP_AVAILABLE)
        check = next(c for c in r.checks if c['name'].startswith('row dp within'))
        self.assertIsNone(check['passed'])
        self.assertAlmostEqual(check['limit'], 80 * PSI)
        q = 350_000 / 39_000 / 1025
        known = build_row(RowSpec(replace(self.branch, rack_dp_Pa=100_000., rack_rated_flow_m3_s=q,
                                          rack_dp_source='test'), 8, available_dp=DESCHUTES_IT_DP_AVAILABLE), PG)
        check = next(c for c in known.checks if c['name'].startswith('row dp within'))
        self.assertTrue(check['passed'])

    def test_connection_is_the_interface_a_feeder_needs(self):
        c = self.row().connection()
        for key in ('mass_kg_s', 'flow_m3_s', 'supply_T_C', 'return_T_C', 'required_dp_Pa',
                    'required_head_m', 'dp_complete', 'unknowns'):
            self.assertIn(key, c)
        self.assertFalse(c['dp_complete'])
        self.assertEqual(len(c['unknowns']), 8)

    def test_bad_row_inputs(self):
        with self.assertRaises(ValueError):
            build_row(RowSpec(self.branch, 0), PG)
        with self.assertRaises(ValueError):
            build_row(RowSpec(self.branch, 4, arrangement='sideways'), PG)


if __name__ == '__main__':
    unittest.main()
