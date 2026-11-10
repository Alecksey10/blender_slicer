"""Contact analysis between slices of different cutting passes.

Welding and assembly need to know where two cuts meet (or come close).  Slice
geometry is stored in local 2D frames, so this module lifts each contour back
to 3D through its ``CoordinateFrame`` and measures segment-to-segment distance.
The result is host independent: a list of contact points with both sides, the
distance and the midpoint to visualise.

Contacts are computed between *layers* (e.g. the X pass and the Z pass) and,
optionally, between neighbouring slices of the same layer.  When two contours
really cross, **every** intersection point is reported (deduplicated); when
they only come close, the single closest pair is reported, so a parallel pass
does not flood the viewport with redundant points.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Iterable, Protocol

from ..protocol.shapes import Slice
from ..protocol.units import Point2, Vec3
from .frames import CoordinateFrame
from .vectors import v3_add, v3_dist, v3_dot, v3_lerp, v3_mul, v3_sub

#: Below this distance two segments are considered to intersect.
INTERSECTION_EPS_MM = 1e-6

#: Dense contours are sampled so contact search stays interactive.
MAX_SEGMENTS_PER_CONTOUR = 160

#: Default cap for one request; the adapter can render fewer.
DEFAULT_MAX_CONTACTS = 2000


class LayerGeometry(Protocol):
    """Everything contact analysis needs from a layer."""

    id: str
    slices: list[Slice]
    frames: dict[str, CoordinateFrame]


@dataclass(frozen=True)
class ContactPoint:
    layer_a: str
    slice_a: str
    contour_a: str
    layer_b: str
    slice_b: str
    contour_b: str
    point_a: Vec3
    point_b: Vec3
    position: Vec3
    distance_mm: float
    #: ``intersection`` for a real crossing, ``near`` for a gap contact.
    kind: str = "near"

    def as_dict(self) -> dict:
        return {
            "layer_a": self.layer_a,
            "slice_a": self.slice_a,
            "contour_a": self.contour_a,
            "layer_b": self.layer_b,
            "slice_b": self.slice_b,
            "contour_b": self.contour_b,
            "point_a": list(self.point_a),
            "point_b": list(self.point_b),
            "position": list(self.position),
            "distance_mm": self.distance_mm,
            "kind": self.kind,
        }


def _closest_on_segments(
    p1: Vec3, q1: Vec3, p2: Vec3, q2: Vec3
) -> tuple[float, Vec3, Vec3]:
    """Closest points of two 3D segments (Ericson, Real-Time Collision Detection)."""

    d1 = v3_sub(q1, p1)
    d2 = v3_sub(q2, p2)
    r = v3_sub(p1, p2)
    a = v3_dot(d1, d1)
    e = v3_dot(d2, d2)
    f = v3_dot(d2, r)
    eps = 1e-15

    if a <= eps and e <= eps:
        return v3_dist(p1, p2), p1, p2
    if a <= eps:
        s = 0.0
        t = min(1.0, max(0.0, f / e))
    else:
        c = v3_dot(d1, r)
        if e <= eps:
            t = 0.0
            s = min(1.0, max(0.0, -c / a))
        else:
            b = v3_dot(d1, d2)
            denominator = a * e - b * b
            if denominator > eps:
                s = min(1.0, max(0.0, (b * f - c * e) / denominator))
            else:
                s = 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = min(1.0, max(0.0, -c / a))
            elif t > 1.0:
                t = 1.0
                s = min(1.0, max(0.0, (b - c) / a))
    point1 = v3_add(p1, v3_mul(d1, s))
    point2 = v3_add(p2, v3_mul(d2, t))
    return v3_dist(point1, point2), point1, point2


def _segments(points: list[Point2], closed: bool) -> Iterable[tuple[Point2, Point2]]:
    count = len(points) if closed else len(points) - 1
    if count <= 0:
        return
    step = max(1, count // MAX_SEGMENTS_PER_CONTOUR)
    for i in range(0, count, step):
        yield points[i], points[(i + 1) % len(points)]


def _world_points(slice_: Slice, frame: CoordinateFrame) -> list[tuple[str, list[Vec3], bool]]:
    out: list[tuple[str, list[Vec3], bool]] = []
    for contour in slice_.contours:
        if len(contour.points) < 2:
            continue
        out.append((contour.id, [frame.to_3d(p) for p in contour.points], contour.closed))
    return out


def _slice_bounds(points: list[Vec3]) -> tuple[Vec3, Vec3]:
    return (
        (min(p[0] for p in points), min(p[1] for p in points), min(p[2] for p in points)),
        (max(p[0] for p in points), max(p[1] for p in points), max(p[2] for p in points)),
    )


def _bounds_overlap(a: tuple[Vec3, Vec3], b: tuple[Vec3, Vec3], gap: float) -> bool:
    for axis in range(3):
        if a[0][axis] - gap > b[1][axis] or b[0][axis] - gap > a[1][axis]:
            return False
    return True


def _pair_contacts(
    pts_a: list[Vec3],
    closed_a: bool,
    pts_b: list[Vec3],
    closed_b: bool,
    gap_mm: float,
    merge_mm: float,
    max_per_pair: int,
) -> list[tuple[float, Vec3, Vec3]]:
    """All intersections of two contours, or the closest pair if they miss."""

    candidates: list[tuple[float, Vec3, Vec3]] = []
    for a1, a2 in _segments(pts_a, closed_a):
        for b1, b2 in _segments(pts_b, closed_b):
            distance, point_a, point_b = _closest_on_segments(a1, a2, b1, b2)
            if distance <= gap_mm + 1e-12:
                candidates.append((distance, point_a, point_b))
    if not candidates:
        return []

    intersections = [c for c in candidates if c[0] <= INTERSECTION_EPS_MM]
    chosen = intersections if intersections else [min(candidates, key=lambda c: c[0])]
    chosen.sort(key=lambda c: c[0])

    kept: list[tuple[Vec3, tuple[float, Vec3, Vec3]]] = []
    for candidate in chosen:
        position = v3_lerp(candidate[1], candidate[2], 0.5)
        if any(v3_dist(position, other) < merge_mm for other, _c in kept):
            continue
        kept.append((position, candidate))
        if len(kept) >= max_per_pair:
            break
    return [candidate for _position, candidate in kept]


def _contacts_between_layers(
    layer_a: LayerGeometry,
    layer_b: LayerGeometry,
    gap_mm: float,
    *,
    same_layer: bool = False,
    merge_mm: float = 0.25,
    max_per_pair: int = 64,
) -> list[ContactPoint]:
    contacts: list[ContactPoint] = []
    for index_a, slice_a in enumerate(layer_a.slices):
        frame_a = layer_a.frames.get(slice_a.frame_id or "")
        if frame_a is None:
            continue
        contours_a = _world_points(slice_a, frame_a)
        if not contours_a:
            continue
        bounds_a = _slice_bounds([p for _cid, pts, _cl in contours_a for p in pts])
        for index_b, slice_b in enumerate(layer_b.slices):
            if same_layer and index_b <= index_a:
                # Same pass: a slice must not be compared with itself and each
                # unordered pair is visited once.
                continue
            frame_b = layer_b.frames.get(slice_b.frame_id or "")
            if frame_b is None:
                continue
            contours_b = _world_points(slice_b, frame_b)
            if not contours_b:
                continue
            bounds_b = _slice_bounds([p for _cid, pts, _cl in contours_b for p in pts])
            if not _bounds_overlap(bounds_a, bounds_b, gap_mm):
                continue
            for cid_a, pts_a, closed_a in contours_a:
                bounds_pair_a = _slice_bounds(pts_a)
                for cid_b, pts_b, closed_b in contours_b:
                    if not _bounds_overlap(bounds_pair_a, _slice_bounds(pts_b), gap_mm):
                        continue
                    for distance, point_a, point_b in _pair_contacts(
                        pts_a,
                        closed_a,
                        pts_b,
                        closed_b,
                        gap_mm,
                        merge_mm,
                        max_per_pair,
                    ):
                        contacts.append(
                            ContactPoint(
                                layer_a=layer_a.id,
                                slice_a=slice_a.id,
                                contour_a=cid_a,
                                layer_b=layer_b.id,
                                slice_b=slice_b.id,
                                contour_b=cid_b,
                                point_a=point_a,
                                point_b=point_b,
                                position=v3_lerp(point_a, point_b, 0.5),
                                distance_mm=distance,
                                kind=(
                                    "intersection"
                                    if distance <= INTERSECTION_EPS_MM
                                    else "near"
                                ),
                            )
                        )
    return contacts


def find_contacts(
    layers: Iterable[LayerGeometry],
    gap_mm: float = 1.0,
    max_contacts: int = DEFAULT_MAX_CONTACTS,
    include_same_layer: bool = False,
    merge_mm: float = 0.25,
    max_per_pair: int = 64,
) -> list[ContactPoint]:
    """Return contacts closer than ``gap_mm``, sorted by distance.

    ``merge_mm`` collapses points that describe the same physical contact;
    ``max_per_pair`` limits how many distinct crossings one pair of contours
    may contribute.
    """

    layers = [layer for layer in layers if layer.slices]
    if len(layers) < 2 and not include_same_layer:
        return []

    pairs: list[tuple[LayerGeometry, LayerGeometry, bool]] = []
    for a, b in itertools.combinations(layers, 2):
        pairs.append((a, b, False))
    if include_same_layer:
        pairs.extend((layer, layer, True) for layer in layers)

    found: list[ContactPoint] = []
    for layer_a, layer_b, same in pairs:
        found.extend(
            _contacts_between_layers(
                layer_a,
                layer_b,
                max(0.0, gap_mm),
                same_layer=same,
                merge_mm=max(0.0, merge_mm),
                max_per_pair=max(1, int(max_per_pair)),
            )
        )

    found.sort(key=lambda c: (c.distance_mm, c.layer_a, c.slice_a, c.layer_b, c.slice_b))
    if max_contacts > 0:
        found = found[:max_contacts]
    return found
