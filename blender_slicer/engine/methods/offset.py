"""Cut offset: applies the signed clearance the adapter attached to a slice.

The adapter decides the policy (for example: +X cuts outward, +Z cuts inward,
never less than the material cross-section radius).  The engine method is the
single implementation of the geometry, so every host gets the same clearance.
"""

from __future__ import annotations

from ...protocol.descriptor import Choice, MethodDescriptor, ParamSpec
from ...protocol.geometry import signed_area
from ...protocol.offset import offset_polyline
from ...protocol.shapes import Contour
from ...protocol.types import ErrorCode
from .base import Method, MethodContext, with_points


class OffsetMethod(Method):
    descriptor = MethodDescriptor(
        name="offset_contour",
        version="1.0",
        title="Cut offset",
        description=(
            "Offsets cut contours by the per-slice clearance (positive grows the "
            "contour). Used for weld/assembly gaps and material cross-section."
        ),
        scope="contour",
        params=(
            ParamSpec(
                "distance_mm",
                "float",
                "Offset",
                default=0.0,
                min=-10000.0,
                max=10000.0,
                step=0.1,
                unit="mm",
                description="Positive grows the contour outward; ignored when use_slice_offset is on.",
            ),
            ParamSpec(
                "use_slice_offset",
                "bool",
                "Use per-slice offset",
                default=True,
                description="Take the signed distance from Slice.offset_mm set by the adapter.",
            ),
            ParamSpec(
                "join",
                "enum",
                "Corner join",
                default="round",
                choices=(
                    Choice("round", "Round"),
                    Choice("miter", "Miter"),
                    Choice("bevel", "Bevel"),
                ),
            ),
            ParamSpec(
                "miter_limit",
                "float",
                "Miter limit",
                default=2.0,
                min=1.0,
                max=10.0,
                step=0.1,
                unit="ratio",
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
            ),
            ParamSpec(
                "chord_tolerance_mm",
                "float",
                "Arc chord tolerance",
                default=0.05,
                min=0.0,
                step=0.01,
                unit="mm",
            ),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        distance = (
            float(ctx.slice_offset_mm)
            if bool(params["use_slice_offset"])
            else float(params["distance_mm"])
        )
        if abs(distance) <= 1e-12:
            return contour

        before_area = abs(signed_area(contour.points)) if contour.closed else None
        points, warnings = offset_polyline(
            contour.points,
            contour.closed,
            distance,
            join=str(params["join"]),
            miter_limit=float(params["miter_limit"]),
            arc_segments=int(params["arc_segments"]),
            chord_tolerance_mm=float(params["chord_tolerance_mm"]),
        )
        for warning in warnings:
            ctx.warn(
                warning["code"],
                warning["message"],
                point_index=warning.get("point_index"),
                details=warning.get("details"),
            )
        if before_area is not None and contour.closed:
            after_area = abs(signed_area(points))
            if after_area > 0 and after_area < before_area * 1e-6:
                ctx.warn(
                    ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    f"Offset {distance:.4f} mm collapsed {contour.id}; contour kept",
                    details={"requested_offset_mm": distance},
                )
                return contour
        return with_points(contour, points)
