from __future__ import annotations

from ...protocol.descriptor import Choice, MethodDescriptor, ParamSpec
from ...protocol.geometry import (
    approximate_smooth_curve,
    polyline_max_deviation,
)
from ...protocol.types import Contour, ErrorCode
from .base import Method, MethodContext, with_points


class SmoothCurveApproxMethod(Method):
    descriptor = MethodDescriptor(
        name="smooth_curve_approx",
        version="1.1",
        title="Smooth Curve Approximation",
        description=(
            "Fits a C1-continuous cubic Bezier spline through (or near) the "
            "control points.  The interpolating mode passes exactly through "
            "every point so corners and irregularities are preserved; the "
            "approximate mode simplifies first and bounds the deviation from "
            "the original.  Detail adapts to curvature via chord tolerance, so "
            "flat spans stay sparse and tight curves get more samples."
        ),
        scope="contour",
        params=(
            ParamSpec("use_material_min_radius", "bool", "Use material minimum bend radius", default=True),
            ParamSpec("min_radius_mm", "float", "Custom minimum radius", default=6.0, min=0.0, step=0.1, unit="mm"),
            ParamSpec(
                "mode",
                "enum",
                "Fit mode",
                default="interpolate",
                choices=(
                    Choice("interpolate", "Interpolate (passes through points)"),
                    Choice("approximate", "Approximate (bounded deviation)"),
                    Choice("hybrid", "Hybrid (light inertia + interpolate)"),
                ),
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
                description=(
                    "0.0 = straight chords; 1.0 = tight Catmull-Rom curves. "
                    "In approximate mode the effective tension may be lowered "
                    "automatically to meet max_deviation_mm."
                ),
            ),
            ParamSpec(
                "max_deviation_mm",
                "float",
                "Max deviation from source",
                default=0.0,
                min=0.0,
                step=0.01,
                unit="mm",
                description="0 disables: curve passes exactly through anchors.",
            ),
            ParamSpec(
                "preserve_corners_deg",
                "float",
                "Preserve corners above",
                default=0.0,
                min=0.0,
                max=180.0,
                step=1.0,
                unit="deg",
                description=(
                    "Turns sharper than this stay exact corners; the spline is "
                    "split there so neighbouring smooth runs do not round them."
                ),
            ),
            ParamSpec(
                "chord_tolerance_mm",
                "float",
                "Chord tolerance",
                default=0.05,
                min=0.0,
                step=0.01,
                unit="mm",
                description=(
                    "Adaptive detail: smaller = more samples on tight curves, "
                    "fewer on flat spans.  0 uses uniform segments_per_span."
                ),
            ),
            ParamSpec(
                "max_spacing_mm",
                "float",
                "Max point spacing",
                default=0.0,
                min=0.0,
                step=0.1,
                unit="mm",
                description="0 disables.",
            ),
            ParamSpec("segments_per_span", "int", "Segments per span", default=8, min=2, max=64, step=1, unit="count"),
            ParamSpec(
                "inertia_smoothing",
                "int",
                "Inertia passes",
                default=0,
                min=0,
                max=10,
                step=1,
                unit="count",
                description="Optional pre-blur; 0 keeps sharp features.",
            ),
            ParamSpec(
                "inertia",
                "float",
                "Overall inertia",
                default=0.0,
                min=0.0,
                max=1.0,
                step=0.05,
                unit="ratio",
                description=(
                    "0.0 = exact following of every point; 1.0 = degenerates "
                    "into a best-fit circle; intermediate values blend "
                    "progressively between the two."
                ),
            ),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        use_mat = bool(params["use_material_min_radius"])
        min_r = ctx.material.min_bend_radius_mm if use_mat else float(params["min_radius_mm"])
        mode = str(params["mode"])
        tension = float(params["tension"])
        max_dev = float(params["max_deviation_mm"])
        preserve_corners = float(params["preserve_corners_deg"])
        chord_tol = float(params["chord_tolerance_mm"])
        max_spacing = float(params["max_spacing_mm"])
        segments = int(params["segments_per_span"])
        inertia_passes = int(params["inertia_smoothing"])
        inertia = float(params["inertia"])

        points = list(contour.points)
        closed = contour.closed

        approximated = approximate_smooth_curve(
            points,
            closed=closed,
            min_bend_radius_mm=min_r,
            segments_per_span=segments,
            tension=tension,
            inertia_smoothing=inertia_passes,
            inertia=inertia,
            mode=mode,
            max_deviation_mm=max_dev,
            chord_tolerance_mm=chord_tol,
            max_spacing_mm=max_spacing,
            preserve_corners_deg=preserve_corners,
        )

        if max_dev > 0.0 and approximated:
            deviation = polyline_max_deviation(approximated, points, closed)
            if deviation > max_dev:
                ctx.warn(
                    ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    f"Curve deviation {deviation:.4f} mm exceeds limit {max_dev:.4f} mm",
                    details={
                        "deviation_mm": deviation,
                        "limit_mm": max_dev,
                        "method": self.descriptor.name,
                    },
                )
        return with_points(contour, approximated)
