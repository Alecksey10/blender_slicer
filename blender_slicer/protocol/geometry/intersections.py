"""Containment and self-intersection queries."""

from __future__ import annotations

import heapq

from ..types import Point2
from .core import cross, dist, v_sub


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
