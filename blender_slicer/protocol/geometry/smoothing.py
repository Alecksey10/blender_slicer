"""Chaikin, Laplacian and minimum-curvature smoothing."""

from __future__ import annotations

from ..types import Point2
from .core import dedupe, dist, v_lerp, vertex_radius


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
