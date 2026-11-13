"""Tube-path (group B) method: rod centreline following a guide curve (group A).

Builds the centreline of a cylindrical rod of radius ``rod_radius_mm`` that runs
along a guide curve at a constant tangent offset.  The rod surface touches the
guide everywhere, so the centreline never collides with the guide material —
this is exactly the "pass by the tangent, not through the centre" behaviour
requested for group-B cross-section curves.

The method works on a single contour (group A) and emits a parallel contour
(group B).  When ``use_cross_sections`` is on it also looks up neighbouring
slices via ``ctx.all_slices`` / ``ctx.slice_frames`` and builds cross-section
contact points in the perpendicular planes before approximating the final
group-B curve through them.
"""

from __future__ import annotations

import math

from ...protocol.descriptor import Choice, MethodDescriptor, ParamSpec
from ...protocol.geometry import (
    approximate_smooth_curve,
    dedupe,
    dist,
    evaluate_bezier_cubic,
    rod_centre_path,
    tangent_offset_points,
    unit,
    v_sub,
)
from ...protocol.shapes import Contour
from ...protocol.types import ErrorCode
from .base import Method, MethodContext, with_points


class TubePathMethod(Method):
    descriptor = MethodDescriptor(
        name="tube_path",
        version="1.0",
        title="Tube path (group B)",
        description=(
            "Builds the centreline of a rod (tube) of given radius following a "
            "guide curve (group A) at a constant tangent offset.  The rod "
            "surface stays tangent to the guide, so the centreline avoids "
            "collisions with the guide material.  With cross-sections enabled "
            "it also builds contact points in perpendicular planes across "
            "neighbouring slices."
        ),
        scope="contour",
        params=(
            ParamSpec(
                "rod_radius_mm",
                "float",
                "Rod / tube radius",
                default=3.0,
                min=0.0,
                step=0.1,
                unit="mm",
                description="Radius of the rod; centreline is offset by this amount from the guide.",
            ),
            ParamSpec(
                "side",
                "enum",
                "Offset side",
                default="outer",
                choices=(
                    Choice("outer", "Outer (left of travel)"),
                    Choice("inner", "Inner (right of travel)"),
                    Choice("center", "Center (no offset)"),
                ),
                description="Which side of the guide the rod centre runs on.",
            ),
            ParamSpec(
                "use_cross_sections",
                "bool",
                "Use cross-section planes",
                default=False,
                description="Build contact points in perpendicular planes across neighbouring slices.",
            ),
            ParamSpec(
                "cross_section_step_mm",
                "float",
                "Cross-section step",
                default=5.0,
                min=0.5,
                step=0.5,
                unit="mm",
                description="Distance between consecutive cross-section planes along the guide.",
            ),
            ParamSpec(
                "guide_group_tag",
                "string",
                "Guide group tag",
                default="group_a",
                description="Tag used to identify guide (group A) contours across slices.",
            ),
            ParamSpec(
                "contact_tolerance_mm",
                "float",
                "Contact tolerance",
                default=0.05,
                min=0.0,
                step=0.01,
                unit="mm",
                description="Chord tolerance when approximating the final group-B curve through contact points.",
            ),
            ParamSpec(
                "tension",
                "float",
                "Curve tension",
                default=0.5,
                min=0.0,
                max=1.0,
                step=0.05,
                unit="ratio",
                description="Spline tension for the final group-B curve approximation.",
            ),
            ParamSpec(
                "arc_segments",
                "int",
                "Arc segments",
                default=8,
                min=1,
                max=64,
                step=1,
                unit="count",
                description="Segments per rounded join in the tangent offset.",
            ),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        rod_radius = float(params["rod_radius_mm"])
        side_str = str(params["side"])
        use_xs = bool(params["use_cross_sections"])
        xs_step = float(params["cross_section_step_mm"])
        tag = str(params["guide_group_tag"])
        contact_tol = float(params["contact_tolerance_mm"])
        tension = float(params["tension"])
        arc_segments = int(params["arc_segments"])

        side = 1.0 if side_str == "outer" else (-1.0 if side_str == "inner" else 0.0)

        points = list(contour.points)
        closed = contour.closed

        if use_xs and ctx.all_slices:
            group_b = self._build_cross_sections(
                contour, points, closed, rod_radius, side, xs_step,
                tag, contact_tol, tension, arc_segments, ctx,
            )
        else:
            if rod_radius <= 0.0 or side == 0.0:
                group_b = list(points)
            else:
                group_b = rod_centre_path(
                    points, closed, rod_radius, side, arc_segments
                )

        if not group_b:
            group_b = list(points)

        # Final smooth approximation through the contact / offset points.
        group_b = approximate_smooth_curve(
            group_b,
            closed=closed,
            tension=tension,
            chord_tolerance_mm=contact_tol,
            mode="interpolate",
        )

        return with_points(contour, group_b)

    # ------------------------------------------------------------------ cross sections

    def _build_cross_sections(
        self,
        contour: Contour,
        guide_points: list[tuple[float, float]],
        closed: bool,
        rod_radius: float,
        side: float,
        xs_step: float,
        tag: str,
        contact_tol: float,
        tension: float,
        arc_segments: int,
        ctx: MethodContext,
    ) -> list[tuple[float, float]]:
        """Build group-B contact points using perpendicular cross-section planes.

        For each sample point on the guide curve we build a plane perpendicular
        to the guide tangent, intersect it with the guide itself and with any
        neighbouring-slice silhouettes that carry ``tag``, and take the
        tangent-contact point on the rod circle as the group-B sample.
        """
        if not guide_points or len(guide_points) < 2:
            return list(guide_points)

        # Resample the guide evenly so cross-sections are regularly spaced.
        guide = self._resample_guide(guide_points, closed, xs_step, tension)
        if len(guide) < 2:
            return list(guide_points)

        contact_points: list[tuple[float, float]] = []
        n = len(guide)

        # Build a lookup of neighbouring silhouettes (other contours in the
        # same slice or tagged contours in other slices) for contact probing.
        silhouettes = self._collect_silhouettes(contour, tag, ctx)

        for i in range(n):
            p = guide[i]
            # Tangent at this guide point (averaged from neighbours).
            tan = self._tangent_at(guide, closed, i)
            nrm = (-tan[1], tan[0])  # left normal
            if side < 0.0:
                nrm = (-nrm[0], -nrm[1])

            # Rod centre at this guide point.
            centre = (
                p[0] + nrm[0] * rod_radius,
                p[1] + nrm[1] * rod_radius,
            )

            # The contact point is where the rod surface touches the guide:
            # centre shifted back along the normal by rod_radius.
            contact = (
                centre[0] - nrm[0] * rod_radius,
                centre[1] - nrm[1] * rod_radius,
            )

            # Probe silhouettes in the perpendicular plane for closer contact
            # points (avoiding collisions with adjacent tubes/walls).
            best = contact
            best_dist = rod_radius
            for sil in silhouettes:
                cp = self._closest_on_silhouette(sil, centre, rod_radius)
                if cp is not None:
                    d = dist(centre, cp)
                    if d < best_dist:
                        best_dist = d
                        best = cp

            contact_points.append(best)

        if closed and contact_points:
            contact_points.append(contact_points[0])

        return dedupe(contact_points, closed)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _resample_guide(
        points: list[tuple[float, float]],
        closed: bool,
        step_mm: float,
        tension: float,
    ) -> list[tuple[float, float]]:
        """Resample ``points`` so consecutive samples are ~``step_mm`` apart."""
        if len(points) < 2:
            return list(points)
        n = len(points)
        seg_count = n if closed else n - 1
        # Cumulative length per vertex.
        lengths = [0.0] * n
        total = 0.0
        for i in range(seg_count):
            total += dist(points[i], points[(i + 1) % n])
            lengths[(i + 1) % n] = total
        if total <= 0.0:
            return list(points)

        target_count = max(2, int(math.ceil(total / max(step_mm, 1e-6))))
        out: list[tuple[float, float]] = []
        for k in range(target_count):
            s = total * k / (target_count - 1) if target_count > 1 else 0.0
            # Find segment containing s.
            seg_i = 0
            for i in range(seg_count):
                a_len = lengths[i]
                b_len = lengths[(i + 1) % n]
                lo, hi = min(a_len, b_len), max(a_len, b_len)
                if lo - 1e-9 <= s <= hi + 1e-9:
                    seg_i = i
                    break
            a = points[seg_i]
            b = points[(seg_i + 1) % n]
            seg_len = dist(a, b)
            if seg_len <= 1e-12:
                t = 0.0
            else:
                t = (s - min(lengths[seg_i], lengths[(seg_i + 1) % n])) / seg_len
            t = max(0.0, min(1.0, t))
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        return out

    @staticmethod
    def _tangent_at(
        points: list[tuple[float, float]], closed: bool, index: int
    ) -> tuple[float, float]:
        n = len(points)
        if n < 2:
            return (1.0, 0.0)
        prev = points[(index - 1) % n]
        cur = points[index]
        nxt = points[(index + 1) % n]
        d0 = unit(v_sub(cur, prev)) if dist(prev, cur) > 1e-12 else (0.0, 0.0)
        d1 = unit(v_sub(nxt, cur)) if dist(nxt, cur) > 1e-12 else (0.0, 0.0)
        tx = d0[0] + d1[0]
        ty = d0[1] + d1[1]
        tx2 = tx
        ty2 = ty
        length = (tx2 * tx2 + ty2 * ty2) ** 0.5
        if length <= 1e-12:
            return (1.0, 0.0)
        return (tx2 / length, ty2 / length)

    def _collect_silhouettes(
        self,
        contour: Contour,
        tag: str,
        ctx: MethodContext,
    ) -> list[list[tuple[float, float]]]:
        """Collect other contours that can act as contact obstacles."""
        silhouettes: list[list[tuple[float, float]]] = []
        if ctx.all_slices:
            for sl in ctx.all_slices:
                for c in sl.contours:
                    if c.id == contour.id:
                        continue
                    if tag and tag not in (c.tags or []):
                        continue
                    silhouettes.append(list(c.points))
        return silhouettes

    @staticmethod
    def _closest_on_silhouette(
        silhouette: list[tuple[float, float]],
        centre: tuple[float, float],
        rod_radius: float,
    ) -> tuple[float, float] | None:
        """Closest point on ``silhouette`` to ``centre`` within ``rod_radius``."""
        if len(silhouette) < 2:
            return None
        best: tuple[float, float] | None = None
        best_d = rod_radius + 1e-9
        n = len(silhouette)
        closed = n > 1 and silhouette[0] == silhouette[-1]
        count = n if closed else n - 1
        for i in range(count):
            a = silhouette[i]
            b = silhouette[(i + 1) % n]
            # Closest point on segment a-b to centre.
            abx = b[0] - a[0]
            aby = b[1] - a[1]
            denom = abx * abx + aby * aby
            if denom <= 1e-12:
                t = 0.0
            else:
                t = ((centre[0] - a[0]) * abx + (centre[1] - a[1]) * aby) / denom
                t = max(0.0, min(1.0, t))
            cp = (a[0] + abx * t, a[1] + aby * t)
            dx = cp[0] - centre[0]
            dy = cp[1] - centre[1]
            d = (dx * dx + dy * dy) ** 0.5
            if d < best_d:
                best_d = d
                best = cp
        return best
