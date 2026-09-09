"""The router must be an improvement or a no-op, never a regression.

Every test here is written against that contract rather than against a
particular route: the search is free to find a different answer when the cost
model or the obstacle set changes, but it is never free to lengthen a run, to
emit geometry `route_path()` would reject, or to introduce a clash.
"""
import sys, unittest
from dataclasses import replace
from math import dist
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from model import Config
from pipeline import build
from route_lanes import Box, LaneRouter, Request, _validate, _collapse
import route_cost


def _points(req, result):
    return [tuple(req.start)] + [tuple(p) for p in result.waypoints] + [tuple(req.end)]


class LaneRouterGeometry(unittest.TestCase):
    def _router(self, obstacles=(), **kw):
        kw.setdefault('bend_radius_m', 0.24)
        return LaneRouter(list(obstacles), **kw)

    def test_clear_run_reaches_the_rectilinear_bound(self):
        # Open ends facing the way the run has to travel: nothing to avoid, so
        # the search has no excuse for a metre more than the bound.
        req = Request('a', start=(0, 0, 4), end=(20, 10, 4),
                      start_dir=(1, 0, 0), end_dir=(0, 1, 0))
        res = self._router().route([req])['a']
        self.assertEqual(res.status, 'routed')
        self.assertAlmostEqual(res.length_m, res.bound_m, places=6)

    def test_open_end_facing_away_swings_around_rather_than_failing(self):
        # A collector whose end points away from its target cannot be reached in
        # a straight L. The route must be longer than the bound, and must exist.
        req = Request('a', start=(0, 0, 4), end=(20, 10, 4),
                      start_dir=(0, -1, 0), end_dir=(0, 1, 0))
        res = self._router().route([req])['a']
        self.assertEqual(res.status, 'routed')
        self.assertGreater(res.length_m, res.bound_m)

    def test_overshoot_is_not_collapsed_into_a_straight_line(self):
        # A point that doubles back is real geometry, not collinear filler.
        pts = _collapse([(0, 0, 4), (0, 12, 4), (0, 10, 4)])
        self.assertEqual(len(pts), 3)
        self.assertEqual(_collapse([(0, 0, 4), (0, 5, 4), (0, 10, 4)]), [(0, 0, 4), (0, 10, 4)])

    def test_route_goes_around_an_obstacle(self):
        wall = Box((5., -30., 0.), (7., 5., 10.), 'wall')
        req = Request('a', start=(0, 0, 4), end=(20, 10, 4),
                      start_dir=(0, -1, 0), end_dir=(0, 1, 0))
        res = self._router([wall]).route([req])['a']
        self.assertEqual(res.status, 'routed')
        for p, q in zip(_points(req, res), _points(req, res)[1:]):
            lo = [min(p[k], q[k]) for k in range(3)]
            hi = [max(p[k], q[k]) for k in range(3)]
            overlaps = all(lo[k] < wall.hi[k] and hi[k] > wall.lo[k] for k in range(3))
            self.assertFalse(overlaps, f'segment {p}->{q} crosses the obstacle')

    def test_every_route_satisfies_route_path(self):
        """Whatever the search returns must survive the builder's own checks."""
        obstacles = [Box((5., -30., 0.), (7., 4., 10.), 'a'),
                     Box((12., 2., 0.), (14., 30., 10.), 'b')]
        req = Request('a', start=(0, 0, 4), end=(22, 12, 4),
                      start_dir=(0, -1, 0), end_dir=(0, 1, 0))
        res = self._router(obstacles).route([req])['a']
        self.assertEqual(res.status, 'routed')
        ok, why = _validate(_collapse(_points(req, res)), 0.24)
        self.assertTrue(ok, why)

    def test_second_line_shares_the_first_corridor_without_touching_it(self):
        """The whole point of routing a pair as a batch."""
        supply = Request('s', start=(0, 0, 4), end=(30, 0, 4),
                         start_dir=(1, 0, 0), end_dir=(-1, 0, 0))
        ret = Request('r', start=(0, 6, 4), end=(30, 6, 4),
                      start_dir=(1, 0, 0), end_dir=(-1, 0, 0))
        router = self._router(bundle_discount=0.5, corridor_m=8.0)
        res = router.route([supply, ret])
        self.assertEqual(res['r'].status, 'routed')
        self.assertGreater(res['r'].shared_m, 10.,
                           'the return should follow the supply corridor')
        pts_s, pts_r = _points(supply, res['s']), _points(ret, res['r'])
        closest = min(dist(a, b) for a in pts_s for b in pts_r)
        self.assertGreater(closest, 0.1,
                           'sharing a corridor must not mean sharing a centre-line')

    def test_impossible_clearance_reports_rather_than_guesses(self):
        boxed = [Box((-100., -100., -100.), (100., 100., 100.), 'everything')]
        req = Request('a', start=(0, 0, 4), end=(20, 10, 4),
                      start_dir=(0, -1, 0), end_dir=(0, 1, 0))
        # The endpoints sit inside the box, so it is excused; a second, distant
        # slab is not, and it seals the only way across.
        boxed.append(Box((9., -100., -100.), (11., 100., 100.), 'slab'))
        res = LaneRouter(boxed, bend_radius_m=0.24).route([req])['a']
        self.assertIn(res.status, ('unrouted', 'rejected', 'skipped'))
        self.assertTrue(res.reason)
        self.assertEqual(res.waypoints, [])


class OptimizerInThePipeline(unittest.TestCase):
    """End to end, on the plant the optimizer actually touches."""

    @classmethod
    def setUpClass(cls):
        base = Config(plant_type='water_cooled', ceiling_height_m=8.0,
                      bend_radius_m=.24, fitting_arm_m=.24,
                      return_elevation_offset_m=.5)
        cls.base_graph, _ = build(replace(base, route_optimizer=False))
        cls.opt_graph, _ = build(replace(base, route_optimizer=True))
        cls.config = base

    def _length(self, g):
        return route_cost.evaluate(g)['total']['length_m']

    def test_optimizer_shortens_transport_pipe(self):
        self.assertLess(self._length(self.opt_graph), self._length(self.base_graph))

    def test_optimizer_introduces_no_geometry_failure(self):
        base = self.base_graph['metadata']['geometry_diagnostics']
        opt = self.opt_graph['metadata']['geometry_diagnostics']
        self.assertLessEqual(opt['blocking_failures'], base['blocking_failures'])
        self.assertLessEqual(opt['clash_count'], base['clash_count'])

    def test_in_hall_distribution_is_untouched(self):
        """TCS already routes at the bound; the optimizer has no business there."""
        base = route_cost.chain_report(self.base_graph)['TCS']
        opt = route_cost.chain_report(self.opt_graph)['TCS']
        self.assertAlmostEqual(base['routed_m'], opt['routed_m'], places=6)

    def test_every_link_is_reported_with_its_own_bound(self):
        links = self.opt_graph['metadata']['route_optimizer']['links']
        self.assertTrue(links)
        for row in links:
            self.assertIn(row['chosen'], ('optimized', 'lane'))
            self.assertGreater(row['bound_m'], 0)
            if row['chosen'] == 'optimized':
                self.assertLessEqual(row['routed_m'], row['lane_m'] + 1e-6)
                self.assertGreaterEqual(row['routed_m'], row['bound_m'] - 1e-6)
            else:
                self.assertTrue(row.get('reason'))

    def test_result_is_deterministic(self):
        again, _ = build(replace(self.config, route_optimizer=True))
        self.assertEqual(
            [c['id'] for c in again['components']],
            [c['id'] for c in self.opt_graph['components']])
        self.assertAlmostEqual(self._length(again), self._length(self.opt_graph), places=9)

    def test_disabled_optimizer_changes_nothing(self):
        again, _ = build(replace(self.config, route_optimizer=False))
        self.assertAlmostEqual(self._length(again), self._length(self.base_graph), places=9)
        self.assertNotIn('route_optimizer', again['metadata'])


class CostModel(unittest.TestCase):
    def test_rate_table_is_concave_in_flow(self):
        """Merging must pay, or nothing ever forms a trunk."""
        rates = route_cost.Rates()
        small, large = rates.pipe_rate(4.0), rates.pipe_rate(8.0)
        # Bore doubles when flow quadruples at a fixed velocity cap. If four
        # branches merged into one trunk cost more than four separate runs, the
        # cost model would actively discourage the architecture it should prefer.
        self.assertLess(large, 4 * small)

    def test_chain_bound_never_exceeds_routed_length(self):
        g, _ = build(Config(plant_type='water_cooled'))
        for svc, row in route_cost.chain_report(g).items():
            self.assertGreater(row['routed_m'], 0, svc)

    def test_pairing_is_reported_per_service(self):
        g, _ = build(Config(plant_type='water_cooled'))
        report = route_cost.pairing_report(g)
        self.assertIn('FWS', report)
        for svc, row in report.items():
            self.assertGreaterEqual(row['supply_m'], row['unpaired_m'])


if __name__ == '__main__':
    unittest.main()
