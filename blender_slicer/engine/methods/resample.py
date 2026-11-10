from __future__ import annotations

from ...protocol.descriptor import MethodDescriptor, ParamSpec
from ...protocol.geometry import resample
from ...protocol.types import Contour
from .base import Method, MethodContext, with_points


class ResampleMethod(Method):
    descriptor = MethodDescriptor(
        name="resample",
        version="1.0",
        title="Resample",
        description="Uniform or curvature-adaptive point redistribution.",
        scope="contour",
        params=(
            ParamSpec("spacing_mm", "float", "Spacing", default=2.0, min=0.001, step=0.1, unit="mm"),
            ParamSpec("adaptive", "bool", "Adaptive spacing", default=False),
            ParamSpec(
                "min_spacing_mm",
                "float",
                "Minimum spacing",
                default=0.1,
                min=0.001,
                step=0.05,
                unit="mm",
                visible_when=(),
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
        points = resample(
            contour.points,
            contour.closed,
            float(params["spacing_mm"]),
            adaptive=bool(params["adaptive"]),
            min_spacing_mm=float(params["min_spacing_mm"]),
            chord_tolerance_mm=float(params["chord_tolerance_mm"]),
        )
        return with_points(contour, points)
