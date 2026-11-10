"""Section shrink: scale a contour toward its own centre.

Wide tubes and wires sometimes need narrower cross-sections while the part must
stay smooth and bendable.  Shrinking is a pure 2D operation, so it belongs to
the engine; the adapter decides *how much* each slice shrinks (per-slice ratio
in ``Slice.metadata``), exactly like the cut offset policy.
"""

from __future__ import annotations

from .geometry import signed_area
from .units import Point2


def bounds_center(points: list[Point2]) -> Point2:
    if not points:
        return (0.0, 0.0)
    return (
        (min(p[0] for p in points) + max(p[0] for p in points)) * 0.5,
        (min(p[1] for p in points) + max(p[1] for p in points)) * 0.5,
    )


def area_centroid(points: list[Point2]) -> Point2:
    """Area centroid for a closed contour, mean of vertices as a fallback."""

    if not points:
        return (0.0, 0.0)
    area = signed_area(points)
    if abs(area) <= 1e-12 or len(points) < 3:
        return (
            sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points),
        )
    cx = 0.0
    cy = 0.0
    count = len(points)
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % count]
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    factor = 1.0 / (6.0 * area)
    return (cx * factor, cy * factor)


def anchor_point(points: list[Point2], anchor: str = "centroid") -> Point2:
    if (anchor or "").lower() == "bounds":
        return bounds_center(points)
    return area_centroid(points)


def shrink_points(
    points: list[Point2],
    ratio: float,
    *,
    anchor: str = "centroid",
    closed: bool = True,
) -> list[Point2]:
    """Scale ``points`` toward an anchor by ``ratio`` (1.0 keeps them)."""

    if not points:
        return []
    factor = min(1.0, max(0.0, float(ratio)))
    if abs(factor - 1.0) <= 1e-12:
        return list(points)
    cx, cy = anchor_point(points, anchor if closed else "centroid")
    return [(cx + (x - cx) * factor, cy + (y - cy) * factor) for x, y in points]
