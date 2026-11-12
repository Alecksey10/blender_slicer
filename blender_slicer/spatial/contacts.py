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

A processed layer is analysed through its *result* curves: the result is what
the user sees and cuts, while the source slices are only the input of the
engine.  Using the source for contacts put the markers on geometry that was no
longer displayed.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Iterable, Protocol

from ..protocol.shapes import Slice
from ..protocol.units import Point2, Vec3
from .frames import CoordinateFrame
from .vectors import v3_add, v3_dist, v3_dot, v3_lerp, v3_mul, v3_sub

#: Below this distance two segments are considered to intersect.
INTERSECTION_EPS_MM = 1e-6

#: Dense contours are thinned before the search stays interactive.  Thinning
#: keeps the outline (Douglas-Peucker) instead of dropping segments.
MAX_SEGMENTS_PER_CONTOUR = 160

#: How far a thinned chord may stray from the points it replaces.
CONTACT_SIMPLIFY_MM = 0.01

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


def _point_segment_distance(p: Vec3, a: Vec3, b: Vec3) -> float:
    ab = v3_sub(b, a)
    length2 = v3_dot(ab, ab)
    if length2 <= 1e-18:
        return v3_dist(p, a)
    t = v3_dot(v3_sub(p, a), ab) / length2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return v3_dist(p, v3_add(a, v3_mul(ab, t)))


def _dp_chain(points: list[Vec3], chain: list[int], tolerance: float) -> list[int]:
    """Douglas-Peucker over a chain of point indices."""

    keep = [False] * len(chain)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(chain) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a = points[chain[i]]
        b = points[chain[j]]
        worst = tolerance
        worst_k = -1
        for k in range(i + 1, j):
            distance = _point_segment_distance(points[chain[k]], a, b)
            if distance > worst:
                worst = distance
                worst_k = k
        if worst_k >= 0:
            keep[worst_k] = True
            stack.append((i, worst_k))
            stack.append((worst_k, j))
    return [chain[k] for k in range(len(chain)) if keep[k]]


def _simplify_indices(points: list[Vec3], closed: bool, tolerance: float) -> list[int]:
    """Indices of the points that describe the contour within ``tolerance``."""

    n = len(points)
    if n <= 3 or tolerance <= 0.0:
        return list(range(n))
    if not closed:
        return _dp_chain(points, list(range(n)), tolerance)
    # Split the loop into two arcs so the result does not depend on the start.
    far = max(range(1, n), key=lambda i: v3_dist(points[0], points[i]))
    if far == 0:
        return list(range(n))
    first = _dp_chain(points, list(range(0, far + 1)), tolerance)
    second = _dp_chain(points, list(range(far, n)) + [0], tolerance)
    return sorted(set(first) | set(second))


def _chain_error(points: list[Vec3], i: int, j: int, a: Vec3, b: Vec3) -> float:
    """Largest distance of the points a chord replaces from the chord itself."""

    n = len(points)
    if j <= i:
        j += n
    worst = 0.0
    for k in range(i + 1, j):
        distance = _point_segment_distance(points[k % n], a, b)
        if distance > worst:
            worst = distance
    return worst


def _chords(
    points: list[Vec3],
    closed: bool,
    max_segments: int = MAX_SEGMENTS_PER_CONTOUR,
    tolerance: float = CONTACT_SIMPLIFY_MM,
) -> list[tuple[Vec3, Vec3, float]]:
    """Straight chords that cover the **whole** contour, with a shape error each.

    The search used to sample ``range(0, count, step)`` and therefore tested
    only every n-th segment: with the dense contours the engine produces (150
    to 2500 points) that left most of the outline unchecked, so crossings lying
    in the skipped part were never reported.  Thinning by Douglas-Peucker keeps
    the outline and returns, per chord, how far it may sit from the real curve,
    which is what the intersection test needs to stay honest.
    """

    count = len(points) if closed else len(points) - 1
    if count <= 0:
        return []

    if len(points) <= max_segments:
        # Nothing to gain: keep the geometry exact.
        kept = list(range(len(points)))
    else:
        kept = _simplify_indices(points, closed, tolerance)
        if len(kept) > max_segments:
            stride = int(math.ceil(len(kept) / float(max_segments)))
            kept = kept[::stride]

    pairs = list(zip(kept, kept[1:]))
    if closed:
        pairs.append((kept[-1], kept[0]))

    chords: list[tuple[Vec3, Vec3, float]] = []
    n = len(points)
    for i, j in pairs:
        a = points[i]
        b = points[j]
        if j == i + 1 or (closed and i == n - 1 and j == 0):
            chords.append((a, b, 0.0))
        else:
            chords.append((a, b, _chain_error(points, i, j, a, b)))
    return chords


def _contours_of(layer: LayerGeometry) -> Iterable[tuple[int, str, str, list]]:
    """Yield ``(index, slice_id, frame_id, contours)`` for the geometry to use.

    A processed layer contributes its **result** curves; the source slices are
    kept only as a fallback so contacts work before (or without) processing.
    """

    result = getattr(layer, "result", None)
    if result is not None:
        for index, slice_result in enumerate(result.slices):
            yield (
                index,
                slice_result.slice_id,
                slice_result.frame_id or "",
                [(c.id, c.points, c.closed) for c in slice_result.contours],
            )
        return
    for index, slice_ in enumerate(layer.slices):
        yield (
            index,
            slice_.id,
            slice_.frame_id or "",
            [(c.id, c.points, c.closed) for c in slice_.contours],
        )


def _world_contours(contours, frame: CoordinateFrame) -> list[tuple[str, list[Vec3], bool, list]]:
    out: list[tuple[str, list[Vec3], bool, list]] = []
    for contour_id, points, closed in contours:
        if len(points) < 2:
            continue
        world = [frame.to_3d(p) for p in points]
        out.append((contour_id, world, bool(closed), _chords(world, bool(closed))))
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
    chords_a: list[tuple[Vec3, Vec3, float]],
    chords_b: list[tuple[Vec3, Vec3, float]],
    gap_mm: float,
    merge_mm: float,
    max_per_pair: int,
) -> list[tuple[float, Vec3, Vec3]]:
    """All intersections of two contours, or the closest pair if they miss."""

    candidates: list[tuple[float, Vec3, Vec3, bool]] = []
    for a1, a2, error_a in chords_a:
        for b1, b2, error_b in chords_b:
            distance, point_a, point_b = _closest_on_segments(a1, a2, b1, b2)
            if distance <= gap_mm + 1e-12:
                # A thinned chord stands for a stretch of the real curve, so two
                # contours that touch can still measure a few microns apart:
                # the chord error is the honest tolerance of "these lines cross".
                crosses = distance <= max(INTERSECTION_EPS_MM, error_a + error_b)
                candidates.append((distance, point_a, point_b, crosses))
    if not candidates:
        return []

    intersections = [c for c in candidates if c[3]]
    chosen = intersections if intersections else [min(candidates, key=lambda c: c[0])]
    chosen.sort(key=lambda c: c[0])

    kept: list[tuple[Vec3, tuple[float, Vec3, Vec3, bool]]] = []
    for candidate in chosen:
        position = v3_lerp(candidate[1], candidate[2], 0.5)
        if any(v3_dist(position, other) < merge_mm for other, _c in kept):
            continue
        kept.append((position, candidate))
        if len(kept) >= max_per_pair:
            break
    return [candidate for _position, candidate in kept]


def _prepare_slices(layer: LayerGeometry) -> list[tuple[int, str, list, tuple[Vec3, Vec3]]]:
    """Lift every drawable slice of a layer to 3D once, ready for the search."""

    prepared: list[tuple[int, str, list, tuple[Vec3, Vec3]]] = []
    for index, slice_id, frame_id, contours in _contours_of(layer):
        frame = layer.frames.get(frame_id)
        if frame is None:
            continue
        world = _world_contours(contours, frame)
        if not world:
            continue
        bounds = _slice_bounds([p for _cid, pts, _closed, _chords_list in world for p in pts])
        prepared.append((index, slice_id, world, bounds))
    return prepared


def _contacts_between_layers(
    layer_a: LayerGeometry,
    layer_b: LayerGeometry,
    gap_mm: float,
    *,
    same_layer: bool = False,
    merge_mm: float = 0.25,
    max_per_pair: int = 64,
) -> list[ContactPoint]:
    prepared_a = _prepare_slices(layer_a)
    if not prepared_a:
        return []
    prepared_b = prepared_a if same_layer else _prepare_slices(layer_b)
    if not prepared_b:
        return []

    contacts: list[ContactPoint] = []
    for index_a, slice_id_a, contours_a, bounds_a in prepared_a:
        for index_b, slice_id_b, contours_b, bounds_b in prepared_b:
            if same_layer and index_b <= index_a:
                # A slice must not be compared with itself and each unordered
                # pair is visited once.
                continue
            if not _bounds_overlap(bounds_a, bounds_b, gap_mm):
                continue
            for cid_a, pts_a, closed_a, chords_a in contours_a:
                bounds_pair_a = _slice_bounds(pts_a)
                for cid_b, pts_b, closed_b, chords_b in contours_b:
                    if not _bounds_overlap(bounds_pair_a, _slice_bounds(pts_b), gap_mm):
                        continue
                    for distance, point_a, point_b, crosses in _pair_contacts(
                        chords_a,
                        chords_b,
                        gap_mm,
                        merge_mm,
                        max_per_pair,
                    ):
                        contacts.append(
                            ContactPoint(
                                layer_a=layer_a.id,
                                slice_a=slice_id_a,
                                contour_a=cid_a,
                                layer_b=layer_b.id,
                                slice_b=slice_id_b,
                                contour_b=cid_b,
                                point_a=point_a,
                                point_b=point_b,
                                position=v3_lerp(point_a, point_b, 0.5),
                                distance_mm=distance,
                                kind="intersection" if crosses else "near",
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

    layers = [layer for layer in layers if layer.slices or getattr(layer, "result", None)]
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
