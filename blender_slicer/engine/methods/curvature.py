from __future__ import annotations

from ...protocol.descriptor import MethodDescriptor, ParamSpec
from ...protocol.geometry import limit_curvature
from ...protocol.types import Contour, ErrorCode
from .base import Method, MethodContext, with_points


class LimitCurvatureMethod(Method):
    descriptor = MethodDescriptor(
        name="limit_curvature",
        version="1.0",
        title="Limit curvature",
        description="Smooths vertices until the minimum bend radius is respected.",
        scope="contour",
        params=(
            ParamSpec("use_material_min_radius", "bool", "Use material minimum", default=True),
            ParamSpec("min_radius_mm", "float", "Minimum radius", default=6.0, min=0.001, step=0.1, unit="mm"),
            ParamSpec("max_iterations", "int", "Max iterations", default=20, min=1, max=200, step=1, unit="count"),
            ParamSpec("weight", "float", "Smoothing weight", default=0.5, min=0.05, max=1.0, step=0.05, unit="ratio"),
            ParamSpec("strict", "bool", "Fail if not converged", default=False),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        radius = (
            ctx.material.min_bend_radius_mm
            if bool(params["use_material_min_radius"])
            else float(params["min_radius_mm"])
        )
        points, remaining = limit_curvature(
            contour.points,
            contour.closed,
            float(radius),
            int(params["max_iterations"]),
            float(params["weight"]),
        )
        if remaining:
            message = (
                f"{remaining} vertices still have radius below {radius:.4f} mm "
                f"after {int(params['max_iterations'])} iterations"
            )
            if bool(params["strict"]):
                from ..errors import DomainError

                raise DomainError(
                    ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    message,
                    contour_id=contour.id,
                    details={"remaining": remaining, "min_radius_mm": radius},
                )
            ctx.warn(
                ErrorCode.E_CONSTRAINT_UNSATISFIED,
                message,
                details={"remaining": remaining, "min_radius_mm": radius},
            )
        return with_points(contour, points)
