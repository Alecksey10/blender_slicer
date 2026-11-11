"""Trim contour sections that are too tight for the requested fillet radius.

``fillet_corners`` can only clamp the radius (or skip the corner) when a
segment is too short.  This optional stage instead cuts the too-tight run away
and joins the contour at the nearest vertices where the full radius still fits,
so the following fillet keeps the requested radius instead of shrinking it.

The method is optional and runs *before* fillet in the pipeline.
"""

from __future__ import annotations

from ...protocol.descriptor import Choice, MethodDescriptor, ParamSpec
from ...protocol.geometry import tight_corners, trim_tight_corners
from ...protocol.shapes import Contour
from ...protocol.types import ErrorCode
from .base import Method, MethodContext, emit_warnings, with_points


class TrimTightCornersMethod(Method):
    descriptor = MethodDescriptor(
        name="trim_tight_corners",
        version="1.0",
        title="Trim tight corners",
        description=(
            "Cuts contour sections whose corners cannot host the requested "
            "fillet radius and joins the curve where the full radius fits. "
            "Runs before fillet; disable it to keep the current clamp/skip "
            "behaviour."
        ),
        scope="contour",
        params=(
            ParamSpec(
                "radius_mm",
                "float",
                "Fillet radius (mm)",
                default=4.0,
                min=0.0,
                max=10000.0,
                step=0.1,
                unit="mm",
                description=(
                    "Radius that must fit after trimming. Usually the same as "
                    "the fillet radius."
                ),
            ),
            ParamSpec(
                "min_turn_deg",
                "float",
                "Min corner turn (deg)",
                default=20.0,
                min=0.0,
                max=179.0,
                step=1.0,
                unit="deg",
                description=(
                    "Only corners with a turn above this angle are trimmed; "
                    "almost-straight vertices are never cut."
                ),
            ),
            ParamSpec(
                "max_removed_ratio",
                "float",
                "Max removed ratio",
                default=0.5,
                min=0.0,
                max=1.0,
                step=0.05,
                unit="ratio",
                description=(
                    "Safety limit: trimming stops before more than this "
                    "fraction of the contour vertices is removed."
                ),
            ),
            ParamSpec(
                "action",
                "enum",
                "If radius does not fit",
                default="trim",
                choices=(
                    Choice("trim", "Trim the curve"),
                    Choice("ignore", "Leave it to fillet"),
                ),
                description=(
                    "Trim removes the section; ignore only reports it and lets "
                    "the fillet stage pick the largest radius that fits."
                ),
            ),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        radius = float(params["radius_mm"])
        min_turn = float(params["min_turn_deg"])

        if str(params["action"]) == "ignore":
            tight = tight_corners(contour.points, contour.closed, radius, min_turn)
            if tight:
                smallest = min(available for _, available, _ in tight)
                ctx.info(
                    ErrorCode.I_INFO,
                    (
                        f"{len(tight)} corner(s) cannot host radius "
                        f"{radius:.4f} mm (smallest available {smallest:.4f} mm); "
                        "contour left unchanged"
                    ),
                    details={
                        "corners": len(tight),
                        "radius_mm": radius,
                        "smallest_available_mm": smallest,
                    },
                )
            return contour

        points, warnings = trim_tight_corners(
            contour.points,
            contour.closed,
            radius,
            min_turn,
            float(params["max_removed_ratio"]),
        )
        emit_warnings(ctx, warnings)
        return with_points(contour, points)
