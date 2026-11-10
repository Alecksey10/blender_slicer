from __future__ import annotations

from ...protocol.descriptor import MethodDescriptor, ParamSpec
from ...protocol.geometry import sharp_corners, simplify
from ...protocol.types import Contour
from .base import Method, MethodContext, with_points


class SimplifyMethod(Method):
    descriptor = MethodDescriptor(
        name="simplify",
        version="1.0",
        title="Simplify",
        description="Douglas-Peucker simplification with preserved corners.",
        scope="contour",
        params=(
            ParamSpec("tolerance_mm", "float", "Tolerance", default=0.05, min=0.0, step=0.01, unit="mm"),
            ParamSpec(
                "preserve_corners_deg",
                "float",
                "Preserve corners above",
                default=70.0,
                min=0.0,
                max=180.0,
                step=1.0,
                unit="deg",
            ),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        anchors = sharp_corners(
            contour.points, contour.closed, float(params["preserve_corners_deg"])
        )
        points = simplify(
            contour.points,
            contour.closed,
            float(params["tolerance_mm"]),
            anchors,
        )
        return with_points(contour, points)
