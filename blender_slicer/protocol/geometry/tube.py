"""Tube / rod following geometry: tangent offsets and contact points.

These helpers build the *centreline* of a cylindrical rod (radius ``r``) that
runs along a guide curve (group A) at a constant distance ``r`` — i.e. the rod
surface touches the guide everywhere, so the centre never collides with the
guide material.  Used for group-B cross-section curves that must wrap around
group-A tubes.
"""

from __future__ import annotations

import math

from .core import (
    EPS,
    dedupe,
    dist,
    left_normal,
    signed_turn,
    unit,
    v_add,
    v_mul,
    v_sub,
)
from ..types import Point2


def _tangent_at(
    points: list[Point2], closed: bool, index: int
) -> Point2:
    """Unit tangent direction at ``points[index]`` (averaged from neighbours)."""
    n = len(points)
    if n < 2:
        return (1.0, 0.0)
    if n == 2:
        return unit(v_sub(points[1], points[0]))
    prev = points[(index - 1) % n]
    cur = points[index]
    nxt = points[(index + 1) % n]
    d0 = unit(v_sub(cur, prev)) if dist(prev, cur) > EPS else (0.0, 0.0)
    d1 = unit(v_sub(nxt, cur)) if dist(nxt, cur) > EPS else (0.0, 0.0)
    tx = d0[0] + d1[0]
    ty = d0[1] + d1[1]
    return unit((tx, ty)) if (tx != 0.0 or ty != 0.0) else (1.0, 0.0)


def _normal_at(points: list[Point2], closed: bool, index: int, side: float) -> Point2:
    """Unit normal at ``index`` pointing to ``side`` (+1 left / -1 right)."""
    tan = _tangent_at(points, closed, index)
    nrm = left_normal(tan)
    if side < 0.0:
        nrm = v_mul(nrm, -1.0)
    return nrm


def tangent_offset_points(
    points: list[Point2],
    closed: bool,
    distance_mm: float,
    side: float = 1.0,
    arc_segments: int = 8,
) -> list[Point2]:
    """Offset a polyline by ``distance_mm`` on ``side`` of travel.

    ``side = +1`` keeps the offset to the left of travel, ``-1`` to the right.
    For closed contours the side is relative to the winding direction.  This is
    a lightweight wrapper around :func:`blender_slicer.protocol.offset.offset_polyline`
    that keeps the public signature simple.
    """
    from ..offset import offset_polyline

    out, _ = offset_polyline(
        points,
        closed,
        distance_mm * side,
        join="round",
        arc_segments=arc_segments,
        chord_tolerance_mm=0.05,
    )
    return dedupe(out, closed)


def circle_tangent_point(
    guide_point: Point2,
    guide_tangent: Point2,
    contact_point: Point2,
    radius_mm: float,
) -> Point2:
    """Point on a circle of radius ``radius_mm`` tangent to the guide at ``guide_point``.

    The circle centre lies on the normal to the guide tangent at distance
    ``radius_mm``.  The returned point is where the circle perimeter passes
    through ``contact_point`` — used when the rod must touch a specific obstacle
    point while its centre follows the guide.
    """
    # Unit normal to the guide tangent.
    nx = -guide_tangent[1]
    ny = guide_tangent[0]
    n_len = math.hypot(nx, ny)
    if n_len <= EPS:
        return contact_point
    nx /= n_len
    ny /= n_len

    # Centre of the rod cross-section circle.
    cx = guide_point[0] + nx * radius_mm
    cy = guide_point[1] + ny * radius_mm

    # Vector from centre to the contact point.
    vx = contact_point[0] - cx
    vy = contact_point[1] - cy
    v_len = math.hypot(vx, vy)
    if v_len <= EPS:
        # Contact point equals centre: return any point on the circle.
        return (cx + radius_mm, cy)
    # Normalise to the circle radius.
    return (cx + vx * radius_mm / v_len, cy + vy * radius_mm / v_len)


def rod_centre_path(
    guide: list[Point2],
    closed: bool,
    rod_radius_mm: float,
    side: float = 1.0,
    arc_segments: int = 8,
) -> list[Point2]:
    """Centreline of a rod of radius ``rod_radius_mm`` following ``guide``.

    The rod surface stays tangent to the guide everywhere: the centre is offset
    from the guide by exactly ``rod_radius_mm`` along the guide normal.  This is
    the group-B curve that wraps around group-A tubes without colliding with
    them.
    """
    if rod_radius_mm <= 0.0 or len(guide) < 2:
        return list(guide)
    return tangent_offset_points(guide, closed, rod_radius_mm, side, arc_segments)


def interpolate_guide(
    points: list[Point2],
    closed: bool,
    samples: int = 64,
    tension: float = 0.5,
) -> list[Point2]:
    """Resample a guide curve evenly by parameter for stable tangent sampling."""
    if len(points) < 2:
        return list(points)
    # Build cumulative chord-length parameter.
    n = len(points)
    seg_count = n if closed else n - 1
    lengths: list[float] = [0.0] * n
    total = 0.0
    for i in range(seg_count):
        a = points[i]
        b = points[(i + 1) % n]
        total += dist(a, b)
        lengths[(i + 1) % n] = total
    if total <= 0.0:
        return list(points)

    from .approximation import evaluate_bezier_cubic

    # Use Catmull-Rom tangents for smooth sampling.
    tangents: list[Point2] = [(0.0, 0.0)] * n
    for i in range(n):
        if closed:
            p_prev = points[(i - 1) % n]
            p_next = points[(i + 1) % n]
            scale = 0.5
        elif i == 0:
            p_prev = points[0]
            p_next = points[1] if n > 1 else points[0]
            scale = 1.0
        elif i == n - 1:
            p_prev = points[n - 2] if n > 1 else points[0]
            p_next = points[n - 1]
            scale = 1.0
        else:
            p_prev = points[i - 1]
            p_next = points[i + 1]
            scale = 0.5
        tangents[i] = (
            (p_next[0] - p_prev[0]) * tension * scale,
            (p_next[1] - p_prev[1]) * tension * scale,
        )

    out: list[Point2] = []
    spans = n if closed else n - 1
    per_span = max(1, samples // max(1, spans))
    for i in range(spans):
        p0 = points[i]
        p3 = points[(i + 1) % n]
        m0 = tangents[i]
        m1 = tangents[(i + 1) % n]
        b0 = p0
        b1 = (p0[0] + m0[0] / 3.0, p0[1] + m0[1] / 3.0)
        b2 = (p3[0] - m1[0] / 3.0, p3[1] - m1[1] / 3.0)
        b3 = p3
        for k in range(per_span):
            t = k / float(per_span)
            out.append(evaluate_bezier_cubic(b0, b1, b2, b3, t))
    if not closed and out:
        out.append(points[-1])
    return dedupe(out, closed)
