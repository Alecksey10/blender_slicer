from __future__ import annotations

from ..descriptors import MethodDescriptor, ParamSpec
from ..geometry import densify
from ..types import Contour
from .base import Method, MethodContext, with_points


class DensifyMethod(Method):
    descriptor = MethodDescriptor(
        name="densify",
        version="1.0",
        title="Densify",
        description="Adds points to satisfy spacing, angle and chord tolerances.",
        scope="contour",
        params=(
            ParamSpec("max_spacing_mm", "float", "Max spacing", default=2.0, min=0.001, step=0.1, unit="mm"),
            ParamSpec(
                "max_angle_step_deg",
                "float",
                "Max angle step",
                default=12.0,
                min=0.0,
                max=180.0,
                step=1.0,
                unit="deg",
            ),
            ParamSpec(
                "chord_tolerance_mm",
                "float",
                "Chord tolerance",
                default=0.05,
                min=0.0,
                step=0.01,
                unit="mm",
            ),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        points = densify(
            contour.points,
            contour.closed,
            float(params["max_spacing_mm"]),
            float(params["max_angle_step_deg"]),
            float(params["chord_tolerance_mm"]),
        )
        return with_points(contour, points)
