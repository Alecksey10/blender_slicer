"""Declarative GUI schema for the Blender N-panel.

The panel builder does not know what a fillet is.  It reads sections/fields
from this file.  Method descriptors still own defaults and ranges; this file
owns layout, labels and conditional visibility.
"""

from __future__ import annotations

import traceback
from typing import Any


def _visible(settings, conditions: tuple[dict[str, Any], ...]) -> bool:
    for cond in conditions:
        value = getattr(settings, cond["prop"], None)
        if "equals" in cond and value != cond["equals"]:
            return False
        if "not_equals" in cond and value == cond["not_equals"]:
            return False
        if "truthy" in cond and bool(value) != bool(cond["truthy"]):
            return False
    return True


def _field(
    prop: str, label: str | None = None, visible: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One row of a section.

    ``visible`` holds a single condition, e.g. ``{"prop": "slice_mode",
    "equals": "PLANAR"}``; ``_visible`` reads its keys.  It must be stored
    as-is — wrapping it into another dict made every conditional row raise and
    aborted the whole panel draw.
    """
    return {"prop": prop, "label": label, "visible_if": (visible,) if visible else ()}


SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "source",
        "title": "Source",
        "open": True,
        "fields": (
            _field("source_object"),
            _field("unit_scale_mm", "1 BU = mm"),
        ),
    },
    {
        "id": "plan",
        "title": "Slice plan",
        "open": True,
        "fields": (
            _field("slice_mode"),
            _field("axis"),
            _field("count"),
            _field("spacing_mm", "Spacing (mm)", visible={"prop": "slice_mode", "equals": "PLANAR"}),
            _field("offset_mm", "Offset (mm)", visible={"prop": "slice_mode", "equals": "PLANAR"}),
            _field("centered", "Centered on object", visible={"prop": "slice_mode", "equals": "PLANAR"}),
            _field("angle_start_deg", "Start angle", visible={"prop": "slice_mode", "equals": "RADIAL"}),
            _field("angle_end_deg", "End angle", visible={"prop": "slice_mode", "equals": "RADIAL"}),
            _field("origin_offset_mm", "Origin offset (mm)"),
        ),
    },
    {
        "id": "material",
        "title": "Material",
        "fields": (
            _field("material_thickness_mm", "Thickness (mm)"),
            _field("material_min_bend_radius_mm", "Min bend radius (mm)"),
            _field("material_max_bend_angle_deg", "Max bend angle (deg)"),
            _field("material_min_segment_mm", "Min segment (mm)"),
            _field("material_kerf_mm", "Kerf (mm)"),
            _field("material_k_factor", "K-factor"),
        ),
    },
    {
        "id": "fillet",
        "title": "Fillet corners",
        "fields": (
            _field("fillet_enabled"),
            _field("fillet_radius_mm", "Radius (mm)", visible={"prop": "fillet_enabled", "truthy": True}),
            _field("fillet_min_turn_deg", "Min turn (deg)", visible={"prop": "fillet_enabled", "truthy": True}),
            _field("fillet_arc_segments", "Arc segments", visible={"prop": "fillet_enabled", "truthy": True}),
            _field("fillet_chord_tolerance_mm", "Chord tolerance (mm)", visible={"prop": "fillet_enabled", "truthy": True}),
            _field("fillet_mode", "If it does not fit", visible={"prop": "fillet_enabled", "truthy": True}),
            _field("fillet_check_material", "Check material radius", visible={"prop": "fillet_enabled", "truthy": True}),
        ),
    },
    {
        "id": "smooth",
        "title": "Smooth",
        "fields": (
            _field("smooth_enabled"),
            _field("smooth_algorithm", "Algorithm", visible={"prop": "smooth_enabled", "truthy": True}),
            _field("smooth_iterations", "Iterations", visible={"prop": "smooth_enabled", "truthy": True}),
            _field("smooth_preserve_corners_deg", "Preserve corners (deg)", visible={"prop": "smooth_enabled", "truthy": True}),
            _field("smooth_max_deviation_mm", "Max deviation (mm)", visible={"prop": "smooth_enabled", "truthy": True}),
            _field("smooth_weight", "Laplacian weight", visible={"prop": "smooth_enabled", "truthy": True}),
        ),
    },
    {
        "id": "simplify",
        "title": "Simplify",
        "fields": (
            _field("simplify_enabled"),
            _field("simplify_tolerance_mm", "Tolerance (mm)", visible={"prop": "simplify_enabled", "truthy": True}),
            _field("simplify_preserve_corners_deg", "Preserve corners (deg)", visible={"prop": "simplify_enabled", "truthy": True}),
        ),
    },
    {
        "id": "densify",
        "title": "Densify",
        "fields": (
            _field("densify_enabled"),
            _field("densify_max_spacing_mm", "Max spacing (mm)", visible={"prop": "densify_enabled", "truthy": True}),
            _field("densify_max_angle_step_deg", "Max angle step (deg)", visible={"prop": "densify_enabled", "truthy": True}),
            _field("densify_chord_tolerance_mm", "Chord tolerance (mm)", visible={"prop": "densify_enabled", "truthy": True}),
        ),
    },
    {
        "id": "resample",
        "title": "Resample",
        "fields": (
            _field("resample_enabled"),
            _field("resample_spacing_mm", "Spacing (mm)", visible={"prop": "resample_enabled", "truthy": True}),
            _field("resample_adaptive", "Adaptive spacing", visible={"prop": "resample_enabled", "truthy": True}),
            _field("resample_min_spacing_mm", "Minimum spacing (mm)", visible={"prop": "resample_enabled", "truthy": True}),
            _field("resample_chord_tolerance_mm", "Chord tolerance (mm)", visible={"prop": "resample_enabled", "truthy": True}),
        ),
    },
    {
        "id": "curvature",
        "title": "Limit curvature",
        "fields": (
            _field("limit_curvature_enabled"),
            _field("limit_curvature_use_material", "Use material minimum", visible={"prop": "limit_curvature_enabled", "truthy": True}),
            _field("limit_curvature_min_radius_mm", "Minimum radius (mm)", visible={"prop": "limit_curvature_enabled", "truthy": True}),
            _field("limit_curvature_max_iterations", "Max iterations", visible={"prop": "limit_curvature_enabled", "truthy": True}),
            _field("limit_curvature_weight", "Weight", visible={"prop": "limit_curvature_enabled", "truthy": True}),
            _field("limit_curvature_strict", "Fail if not converged", visible={"prop": "limit_curvature_enabled", "truthy": True}),
        ),
    },
    {
        "id": "output",
        "title": "Output",
        "fields": (
            _field("build_curves", "Build curves in scene"),
            _field("curve_radius_mm", "Curve radius (mm)", visible={"prop": "build_curves", "truthy": True}),
            _field("check_self_intersections", "Check self-intersections"),
        ),
    },
)


def draw_sections(layout, settings, sections=SECTIONS, boxed: bool = True) -> None:
    """Draw fields from the schema.

    ``boxed`` adds the section title box, which is redundant inside a sub-panel.
    A broken field is shown inline instead of aborting the whole panel draw:
    Blender would otherwise silently truncate the panel and hide everything
    below it.
    """
    for section in sections:
        container = layout.box() if boxed else layout
        if boxed:
            container.label(text=section["title"])
        for item in section["fields"]:
            try:
                if not _visible(settings, item["visible_if"]):
                    continue
                row = container.row()
                label = item.get("label")
                if label:
                    row.prop(settings, item["prop"], text=label)
                else:
                    row.prop(settings, item["prop"])
            except Exception as exc:  # noqa: BLE001 - surface, never hide
                traceback.print_exc()
                container.label(text=f"{item['prop']}: {exc}", icon="ERROR")
