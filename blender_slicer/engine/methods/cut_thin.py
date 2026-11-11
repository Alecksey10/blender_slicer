"""Cut thin sections off contours.

Wide tubes and wires sometimes develop thin tabs or necks on a slice where a
fillet of the desired radius cannot fit.  This method removes those thin
sections and joins across the gap, so the remaining contour stays smooth and
the fillet stage no longer fails on them.

The method is optional: it only runs when enabled in the operation list, and it
is placed *before* fillet in the pipeline so that narrow protrusions are gone
before any corner is rounded.
"""

from __future__ import annotations

from ...protocol.descriptor import MethodDescriptor, ParamSpec
from ...protocol.geometry import cut_thin_sections
from ...protocol.shapes import Contour
from .base import Method, MethodContext, emit_warnings, with_points


class CutThinSectionsMethod(Method):
    descriptor = MethodDescriptor(
        name="cut_thin_sections",
        version="1.0",
        title="Cut thin sections",
        description=(
            "Removes thin parts of a contour (tabs/necks) that are narrower "
            "than the given width, so a fillet of the desired radius can fit. "
            "Runs before fillet in the pipeline."
        ),
        scope="contour",
        params=(
            ParamSpec(
                "min_width_mm",
                "float",
                "Min width (mm)",
                default=6.0,
                min=0.1,
                max=1000.0,
                step=0.1,
                unit="mm",
                description=(
                    "Sections narrower than this are cut off. "
                    "Set to 2 x fillet radius so corners have room on both sides."
                ),
            ),
            ParamSpec(
                "corner_turn_deg",
                "float",
                "Min corner turn",
                default=20.0,
                min=0.0,
                max=179.0,
                step=1.0,
                unit="deg",
                description=(
                    "Only corners with a turn above this angle are considered; "
                    "almost-straight vertices are never cut."
                ),
            ),
            ParamSpec(
                "max_removed_ratio",
                "float",
                "Max removed ratio",
                default=0.5,
                min=0.0,
                max=1.0,
                step=0.05,
                unit="ratio",
                description=(
                    "Safety limit: if more than this fraction of vertices would "
                    "be removed, the contour is kept unchanged."
                ),
            ),
        ),
    )

    def apply_contour(self, contour: Contour, params: dict, ctx: MethodContext) -> Contour:
        min_width = float(params["min_width_mm"])
        corner_turn = float(params["corner_turn_deg"])
        max_ratio = float(params["max_removed_ratio"])

        points, warnings = cut_thin_sections(
            contour.points,
            contour.closed,
            min_width,
            corner_turn_deg=corner_turn,
            max_removed_ratio=max_ratio,
        )

        emit_warnings(ctx, warnings)
        return with_points(contour, points)
