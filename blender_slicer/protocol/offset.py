"""Planar offset of closed contours and open polylines.

The engine needs offsets at its own level because a cut boundary is not only a
shape decision: neighbouring parts need clearance for welding or for the
material cross-section.  The adapter decides the *value* per slice
(``Slice.offset_mm``, positive = outward); this module only applies it.

Conventions
-----------
* closed contours: ``distance > 0`` grows the contour, ``< 0`` shrinks it,
  independent of the winding direction (it is normalized internally);
* open polylines: ``distance > 0`` moves the line to the left of travel;
* joins are ``round`` (default), ``miter`` or ``bevel``; inner corners always
  use the intersection of the two offset lines, which is what sheet metal needs;
* the output keeps the original winding and point order as far as possible.
"""

from __future__ import annotations

import math

from .geometry import (
    count_self_intersections,
    cross,
    dedupe,
    dist,
    left_normal,
    signed_area,
    unit,
    v_add,
    v_mul,
    v_sub,
)
from .types import ErrorCode
from .units import Point2

EPS = 1e-12


def _outward_normal(a: Point2, b: Point2, closed: bool) -> Point2:
    """Unit normal pointing away from the material for CCW input."""

    direction = unit(v_sub(b, a))
    left = left_normal(direction)
    # For a CCW polygon the interior is on the left, so outward is -left.
    # Open polylines have no interior; positive offset goes to the left.
    return v_mul(left, -1.0 if closed else 1.0)


def _line_intersection(
    e0: tuple[Point2, Point2], e1: tuple[Point2, Point2]
) -> Point2 | None:
    a0, b0 = e0
    a1, b1 = e1
    d0 = v_sub(b0, a0)
    d1 = v_sub(b1, a1)
    denominator = cross(d0, d1)
    if abs(denominator) <= 1e-15:
        return None
    t = cross(v_sub(a1, a0), d1) / denominator
    return v_add(a0, v_mul(d0, t))


def _arc_points(
    center: Point2,
    start: Point2,
    end: Point2,
    radius: float,
    segments: int,
    sweep_sign: float,
) -> list[Point2]:
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = a1 - a0
    if sweep_sign >= 0:
        while sweep <= 0.0:
            sweep += 2.0 * math.pi
        while sweep > 2.0 * math.pi:
            sweep -= 2.0 * math.pi
    else:
        while sweep >= 0.0:
            sweep -= 2.0 * math.pi
        while sweep < -2.0 * math.pi:
            sweep += 2.0 * math.pi
    steps = max(1, int(segments))
    out = [start]
    for i in range(1, steps):
        angle = a0 + sweep * i / steps
        out.append((center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle)))
    out.append(end)
    return out


def _arc_segments(radius: float, arc_segments: int, chord_tolerance_mm: float) -> int:
    if chord_tolerance_mm > 0 and radius > chord_tolerance_mm:
        cos_value = max(-1.0, min(1.0, 1.0 - chord_tolerance_mm / radius))
        step = 2.0 * math.acos(cos_value)
        needed = int(math.ceil((math.pi / 2.0) / max(step, 1e-9)))
        return max(int(arc_segments), needed, 1)
    return max(1, int(arc_segments))


def offset_polyline(
    points: list[Point2],
    closed: bool,
    distance_mm: float,
    join: str = "round",
    miter_limit: float = 2.0,
    arc_segments: int = 8,
    chord_tolerance_mm: float = 0.05,
) -> tuple[list[Point2], list[dict]]:
    """Offset a contour by ``distance_mm`` and return ``(points, warnings)``."""

    warnings: list[dict] = []
    cleaned = dedupe([(float(p[0]), float(p[1])) for p in points], closed)
    if abs(distance_mm) <= EPS or len(cleaned) < (3 if closed else 2):
        return list(points), warnings

    original_reversed = False
    working = list(cleaned)
    if closed:
        if signed_area(working) < 0.0:
            working.reverse()
            original_reversed = True

    n = len(working)
    segment_count = n if closed else n - 1
    if segment_count < (3 if closed else 1):
        return list(points), warnings

    direction = float(distance_mm)
    edges: list[tuple[Point2, Point2]] = []
    for i in range(segment_count):
        a = working[i]
        b = working[(i + 1) % n]
        shift = v_mul(_outward_normal(a, b, closed), direction)
        edges.append((v_add(a, shift), v_add(b, shift)))

    radius = abs(direction)
    segments = _arc_segments(radius, arc_segments, chord_tolerance_mm)
    style = str(join)
    out: list[Point2] = []
    if not closed:
        out.append(edges[0][0])

    join_count = segment_count if closed else segment_count - 1
    for i in range(join_count):
        e0 = edges[i]
        e1 = edges[(i + 1) % segment_count]
        end_prev = e0[1]
        start_next = e1[0]
        vertex = working[(i + 1) % n]
        d0 = unit(v_sub(working[(i + 1) % n], working[i]))
        d1 = unit(v_sub(working[(i + 2) % n], working[(i + 1) % n]))
        turn = cross(d0, d1)

        if dist(end_prev, start_next) <= 1e-9 or abs(turn) <= 1e-12:
            out.append(end_prev)
            continue

        if turn * direction > 0.0:
            # The two offset edges diverge: the gap belongs to the join.
            if style == "round":
                out.extend(
                    _arc_points(
                        vertex,
                        end_prev,
                        start_next,
                        radius,
                        segments,
                        1.0 if turn > 0 else -1.0,
                    )
                )
            elif style == "miter":
                hit = _line_intersection(e0, e1)
                limit = max(1.0, float(miter_limit)) * radius
                if hit is not None and dist(vertex, hit) <= limit + 1e-9:
                    out.append(hit)
                else:
                    warnings.append(
                        {
                            "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                            "severity": "warning",
                            "message": (
                                f"Miter at vertex {i} exceeds the limit "
                                f"{miter_limit:.2f}x; bevel used"
                            ),
                            "point_index": i,
                            "details": {"miter_limit": miter_limit, "distance_mm": direction},
                        }
                    )
                    out.append(end_prev)
                    out.append(start_next)
            else:  # bevel
                out.append(end_prev)
                out.append(start_next)
        else:
            # Edges converge: intersect them to keep a sharp inner corner.
            hit = _line_intersection(e0, e1)
            if hit is None:
                out.append(end_prev)
                out.append(start_next)
            else:
                out.append(hit)

    if not closed:
        out.append(edges[-1][1])
    elif out:
        # The loop above closes the join chain; make sure the polyline starts
        # with a clean copy of the first join point.
        out = dedupe(out, True)

    if original_reversed:
        out.reverse()

    if closed and len(out) >= 3:
        signed_before = signed_area(cleaned)
        signed_after = signed_area(out)
        area_before = abs(signed_before)
        area_after = abs(signed_after)
        if signed_before * signed_after < 0.0:
            warnings.append(
                {
                    "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    "severity": "warning",
                    "message": (
                        f"Offset {direction:.4f} mm inverted the contour; "
                        "reduce the distance"
                    ),
                    "details": {"distance_mm": direction},
                }
            )
        elif area_after <= 1e-12 or (area_before > 0 and area_after < area_before * 1e-6):
            warnings.append(
                {
                    "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    "severity": "warning",
                    "message": (
                        f"Offset {direction:.4f} mm collapsed the contour "
                        f"(area {area_before:.4f} -> {area_after:.4f} mm^2)"
                    ),
                    "details": {"distance_mm": direction},
                }
            )
        elif count_self_intersections(out, True):
            warnings.append(
                {
                    "code": ErrorCode.E_GEOM_SELF_INTERSECTION,
                    "severity": "warning",
                    "message": (
                        f"Offset {direction:.4f} mm produced a self-intersecting contour; "
                        "reduce the distance or the material thickness"
                    ),
                    "details": {"distance_mm": direction},
                }
            )

    if len(out) < (3 if closed else 2):
        warnings.append(
            {
                "code": ErrorCode.E_GEOM_DEGENERATE,
                "severity": "warning",
                "message": "Offset removed too many points; the original contour is kept",
                "details": {"distance_mm": direction},
            }
        )
        return list(points), warnings
    return out, warnings
