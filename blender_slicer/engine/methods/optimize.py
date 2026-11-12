from __future__ import annotations

import math

from ...protocol.descriptor import MethodDescriptor, ParamSpec
from ...protocol.geometry import optimize_curve
from ...protocol.types import Contour, ErrorCode
from .base import Method, MethodContext, with_points


AUTO_SAMPLES = 600


def _perimeter(points, closed: bool) -> float:
    """Length of the contour, for judging whether the sampling resolves it."""

    if len(points) < 2:
        return 0.0
    total = 0.0
    for index in range(1, len(points)):
        total += math.dist(points[index - 1], points[index])
    if closed:
        total += math.dist(points[-1], points[0])
    return total


class OptimizeCurveMethod(Method):
    descriptor = MethodDescriptor(
        name="optimize_curve",
        version="1.0",
        title="Optimize curve",
        description=(
            "Global fit of the contour in one constrained least-squares solve: "
            "data fidelity (stays on the measured points), bending energy "
            "(thin-rod smoothing) and the material bend radius as a soft "
            "penalty are minimised together by Levenberg-Marquardt.  Unlike "
            "the sequential stages, a tight bend is traded against deviation "
            "instead of being clamped corner by corner, so the result is as "
            "close to the source as the material allows."
        ),
        scope="contour",
        params=(
            ParamSpec(
                "sample_points",
                "int",
                "Curve samples",
                default=150,
                min=8,
                max=4000,
                step=1,
                unit="count",
                description=(
                    "Minimum points the contour is resampled to before the "
                    "solve; a denser contour keeps its detail up to 600 samples."
                ),
            ),
            ParamSpec(
                "data_weight",
                "float",
                "Data weight",
                default=20.0,
                min=0.0,
                max=1_000_000.0,
                step=1.0,
                unit="ratio",
                description="Pull towards the measured points; higher keeps detail.",
            ),
            ParamSpec(
                "smooth",
                "float",
                "Smooth",
                default=2.0,
                min=0.0,
                max=1000.0,
                step=0.5,
                unit="mm",
                description=(
                    "Smoothing length: the scale over which the fit may trade "
                    "data for a straighter curve. 0 lets the curve follow every "
                    "measured wobble; 5-10 mm irons out noise while keeping "
                    "corners."
                ),
            ),
            ParamSpec(
                "use_material_min_radius",
                "bool",
                "Use material minimum bend radius",
                default=True,
            ),
            ParamSpec(
                "min_radius_mm",
                "float",
                "Minimum bend radius",
                default=6.0,
                min=0.0,
                step=0.1,
                unit="mm",
            ),
            ParamSpec(
                "radius_weight",
                "float",
                "Bend radius penalty",
                default=1000.0,
                min=0.0,
                max=1_000_000.0,
                step=10.0,
                unit="ratio",
                description=(
                    "How hard a bend tighter than the minimum radius is punished. "
                    "The trade is deviation vs bend: continue/stop = "
                    "sqrt(radius_weight / data_weight) millimetres per radian."
                ),
            ),
            ParamSpec(
                "max_iterations",
                "int",
                "Max iterations",
                default=40,
                min=1,
                max=500,
                step=1,
                unit="count",
            ),
            ParamSpec(
                "cost_tolerance",
                "float",
                "Relative cost tolerance",
                default=1e-6,
                min=0.0,
                step=1e-7,
                unit="ratio",
                description="Stop when one step improves the cost by less than this.",
            ),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        radius = (
            ctx.material.min_bend_radius_mm
            if bool(params["use_material_min_radius"])
            else float(params["min_radius_mm"])
        )
        radius = max(0.0, float(radius))
        # A bend needs a couple of points per radius to be representable at all,
        # so the requested sample count is a *minimum*: on a large part 150
        # points would turn every corner into a long chamfer.  The raise is
        # capped so one solve stays interactive; beyond that the method warns.
        samples = int(params["sample_points"])
        perimeter = _perimeter(contour.points, contour.closed)
        if radius > 0.0 and perimeter > 0.0:
            needed = int(perimeter / max(radius * 0.5, 1e-9))
            samples = max(samples, min(needed, AUTO_SAMPLES))

        def on_progress(info: dict) -> None:
            ctx.report(
                info.get("fraction"),
                f"iteration {info['iteration']}/{info['max_iterations']}",
            )

        points, stats = optimize_curve(
            contour.points,
            contour.closed,
            count=samples,
            data_weight=float(params["data_weight"]),
            smooth=float(params["smooth"]),
            min_radius_mm=radius,
            radius_weight=float(params["radius_weight"]),
            max_iterations=int(params["max_iterations"]),
            cost_tolerance=float(params["cost_tolerance"]),
            progress=on_progress,
            cancel=ctx.progress.cancelled if ctx.progress is not None else None,
        )

        # The host asked to stop: never hand a half-fitted contour upstream.
        ctx.check_cancel()

        # A bend can only be resolved if it is sampled by at least a couple of
        # points: an arc shorter than the spacing degenerates into a chamfer.
        samples = int(stats.get("samples", 0))
        perimeter = _perimeter(contour.points, contour.closed)
        spacing = perimeter / samples if samples else 0.0
        if radius > 0.0 and spacing > radius:
            ctx.warn(
                ErrorCode.E_CONSTRAINT_UNSATISFIED,
                (
                    f"Points are {spacing:.3f} mm apart while the minimum radius "
                    f"is {radius:.3f} mm: the bend is under-sampled. Raise "
                    "'Curve samples' to about "
                    f"{max(samples, int(perimeter / max(radius * 0.5, 1e-9)))}."
                ),
                details={"spacing_mm": spacing, "samples": samples, "method": "optimize_curve"},
            )

        smallest = stats.get("min_radius_mm")
        # A fit that lands within 2% of the limit is a success, not a warning:
        # reporting 5.999 against 6.000 is noise the user cannot act on.
        if radius > 0.0 and smallest is not None and smallest < radius * 0.98:
            ctx.warn(
                ErrorCode.E_CONSTRAINT_UNSATISFIED,
                (
                    f"Bend radius {smallest:.4f} mm is below the {radius:.4f} mm "
                    "minimum; the curve was fitted as close as the material allows"
                ),
                details={
                    "min_radius_mm": smallest,
                    "limit_mm": radius,
                    "violations": stats.get("violations", 0),
                    "method": self.descriptor.name,
                },
            )
        ctx.info(
            ErrorCode.I_INFO,
            (
                f"optimize_curve: {stats['iterations']} iteration(s), "
                f"cost {stats['cost']:.6f}, {stats['time']:.3f} s, "
                f"{stats['violations']} bend violation(s)"
            ),
            details=stats,
        )
        return with_points(contour, points)
