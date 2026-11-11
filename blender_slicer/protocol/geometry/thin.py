"""Cutting thin tabs and necks away from a contour."""

from __future__ import annotations

import math

from ..types import ErrorCode, Point2
from .core import EPS, dedupe, dist, signed_turn
from .corners import collapse_collinear


def cut_thin_sections(
    points: list[Point2],
    closed: bool,
    min_width_mm: float,
    *,
    corner_turn_deg: float = 20.0,
    max_removed_ratio: float = 0.5,
) -> tuple[list[Point2], list[dict]]:
    """Cut off thin sections of a contour that are narrower than ``min_width_mm``.

    A vertex is considered part of a thin section when it is a corner (turn above
    ``corner_turn_deg``) whose *both* adjacent edges are shorter than
    ``min_width_mm`` — meaning a fillet of radius ``min_width_mm / 2`` cannot fit
    at that corner.  Contiguous runs of such vertices are removed and the points
    on either side are joined, which cuts the thin protrusion/neck off down to
    the main body of the contour.

    Returns ``(points, warnings)``.  The original contour is returned unchanged
    when nothing is cut.
    """
    warnings: list[dict] = []
    if min_width_mm <= 0 or len(points) < 3:
        return list(points), warnings

    points = collapse_collinear(dedupe(points, closed), closed)
    n = len(points)
    if n < 3:
        return list(points), warnings

    min_turn = math.radians(max(0.0, corner_turn_deg))

    # ------------------------------------------------------------------ marks
    to_remove: set[int] = set()
    for i in range(n):
        prev = points[(i - 1) % n]
        cur = points[i]
        nxt = points[(i + 1) % n]

        turn = abs(signed_turn(prev, cur, nxt))
        if turn < min_turn or turn > math.pi - 1e-6:
            continue

        len_prev = dist(prev, cur)
        len_next = dist(cur, nxt)
        if len_prev <= EPS or len_next <= EPS:
            continue

        # Both adjacent edges must be short: this is a thin tip/neck, not a
        # corner of the main body.
        if len_prev >= min_width_mm or len_next >= min_width_mm:
            continue

        # A fillet of radius min_width_mm/2 needs room on both sides:
        # r_max = min(len_prev, len_next) * 0.5 / tan(turn/2).
        # If both edges are shorter than min_width_mm, r_max < min_width_mm/2
        # for any turn >= 90 deg; for shallower turns we still check explicitly.
        tan_half = math.tan(turn * 0.5)
        if tan_half <= EPS:
            continue
        r_max = min(len_prev, len_next) * 0.5 / tan_half
        if r_max >= min_width_mm * 0.5:
            continue  # the desired radius would fit; not thin

        to_remove.add(i)

    if not to_remove:
        return list(points), warnings

    # ------------------------------------------------- contiguous thin runs
    sorted_removed = sorted(to_remove)
    runs: list[list[int]] = []
    current: list[int] = [sorted_removed[0]]
    for idx in sorted_removed[1:]:
        if idx == current[-1] + 1:
            current.append(idx)
        else:
            runs.append(current)
            current = [idx]
    runs.append(current)

    # For closed contours, merge the first and last run if they touch through
    # the wrap-around boundary.
    if closed and len(runs) > 1:
        first, last = runs[0], runs[-1]
        if first[0] == 0 and last[-1] == n - 1:
            runs[0] = last + first
            runs.pop()

    removed_count = sum(len(r) for r in runs)
    if removed_count >= n - (3 if closed else 2):
        warnings.append(
            {
                "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                "severity": "warning",
                "message": (
                    f"Thin sections would remove {removed_count} of {n} vertices; "
                    "contour kept unchanged"
                ),
                "details": {"removed": removed_count, "total": n},
            }
        )
        return list(points), warnings

    if removed_count / n > max_removed_ratio:
        warnings.append(
            {
                "code": ErrorCode.E_CONSTRAINT_UNSATISFIED,
                "severity": "warning",
                "message": (
                    f"Thin sections would remove {removed_count / n:.0%} of vertices "
                    f"(limit {max_removed_ratio:.0%}); contour kept unchanged"
                ),
                "details": {"removed": removed_count, "total": n, "ratio": removed_count / n},
            }
        )
        return list(points), warnings

    # ----------------------------------------------------------- cut runs out
    keep = [i for i in range(n) if i not in to_remove]
    result = [points[i] for i in keep]

    result = dedupe(result, closed)
    if len(result) < (3 if closed else 2):
        warnings.append(
            {
                "code": ErrorCode.E_GEOM_DEGENERATE,
                "severity": "warning",
                "message": "Thin section cutting collapsed the contour",
                "details": {"removed": removed_count, "total": n},
            }
        )
        return list(points), warnings

    warnings.append(
        {
            "code": ErrorCode.I_INFO,
            "severity": "info",
            "message": (
                f"Cut {removed_count} thin-section vertex(s) from contour "
                f"({n} -> {len(result)} points)"
            ),
            "details": {"removed": removed_count, "total": n, "remaining": len(result)},
        }
    )
    return result, warnings
