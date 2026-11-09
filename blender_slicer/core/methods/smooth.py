from __future__ import annotations

from ..descriptors import Choice, MethodDescriptor, ParamSpec
from ..geometry import chaikin, laplacian, polyline_max_deviation, sharp_corners
from ..types import Contour, ErrorCode
from .base import Method, MethodContext, with_points


class SmoothMethod(Method):
    descriptor = MethodDescriptor(
        name="smooth",
        version="1.0",
        title="Smooth",
        description="Chaikin or constrained Laplacian smoothing.",
        scope="contour",
        params=(
            ParamSpec(
                "algorithm",
                "enum",
                "Algorithm",
                default="chaikin",
                choices=(Choice("chaikin", "Chaikin"), Choice("laplacian", "Constrained Laplacian")),
            ),
            ParamSpec("iterations", "int", "Iterations", default=1, min=0, max=20, step=1, unit="count"),
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
            ParamSpec(
                "max_deviation_mm",
                "float",
                "Max deviation",
                default=0.2,
                min=0.0,
                step=0.01,
                unit="mm",
                description="0 disables the guard.",
            ),
            ParamSpec(
                "weight",
                "float",
                "Laplacian weight",
                default=0.5,
                min=0.0,
                max=1.0,
                step=0.05,
                unit="ratio",
            ),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        anchors = sharp_corners(
            contour.points, contour.closed, float(params["preserve_corners_deg"])
        )
        algorithm = str(params["algorithm"])
        iterations = int(params["iterations"])
        max_dev = float(params["max_deviation_mm"])

        if algorithm == "laplacian":
            points = laplacian(
                contour.points,
                contour.closed,
                iterations,
                weight=float(params["weight"]),
                anchor_indices=anchors,
                max_deviation_mm=max_dev if max_dev > 0 else None,
            )
        else:
            points = chaikin(contour.points, contour.closed, iterations, anchors)

        if max_dev > 0 and points:
            deviation = polyline_max_deviation(points, contour.points, contour.closed)
            if deviation > max_dev:
                ctx.warn(
                    ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    f"Smoothing deviation {deviation:.4f} mm exceeds limit; contour kept",
                    details={"deviation_mm": deviation, "limit_mm": max_dev},
                )
                points = list(contour.points)
        return with_points(contour, points)
