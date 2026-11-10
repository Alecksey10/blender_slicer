"""Geometric invariants checked before and after the pipeline."""

from __future__ import annotations

from ...protocol.diagnostics import Diagnostic, ErrorCode, Severity, diagnostic
from ...protocol.geometry import count_self_intersections, dist, signed_area
from ...protocol.shapes import Contour, Slice
from ...protocol.request import ProcessingRequest

SELF_INTERSECTION_LIMIT = 5000


def contour_invariants(
    contour: Contour, slice_id: str, *, max_points: int | None = None
) -> list[Diagnostic]:
    """Structural checks of a single contour (input and output)."""

    out: list[Diagnostic] = []
    needed = 3 if contour.closed else 2
    if len(contour.points) < needed:
        out.append(
            diagnostic(
                Severity.ERROR,
                ErrorCode.E_GEOM_DEGENERATE,
                "Contour has too few points",
                slice_id=slice_id,
                contour_id=contour.id,
            )
        )
        return out
    if max_points is not None and len(contour.points) > max_points:
        out.append(
            diagnostic(
                Severity.ERROR,
                ErrorCode.E_LIMIT_EXCEEDED,
                "Contour exceeds max_points_per_contour",
                slice_id=slice_id,
                contour_id=contour.id,
                details={"points": len(contour.points)},
            )
        )
    for index, point in enumerate(contour.points):
        if not (is_finite(point[0]) and is_finite(point[1])):
            out.append(
                diagnostic(
                    Severity.ERROR,
                    ErrorCode.E_NON_FINITE,
                    "Non-finite coordinate",
                    slice_id=slice_id,
                    contour_id=contour.id,
                    point_index=index,
                )
            )
            break
    if contour.closed and abs(signed_area(contour.points)) <= 1e-12:
        out.append(
            diagnostic(
                Severity.ERROR,
                ErrorCode.E_GEOM_DEGENERATE,
                "Closed contour has zero area",
                slice_id=slice_id,
                contour_id=contour.id,
            )
        )
    return out


def final_invariants(slice_: Slice, request: ProcessingRequest) -> list[Diagnostic]:
    """Checks after the user pipeline: limits, short segments, self-crossings."""

    from math import isfinite

    out: list[Diagnostic] = []
    min_segment = request.material.min_segment_mm
    check_self = bool(request.metadata.get("check_self_intersections", True))
    for contour in slice_.contours:
        out.extend(contour_invariants(contour, slice_.id))
        count = len(contour.points)
        if count < 2:
            continue
        for i in range(count if contour.closed else count - 1):
            segment = dist(contour.points[i], contour.points[(i + 1) % count])
            if segment < min_segment * 1e-3:
                out.append(
                    diagnostic(
                        Severity.WARNING,
                        ErrorCode.E_GEOM_DEGENERATE,
                        f"Segment shorter than {min_segment:.4f} mm",
                        stage="validate",
                        slice_id=slice_.id,
                        contour_id=contour.id,
                        point_index=i,
                        details={"length_mm": segment},
                    )
                )
                break
        if check_self and count <= SELF_INTERSECTION_LIMIT:
            intersections = count_self_intersections(contour.points, contour.closed)
            if intersections:
                out.append(
                    diagnostic(
                        Severity.ERROR,
                        ErrorCode.E_GEOM_SELF_INTERSECTION,
                        f"Contour has {intersections} self-intersection(s)",
                        stage="validate",
                        slice_id=slice_.id,
                        contour_id=contour.id,
                        details={"count": intersections},
                    )
                )
    return out


def is_finite(value: float) -> bool:
    from math import isfinite

    return isfinite(float(value))
