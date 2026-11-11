"""Core 2D primitives: vectors, lengths, turns, radii and polyline cleanup."""

from __future__ import annotations

import math
from collections.abc import Iterable

from ..types import Point2

EPS = 1e-12
PI = math.pi

#: Vertices whose turn is below this are triangulation noise, not corners.
#: 0.01 deg is far below any real feature but well above float jitter on long
#: mesh edges; keeping such points makes identical corners differ in free room.
COLLINEAR_TOL_DEG = 0.01


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
