from __future__ import annotations

import math

from ...protocol.errors import DomainError
from ...protocol.geometry import (
    contour_inside,
    dedupe,
    dist,
    point_in_polygon,
    signed_area,
)
from ...protocol.types import (
    Contour,
    ContourRole,
    Diagnostic,
    ErrorCode,
    MaterialProfile,
    RequestOptions,
    Severity,
    Slice,
)


def _reverse(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return list(reversed(points))


def _area_of(points: list[tuple[float, float]]) -> float:
    return abs(signed_area(points))


def normalize_slice(
    source: Slice,
    material: MaterialProfile,
    options: RequestOptions,
    diagnostics: list[Diagnostic] | None = None,
) -> Slice:
    """Bring a slice to the contract invariants.

    * finite coordinates, no consecutive duplicates;
    * closed contours do not repeat the first point;
    * nesting via even-odd containment;
    * outer loops CCW, holes CW (when ``normalize_winding`` is enabled).
    """
    diagnostics = diagnostics if diagnostics is not None else []
    out = source.clone()
    min_seg = max(1e-6, material.min_segment_mm * 1e-3)

    seen_ids: set[str] = set()
    closed_contours: list[Contour] = []
    for contour in out.contours:
        if contour.id in seen_ids:
            raise DomainError(
                ErrorCode.E_SCHEMA,
                f"Duplicate contour id {contour.id!r}",
                slice_id=out.id,
                contour_id=contour.id,
            )
        seen_ids.add(contour.id)

        pts = []
        for p in contour.points:
            if not (math.isfinite(p[0]) and math.isfinite(p[1])):
                raise DomainError(
                    ErrorCode.E_NON_FINITE,
                    "Contour contains NaN or Infinity",
                    slice_id=out.id,
                    contour_id=contour.id,
                )
            pts.append((float(p[0]), float(p[1])))
        cleaned = dedupe(pts, contour.closed, tol=min_seg)
        if cleaned != pts:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.INFO,
                    code=ErrorCode.E_GEOM_DEGENERATE,
                    message="Removed duplicate points during normalization",
                    stage="normalize",
                    slice_id=out.id,
                    contour_id=contour.id,
                )
            )
        contour.points = cleaned
        if contour.segment_tags is not None and len(contour.segment_tags) != (
            len(cleaned) if contour.closed else max(0, len(cleaned) - 1)
        ):
            contour.segment_tags = None

        needed = 3 if contour.closed else 2
        if len(contour.points) < needed:
            raise DomainError(
                ErrorCode.E_GEOM_DEGENERATE,
                f"Contour needs at least {needed} points, got {len(contour.points)}",
                slice_id=out.id,
                contour_id=contour.id,
            )
        if contour.closed:
            area = signed_area(contour.points)
            if abs(area) <= 1e-12:
                raise DomainError(
                    ErrorCode.E_GEOM_DEGENERATE,
                    "Closed contour has zero area",
                    slice_id=out.id,
                    contour_id=contour.id,
                )
            closed_contours.append(contour)

    # Parent/child relationships: smallest containing loop wins.
    if len(closed_contours) >= 2:
        parent: dict[str, str | None] = {}
        for inner in closed_contours:
            best: Contour | None = None
            for outer in closed_contours:
                if outer is inner:
                    continue
                if not contour_inside(inner.points, outer.points):
                    continue
                if best is None or _area_of(outer.points) < _area_of(best.points):
                    best = outer
            parent[inner.id] = best.id if best else None

        # Depth via parent chain; guard against malformed/cyclic input.
        def depth(contour_id: str) -> int:
            d = 0
            cur = parent.get(contour_id)
            guard = 0
            while cur is not None and guard < len(closed_contours) + 1:
                d += 1
                cur = parent.get(cur)
                guard += 1
            return d

        for c in closed_contours:
            c.parent_id = parent.get(c.id)
            if options.normalize_winding and c.role == ContourRole.CUT:
                area = signed_area(c.points)
                want_ccw = depth(c.id) % 2 == 0
                if (want_ccw and area < 0) or ((not want_ccw) and area > 0):
                    c.points = _reverse(c.points)
                    c.segment_tags = None
    else:
        for c in closed_contours:
            if c.parent_id:
                c.parent_id = None
            if options.normalize_winding and c.role == ContourRole.CUT and signed_area(c.points) < 0:
                c.points = _reverse(c.points)
                c.segment_tags = None

    # Mark the common outer/hole case with tags, but never overwrite user tags.
    for c in closed_contours:
        if c.role == ContourRole.CUT and not c.tags:
            c.tags = ["hole"] if c.parent_id else ["outer"]

    return out


def classify_point(slice_: Slice, point: tuple[float, float]) -> Contour | None:
    """Return the smallest closed contour containing ``point``."""
    best: Contour | None = None
    best_area = float("inf")
    for c in slice_.contours:
        if not c.closed:
            continue
        if point_in_polygon(point, c.points):
            a = _area_of(c.points)
            if a < best_area:
                best = c
                best_area = a
    return best
