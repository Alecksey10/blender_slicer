"""Global curve optimization: one constrained least-squares solve.

This is the method from the prototype notebook, ported to the dependency-free
kernel (Blender ships NumPy but not SciPy, and the engine imports nothing but
the standard library).  The objective is exactly the prototype's:

    cost = 1/2 * sum(
        w_data   * |p[i] - base[i]|^2                     data fidelity
      + w_smooth * |p[i-1] - 2 p[i] + p[i+1]|^2           bending energy
      + w_radius * max(|k[i]| - 1/R, 0)^2                 bend-radius penalty
    )

``data`` keeps the curve on the measured contour, ``smooth`` is the elastic
energy of a thin rod, and ``radius`` makes the material limit a soft constraint:
a bend tighter than ``R`` is penalised instead of failing the slice, so an
impossible section comes back as close as the material allows rather than being
dropped.

Every weight is applied per unit of curve length (each vertex stands for one
segment), so the balance between the three terms - and therefore the result -
does not change when the contour is sampled more or less densely.

The bend-radius term is the same constraint written per vertex: a vertex turns by
``theta``, and the circumcircle through its neighbours has radius
``R = chord / (2 sin(theta))``, so ``|k| > 1/R_min`` is exactly
``|theta| > asin(chord / (2 R_min))``.  The turn-angle form is used because the
circumcircle curvature behaves like ``1 / turn``: at vertices that move close to
collinear its derivative explodes, the penalty becomes an infinitely stiff spring
and the solve stalls.  The angle keeps a bounded derivative and the same
feasible set.

Instead of SciPy's ``least_squares`` the solver is a Levenberg-Marquardt
iteration on banded normal equations: the data and bending terms are linear and
give an exact Jacobian, the bend penalty is differentiated locally by finite
differences (only at vertices that violate the radius), and the damped system is
solved by a banded Cholesky.  One iteration costs O(n) time with a
half-bandwidth of five, so pure Python is fast enough for interactive use.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Sequence

from ..types import Point2
from .core import dist, min_radius, polyline_length
from .smoothing import limit_curvature

EPS = 1e-12

#: Half-bandwidth of the normal equations, in variables (x/y are interleaved).
#: The widest coupling is the curvature of vertex i, which touches i-1..i+1:
#: the y of i-1 is five variables away from the x of i+1.
BAND = 5

#: Relative perturbation used for the local curvature derivative.
FD_STEP = 1e-6

#: A contour denser than this is resampled down to it unless the caller asks
#: for more samples explicitly; keeps one solve well under a second.
AUTO_DENSITY_CAP = 600

#: Levenberg-Marquardt damping bounds.
LAMBDA_MIN = 1e-9
LAMBDA_MAX = 1e12

ProgressHook = Callable[[dict[str, Any]], None]
CancelHook = Callable[[], bool]


def resample_by_count(points: Sequence[Point2], closed: bool, count: int) -> list[Point2]:
    """Resample a contour to exactly ``count`` points, evenly by arc length."""

    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 2 or count < 2:
        return pts
    if closed:
        pts = pts + [pts[0]]

    cumulative = [0.0]
    for previous, current in zip(pts, pts[1:]):
        cumulative.append(cumulative[-1] + dist(previous, current))
    total = cumulative[-1]
    if total <= EPS:
        return [(float(p[0]), float(p[1])) for p in points]

    last = 0
    out: list[Point2] = []
    for k in range(count):
        ratio = k / count if closed else k / (count - 1)
        target = total * ratio
        while last < len(cumulative) - 2 and cumulative[last + 1] < target:
            last += 1
        span = cumulative[last + 1] - cumulative[last]
        t = 0.0 if span <= EPS else (target - cumulative[last]) / span
        ax, ay = pts[last]
        bx, by = pts[last + 1]
        out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return out


def turn_angle_at(previous: Point2, current: Point2, following: Point2) -> float:
    """Signed turn (radians) from the incoming to the outgoing segment."""

    ax = current[0] - previous[0]
    ay = current[1] - previous[1]
    bx = following[0] - current[0]
    by = following[1] - current[1]
    if (ax == 0.0 and ay == 0.0) or (bx == 0.0 and by == 0.0):
        return 0.0
    return math.atan2(ax * by - ay * bx, ax * bx + ay * by)


def turn_limit(chord: float, min_radius_mm: float) -> float:
    """Largest turn a bend of ``min_radius_mm`` allows over ``chord``."""

    if min_radius_mm <= 0.0 or chord <= 0.0:
        return math.pi
    # R = chord / (2 sin(theta)) for the circle through the three points, so
    # |R| >= R_min is sin(theta) <= chord / (2 R_min).
    ratio = chord / (2.0 * min_radius_mm)
    if ratio >= 1.0:
        # The chord alone already spans more than the diameter: any turn fits.
        return math.pi
    return math.asin(ratio)


def radius_at(
    previous: Point2,
    current: Point2,
    following: Point2,
    turn: float | None = None,
) -> float:
    """Circumradius through three points; ``inf`` for a straight vertex."""

    chord = dist(previous, following)
    if chord <= EPS:
        return math.inf
    if turn is None:
        turn = turn_angle_at(previous, current, following)
    sine = abs(math.sin(turn))
    if sine <= 1e-12:
        return math.inf
    return chord / (2.0 * sine)


def curve_curvature(previous: Point2, current: Point2, following: Point2) -> float:
    """Signed curvature of three consecutive points (circumcircle formula)."""

    ax = current[0] - previous[0]
    ay = current[1] - previous[1]
    bx = following[0] - current[0]
    by = following[1] - current[1]
    cx = following[0] - previous[0]
    cy = following[1] - previous[1]
    cross = ax * by - ay * bx
    denominator = math.hypot(ax, ay) * math.hypot(bx, by) * math.hypot(cx, cy)
    return 2.0 * cross / max(denominator, 1e-10)


class _BandedSymmetric:
    """Symmetric positive-definite matrix stored as lower bands.

    ``low[d][j]`` holds ``A[j + d][j]``; the Cholesky factor replaces it in
    place so a solve needs no extra matrix.
    """

    __slots__ = ("n", "band", "low")

    def __init__(self, n: int, band: int = BAND) -> None:
        self.n = n
        self.band = band
        self.low = [[0.0] * n for _ in range(band + 1)]

    def add(self, i: int, j: int, value: float) -> None:
        if i < j:
            i, j = j, i
        difference = i - j
        if difference <= self.band:
            self.low[difference][j] += value

    def diagonal(self, i: int) -> float:
        return self.low[0][i]

    def factor(self) -> None:
        """In-place Cholesky; raises ``ValueError`` when not positive definite."""

        n, band, low = self.n, self.band, self.low
        for column in range(n):
            total = low[0][column]
            for k in range(max(0, column - band), column):
                value = low[column - k][k]
                total -= value * value
            if total <= EPS:
                raise ValueError("matrix is not positive definite")
            pivot = math.sqrt(total)
            low[0][column] = pivot
            limit = min(n, column + band + 1)
            for row in range(column + 1, limit):
                total = low[row - column][column]
                for k in range(max(0, row - band), column):
                    total -= low[row - k][k] * low[column - k][k]
                low[row - column][column] = total / pivot

    def solve(self, rhs: Sequence[float]) -> list[float]:
        n, band, low = self.n, self.band, self.low
        y = [0.0] * n
        for i in range(n):
            total = rhs[i]
            for k in range(max(0, i - band), i):
                total -= low[i - k][k] * y[k]
            y[i] = total / low[0][i]
        x = [0.0] * n
        for i in range(n - 1, -1, -1):
            total = y[i]
            for k in range(i + 1, min(n, i + band + 1)):
                total -= low[k - i][i] * x[k]
            x[i] = total / low[0][i]
        return x


def _evaluate(
    x: list[float],
    bx: list[float],
    by: list[float],
    n: int,
    closed: bool,
    rows: range,
    w_data: float,
    w_smooth: float,
    w_radius: float,
    max_curvature: float,
) -> tuple[float, float, float, float, list[float], list[tuple[int, float]]]:
    """Return ``(cost, data, smooth, radius, second_diff, violations)``.

    ``violations`` holds ``(vertex index, actual bend radius)`` for every vertex
    whose bend is tighter than the material allows.
    """

    data_cost = 0.0
    for i in range(n):
        dx = x[2 * i] - bx[i]
        dy = x[2 * i + 1] - by[i]
        data_cost += w_data * (dx * dx + dy * dy)

    second: list[float] = []
    smooth_cost = 0.0
    if w_smooth > 0.0:
        prev_next = [
            ((i - 1) % n, (i + 1) % n)
            if closed
            else (max(0, i - 1), min(n - 1, i + 1))
            for i in range(n)
        ]
        second = [0.0] * (2 * n)
        for i in rows:
            im, ip = prev_next[i]
            for c in (0, 1):
                value = x[2 * im + c] - 2.0 * x[2 * i + c] + x[2 * ip + c]
                second[2 * i + c] = value
                smooth_cost += w_smooth * value * value

    radius_cost = 0.0
    violations: list[tuple[int, float]] = []
    if w_radius > 0.0 and max_curvature > 0.0:
        min_radius_mm = 1.0 / max_curvature
        for i in rows:
            im = (i - 1) % n if closed else i - 1
            ip = (i + 1) % n if closed else i + 1
            previous = (x[2 * im], x[2 * im + 1])
            current = (x[2 * i], x[2 * i + 1])
            following = (x[2 * ip], x[2 * ip + 1])
            turn = turn_angle_at(previous, current, following)
            limit = turn_limit(dist(previous, following), min_radius_mm)
            if abs(turn) > limit:
                # Distance, not angle: the penalty compares with the data term
                # in millimetres, so the trade does not change with the scale of
                # the bend (a 20 mm radius is not cheaper to break than 3 mm).
                actual = radius_at(previous, current, following, turn)
                shortfall = min_radius_mm - actual
                if shortfall > 0.0:
                    violations.append((i, actual))
                    radius_cost += w_radius * shortfall * shortfall

    cost = 0.5 * (data_cost + smooth_cost + radius_cost)
    return cost, data_cost, smooth_cost, radius_cost, second, violations


def _normal_equations(
    x: list[float],
    n: int,
    closed: bool,
    rows: range,
    previous_next: list[tuple[int, int]],
    bx: list[float],
    by: list[float],
    second: list[float],
    violations: list[tuple[int, float]],
    w_data: float,
    w_smooth: float,
    w_radius: float,
    max_curvature: float,
    step: float,
) -> tuple[list[float], _BandedSymmetric]:
    """Gradient and Gauss-Newton matrix of the cost at ``x``.

    The data and bending terms are linear, so their Jacobian is exact; the
    curvature penalty is differentiated locally for every violating vertex.
    The matrix is returned in the same banded form the LM step solves.
    """

    gradient = [0.0] * (2 * n)
    for i in range(2 * n):
        target = bx[i // 2] if i % 2 == 0 else by[i // 2]
        gradient[i] = w_data * (x[i] - target)

    normal = _BandedSymmetric(2 * n, BAND)
    for i in range(2 * n):
        normal.add(i, i, w_data)

    if w_smooth > 0.0:
        for i in rows:
            im, ip = previous_next[i]
            for c in (0, 1):
                value = second[2 * i + c]
                gradient[2 * im + c] += w_smooth * value
                gradient[2 * i + c] += -2.0 * w_smooth * value
                gradient[2 * ip + c] += w_smooth * value
                if im != i:
                    normal.add(2 * im + c, 2 * im + c, w_smooth)
                    normal.add(2 * i + c, 2 * im + c, -2.0 * w_smooth)
                normal.add(2 * i + c, 2 * i + c, 4.0 * w_smooth)
                if ip != i:
                    normal.add(2 * ip + c, 2 * i + c, -2.0 * w_smooth)
                    normal.add(2 * ip + c, 2 * ip + c, w_smooth)
                if im != i and ip != i:
                    normal.add(2 * ip + c, 2 * im + c, w_smooth)

    min_radius_mm = 1.0 / max_curvature if max_curvature > 0.0 else 0.0
    for i, actual in violations:
        im = (i - 1) % n if closed else i - 1
        ip = (i + 1) % n if closed else i + 1
        coords = (2 * im, 2 * im + 1, 2 * i, 2 * i + 1, 2 * ip, 2 * ip + 1)
        triple = [
            (x[2 * im], x[2 * im + 1]),
            (x[2 * i], x[2 * i + 1]),
            (x[2 * ip], x[2 * ip + 1]),
        ]
        derivative: list[float] = []
        for slot, coord in enumerate(coords):
            point_index, axis = slot // 2, slot % 2
            saved = x[coord]
            x[coord] = saved + step
            moved = list(triple)
            point = list(moved[point_index])
            point[axis] = x[coord]
            moved[point_index] = (point[0], point[1])
            derivative.append((radius_at(moved[0], moved[1], moved[2]) - actual) / step)
            x[coord] = saved

        # d/dp of (R_min - R)^2 is -2 (R_min - R) dR/dp.
        weight = -w_radius * (min_radius_mm - actual)
        for slot, coord in enumerate(coords):
            gradient[coord] += weight * derivative[slot]
        for a, coord_a in enumerate(coords):
            scaled = w_radius * derivative[a]
            for b, coord_b in enumerate(coords):
                normal.add(coord_a, coord_b, scaled * derivative[b])

    return gradient, normal


def optimize_curve(
    points: Sequence[Point2],
    closed: bool,
    *,
    count: int = 150,
    data_weight: float = 20.0,
    smooth: float = 2.0,
    min_radius_mm: float = 0.0,
    radius_weight: float = 30.0,
    max_iterations: int = 40,
    cost_tolerance: float = 1e-6,
    start: Sequence[Point2] | None = None,
    progress: ProgressHook | None = None,
    cancel: CancelHook | None = None,
) -> tuple[list[Point2], dict[str, Any]]:
    """Fit ``points`` to a smooth curve that respects ``min_radius_mm``.

    ``start`` is an optional initial guess.  Without it the solve is seeded by
    a curvature relaxation of the resampled contour: a sharp corner is a cusp
    for the local model (moving the corner vertex alone *increases* its turn),
    so a least-squares step taken from the raw polygon cannot unfold it and the
    fit would stall at the source shape.  Seeding inside the feasible basin
    keeps the objective - not the seed - in charge of the result.

    Returns the optimized contour and a statistics dictionary (iterations,
    cost, duration, remaining radius violations) for the client monitor.
    """

    started = time.perf_counter()
    source = [(float(p[0]), float(p[1])) for p in points]
    stats: dict[str, Any] = {
        "iterations": 0,
        "evaluations": 0,
        "cost": 0.0,
        "success": False,
        "message": "",
        "time": 0.0,
        "points": len(source),
        "min_radius_mm": None,
        "max_curvature": 0.0,
        "violations": 0,
        "data_cost": 0.0,
        "smooth_cost": 0.0,
        "radius_cost": 0.0,
    }

    if len(source) < 4:
        stats["message"] = "contour is too short to optimize"
        stats["time"] = time.perf_counter() - started
        return list(source), stats

    # ``count`` is a minimum density: a contour that is already denser than that
    # keeps its detail instead of being thinned out.  The automatic density is
    # capped so a very dense slice stays interactive; asking for more explicit
    # samples is still honoured.
    target_count = max(4, min(max(int(count), min(len(source), AUTO_DENSITY_CAP)), 4000))
    base = resample_by_count(source, closed, target_count)
    n = len(base)
    if n < 4:
        stats["message"] = "contour is too short to optimize"
        stats["time"] = time.perf_counter() - started
        return list(source), stats

    stats["samples"] = n
    bx = [p[0] for p in base]
    by = [p[1] for p in base]

    if start is not None:
        seed = resample_by_count(start, closed, n)
    elif min_radius_mm and min_radius_mm > 0:
        # Corner rounding is a diffusion: it needs roughly (R / spacing)^2 passes
        # to spread the turn of a tight corner, so relax in chunks until no
        # vertex violates (a sharp corner left in the seed traps the fit in the
        # cusp local minimum).  Chunks stop early, so an easily feasible
        # contour costs a single O(n) sweep.
        chunk = max(20, n)
        budget = 40 * chunk
        seed = base
        remaining = 1
        while remaining and budget > 0:
            if cancel is not None and cancel():
                stats["message"] = "cancelled"
                stats["time"] = time.perf_counter() - started
                return list(source), stats
            seed, remaining = limit_curvature(
                seed, closed, float(min_radius_mm), chunk, 0.5
            )
            budget -= chunk
    else:
        seed = base
    if len(seed) != n:
        seed = resample_by_count(seed, closed, n)
    x: list[float] = []
    for px, py in seed:
        x.extend((px, py))

    length = polyline_length(base, closed)
    segments = n if closed else n - 1
    ds = max(length / max(1, segments), EPS)

    # All three terms are per unit of curve length (each vertex stands for one
    # segment), so the balance between them - and therefore the result - does
    # not change when the contour is sampled more or less densely.
    w_data = max(0.0, float(data_weight)) * ds
    # ``smooth`` is a smoothing *length* in millimetres, not a raw weight: it is
    # the scale over which the fit may trade data for a straighter curve.
    # Written as a length the control stays meaningful at any sampling; as a raw
    # weight it had to be rescaled by ds^4 to mean the same thing, which made the
    # slider look dead (0.5 to 10000 changed little: at 2.5 mm spacing that is
    # only 13x the data weight).
    smooth_length = max(0.0, float(smooth))
    w_smooth = (
        w_data * smooth_length**4 / ds**4 if smooth_length > 0.0 else 0.0
    )
    max_curvature = 1.0 / min_radius_mm if min_radius_mm and min_radius_mm > 0 else 0.0
    w_radius = max(0.0, float(radius_weight)) * ds
    rows = range(n) if closed else range(1, n - 1)

    iterations = max(1, int(max_iterations))
    tolerance = max(0.0, float(cost_tolerance))
    step = FD_STEP * max(1.0, ds)

    cost, data_cost, smooth_cost, radius_cost, second, violations = _evaluate(
        x, bx, by, n, closed, rows, w_data, w_smooth, w_radius, max_curvature
    )
    evaluations = 1
    lam = 1e-3
    iterations_done = 0
    stage_weight = w_radius
    message = f"stopped after {iterations} iterations"
    success = False

    previous_next = [
        ((i - 1) % n, (i + 1) % n)
        if closed
        else (max(0, i - 1), min(n - 1, i + 1))
        for i in range(n)
    ]

    for iteration in range(iterations):
        if cancel is not None and cancel():
            message = "cancelled"
            break
        # Give the GIL back between iterations: the host usually runs this on a
        # worker thread and wants its window to stay responsive.
        time.sleep(0)

        stage_weight = w_radius
        cost, data_cost, smooth_cost, radius_cost, second, violations = _evaluate(
            x, bx, by, n, closed, rows, w_data, w_smooth, stage_weight, max_curvature
        )
        evaluations += 1

        # ------------------------------------------------------- derivatives
        gradient, normal = _normal_equations(
            x,
            n,
            closed,
            rows,
            previous_next,
            bx,
            by,
            second,
            violations,
            w_data,
            w_smooth,
            stage_weight,
            max_curvature,
            step,
        )

        # ------------------------------------------------------------ LM step
        accepted = False
        while lam <= LAMBDA_MAX:
            damped = _BandedSymmetric(2 * n, BAND)
            damped.low = [list(band) for band in normal.low]
            for i in range(2 * n):
                damped.add(i, i, lam * max(normal.diagonal(i), 1e-9))
            try:
                damped.factor()
                delta = damped.solve([-value for value in gradient])
            except ValueError:
                lam *= 10.0
                continue

            candidate = [value + shift for value, shift in zip(x, delta)]
            trial, t_data, t_smooth, t_radius, _t_second, _t_violations = _evaluate(
                candidate, bx, by, n, closed, rows, w_data, w_smooth, stage_weight, max_curvature
            )
            evaluations += 1
            if trial < cost:
                relative = (cost - trial) / max(cost, EPS)
                x, cost = candidate, trial
                data_cost, smooth_cost, radius_cost = t_data, t_smooth, t_radius
                lam = max(lam / 3.0, LAMBDA_MIN)
                accepted = True
                if relative < tolerance:
                    message = "converged"
                    success = True
                break
            lam *= 10.0

        iterations_done = iteration + 1
        if progress is not None:
            try:
                progress(
                    {
                        "iteration": iterations_done,
                        "max_iterations": iterations,
                        "cost": cost,
                        "fraction": iterations_done / iterations,
                    }
                )
            except Exception:  # noqa: BLE001 - a monitor must never break a run
                pass
        if success or not accepted:
            if not accepted:
                message = "no further improvement"
                success = False
            break

    result = [(x[2 * i], x[2 * i + 1]) for i in range(n)]
    radii = min_radius(result, closed)
    # Report the objective at the returned points, not at the state before the
    # last accepted step.
    final_x = [value for point in result for value in point]
    cost, data_cost, smooth_cost, radius_cost, _second, violations = _evaluate(
        final_x, bx, by, n, closed, rows, w_data, w_smooth, stage_weight, max_curvature
    )
    peak_curvature = 0.0
    for i in rows:
        im = (i - 1) % n if closed else i - 1
        ip = (i + 1) % n if closed else i + 1
        peak_curvature = max(
            peak_curvature, abs(curve_curvature(result[im], result[i], result[ip]))
        )
    stats.update(
        {
            "iterations": iterations_done,
            "evaluations": evaluations,
            "cost": cost,
            "success": bool(success),
            "message": message,
            "time": time.perf_counter() - started,
            "points": n,
            "min_radius_mm": radii,
            "max_curvature": peak_curvature,
            "violations": len(violations),
            "data_cost": data_cost,
            "smooth_cost": smooth_cost,
            "radius_cost": radius_cost,
        }
    )
    return result, stats
