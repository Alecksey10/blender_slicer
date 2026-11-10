from __future__ import annotations

from ...protocol.descriptor import Choice, MethodDescriptor, ParamSpec
from ...protocol.geometry import fillet_corners
from ...protocol.types import Contour
from .base import Method, MethodContext, with_points


class FilletMethod(Method):
    descriptor = MethodDescriptor(
        name="fillet_corners",
        version="1.0",
        title="Corner fillets",
        description="Replaces corners with tangent arcs, respecting available material.",
        scope="contour",
        params=(
            ParamSpec("radius_mm", "float", "Radius", default=3.0, min=0.0, max=10000.0, step=0.1, unit="mm"),
            ParamSpec(
                "min_turn_deg",
                "float",
                "Minimum turn angle",
                default=20.0,
                min=0.0,
                max=179.0,
                step=1.0,
                unit="deg",
            ),
            ParamSpec("arc_segments", "int", "Arc segments", default=3, min=1, max=64, step=1, unit="count"),
            ParamSpec(
                "chord_tolerance_mm",
                "float",
                "Arc chord tolerance",
                default=0.05,
                min=0.0,
                step=0.01,
                unit="mm",
            ),
            ParamSpec(
                "mode",
                "enum",
                "If radius does not fit",
                default="error",
                choices=(
                    Choice("clamp", "Clamp and warn"),
                    Choice("error", "Fail contour"),
                    Choice("skip", "Leave corner"),
                ),
            ),
            ParamSpec("check_material", "bool", "Check material minimum radius", default=True),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        material_min = (
            ctx.material.min_bend_radius_mm if bool(params["check_material"]) else None
        )
        points, warnings = fillet_corners(
            contour.points,
            contour.closed,
            float(params["radius_mm"]),
            float(params["min_turn_deg"]),
            int(params["arc_segments"]),
            mode=str(params["mode"]),
            chord_tolerance_mm=float(params["chord_tolerance_mm"]),
            material_min_radius_mm=material_min,
        )
        for w in warnings:
            ctx.warn(
                w["code"],
                w["message"],
                point_index=w.get("point_index"),
                details=w.get("details"),
            )
        return with_points(contour, points)
