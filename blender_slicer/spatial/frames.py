"""Coordinate Manager: mapping between world 3D and a slice-local 2D plane.

The engine never sees these objects; it receives 2D millimetres plus an opaque
``frame_id``.  The frame owns the 3D <-> 2D conversion, the millimetre scale and
the orientation of the slice plane, so every host (Blender, Unreal, Qt) can
describe its planes the same way.
"""

from __future__ import annotations

import math

from ..protocol.units import Point2, Vec3
from .vectors import v3_cross, v3_dot, v3_length, v3_mul, v3_sub, v3_unit


def _fallback_hint(normal: Vec3) -> Vec3:
    axis = max(range(3), key=lambda i: abs(normal[i]))
    if axis == 0:
        return (0.0, 1.0, 0.0)
    if axis == 1:
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
    projected = v3_sub(u_hint, v3_mul(n, v3_dot(u_hint, n)))
    if v3_length(projected) <= 1e-9:
        hint = _fallback_hint(n)
        projected = v3_sub(hint, v3_mul(n, v3_dot(hint, n)))
    u = v3_unit(projected)
    v = v3_unit(v3_cross(n, u))
    return CoordinateFrame(id=frame_id, origin=origin, u=u, v=v, unit_scale_mm=unit_scale_mm)


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

    def plane_offset_mm(self, p: Vec3) -> float:
        """Signed distance of a world point from the slice plane."""

        return v3_dot(v3_sub(p, self.origin), self.normal) * self.unit_scale_mm

    def verify_roundtrip(self, points: list[Point2], tolerance_mm: float = 1e-6) -> float:
        """Return the worst 2D -> 3D -> 2D error in millimetres."""

        worst = 0.0
        for point in points:
            back = self.to_2d(self.to_3d(point))
            error = math.hypot(back[0] - point[0], back[1] - point[1])
            worst = max(worst, error)
        return worst

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"CoordinateFrame(id={self.id!r}, scale={self.unit_scale_mm})"


class FrameStore:
    """Frames owned by the adapter's runtime state."""

    def __init__(self) -> None:
        self._frames: dict[str, CoordinateFrame] = {}

    def put(self, frame: CoordinateFrame) -> None:
        self._frames[frame.id] = frame

    def update(self, frames: dict[str, CoordinateFrame]) -> None:
        self._frames.update(frames)

    def get(self, frame_id: str | None) -> CoordinateFrame | None:
        if not frame_id:
            return None
        return self._frames.get(frame_id)

    def items(self):
        return self._frames.items()

    def values(self):
        return self._frames.values()

    def ids(self) -> tuple[str, ...]:
        return tuple(self._frames)

    def clear(self) -> None:
        self._frames.clear()

    def __len__(self) -> int:
        return len(self._frames)

    def __bool__(self) -> bool:
        return bool(self._frames)

    def __contains__(self, frame_id: object) -> bool:
        return frame_id in self._frames
