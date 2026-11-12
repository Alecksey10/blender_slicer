"""Differentiable cubic Bezier-spline approximation for the engine.

Replaces the purely Laplacian/Chaikin smoothing with C1-continuous Bezier
splines.  The interpolating spline passes exactly through every anchor point,
so real irregularities and corners are kept instead of being "licked away".
Smoothness vs fidelity is controlled by ``tension``, ``max_deviation_mm``,
``mode`` and the adaptive ``chord_tolerance_mm`` detail level.
"""

from __future__ import annotations

import math

from ..types import Point2
from .core import (
    dedupe,
    dist,
    point_to_segment_distance,
    polyline_max_deviation,
    turn_angle,
    v_lerp,
)
from .simplification import simplify
from .smoothing import limit_curvature


def evaluate_bezier_cubic(p0: Point2, p1: Point2, p2: Point2, p3: Point2, t: float) -> Point2:
    """Cubic Bezier curve evaluation at parameter t in [0, 1]."""
    u = 1.0 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    x = uuu * p0[0] + 3.0 * uu * t * p1[0] + 3.0 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3.0 * uu * t * p1[1] + 3.0 * u * tt * p2[1] + ttt * p3[1]
    return (x, y)


def _inertia_smooth(points: list[Point2], closed: bool, passes: int) -> list[Point2]:
    """Optional light pre-smoothing (kept for backward compatibility).

    Each pass nudges a vertex toward the midpoint of its neighbours.  Endpoints
    of open contours stay fixed.  Passes > 0 blur micro-jags but also soften
    real features, so the default is 0.
    """
    working = list(points)
    n = len(working)
    if n < 3 or passes <= 0:
        return working
    for _ in range(max(0, int(passes))):
        nxt = list(working)
        for i in range(n):
            if not closed and (i == 0 or i == n - 1):
                continue
            p_prev = working[(i - 1) % n]
            p_curr = working[i]
            p_next = working[(i + 1) % n]
            avg_x = (p_prev[0] + p_next[0]) * 0.5
            avg_y = (p_prev[1] + p_next[1]) * 0.5
            nxt[i] = (
                p_curr[0] * 0.4 + avg_x * 0.6,
                p_curr[1] * 0.4 + avg_y * 0.6,
            )
        working = nxt
    return working


def _cardinal_tangents(
    seg_points: list[Point2], closed_span: bool, tension: float
) -> list[Point2]:
    """C1 tangents for a Catmull-Rom / Cardinal spline over ``seg_points``.

    ``closed_span`` means the segment wraps around a closed loop (tangents use
    modulo indexing).  Otherwise the segment is treated as an open run with
    one-sided end tangents, so adjacent segments can meet at a sharp corner.
    """
    n = len(seg_points)
    tangents: list[Point2] = [(0.0, 0.0)] * n
    for i in range(n):
        if closed_span:
            p_prev = seg_points[(i - 1) % n]
            p_next = seg_points[(i + 1) % n]
            scale = 0.5
        elif i == 0:
            p_prev = seg_points[0]
            p_next = seg_points[1] if n > 1 else seg_points[0]
            scale = 1.0
        elif i == n - 1:
            p_prev = seg_points[n - 2] if n > 1 else seg_points[0]
            p_next = seg_points[n - 1]
            scale = 1.0
        else:
            p_prev = seg_points[i - 1]
            p_next = seg_points[i + 1]
            scale = 0.5
        tangents[i] = (
            (p_next[0] - p_prev[0]) * tension * scale,
            (p_next[1] - p_prev[1]) * tension * scale,
        )
    return tangents


def _split_segments(
    points: list[Point2], closed: bool, preserve_corners_deg: float
) -> list[list[int]]:
    """Split a contour into smooth runs separated by sharp corners.

    Returns a list of index lists.  Adjacent runs share their corner endpoint
    so the corner itself survives as an exact vertex in the output.
    """
    n = len(points)
    if n < 2:
        return [list(range(n))]
    threshold = math.radians(max(0.0, float(preserve_corners_deg)))
    corners: set[int] = set()
    if threshold > 0.0:
        for i in range(n):
            if (
                turn_angle(points[(i - 1) % n], points[i], points[(i + 1) % n])
                >= threshold
            ):
                corners.add(i)
    if not corners:
        return [list(range(n))]
    if closed:
        ordered = sorted(corners)
        segments: list[list[int]] = []
        for k in range(len(ordered)):
            c = ordered[k]
            nxt = ordered[(k + 1) % len(ordered)]
            seg: list[int] = []
            i = c
            while True:
                seg.append(i)
                if i == nxt:
                    break
                i = (i + 1) % n
            segments.append(seg)
        return segments
    bounds = [0] + sorted(c for c in corners if 0 < c < n - 1) + [n - 1]
    return [list(range(bounds[k], bounds[k + 1] + 1)) for k in range(len(bounds) - 1)]


def _flatten_span(
    b0: Point2,
    b1: Point2,
    b2: Point2,
    b3: Point2,
    chord_tol: float,
    max_spacing: float,
    seg_samples: int,
    depth: int,
    out: list[Point2],
) -> None:
    """Recursively append adaptive samples of one cubic Bezier span.

    ``out`` receives b0 and interior samples; b3 is left for the next span (or
    the final close) so consecutive spans share their endpoint exactly.
    """
    if chord_tol <= 0.0:
        # Uniform fallback detail level.
        for k in range(seg_samples):
            t = k / float(seg_samples)
            out.append(evaluate_bezier_cubic(b0, b1, b2, b3, t))
        return
    if depth >= 16:
        out.append(b0)
        return
    d1 = point_to_segment_distance(b1, b0, b3)
    d2 = point_to_segment_distance(b2, b0, b3)
    seg_len = dist(b0, b3)
    flat = max(d1, d2) <= chord_tol
    spacing_ok = max_spacing <= 0.0 or seg_len <= max_spacing
    if flat and spacing_ok:
        out.append(b0)
        return
    # de Casteljau split at t = 0.5
    p01 = v_lerp(b0, b1, 0.5)
    p12 = v_lerp(b1, b2, 0.5)
    p23 = v_lerp(b2, b3, 0.5)
    p012 = v_lerp(p01, p12, 0.5)
    p123 = v_lerp(p12, p23, 0.5)
    mid = v_lerp(p012, p123, 0.5)
    _flatten_span(b0, p01, p012, mid, chord_tol, max_spacing, seg_samples, depth + 1, out)
    _flatten_span(mid, p123, p23, b3, chord_tol, max_spacing, seg_samples, depth + 1, out)


def _fit_segment(
    points: list[Point2],
    segment: list[int],
    closed_span: bool,
    tension: float,
    chord_tol: float,
    max_spacing: float,
    seg_samples: int,
    out: list[Point2],
) -> None:
    """Append adaptive Bezier samples for one smooth segment into ``out``."""
    if len(segment) < 2:
        return
    seg_pts = [points[i] for i in segment]
    if len(seg_pts) == 2:
        out.append(seg_pts[0])
        return
    tangents = _cardinal_tangents(seg_pts, closed_span, tension)
    m = len(seg_pts)
    spans = m if closed_span else m - 1
    for i in range(spans):
        p0 = seg_pts[i]
        p3 = seg_pts[(i + 1) % m]
        m0 = tangents[i]
        m1 = tangents[(i + 1) % m]
        b0 = p0
        b1 = (p0[0] + m0[0] / 3.0, p0[1] + m0[1] / 3.0)
        b2 = (p3[0] - m1[0] / 3.0, p3[1] - m1[1] / 3.0)
        b3 = p3
        _flatten_span(b0, b1, b2, b3, chord_tol, max_spacing, seg_samples, 0, out)


def _fit_interpolating(
    points: list[Point2],
    closed: bool,
    tension: float,
    chord_tol: float,
    max_spacing: float,
    seg_samples: int,
    preserve_corners_deg: float,
) -> list[Point2]:
    """Core interpolating spline fit through ``points`` (already the anchors)."""
    working = dedupe(points, closed)
    if len(working) < 2:
        return list(points[: len(working)])

    segments = _split_segments(working, closed, preserve_corners_deg)
    out: list[Point2] = []
    for seg in segments:
        closed_span = closed and len(segments) == 1 and len(seg) == len(working)
        _fit_segment(
            working,
            seg,
            closed_span,
            tension,
            chord_tol,
            max_spacing,
            seg_samples,
            out,
        )
        if not closed_span:
            # Segment's final endpoint (shared with the next run -> deduped).
            out.append(working[seg[-1]])

    out = dedupe(out, closed)

    # Safety: guarantee open-contour endpoints survive.
    if not closed and out:
        if dist(out[0], working[0]) > 1e-9:
            out.insert(0, working[0])
        if dist(out[-1], working[-1]) > 1e-9:
            out.append(working[-1])
    return out


def _fit_approximate(
    points: list[Point2],
    closed: bool,
    tolerance: float,
    tension: float,
    chord_tol: float,
    max_spacing: float,
    seg_samples: int,
    preserve_corners_deg: float,
) -> list[Point2]:
    """Fit through simplified anchors, lowering tension until within tolerance.

    Because the source between consecutive anchors is (almost) a straight chord,
    the only off-source distance is the spline bulge, which scales with
    tension.  Halving tension until the deviation budget is met therefore
    genuinely bounds the output-to-source distance while staying smooth.
    """
    t = tension
    curve: list[Point2] | None = None
    for _ in range(10):
        anchors = simplify(points, closed, tolerance)
        curve = _fit_interpolating(
            anchors, closed, t, chord_tol, max_spacing, seg_samples, preserve_corners_deg
        )
        dev = polyline_max_deviation(curve, points, closed)
        if dev <= tolerance + 1e-9:
            return curve
        t *= 0.5
        if t < 1e-3:
            break
    return curve if curve is not None else list(points)


def _circle_fit(points: list[Point2]) -> tuple[Point2, float]:
    """Best-fit circle: centroid + mean radius of the input points."""
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    radii = [math.hypot(p[0] - cx, p[1] - cy) for p in points]
    mean_r = sum(radii) / len(radii)
    return (cx, cy), mean_r


def _blend_toward_circle(
    points: list[Point2], closed: bool, inertia: float
) -> list[Point2]:
    """Blend every point toward the best-fit circle by ``inertia`` in [0, 1].

    ``inertia = 0.0`` returns the input unchanged (exact following).
    ``inertia = 1.0`` returns a perfect circle through the mean radius.
    Intermediate values smooth progressively between the two.
    """
    if inertia <= 0.0 or len(points) < 3:
        return list(points)
    if not closed:
        # Open contours have no natural circle; just return as-is.
        return list(points)
    center, mean_r = _circle_fit(points)
    if mean_r <= 1e-9:
        return list(points)
    cx, cy = center
    out: list[Point2] = []
    for p in points:
        angle = math.atan2(p[1] - cy, p[0] - cx)
        cx_i = cx + mean_r * math.cos(angle)
        cy_i = cy + mean_r * math.sin(angle)
        out.append(
            (
                p[0] * (1.0 - inertia) + cx_i * inertia,
                p[1] * (1.0 - inertia) + cy_i * inertia,
            )
        )
    return out


def approximate_smooth_curve(
    points: list[Point2],
    closed: bool,
    min_bend_radius_mm: float = 0.0,
    segments_per_span: int = 8,
    tension: float = 0.5,
    inertia_smoothing: int = 0,
    *,
    mode: str = "interpolate",
    max_deviation_mm: float = 0.0,
    chord_tolerance_mm: float = 0.05,
    max_spacing_mm: float = 0.0,
    preserve_corners_deg: float = 0.0,
    inertia: float = 0.0,
) -> list[Point2]:
    """Approximates a contour with a differentiable C1-continuous Bezier spline.

    Parameters
    ----------
    points:
        Input control points.
    closed:
        Whether the contour is a closed loop.
    min_bend_radius_mm:
        Minimum radius of curvature enforced a-posteriori (0 disables).
    segments_per_span:
        Base number of samples per span when chord-tolerance adaptation is
        disabled (``chord_tolerance_mm <= 0``).
    tension:
        Curve tension in [0, 1].  0.0 gives straight chords between anchors;
        1.0 gives a tight Catmull-Rom spline.  In ``approximate`` mode the
        effective tension may be lowered automatically to meet
        ``max_deviation_mm``.
    inertia_smoothing:
        Optional pre-blur passes (0 keeps sharp features; this is what used to
        "lick away" the irregularities).
    inertia:
        Overall smoothness/inertia in [0, 1].  0.0 = exact following of every
        input point; 1.0 = degenerates into a best-fit circle; intermediate
        values blend progressively between the two.
    mode:
        * ``interpolate`` — spline passes exactly through every anchor point
          (corners and irregularities preserved).
        * ``approximate`` — Douglas-Peucker simplifies to
          ``max_deviation_mm`` first, then interpolates, and tension is eased
          until the output stays within that deviation of the source.
        * ``hybrid`` — light inertia smoothing, then interpolate.
    max_deviation_mm:
        Max allowed deviation from the original polyline (0 = exact fit).
    chord_tolerance_mm:
        Adaptive detail level: smaller = more samples on tight curves, fewer on
        flat spans.  0 disables adaptation and uses ``segments_per_span``.
    max_spacing_mm:
        Maximum distance between consecutive output samples (0 disables).
    preserve_corners_deg:
        Turns sharper than this (degrees) are kept as exact corners; the spline
        is split there so neighbouring smooth runs do not round them off.
    """
    if len(points) < 2:
        return list(points)

    working = dedupe(points, closed)
    if len(working) < 2:
        return list(points[: len(working)])

    mode = str(mode).lower()
    if mode == "approximate" and max_deviation_mm > 0.0:
        out = _fit_approximate(
            working,
            closed,
            max_deviation_mm,
            tension,
            chord_tolerance_mm,
            max_spacing_mm,
            max(2, int(segments_per_span)),
            preserve_corners_deg,
        )
    else:
        if mode == "hybrid":
            working = _inertia_smooth(working, closed, max(0, inertia_smoothing))
        elif inertia_smoothing > 0:
            working = _inertia_smooth(working, closed, inertia_smoothing)
        working = dedupe(working, closed)
        if len(working) < 2:
            return list(points[: len(working)])
        out = _fit_interpolating(
            working,
            closed,
            tension,
            chord_tolerance_mm,
            max_spacing_mm,
            max(2, int(segments_per_span)),
            preserve_corners_deg,
        )

    # Inertia blending: exact following (0) -> best-fit circle (1).
    out = _blend_toward_circle(out, closed, float(inertia))

    if min_bend_radius_mm > 0.0 and len(out) >= 3:
        out, _ = limit_curvature(out, closed=closed, min_radius_mm=min_bend_radius_mm)

    return out
