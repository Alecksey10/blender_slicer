"""Shrink sections before other operations, keeping the result smooth.

The adapter attaches a per-slice ratio to ``Slice.metadata["shrink_ratio"]`` so
the distribution along the stack stays a client concern (uniform, tapered
towards the middle, ...).  The engine applies that ratio and then smooths the
result, which keeps wide tubes/wires bendable instead of faceted.
"""

from __future__ import annotations

from ...protocol.descriptor import Choice, MethodDescriptor, ParamSpec
from ...protocol.geometry import laplacian, sharp_corners
from ...protocol.shrink import shrink_points
from ...protocol.shapes import Contour
from ...protocol.types import ErrorCode
from .base import Method, MethodContext, with_points


class ShrinkMethod(Method):
    descriptor = MethodDescriptor(
        name="shrink_section",
        version="1.0",
        title="Section shrink",
        description=(
            "Scales each contour toward its centre by a per-slice ratio and "
            "smooths it, so wide sections can be narrowed without kinks."
        ),
        scope="contour",
        params=(
            ParamSpec(
                "ratio",
                "float",
                "Shrink ratio",
                default=1.0,
                min=0.01,
                max=1.0,
                step=0.01,
                unit="ratio",
                description="1.0 keeps the contour; 0.8 keeps 80% of its size. Ignored when use_slice_ratio is on.",
            ),
            ParamSpec(
                "use_slice_ratio",
                "bool",
                "Use per-slice ratio",
                default=True,
                description="Take the ratio from Slice.metadata['shrink_ratio'] set by the adapter.",
            ),
            ParamSpec(
                "anchor",
                "enum",
                "Anchor",
                default="centroid",
                choices=(
                    Choice("centroid", "Area centroid"),
                    Choice("bounds", "Bounding box centre"),
                ),
            ),
            ParamSpec(
                "smooth_iterations",
                "int",
                "Smoothing iterations",
                default=2,
                min=0,
                max=10,
                step=1,
                unit="count",
            ),
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
        ratio = float(params["ratio"])
        if bool(params["use_slice_ratio"]):
            value = ctx.slice_metadata.get("shrink_ratio")
            if value is not None:
                ratio = float(value)
        ratio = min(1.0, max(0.0, ratio))
        if ratio >= 1.0 - 1e-9:
            return contour
        if ratio <= 0.01:
            ctx.warn(
                ErrorCode.E_CONSTRAINT_UNSATISFIED,
                f"Shrink ratio {ratio:.4f} would collapse {contour.id}; contour kept",
                details={"requested_ratio": ratio},
            )
            return contour

        points = shrink_points(
            contour.points,
            ratio,
            anchor=str(params["anchor"]),
            closed=contour.closed,
        )
        iterations = int(params["smooth_iterations"])
        if iterations > 0 and len(points) >= 3:
            anchors = sharp_corners(
                points, contour.closed, float(params["preserve_corners_deg"])
            )
            points = laplacian(
                points,
                contour.closed,
                iterations,
                weight=0.5,
                anchor_indices=anchors,
                max_deviation_mm=None,
            )
        return with_points(contour, points)
