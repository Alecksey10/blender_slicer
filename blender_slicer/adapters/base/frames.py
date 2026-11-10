"""Coordinate frames for the 3D <-> 2D boundary.

The engine never sees these objects; it only receives the resulting 2D points
and an opaque ``frame_id``.  This module is intentionally pure Python so it can
be tested outside Blender.
"""

from __future__ import annotations

import math

Vec3 = tuple[float, float, float]
Point2 = tuple[float, float]


def v3_add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v3_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v3_mul(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def v3_dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v3_cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def v3_length(a: Vec3) -> float:
    return math.sqrt(v3_dot(a, a))


def v3_unit(a: Vec3) -> Vec3:
    n = v3_length(a)
    if n <= 1e-15:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _fallback_hint(normal: Vec3) -> Vec3:
    ax = max(range(3), key=lambda i: abs(normal[i]))
    if ax == 0:
        return (0.0, 1.0, 0.0)
    if ax == 1:
        return (0.0, 0.0, 1.0)
    return (1.0, 0.0, 0.0)


def make_frame(
    normal: Vec3,
    u_hint: Vec3,
    origin: Vec3,
    unit_scale_mm: float,
    frame_id: str,
) -> "CoordinateFrame":
    n = v3_unit(normal)
    if v3_length(n) <= 1e-12:
        n = (0.0, 0.0, 1.0)
    hint = u_hint
    projected = v3_sub(hint, v3_mul(n, v3_dot(hint, n)))
    if v3_length(projected) <= 1e-9:
        hint = _fallback_hint(n)
        projected = v3_sub(hint, v3_mul(n, v3_dot(hint, n)))
    u = v3_unit(projected)
    v = v3_unit(v3_cross(n, u))
    return CoordinateFrame(
        id=frame_id,
        origin=origin,
        u=u,
        v=v,
        unit_scale_mm=unit_scale_mm,
    )


class CoordinateFrame:
    __slots__ = ("id", "origin", "u", "v", "unit_scale_mm")

    def __init__(
        self,
        id: str,
        origin: Vec3,
        u: Vec3,
        v: Vec3,
        unit_scale_mm: float,
    ) -> None:
        self.id = id
        self.origin = origin
        self.u = u
        self.v = v
        self.unit_scale_mm = unit_scale_mm

    @property
    def normal(self) -> Vec3:
        return v3_cross(self.u, self.v)

    def to_2d(self, p: Vec3) -> Point2:
        d = v3_sub(p, self.origin)
        scale = self.unit_scale_mm
        return (v3_dot(d, self.u) * scale, v3_dot(d, self.v) * scale)

    def to_3d(self, q: Point2) -> Vec3:
        scale = self.unit_scale_mm
        x = q[0] / scale
        y = q[1] / scale
        return (
            self.origin[0] + x * self.u[0] + y * self.v[0],
            self.origin[1] + x * self.u[1] + y * self.v[1],
            self.origin[2] + x * self.u[2] + y * self.v[2],
        )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"CoordinateFrame(id={self.id!r}, scale={self.unit_scale_mm})"
