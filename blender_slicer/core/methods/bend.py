from __future__ import annotations

from ..descriptors import Choice, MethodDescriptor, ParamSpec
from ..errors import DomainError
from ..geometry import bend_allowance_mm
from ..types import Contour, ContourRole, ErrorCode
from .base import Method, MethodContext


class BendCheckMethod(Method):
    descriptor = MethodDescriptor(
        name="bend_check",
        version="1.0",
        title="Bend check",
        description="Checks fold angle/radius and reports bend allowance.",
        scope="contour",
        params=(
            ParamSpec(
                "mode",
                "enum",
                "On violation",
                default="warning",
                choices=(Choice("warning", "Warning"), Choice("error", "Error")),
            ),
            ParamSpec("report_allowance", "bool", "Report bend allowance", default=True),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        fold = contour.fold
        if contour.role != ContourRole.SCORE or fold is None:
            return contour
        radius = fold.radius_mm if fold.radius_mm is not None else ctx.material.min_bend_radius_mm
        errors: list[str] = []
        if abs(fold.angle_deg) > ctx.material.max_bend_angle_deg:
            errors.append(
                f"fold angle {fold.angle_deg:.2f} deg exceeds material maximum "
                f"{ctx.material.max_bend_angle_deg:.2f} deg"
            )
        if radius < ctx.material.min_bend_radius_mm:
            errors.append(
                f"fold radius {radius:.4f} mm is below material minimum "
                f"{ctx.material.min_bend_radius_mm:.4f} mm"
            )
        if errors:
            message = "; ".join(errors)
            if str(params["mode"]) == "error":
                raise DomainError(
                    ErrorCode.E_CONSTRAINT_UNSATISFIED,
                    message,
                    contour_id=contour.id,
                    details={"fold": contour.id, "angle_deg": fold.angle_deg, "radius_mm": radius},
                )
            ctx.warn(ErrorCode.E_CONSTRAINT_UNSATISFIED, message, details={"fold": contour.id})
        if bool(params["report_allowance"]):
            ba = bend_allowance_mm(
                fold.angle_deg,
                radius,
                ctx.material.thickness_mm,
                ctx.material.k_factor,
            )
            ctx.info(
                ErrorCode.I_INFO,
                f"Bend allowance: {ba:.4f} mm",
                details={"bend_allowance_mm": ba, "radius_mm": radius},
            )
        return contour
