"""Units and numeric primitives shared by every layer.

All engine coordinates are millimetres and all angles in the public contract are
degrees; the geometry kernel converts to radians internally.  Nothing in this
module knows about a host.
"""

from __future__ import annotations

import math

Point2 = tuple[float, float]
Vec3 = tuple[float, float, float]

UNITS_MM = "mm"


def is_finite_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def is_finite_point(point: tuple[float, ...]) -> bool:
    return len(point) >= 2 and is_finite_number(point[0]) and is_finite_number(point[1])


def clamp(value: float, low: float, high: float) -> float:
    if low > high:
        low, high = high, low
    return low if value < low else high if value > high else value


def nearly_zero(value: float, eps: float = 1e-12) -> bool:
    return abs(value) <= eps
