"""Dependency-free 2D geometry kernel, split by responsibility.

The historical ``protocol.geometry`` import path is preserved: every public
name is re-exported here, so engine methods and adapters do not need to know
which submodule implements it.
"""

from __future__ import annotations

from .core import (
    v_add,
    v_sub,
    v_mul,
    v_lerp,
    dot,
    cross,
    length,
    dist,
    unit,
    left_normal,
    signed_area,
    polyline_length,
    signed_turn,
    turn_angle,
    vertex_radius,
    min_radius,
    max_turn_deg,
    dedupe,
    point_to_segment_distance,
    point_to_polyline_distance,
    polyline_max_deviation,
)

from .intersections import (
    point_on_segment,
    point_in_polygon,
    contour_inside,
    _segments_strictly_intersect,
    count_self_intersections,
)

from .resampling import (
    resample,
    _chord_for_radius,
    densify,
)

from .simplification import (
    _dp_indices,
    simplify,
    sharp_corners,
)

from .smoothing import (
    _chaikin_open,
    _chaikin_closed,
    chaikin,
    laplacian,
    limit_curvature,
)

from .approximation import (
    evaluate_bezier_cubic,
    approximate_smooth_curve,
)

from .corners import (
    collapse_collinear,
    fillet_corners,
    tight_corners,
    _tight_runs,
    trim_tight_corners,
)

from .thin import (
    cut_thin_sections,
)

from .tube import (
    circle_tangent_point,
    interpolate_guide,
    rod_centre_path,
    tangent_offset_points,
)

from .sheet import (
    bend_allowance_mm,
)

from .optimization import (
    curve_curvature,
    optimize_curve,
    resample_by_count,
    turn_angle_at,
    turn_limit,
)

__all__ = [
    "v_add",
    "v_sub",
    "v_mul",
    "v_lerp",
    "dot",
    "cross",
    "length",
    "dist",
    "unit",
    "left_normal",
    "signed_area",
    "polyline_length",
    "signed_turn",
    "turn_angle",
    "vertex_radius",
    "min_radius",
    "max_turn_deg",
    "dedupe",
    "point_to_segment_distance",
    "point_to_polyline_distance",
    "polyline_max_deviation",
    "point_on_segment",
    "point_in_polygon",
    "contour_inside",
    "_segments_strictly_intersect",
    "count_self_intersections",
    "resample",
    "_chord_for_radius",
    "densify",
    "_dp_indices",
    "simplify",
    "sharp_corners",
    "_chaikin_open",
    "_chaikin_closed",
    "chaikin",
    "laplacian",
    "limit_curvature",
    "evaluate_bezier_cubic",
    "approximate_smooth_curve",
    "collapse_collinear",
    "fillet_corners",
    "tight_corners",
    "_tight_runs",
    "trim_tight_corners",
    "cut_thin_sections",
    "bend_allowance_mm",
    "circle_tangent_point",
    "interpolate_guide",
    "rod_centre_path",
    "tangent_offset_points",
    "curve_curvature",
    "optimize_curve",
    "resample_by_count",
    "turn_angle_at",
    "turn_limit",
]
