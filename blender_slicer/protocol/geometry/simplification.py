"""Douglas-Peucker simplification and corner detection."""

from __future__ import annotations

import math

from ..types import Point2
from .core import dist, point_to_segment_distance, turn_angle


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
