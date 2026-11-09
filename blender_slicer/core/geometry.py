"""Pure 2D geometry helpers (millimetres, no Blender imports)."""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable

from .errors import DomainError
from .types import ErrorCode, Point2

EPS = 1e-12
PI = math.pi


# ---------------------------------------------------------------------------
# vector helpers
# ---------------------------------------------------------------------------

def v_add(a: Point2, b: Point2) -> Point2:
    return (a[0] + b[0], a[1] + b[1])


def v_sub(a: Point2, b: Point2) -> Point2:
    return (a[0] - b[0], a[1] - b[1])


def v_mul(a: Point2, s: float) -> Point2:
    return (a[0] * s, a[1] * s)


def v_lerp(a: Point2, b: Point2, t: float) -> Point2:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def dot(a: Point2, b: Point2) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Point2, b: Point2) -> float:
    return a[0] * b[1] - a[1] * b[0]


def length(a: Point2) -> float:
    return math.hypot(a[0], a[1])


def dist(a: Point2, b: Point2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(a: Point2) -> Point2:
    n = length(a)
    if n <= EPS:
        return (0.0, 0.0)
    return (a[0] / n, a[1] / n)


def left_normal(a: Point2) -> Point2:
    return (-a[1], a[0])


# ---------------------------------------------------------------------------
# measurements
# ---------------------------------------------------------------------------

def signed_area(points: list[Point2]) -> float:
    if len(points) < 3:
        return 0.0
    s = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s * 0.5


def polyline_length(points: list[Point2], closed: bool) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(len(points) - 1):
        total += dist(points[i], points[i + 1])
    if closed:
        total += dist(points[-1], points[0])
    return total


def signed_turn(prev: Point2, cur: Point2, nxt: Point2) -> float:
    a = v_sub(cur, prev)
    b = v_sub(nxt, cur)
    if length(a) <= EPS or length(b) <= EPS:
        return 0.0
    return math.atan2(cross(a, b), dot(a, b))


def turn_angle(prev: Point2, cur: Point2, nxt: Point2) -> float:
    return abs(signed_turn(prev, cur, nxt))


def vertex_radius(prev: Point2, cur: Point2, nxt: Point2) -> float | None:
    """Discrete radius through three points; None for a straight/short corner."""
    a = dist(prev, cur)
    b = dist(cur, nxt)
    c = dist(prev, nxt)
    if min(a, b, c) <= EPS:
        return None
    area2 = abs(cross(v_sub(cur, prev), v_sub(nxt, prev)))
    if area2 <= 1e-12:
        return None
    return (a * b * c) / (2.0 * area2)


def min_radius(points: list[Point2], closed: bool) -> float | None:
    if len(points) < 3:
        return None
    best: float | None = None
    n = len(points)
    indices = range(n) if closed else range(1, n - 1)
    for i in indices:
        r = vertex_radius(points[(i - 1) % n], points[i], points[(i + 1) % n])
        if r is not None and (best is None or r < best):
            best = r
    return best


def max_turn_deg(points: list[Point2], closed: bool) -> float | None:
    if len(points) < 3:
        return None
    best = 0.0
    n = len(points)
    indices = range(n) if closed else range(1, n - 1)
    for i in indices:
        best = max(best, turn_angle(points[(i - 1) % n], points[i], points[(i + 1) % n]))
    return math.degrees(best)


def dedupe(points: Iterable[Point2], closed: bool, tol: float = 1e-9) -> list[Point2]:
    out: list[Point2] = []
    for p in points:
        if not out or dist(out[-1], p) > tol:
            out.append(p)
    if closed and len(out) > 1 and dist(out[0], out[-1]) <= tol:
        out.pop()
    return out


# ---------------------------------------------------------------------------
# containment / intersections
# ---------------------------------------------------------------------------

def point_on_segment(p: Point2, a: Point2, b: Point2, tol: float = 1e-9) -> bool:
    if abs(cross(v_sub(p, a), v_sub(b, a))) > tol * max(1.0, dist(a, b)):
        return False
    return (
        min(a[0], b[0]) - tol <= p[0] <= max(a[0], b[0]) + tol
        and min(a[1], b[1]) - tol <= p[1] <= max(a[1], b[1]) + tol
    )


def point_in_polygon(p: Point2, polygon: list[Point2]) -> bool:
    """Ray casting; boundary counts as inside."""
    n = len(polygon)
    if n < 3:
        return False
    for i in range(n):
        if point_on_segment(p, polygon[i], polygon[(i + 1) % n]):
            return True
    x, y = p
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def contour_inside(candidate: list[Point2], container: list[Point2]) -> bool:
    if len(candidate) < 3 or len(container) < 3:
        return False
    # A single vertex can lie on the boundary; use a few samples and majority.
    samples = [candidate[0]]
    if len(candidate) > 1:
        samples.append(candidate[len(candidate) // 3])
    if len(candidate) > 2:
        samples.append(candidate[(2 * len(candidate)) // 3])
    hits = sum(1 for p in samples if point_in_polygon(p, container))
    return hits >= (len(samples) + 1) // 2


def _segments_strictly_intersect(a: Point2, b: Point2, c: Point2, d: Point2) -> bool:
    """Proper intersection, ignoring shared endpoints and collinear overlaps."""
    if dist(a, c) <= 1e-9 or dist(a, d) <= 1e-9 or dist(b, c) <= 1e-9 or dist(b, d) <= 1e-9:
        return False
    ab = v_sub(b, a)
    cd = v_sub(d, c)
    d1 = cross(ab, v_sub(c, a))
    d2 = cross(ab, v_sub(d, a))
    d3 = cross(cd, v_sub(a, c))
    d4 = cross(cd, v_sub(b, c))
    return (d1 * d2 < -1e-12) and (d3 * d4 < -1e-12)


def count_self_intersections(points: list[Point2], closed: bool) -> int:
    """Count proper self-intersections of a polyline.

    A sweep along x keeps only segments whose x-range is still open, so a
    typical contour costs far less than the naive all-pairs loop.  Shared
    endpoints, T-junctions and collinear overlaps are not counted.
    """
    n = len(points)
    if n < 4:
        return 0
    seg_count = n if closed else n - 1
    if seg_count < 4:
        return 0

    boxes: list[tuple[float, float, float, float]] = []
    for i in range(seg_count):
        a = points[i]
        b = points[(i + 1) % n]
        boxes.append(
            (
                min(a[0], b[0]),
                max(a[0], b[0]),
                min(a[1], b[1]),
                max(a[1], b[1]),
            )
        )

    order = sorted(range(seg_count), key=lambda i: (boxes[i][0], i))
    active: set[int] = set()
    closing: list[tuple[float, int]] = []
    count = 0

    for i in order:
        min_ax, max_ax, min_ay, max_ay = boxes[i]
        while closing and closing[0][0] < min_ax:
            _, expired = heapq.heappop(closing)
            active.discard(expired)

        a = points[i]
        b = points[(i + 1) % n]
        for j in active:
            if abs(i - j) == 1:
                continue
            if closed and (
                (i == 0 and j == seg_count - 1) or (j == 0 and i == seg_count - 1)
            ):
                continue
            _, _, min_cy, max_cy = boxes[j]
            if max_cy < min_ay or min_cy > max_ay:
                continue
            c = points[j]
            d = points[(j + 1) % n]
            if _segments_strictly_intersect(a, b, c, d):
                count += 1

        active.add(i)
        heapq.heappush(closing, (max_ax, i))

    return count


# ---------------------------------------------------------------------------
# deviation
# ---------------------------------------------------------------------------

def point_to_segment_distance(p: Point2, a: Point2, b: Point2) -> float:
    ab = v_sub(b, a)
    denom = dot(ab, ab)
    if denom <= EPS:
        return dist(p, a)
    t = max(0.0, min(1.0, dot(v_sub(p, a), ab) / denom))
    return dist(p, v_lerp(a, b, t))


def point_to_polyline_distance(p: Point2, points: list[Point2], closed: bool) -> float:
    if len(points) < 2:
        return dist(p, points[0]) if points else 0.0
    best = float("inf")
    for i in range(len(points) - 1):
        best = min(best, point_to_segment_distance(p, points[i], points[i + 1]))
    if closed:
        best = min(best, point_to_segment_distance(p, points[-1], points[0]))
    return best


def polyline_max_deviation(
    result: list[Point2], reference: list[Point2], closed_reference: bool
) -> float:
    if not result or not reference:
        return 0.0
    return max(point_to_polyline_distance(p, reference, closed_reference) for p in result)


# ---------------------------------------------------------------------------
# resampling
# ---------------------------------------------------------------------------

def resample(
    points: list[Point2],
    closed: bool,
    spacing_mm: float,
    *,
    adaptive: bool = False,
    min_spacing_mm: float = 0.1,
    chord_tolerance_mm: float = 0.05,
) -> list[Point2]:
    if spacing_mm <= EPS or len(points) < 2:
        return list(points)
    n = len(points)
    out: list[Point2] = [points[0]]
    seg_count = n if closed else n - 1

    radii: list[float | None] = [None] * n
    if adaptive and n >= 3:
        for i in range(n):
            if not closed and (i == 0 or i == n - 1):
                radii[i] = None
            else:
                radii[i] = vertex_radius(points[(i - 1) % n], points[i], points[(i + 1) % n])

    for i in range(seg_count):
        a = points[i]
        b = points[(i + 1) % n]
        seg_len = dist(a, b)
        if seg_len <= EPS:
            continue
        local = spacing_mm
        if adaptive:
            for k in (i, (i + 1) % n):
                r = radii[k]
                if r:
                    chord = 2.0 * math.sqrt(max(0.0, 2.0 * r * chord_tolerance_mm - chord_tolerance_mm ** 2))
                    if chord > EPS:
                        local = min(local, chord)
            local = max(min_spacing_mm, local)
        nseg = max(1, int(math.ceil(seg_len / local)))
        for j in range(1, nseg + 1):
            p = v_lerp(a, b, j / nseg)
            if not out or dist(out[-1], p) > 1e-9:
                out.append(p)
    if closed and len(out) > 1 and dist(out[0], out[-1]) <= 1e-9:
        out.pop()
    return out


# ---------------------------------------------------------------------------
# simplification
# ---------------------------------------------------------------------------

def _dp_indices(points: list[Point2], tolerance: float, forced: set[int]) -> list[int]:
    n = len(points)
    if n <= 2:
        return list(range(n))
    keep = [False] * n
    keep[0] = True
    keep[-1] = True
    for i in forced:
        if 0 <= i < n:
            keep[i] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        max_d = -1.0
        max_k = -1
        a = points[i]
        b = points[j]
        for k in range(i + 1, j):
            d = point_to_segment_distance(points[k], a, b)
            if d > max_d:
                max_d = d
                max_k = k
        if max_d > tolerance and max_k > 0:
            keep[max_k] = True
            stack.append((i, max_k))
            stack.append((max_k, j))
    return [i for i, v in enumerate(keep) if v]


def simplify(
    points: list[Point2],
    closed: bool,
    tolerance_mm: float,
    forced: set[int] | None = None,
) -> list[Point2]:
    n = len(points)
    if n < 3 or tolerance_mm <= 0:
        return list(points)
    forced = set(forced or ())
    if not closed:
        forced.add(0)
        forced.add(n - 1)
        idx = _dp_indices(points, tolerance_mm, forced)
        out = [points[i] for i in idx]
        return out if len(out) >= 2 else list(points)

    # Split the loop into two arcs so simplification does not depend on the start.
    far = max(range(1, n), key=lambda i: dist(points[0], points[i]))
    if far == 0:
        return list(points)
    arc1 = points[: far + 1]
    arc2 = points[far:] + [points[0]]
    forced1 = {i for i in forced if 0 <= i <= far}
    forced2 = {i - far for i in forced if i >= far}
    forced1 |= {0, len(arc1) - 1}
    forced2 |= {0, len(arc2) - 1}
    idx1 = _dp_indices(arc1, tolerance_mm, forced1)
    idx2 = _dp_indices(arc2, tolerance_mm, forced2)
    result_idx: list[int] = []
    seen: set[int] = set()
    for i in idx1:
        if i not in seen:
            seen.add(i)
            result_idx.append(i)
    for i in idx2:
        g = far + i if i < len(arc2) - 1 else 0
        if g not in seen:
            seen.add(g)
            result_idx.append(g)
    result_idx.sort()
    out = [points[i] for i in result_idx]
    return out if len(out) >= 3 else list(points)


def sharp_corners(points: list[Point2], closed: bool, threshold_deg: float) -> set[int]:
    if threshold_deg >= 180 or len(points) < 3:
        return set()
    threshold = math.radians(threshold_deg)
    n = len(points)
    indices = range(n) if closed else range(1, n - 1)
    return {
        i
        for i in indices
        if turn_angle(points[(i - 1) % n], points[i], points[(i + 1) % n]) >= threshold
    }


# ---------------------------------------------------------------------------
# smoothing
# ---------------------------------------------------------------------------

def _chaikin_open(points: list[Point2]) -> list[Point2]:
    if len(points) <= 2:
        return list(points)
    out = [points[0]]
    for i in range(len(points) - 1):
        a = points[i]
        b = points[i + 1]
        out.append(v_lerp(a, b, 0.25))
        out.append(v_lerp(a, b, 0.75))
    out.append(points[-1])
    return dedupe(out, False)


def _chaikin_closed(points: list[Point2]) -> list[Point2]:
    n = len(points)
    if n < 3:
        return list(points)
    out: list[Point2] = []
    for i in range(n):
        a = points[i]
        b = points[(i + 1) % n]
        out.append(v_lerp(a, b, 0.25))
        out.append(v_lerp(a, b, 0.75))
    return dedupe(out, True)


def chaikin(
    points: list[Point2],
    closed: bool,
    iterations: int,
    anchor_indices: set[int] | None = None,
) -> list[Point2]:
    if iterations <= 0 or len(points) < 3:
        return list(points)
    anchors = set(anchor_indices or ())
    current = list(points)

    def smooth_span(span: list[Point2]) -> list[Point2]:
        for _ in range(iterations):
            span = _chaikin_open(span)
        return span

    if not closed:
        anchors |= {0, len(current) - 1}
        sorted_anchors = sorted(a for a in anchors if 0 <= a < len(current))
        if len(sorted_anchors) <= 1:
            return smooth_span(current)
        out: list[Point2] = []
        for k in range(len(sorted_anchors) - 1):
            a = sorted_anchors[k]
            b = sorted_anchors[k + 1]
            span = smooth_span(current[a : b + 1])
            out.extend(span if not out else span[1:])
        return out

    sorted_anchors = sorted(a for a in anchors if 0 <= a < len(current))
    if not sorted_anchors:
        for _ in range(iterations):
            current = _chaikin_closed(current)
        return current
    if len(sorted_anchors) == 1:
        # Open the loop at the only anchor so it survives smoothing, then close
        # it again.  Without this the anchor set is silently discarded when a
        # contour has a single sharp corner.
        a = sorted_anchors[0]
        rotated = current[a:] + current[:a] + [current[a]]
        return dedupe(smooth_span(rotated), True)
    out = []
    for k in range(len(sorted_anchors)):
        a = sorted_anchors[k]
        b = sorted_anchors[(k + 1) % len(sorted_anchors)]
        if a < b:
            indices = list(range(a, b + 1))
        else:
            indices = list(range(a, len(current))) + list(range(0, b + 1))
        span = smooth_span([current[i] for i in indices])
        out.extend(span if not out else span[1:])
    return dedupe(out, True)


def laplacian(
    points: list[Point2],
    closed: bool,
    iterations: int,
    weight: float = 0.5,
    anchor_indices: set[int] | None = None,
    max_deviation_mm: float | None = None,
) -> list[Point2]:
    if iterations <= 0 or len(points) < 3:
        return list(points)
    n = len(points)
    anchors = set(anchor_indices or ())
    if not closed:
        anchors |= {0, n - 1}
    reference = list(points)
    current = list(points)
    for _ in range(iterations):
        nxt = list(current)
        for i in range(n):
            if i in anchors:
                continue
            if not closed and (i == 0 or i == n - 1):
                continue
            prev = current[(i - 1) % n]
            after = current[(i + 1) % n]
            avg = ((prev[0] + after[0]) * 0.5, (prev[1] + after[1]) * 0.5)
            candidate = (
                current[i][0] + (avg[0] - current[i][0]) * weight,
                current[i][1] + (avg[1] - current[i][1]) * weight,
            )
            if max_deviation_mm is not None and dist(candidate, reference[i]) > max_deviation_mm:
                continue
            nxt[i] = candidate
        current = nxt
    return current


# ---------------------------------------------------------------------------
# fillet
# ---------------------------------------------------------------------------

def fillet_corners(
    points: list[Point2],
    closed: bool,
    radius_mm: float,
    min_turn_deg: float,
    arc_segments: int,
    mode: str = "error",
    chord_tolerance_mm: float = 0.05,
    material_min_radius_mm: float | None = None,
) -> tuple[list[Point2], list[dict]]:
    """Replace sharp corners with tangent arcs.

    Returns (points, warnings).  ``mode`` is clamp|error|skip.
    """
    n = len(points)
    if n < 3 or radius_mm <= 0:
        return list(points), []
    min_turn = math.radians(max(0.0, min_turn_deg))
    warnings: list[dict] = []
    out: list[Point2] = []
    if not closed:
        out.append(points[0])

    indices = range(n) if closed else range(1, n - 1)
    for i in indices:
        prev = points[(i - 1) % n]
        cur = points[i]
        nxt = points[(i + 1) % n]
        signed = signed_turn(prev, cur, nxt)
        turn = abs(signed)
        if turn < min_turn or turn > math.pi - 1e-6:
            out.append(cur)
            continue

        tan_half = math.tan(turn * 0.5)
        len_prev = dist(prev, cur)
        len_next = dist(cur, nxt)
        if tan_half <= EPS or len_prev <= EPS or len_next <= EPS:
            out.append(cur)
            continue

        r_max = min(len_prev, len_next) * 0.5 / tan_half
        r = radius_mm
        if r_max <= 1e-9:
            if mode == "error":
                raise DomainError(
                    ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    f"Corner {i}: no room for fillet (available radius {r_max:.4f} mm)",
                    contour_id=None,
                    point_index=i,
                    details={"requested_radius_mm": radius_mm, "available_radius_mm": r_max},
                )
            out.append(cur)
            continue

        if r > r_max:
            if mode == "error":
                raise DomainError(
                    ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    f"Corner {i}: requested radius {r:.4f} mm exceeds available {r_max:.4f} mm",
                    point_index=i,
                    details={"requested_radius_mm": radius_mm, "available_radius_mm": r_max},
                )
            if mode == "skip":
                out.append(cur)
                continue
            r = r_max
            warnings.append(
                {
                    "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    "severity": "warning",
                    "message": f"Corner {i}: radius clamped to {r:.4f} mm",
                    "point_index": i,
                    "details": {"requested_radius_mm": radius_mm, "available_radius_mm": r_max},
                }
            )

        if material_min_radius_mm is not None and r + 1e-9 < material_min_radius_mm:
            warnings.append(
                {
                    "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    "severity": "warning",
                    "message": (
                        f"Corner {i}: fillet radius {r:.4f} mm is below material "
                        f"minimum {material_min_radius_mm:.4f} mm"
                    ),
                    "point_index": i,
                    "details": {"radius_mm": r, "min_bend_radius_mm": material_min_radius_mm},
                }
            )

        d_in = unit(v_sub(cur, prev))
        d_out = unit(v_sub(nxt, cur))
        t = r * tan_half
        # Defensive clamp: the radius limit already guarantees this, but floating
        # point can put the tangent a hair beyond the segment midpoint.
        t = min(t, 0.5 * len_prev, 0.5 * len_next)
        if t < r * tan_half - 1e-9:
            r = t / tan_half
        p_start = v_sub(cur, v_mul(d_in, t))
        p_end = v_add(cur, v_mul(d_out, t))
        left = left_normal(d_in)
        center = v_add(p_start, v_mul(left, r)) if signed > 0 else v_sub(p_start, v_mul(left, r))

        a0 = math.atan2(p_start[1] - center[1], p_start[0] - center[0])
        a1 = math.atan2(p_end[1] - center[1], p_end[0] - center[0])
        sweep = a1 - a0
        if signed > 0:
            while sweep <= 0:
                sweep += 2 * math.pi
            while sweep > 2 * math.pi:
                sweep -= 2 * math.pi
        else:
            while sweep >= 0:
                sweep -= 2 * math.pi
            while sweep < -2 * math.pi:
                sweep += 2 * math.pi

        if chord_tolerance_mm > 0 and r > chord_tolerance_mm:
            cos_val = 1.0 - chord_tolerance_mm / r
            cos_val = max(-1.0, min(1.0, cos_val))
            step_angle = 2.0 * math.acos(cos_val)
            needed = max(1, int(math.ceil(abs(sweep) / max(step_angle, 1e-9))))
        else:
            needed = 1
        segments = max(1, min(64, max(int(arc_segments), needed)))

        arc = [p_start]
        for j in range(1, segments):
            a = a0 + sweep * j / segments
            arc.append((center[0] + r * math.cos(a), center[1] + r * math.sin(a)))
        arc.append(p_end)
        out.extend(arc)

    if not closed:
        out.append(points[-1])
    return dedupe(out, closed), warnings


# ---------------------------------------------------------------------------
# densification and curvature limiting
# ---------------------------------------------------------------------------

def _chord_for_radius(radius: float | None, tolerance: float) -> float | None:
    if not radius or radius <= 0 or tolerance <= 0:
        return None
    return 2.0 * math.sqrt(max(0.0, 2.0 * radius * tolerance - tolerance * tolerance))


def densify(
    points: list[Point2],
    closed: bool,
    max_spacing_mm: float,
    max_angle_step_deg: float = 0.0,
    chord_tolerance_mm: float = 0.05,
) -> list[Point2]:
    n = len(points)
    if n < 2:
        return list(points)
    seg_count = n if closed else n - 1
    radii = [None] * n
    for i in range(n):
        if not closed and (i == 0 or i == n - 1):
            radii[i] = None
        else:
            radii[i] = vertex_radius(points[(i - 1) % n], points[i], points[(i + 1) % n])

    out: list[Point2] = [points[0]]
    angle_step = math.radians(max(0.0, max_angle_step_deg))
    for i in range(seg_count):
        a = points[i]
        b = points[(i + 1) % n]
        seg_len = dist(a, b)
        if seg_len <= 1e-12:
            continue
        counts = [1]
        if max_spacing_mm > 0:
            counts.append(int(math.ceil(seg_len / max_spacing_mm)))
        for k in (i, (i + 1) % n):
            r = radii[k]
            chord = _chord_for_radius(r, chord_tolerance_mm)
            if chord:
                counts.append(int(math.ceil(seg_len / chord)))
            if r and angle_step > 0:
                chord_angle = 2.0 * r * math.sin(min(math.pi, angle_step) * 0.5)
                if chord_angle > 1e-9:
                    counts.append(int(math.ceil(seg_len / chord_angle)))
        steps = max(1, min(10000, max(counts)))
        for j in range(1, steps + 1):
            p = v_lerp(a, b, j / steps)
            if not out or dist(out[-1], p) > 1e-9:
                out.append(p)
    if closed and len(out) > 1 and dist(out[0], out[-1]) <= 1e-9:
        out.pop()
    return out


def limit_curvature(
    points: list[Point2],
    closed: bool,
    min_radius_mm: float,
    max_iterations: int = 20,
    weight: float = 0.5,
) -> tuple[list[Point2], int]:
    """Iteratively smooth vertices whose discrete radius is too small.

    Returns (points, remaining_violations).
    """
    if min_radius_mm <= 0 or len(points) < 3:
        return list(points), 0
    current = list(points)
    n = len(current)
    anchors = set() if closed else {0, n - 1}
    remaining = 0
    for _ in range(max(1, max_iterations)):
        violating = []
        for i in range(n):
            if i in anchors:
                continue
            r = vertex_radius(current[(i - 1) % n], current[i], current[(i + 1) % n])
            if r is not None and r < min_radius_mm:
                violating.append(i)
        remaining = len(violating)
        if not violating:
            return current, 0
        nxt = list(current)
        for i in violating:
            prev = current[(i - 1) % n]
            after = current[(i + 1) % n]
            avg = ((prev[0] + after[0]) * 0.5, (prev[1] + after[1]) * 0.5)
            nxt[i] = (
                current[i][0] + (avg[0] - current[i][0]) * weight,
                current[i][1] + (avg[1] - current[i][1]) * weight,
            )
        current = nxt
    return current, remaining


# ---------------------------------------------------------------------------
# sheet-metal helpers
# ---------------------------------------------------------------------------

def bend_allowance_mm(
    angle_deg: float, radius_mm: float, thickness_mm: float, k_factor: float
) -> float:
    return math.radians(abs(angle_deg)) * (radius_mm + k_factor * thickness_mm)
