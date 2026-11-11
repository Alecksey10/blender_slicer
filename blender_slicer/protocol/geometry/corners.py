"""Corner handling: collinear cleanup, fillets and tight-section trimming."""

from __future__ import annotations

import math

from ..errors import DomainError
from ..types import ErrorCode, Point2
from .core import (
    COLLINEAR_TOL_DEG,
    EPS,
    dedupe,
    dist,
    left_normal,
    signed_area,
    signed_turn,
    turn_angle,
    unit,
    v_add,
    v_mul,
    v_sub,
)
from .intersections import count_self_intersections


def collapse_collinear(
    points: list[Point2], closed: bool, tol_deg: float = COLLINEAR_TOL_DEG
) -> list[Point2]:
    """Drop interior vertices that do not change the polyline direction.

    Cross-sections of a triangle mesh contain points where a plane crosses a
    triangle diagonal or a coplanar split.  Those points are pure subdivision
    noise: keeping them makes the free room of a corner, and therefore the
    clamped fillet radius, depend on *where* the plane hits the triangulation
    instead of on the shape of the model.  Collapsing them makes identical
    cross-sections produce identical results.
    """

    n = len(points)
    if n < 3:
        return list(points)
    tolerance = math.radians(max(0.0, tol_deg))
    if closed:
        keep = [
            i
            for i in range(n)
            if turn_angle(points[(i - 1) % n], points[i], points[(i + 1) % n]) > tolerance
        ]
        if len(keep) < 3:
            return list(points)
        return [points[i] for i in keep]

    keep_open = [0]
    keep_open.extend(
        i for i in range(1, n - 1) if turn_angle(points[i - 1], points[i], points[i + 1]) > tolerance
    )
    keep_open.append(n - 1)
    if len(keep_open) < 3:
        # A straight polyline has no corners to protect; keep its points explicit
        # so the function only removes redundant points *inside* a shape.
        return list(points)
    return [points[i] for i in keep_open]


def fillet_corners(
    points: list[Point2],
    closed: bool,
    radius_mm: float,
    min_turn_deg: float,
    arc_segments: int,
    mode: str = "error",
    chord_tolerance_mm: float = 0.05,
    material_min_radius_mm: float | None = None,
) -> tuple[list[Point2], list[dict]]:
    """Replace sharp corners with tangent arcs.

    Returns (points, warnings).  ``mode`` is clamp|error|skip.
    """
    # Mesh triangulation adds collinear points on straight edges; they must not
    # consume the corner room, otherwise identical slices get different radii.
    points = collapse_collinear(dedupe(points, closed), closed)
    n = len(points)
    if n < 3 or radius_mm <= 0:
        return list(points), []
    min_turn = math.radians(max(0.0, min_turn_deg))
    warnings: list[dict] = []
    out: list[Point2] = []
    if not closed:
        out.append(points[0])

    indices = range(n) if closed else range(1, n - 1)
    for i in indices:
        prev = points[(i - 1) % n]
        cur = points[i]
        nxt = points[(i + 1) % n]
        signed = signed_turn(prev, cur, nxt)
        turn = abs(signed)
        if turn < min_turn or turn > math.pi - 1e-6:
            out.append(cur)
            continue

        tan_half = math.tan(turn * 0.5)
        len_prev = dist(prev, cur)
        len_next = dist(cur, nxt)
        if tan_half <= EPS or len_prev <= EPS or len_next <= EPS:
            out.append(cur)
            continue

        r_max = min(len_prev, len_next) * 0.5 / tan_half
        r = radius_mm
        if r_max <= 1e-9:
            if mode == "error":
                raise DomainError(
                    ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    f"Corner {i}: no room for fillet (available radius {r_max:.4f} mm)",
                    contour_id=None,
                    point_index=i,
                    details={"requested_radius_mm": radius_mm, "available_radius_mm": r_max},
                )
            out.append(cur)
            continue

        # A relative slack keeps corners that fit *exactly* from flipping
        # between clamp and no-clamp because of last-bit float noise.
        if r > r_max + max(1e-12, r_max * 1e-9):
            if mode == "error":
                raise DomainError(
                    ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    f"Corner {i}: requested radius {r:.4f} mm exceeds available {r_max:.4f} mm",
                    point_index=i,
                    details={"requested_radius_mm": radius_mm, "available_radius_mm": r_max},
                )
            if mode == "skip":
                out.append(cur)
                continue
            r = r_max
            warnings.append(
                {
                    "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    "severity": "warning",
                    "message": f"Corner {i}: radius clamped to {r:.4f} mm",
                    "point_index": i,
                    "details": {"requested_radius_mm": radius_mm, "available_radius_mm": r_max},
                }
            )

        if material_min_radius_mm is not None and r + 1e-9 < material_min_radius_mm:
            warnings.append(
                {
                    "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    "severity": "warning",
                    "message": (
                        f"Corner {i}: fillet radius {r:.4f} mm is below material "
                        f"minimum {material_min_radius_mm:.4f} mm"
                    ),
                    "point_index": i,
                    "details": {"radius_mm": r, "min_bend_radius_mm": material_min_radius_mm},
                }
            )

        d_in = unit(v_sub(cur, prev))
        d_out = unit(v_sub(nxt, cur))
        t = r * tan_half
        # Defensive clamp: the radius limit already guarantees this, but floating
        # point can put the tangent a hair beyond the segment midpoint.
        t = min(t, 0.5 * len_prev, 0.5 * len_next)
        if t < r * tan_half - 1e-9:
            r = t / tan_half
        p_start = v_sub(cur, v_mul(d_in, t))
        p_end = v_add(cur, v_mul(d_out, t))
        left = left_normal(d_in)
        center = v_add(p_start, v_mul(left, r)) if signed > 0 else v_sub(p_start, v_mul(left, r))

        a0 = math.atan2(p_start[1] - center[1], p_start[0] - center[0])
        a1 = math.atan2(p_end[1] - center[1], p_end[0] - center[0])
        sweep = a1 - a0
        if signed > 0:
            while sweep <= 0:
                sweep += 2 * math.pi
            while sweep > 2 * math.pi:
                sweep -= 2 * math.pi
        else:
            while sweep >= 0:
                sweep -= 2 * math.pi
            while sweep < -2 * math.pi:
                sweep += 2 * math.pi

        if chord_tolerance_mm > 0 and r > chord_tolerance_mm:
            cos_val = 1.0 - chord_tolerance_mm / r
            cos_val = max(-1.0, min(1.0, cos_val))
            step_angle = 2.0 * math.acos(cos_val)
            needed = max(1, int(math.ceil(abs(sweep) / max(step_angle, 1e-9))))
        else:
            needed = 1
        segments = max(1, min(64, max(int(arc_segments), needed)))

        arc = [p_start]
        for j in range(1, segments):
            a = a0 + sweep * j / segments
            arc.append((center[0] + r * math.cos(a), center[1] + r * math.sin(a)))
        arc.append(p_end)
        out.extend(arc)

    if not closed:
        out.append(points[-1])
    return dedupe(out, closed), warnings


def tight_corners(
    points: list[Point2],
    closed: bool,
    radius_mm: float,
    min_turn_deg: float = 20.0,
) -> list[tuple[int, float, float]]:
    """Corners where a fillet of ``radius_mm`` would have to be clamped.

    Returns ``(index, available_radius_mm, turn_deg)`` for each corner whose
    free room ``min(len_prev, len_next) * 0.5 / tan(turn / 2)`` is smaller than
    the requested radius.  Indices refer to the deduplicated contour with
    collinear vertices collapsed, which is the geometry the fillet sees.

    180-degree folds and almost straight vertices are not reported: no tangent
    arc exists there regardless of the radius.
    """

    if radius_mm <= EPS or len(points) < 3:
        return []
    pts = collapse_collinear(dedupe(points, closed), closed)
    n = len(pts)
    if n < 3:
        return []
    min_turn = math.radians(max(0.0, min_turn_deg))
    found: list[tuple[int, float, float]] = []
    indices = range(n) if closed else range(1, n - 1)
    for i in indices:
        prev = pts[(i - 1) % n]
        cur = pts[i]
        nxt = pts[(i + 1) % n]
        turn = abs(signed_turn(prev, cur, nxt))
        if turn < min_turn or turn > math.pi - 1e-6:
            continue
        tan_half = math.tan(turn * 0.5)
        len_prev = dist(prev, cur)
        len_next = dist(cur, nxt)
        if tan_half <= EPS or len_prev <= EPS or len_next <= EPS:
            continue
        available = min(len_prev, len_next) * 0.5 / tan_half
        if available + max(1e-12, available * 1e-9) < radius_mm:
            found.append((i, available, math.degrees(turn)))
    return found


def _tight_runs(bad: set[int], n: int, closed: bool) -> list[list[int]]:
    """Group vertex indices into contiguous runs (handles the loop seam)."""

    if not bad:
        return []
    if not closed:
        runs: list[list[int]] = []
        current = [min(bad)]
        for index in sorted(bad)[1:]:
            if index == current[-1] + 1:
                current.append(index)
            else:
                runs.append(current)
                current = [index]
        runs.append(current)
        return runs
    if len(bad) >= n:
        return [list(range(n))]
    start = next(i for i in range(n) if i not in bad)
    runs = []
    current = []
    for step in range(1, n + 1):
        index = (start + step) % n
        if index in bad:
            current.append(index)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def trim_tight_corners(
    points: list[Point2],
    closed: bool,
    radius_mm: float,
    min_turn_deg: float = 20.0,
    max_removed_ratio: float = 0.5,
    max_passes: int = 8,
) -> tuple[list[Point2], list[dict]]:
    """Cut away contour sections that cannot host the requested fillet radius.

    A corner needs ``radius * tan(turn / 2)`` of free room on both adjacent
    edges.  When the contour has less, the fillet stage can only clamp the
    radius (current default) or skip the corner.  This function instead removes
    the contiguous run of such tight vertices and joins the contour at the
    nearest vertices where a full-radius fillet still fits, then repeats until
    every remaining corner can host the requested radius.

    ``max_removed_ratio`` is a safety limit: trimming stops before more than
    that fraction of the original vertices is gone.  Open contour endpoints are
    never removed.  Returns ``(points, warnings)``; the original points are
    returned unchanged when nothing can be trimmed.
    """

    warnings: list[dict] = []
    original = list(points)
    if radius_mm <= EPS or len(points) < 3:
        return original, warnings

    ratio_limit = min(1.0, max(0.0, float(max_removed_ratio)))
    current = collapse_collinear(dedupe(points, closed), closed)
    total = len(current)
    min_keep = 3 if closed else 2
    if total < min_keep:
        return original, warnings
    max_removed = int(math.floor(ratio_limit * total))

    removed = 0
    stopped = False
    for _ in range(max(1, int(max_passes))):
        bad = {
            index
            for index, _, _ in tight_corners(
                current, closed, radius_mm, min_turn_deg
            )
        }
        if not bad:
            break
        runs = _tight_runs(bad, len(current), closed)
        if not closed:
            runs = [
                [index for index in run if 0 < index < len(current) - 1]
                for run in runs
            ]
            runs = [run for run in runs if run]
        # Keep the two vertices bordering the run: they are usually real
        # corners of the main body whose room is only blocked by the tight
        # feature between them.  Removing the run's interior first lets the
        # next pass see the body corner with the feature already gone.  Short
        # runs (a spike or a two-vertex tip) are removed whole.
        remove: set[int] = set()
        for run in runs:
            if len(run) <= 2:
                remove.update(run)
            else:
                remove.update(run[1:-1])
        if not remove:
            break
        if removed + len(remove) > max_removed:
            stopped = True
            break

        candidate = dedupe(
            [point for index, point in enumerate(current) if index not in remove],
            closed,
        )
        if len(candidate) < min_keep:
            stopped = True
            break
        if closed and abs(signed_area(candidate)) <= 1e-12:
            stopped = True
            break
        if count_self_intersections(candidate, closed) > count_self_intersections(
            current, closed
        ):
            stopped = True
            break

        current = candidate
        removed += len(remove)

    if removed == 0:
        if stopped:
            warnings.append(
                {
                    "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    "severity": "warning",
                    "message": (
                        f"Tight corners would remove more than "
                        f"{ratio_limit:.0%} of the contour; kept unchanged"
                    ),
                    "details": {
                        "radius_mm": radius_mm,
                        "removed": 0,
                        "total": total,
                        "limit_ratio": ratio_limit,
                    },
                }
            )
        return original, warnings

    warnings.append(
        {
            "code": ErrorCode.I_INFO,
            "severity": "info",
            "message": (
                f"Trimmed {removed} tight corner vertex(s) "
                f"({total} -> {len(current)} points) for radius "
                f"{radius_mm:.4f} mm"
            ),
            "details": {
                "radius_mm": radius_mm,
                "removed": removed,
                "total": total,
                "remaining": len(current),
            },
        }
    )
    if stopped:
        warnings.append(
            {
                "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                "severity": "warning",
                "message": (
                    f"Trimming stopped at {removed} of {total} vertices "
                    f"(limit {ratio_limit:.0%}); remaining tight corners kept"
                ),
                "details": {
                    "radius_mm": radius_mm,
                    "removed": removed,
                    "total": total,
                    "limit_ratio": ratio_limit,
                },
            }
        )
    return current, warnings
