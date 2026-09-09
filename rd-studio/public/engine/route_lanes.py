"""Rectilinear lane routing for transport piping.

The generator's default router walks one axis at a time toward the target, and
`plant.py` steers it with hardcoded service lanes. That is deterministic and
cheap, but it has no notion of what a route costs, so a corridor chosen to clear
one obstacle is applied whether or not anything is in the way.

This module searches instead. The search space is a Hanan grid: candidate
coordinates on each axis are the faces of the obstacles plus the coordinates the
endpoints require. A shortest rectilinear obstacle-avoiding path always exists on
that grid, so nothing is lost by not searching free space, and the grid stays
small enough to search exhaustively in milliseconds.

Scope. The router decides *where* pipe goes. It never changes what the network
connects, what size it is, which fittings it uses, or where equipment sits. It
returns waypoints for the existing `route_path()`, which still builds every
component, tag, node and edge exactly as it does today. A route it cannot place
legally is reported as a failure so the caller can keep the deterministic lane.

This is not a hydraulic solver and not a clash-resolution tool. `geometry_checks
.diagnose()` remains the acceptance gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from heapq import heappush, heappop
from typing import Iterable, Optional, Sequence

Point = tuple[float, float, float]
AXES = (0, 1, 2)
_EPS = 1e-7


@dataclass(frozen=True)
class Box:
    """An axis-aligned keep-out, already inflated by whatever clearance applies."""
    lo: Point
    hi: Point
    label: str = ''

    def contains(self, p: Sequence[float], pad: float = 0.0) -> bool:
        return all(self.lo[k] - pad <= p[k] <= self.hi[k] + pad for k in AXES)

    @staticmethod
    def around(center: Sequence[float], size: Sequence[float], pad: float = 0.0,
               pad_z: Optional[float] = None, label: str = '') -> 'Box':
        pz = pad if pad_z is None else pad_z
        pads = (pad, pad, pz)
        lo = tuple(center[k] - size[k] / 2 - pads[k] for k in AXES)
        hi = tuple(center[k] + size[k] / 2 + pads[k] for k in AXES)
        return Box(lo, hi, label)

    @staticmethod
    def segment(a: Sequence[float], b: Sequence[float], pad: float = 0.0,
                label: str = '') -> 'Box':
        lo = tuple(min(a[k], b[k]) - pad for k in AXES)
        hi = tuple(max(a[k], b[k]) + pad for k in AXES)
        return Box(lo, hi, label)


@dataclass
class Request:
    """One connection to route.

    `start`/`end` are the node coordinates the network already fixed. `start_dir`
    and `end_dir` are the outward axial directions at those nodes: a collector's
    open end has to be approached along its own axis, so the route is pinned to
    leave and arrive that way. `lead_m` is how far it runs straight before it is
    allowed to turn.
    """
    key: str
    start: Point
    end: Point
    start_dir: tuple[int, int, int]
    end_dir: tuple[int, int, int]
    lead_m: float = 2.0
    rate: float = 1.0          # relative cost per metre, normally the bore rate
    clearance_m: float = 0.30  # half-width to keep clear of an obstacle
    service: str = ''


@dataclass
class Result:
    key: str
    waypoints: list[Point]      # intermediate points only, for route_path()
    length_m: float
    bends: int
    cost: float
    bound_m: float              # rectilinear lower bound including the leads
    shared_m: float             # length run alongside an already-routed line
    status: str = 'routed'
    reason: str = ''


def _axis_of(direction: Sequence[float]) -> int:
    return max(AXES, key=lambda k: abs(direction[k]))


def _dedupe(values: Iterable[float], keep: Sequence[float], min_sep: float) -> list[float]:
    """Thin a coordinate list without dropping anything the endpoints need."""
    required = sorted(set(round(v, 6) for v in keep))
    out: list[float] = []
    for v in sorted(set(round(v, 6) for v in values)):
        if any(abs(v - r) < _EPS for r in required):
            out.append(v)
            continue
        if out and v - out[-1] < min_sep:
            continue
        if any(abs(v - r) < min_sep for r in required):
            continue
        out.append(v)
    for r in required:
        if not any(abs(r - v) < _EPS for v in out):
            out.append(r)
    return sorted(out)


class LaneRouter:
    """Routes a batch of connections, in order, sharing corridors as it goes.

    Connections routed earlier price the corridors they occupy *down* for the
    ones that follow, so a supply and its return converge on one rack instead of
    each taking its own private shortest path. That is the whole reason to route
    a batch rather than one line at a time.
    """

    def __init__(self, obstacles: Sequence[Box], *, bend_radius_m: float,
                 bend_cost_m: float = 1.5, bundle_discount: float = 0.35,
                 corridor_m: float = 1.2, z_levels: Sequence[float] = (),
                 lane_padding_m: float = 0.6, min_stub_m: float = 0.30,
                 max_nodes: int = 240000):
        self.obstacles = list(obstacles)
        self.bend_radius_m = bend_radius_m
        self.bend_cost_m = bend_cost_m
        self.bundle_discount = max(0.0, min(0.9, bundle_discount))
        self.corridor_m = corridor_m
        self.z_levels = list(z_levels)
        self.lane_padding_m = lane_padding_m
        self.max_nodes = max_nodes
        # route_path() only demands 2r + 10 mm, but a segment that short leaves a
        # stub of pipe between two bend arcs that the clash check then reports
        # against itself. Leave enough for a real pipe.
        self.min_stub_m = min_stub_m
        self.min_segment_m = 2 * bend_radius_m + min_stub_m
        self._used: list[tuple[int, Point, Point]] = []
        self.log: list[str] = []
        self._cell = 3.0
        self._index = self._build_index()

    def _cells(self, lo, hi):
        span = [range(int(lo[k] // self._cell), int(hi[k] // self._cell) + 1) for k in AXES]
        for i in span[0]:
            for j in span[1]:
                for k in span[2]:
                    yield (i, j, k)

    def _build_index(self) -> dict:
        index: dict = {}
        for n, box in enumerate(self.obstacles):
            for cell in self._cells(box.lo, box.hi):
                index.setdefault(cell, []).append(n)
        return index

    # ---- corridor bookkeeping -------------------------------------------------

    def _discount(self, p: Point, q: Point, axis: int) -> float:
        others = [k for k in AXES if k != axis]
        lo, hi = min(p[axis], q[axis]), max(p[axis], q[axis])
        for used_axis, a, b in self._used:
            if used_axis != axis:
                continue
            if any(abs(p[k] - a[k]) > self.corridor_m for k in others):
                continue
            ulo, uhi = min(a[axis], b[axis]), max(a[axis], b[axis])
            if min(hi, uhi) - max(lo, ulo) > self.min_segment_m:
                return self.bundle_discount
        return 0.0

    def _remember(self, points: Sequence[Point]) -> None:
        for p, q in zip(points, points[1:]):
            moved = [k for k in AXES if abs(p[k] - q[k]) > _EPS]
            if len(moved) == 1:
                self._used.append((moved[0], tuple(p), tuple(q)))

    def _occupy(self, points: Sequence[Point], half: float, label: str) -> None:
        """A routed line becomes a keep-out for the lines routed after it.

        Without this the corridor discount would pull a return straight onto its
        supply: sharing a rack is wanted, occupying the same centre-line is a
        clash. The two allowances together set how far apart a bundled pair sits.
        """
        for p, q in zip(points, points[1:]):
            box = Box.segment(p, q, pad=half, label=label)
            n = len(self.obstacles)
            self.obstacles.append(box)
            for cell in self._cells(box.lo, box.hi):
                self._index.setdefault(cell, []).append(n)

    # ---- geometry -------------------------------------------------------------

    def _blocked(self, p: Point, q: Point, half: float, exempt: frozenset) -> bool:
        lo = [min(p[k], q[k]) - half for k in AXES]
        hi = [max(p[k], q[k]) + half for k in AXES]
        seen: set[int] = set()
        for cell in self._cells(lo, hi):
            for n in self._index.get(cell, ()):
                if n in seen or n in exempt:
                    continue
                seen.add(n)
                box = self.obstacles[n]
                if all(lo[k] < box.hi[k] - _EPS and hi[k] > box.lo[k] + _EPS for k in AXES):
                    return True
        return False

    def _exempt_for(self, req: Request, pad: float) -> frozenset:
        """Obstacles the endpoints already sit inside cannot be avoided.

        A collector's open end is surrounded by the bank that feeds it. Treating
        that bank as a keep-out would make every route impossible, so obstacles
        touching either endpoint are excused for this request only.
        """
        anchors = (req.start, req.end)
        return frozenset(n for n, b in enumerate(self.obstacles)
                         if any(b.contains(a, pad) for a in anchors))

    # ---- search ---------------------------------------------------------------

    def _grid(self, req: Request, lead_start: Point, lead_end: Point) -> tuple[list, list, list]:
        pad = req.clearance_m + self.lane_padding_m
        required = [lead_start, lead_end, req.start, req.end]
        lo = [min(p[k] for p in required) for k in AXES]
        hi = [max(p[k] for p in required) for k in AXES]
        margin = max(8.0, 2 * max(req.lead_m, self.lane_padding_m * 2) + 1.0)
        coords: list[list[float]] = []
        for k in AXES:
            values = {p[k] for p in required}
            for box in self.obstacles:
                if box.hi[k] < lo[k] - margin or box.lo[k] > hi[k] + margin:
                    continue
                values.add(box.lo[k] - pad)
                values.add(box.hi[k] + pad)
            if k != 2:
                # Endpoint coordinates alone cannot express a detour: a collector
                # whose open end faces away from its target has to swing wide
                # before it can turn back. Give the plan axes room to do that.
                relief = max(2 * req.lead_m, self.lane_padding_m * 4)
                values.add(lo[k] - relief)
                values.add(hi[k] + relief)
            values = {v for v in values if lo[k] - margin - 1e-6 <= v <= hi[k] + margin + 1e-6}
            keep = [p[k] for p in (lead_start, lead_end)]
            coords.append(_dedupe(values, keep, self.min_segment_m))
        if self.z_levels:
            zs = set(coords[2]) | {z for z in self.z_levels}
            coords[2] = _dedupe(zs, [lead_start[2], lead_end[2]], self.min_segment_m)
        return coords[0], coords[1], coords[2]

    def route(self, requests: Sequence[Request]) -> dict[str, Result]:
        out: dict[str, Result] = {}
        for req in requests:
            res = self._route_one(req)
            out[req.key] = res
            if res.status == 'routed':
                pts = [tuple(req.start)] + [tuple(p) for p in res.waypoints] + [tuple(req.end)]
                self._remember(pts)
                self._occupy(pts, req.clearance_m, req.key)
        return out

    def _route_one(self, req: Request) -> Result:
        sa, ea = _axis_of(req.start_dir), _axis_of(req.end_dir)
        lead_start = tuple(req.start[k] + req.start_dir[k] * req.lead_m for k in AXES)
        lead_end = tuple(req.end[k] + req.end_dir[k] * req.lead_m for k in AXES)
        bound = (2 * req.lead_m
                 + sum(abs(lead_start[k] - lead_end[k]) for k in AXES))

        xs, ys, zs = self._grid(req, lead_start, lead_end)
        if len(xs) * len(ys) * len(zs) > self.max_nodes:
            return Result(req.key, [], 0., 0, 0., bound, 0., 'skipped',
                          f'lane grid too large ({len(xs)}x{len(ys)}x{len(zs)})')
        axes_coords = (xs, ys, zs)

        def index_of(value: float, table: list[float]) -> Optional[int]:
            for i, v in enumerate(table):
                if abs(v - value) < 1e-6:
                    return i
            return None

        start_idx = tuple(index_of(lead_start[k], axes_coords[k]) for k in AXES)
        goal_idx = tuple(index_of(lead_end[k], axes_coords[k]) for k in AXES)
        if None in start_idx or None in goal_idx:
            return Result(req.key, [], 0., 0, 0., bound, 0., 'skipped',
                          'endpoint lead not representable on the lane grid')

        half = req.clearance_m
        exempt = self._exempt_for(req, half + self.lane_padding_m)
        # The pipe from start to its lead point, and from the end lead point to
        # the end, are fixed by the collector geometry. Reject the route only if
        # the search cannot get between the two lead points.
        point = lambda idx: tuple(axes_coords[k][idx[k]] for k in AXES)

        # Leaving the start lead point back along the start axis would double
        # over the pipe that reaches it; same at the goal.
        forbidden_first = (sa, -1 if req.start_dir[sa] > 0 else 1)
        forbidden_last = (ea, 1 if req.end_dir[ea] > 0 else -1)

        def heuristic(idx) -> float:
            p = point(idx)
            return sum(abs(p[k] - lead_end[k]) for k in AXES) * req.rate * (1 - self.bundle_discount)

        start_state = (start_idx, -1)
        best = {start_state: 0.0}
        came: dict = {}
        queue = [(heuristic(start_idx), 0.0, start_state)]
        found = None
        visits = 0
        while queue:
            _, g, state = heappop(queue)
            if g > best.get(state, float('inf')) + _EPS:
                continue
            idx, incoming = state
            if idx == goal_idx and incoming != -1:
                found = state
                break
            visits += 1
            if visits > self.max_nodes:
                return Result(req.key, [], 0., 0, 0., bound, 0., 'skipped',
                              'search budget exhausted')
            p = point(idx)
            for axis in AXES:
                for step in (-1, 1):
                    j = idx[axis] + step
                    if j < 0 or j >= len(axes_coords[axis]):
                        continue
                    if incoming == -1 and (axis, step) == forbidden_first:
                        continue
                    nidx = tuple(j if k == axis else idx[k] for k in AXES)
                    q = point(nidx)
                    if nidx == goal_idx and (axis, step) == forbidden_last:
                        continue
                    if self._blocked(p, q, half, exempt):
                        continue
                    span = abs(q[axis] - p[axis])
                    if span < self.min_segment_m - _EPS:
                        continue
                    rate = req.rate * (1 - self._discount(p, q, axis))
                    cost = span * rate
                    if incoming != -1 and incoming != axis:
                        cost += self.bend_cost_m * req.rate
                    nstate = (nidx, axis)
                    ng = g + cost
                    if ng + _EPS < best.get(nstate, float('inf')):
                        best[nstate] = ng
                        came[nstate] = state
                        heappush(queue, (ng + heuristic(nidx), ng, nstate))
        if found is None:
            return Result(req.key, [], 0., 0, 0., bound, 0., 'unrouted',
                          'no obstacle-free lane path between the endpoint leads')

        chain = [found]
        while chain[-1] in came:
            chain.append(came[chain[-1]])
        chain.reverse()
        raw = [point(state[0]) for state in chain]

        pts = [tuple(req.start)] + raw + [tuple(req.end)]
        pts = _collapse(pts)
        ok, why = _validate(pts, self.bend_radius_m)
        if not ok:
            return Result(req.key, [], 0., 0, 0., bound, 0., 'rejected', why)

        length = sum(_dist(p, q) for p, q in zip(pts, pts[1:]))
        bends = max(0, len(pts) - 2)
        shared = 0.0
        for p, q in zip(pts, pts[1:]):
            moved = [k for k in AXES if abs(p[k] - q[k]) > _EPS]
            if len(moved) == 1 and self._discount(p, q, moved[0]) > 0:
                shared += _dist(p, q)
        cost = length * req.rate + bends * self.bend_cost_m * req.rate
        return Result(req.key, [list(p) for p in pts[1:-1]], length, bends, cost,
                      bound, shared)


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return sum((a[k] - b[k]) ** 2 for k in AXES) ** .5


def _collapse(points: Sequence[Point]) -> list[Point]:
    """Drop repeats and merge collinear runs, the way route_path() would."""
    out: list[Point] = []
    for p in points:
        if out and _dist(out[-1], p) < 1e-8:
            continue
        while len(out) >= 2:
            a, b = out[-2], out[-1]
            # route_path() drops b only when it lies between a and p. A point
            # that overshoots and comes back is not collinear filler, it is a
            # doubled-back pipe, and collapsing it would quietly change the run.
            straight = sum(1 for k in AXES if abs(a[k] - p[k]) > _EPS) == 1
            between = all(min(a[k], p[k]) - _EPS <= b[k] <= max(a[k], p[k]) + _EPS
                          for k in AXES)
            if straight and between:
                out.pop()
                continue
            break
        out.append(tuple(p))
    return out


def _validate(points: Sequence[Point], radius: float) -> tuple[bool, str]:
    """Exactly the conditions route_path() enforces, checked before we call it."""
    if len(points) < 2:
        return False, 'route collapsed to a single point'
    for p, q in zip(points, points[1:]):
        if sum(1 for k in AXES if abs(p[k] - q[k]) > _EPS) != 1:
            return False, 'route produced a non-orthogonal segment'
    for i, (p, q) in enumerate(zip(points, points[1:])):
        required = radius * ((i > 0) + (i < len(points) - 2)) + .01
        if len(points) > 2 and _dist(p, q) < required - 1e-8:
            return False, (f'segment {_dist(p, q):.3f} m cannot fit '
                           f'{radius:.3f} m bends')
    return True, ''


# ---------------------------------------------------------------------------
# Adapter for this generator's graph. Kept here rather than in plant.py so the
# router has one documented way in, and plant.py keeps its own subject matter.

def obstacles_from_graph(g: dict, xyz, *, pipe_half_m: float = 0.20,
                         equipment_pad_m: float = 1.0,
                         overfly_top_m: Optional[float] = None,
                         overfly_kinds: Sequence[str] = ('chiller', 'cooling_tower'),
                         skip_ids: Sequence[str] = ()) -> list[Box]:
    """Everything already in the graph, as keep-outs the router must respect.

    Equipment becomes a box inflated in plan by its service clearance but not in
    elevation, because overhead pipe above a 2.5 m chiller at a 4 m header is not
    a clash. `overfly_top_m` overrides that for equipment that needs clear access
    from above - a cooling tower's airflow, a chiller's tube pull.

    Routed pipe becomes a thin box around its own centre-line, inflated by half
    the separation `geometry_checks.diagnose()` will later demand. The routed
    line is inflated by the same amount again through `Request.clearance_m`, so
    the pair of allowances is what keeps two centre-lines apart.
    """
    skip = set(skip_ids)
    boxes: list[Box] = []
    for comp in g['components']:
        if comp.get('id') in skip or comp.get('attachment'):
            continue
        size, center = comp.get('size_m'), comp.get('center_m')
        if size and center:
            box = Box.around(center, size, pad=equipment_pad_m, pad_z=0.0,
                             label=comp.get('id', ''))
            if overfly_top_m is not None and comp.get('kind') in overfly_kinds:
                box = Box(box.lo, (box.hi[0], box.hi[1], max(box.hi[2], overfly_top_m)),
                          box.label)
            boxes.append(box)
            continue
        if comp.get('kind') in ('pipe', 'elbow') and len(comp.get('ports', [])) == 2:
            try:
                a, b = (xyz(p) for p in comp['ports'])
            except KeyError:
                continue
            boxes.append(Box.segment(a, b, pad=pipe_half_m, label=comp.get('id', '')))
    return boxes
