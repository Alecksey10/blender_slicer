"""Declarative GUI schema for the Blender N-panel.

The panel builder does not know what a fillet is.  It reads sections/fields
from this file, rendered through ``adapters.base.ui`` — the same schema model a
Qt or Unreal adapter would consume.  Method descriptors still own defaults and
ranges; this file owns layout, labels and conditional visibility.
"""

from __future__ import annotations

import traceback
from typing import Any

from ...adapters.base.ui import Field, Section, make_field
from .i18n import tr


SECTIONS: tuple[Section, ...] = (
    Section(
        id="source",
        title="Source",
        open=True,
        fields=(
            make_field("source_object"),
            make_field("unit_scale_mm", "1 BU = mm"),
        ),
    ),
    Section(
        id="plan",
        title="Slice plan",
        open=True,
        fields=(
            make_field("slice_mode"),
            make_field("axis"),
            make_field("count"),
            make_field(
                "spacing_auto",
                "Auto spacing",
                visible={"prop": "slice_mode", "equals": "PLANAR"},
            ),
            make_field(
                "spacing_mm",
                "Spacing (mm)",
                visible=[
                    {"prop": "slice_mode", "equals": "PLANAR"},
                    {"prop": "spacing_auto", "truthy": False},
                ],
            ),
            make_field(
                "offset_mm", "Offset (mm)", visible={"prop": "slice_mode", "equals": "PLANAR"}
            ),
            make_field(
                "centered",
                "Centered on object",
                visible={"prop": "slice_mode", "equals": "PLANAR"},
            ),
            make_field(
                "angle_start_deg", "Start angle", visible={"prop": "slice_mode", "equals": "RADIAL"}
            ),
            make_field(
                "angle_end_deg", "End angle", visible={"prop": "slice_mode", "equals": "RADIAL"}
            ),
            make_field("origin_offset_mm", "Origin offset (mm)"),
        ),
    ),
    Section(
        id="optimize",
        title="Least-squares optimizer",
        open=True,
        fields=(
            make_field("optimize_enabled"),
            make_field(
                "optimize_points",
                "Curve samples",
                visible={"prop": "optimize_enabled", "truthy": True},
            ),
            make_field(
                "optimize_data_weight",
                "Data weight",
                visible={"prop": "optimize_enabled", "truthy": True},
            ),
            make_field(
                "optimize_smooth",
                "Smooth (length, mm)",
                visible={"prop": "optimize_enabled", "truthy": True},
            ),
            make_field(
                "optimize_use_material_min_radius",
                "Use material min radius",
                visible={"prop": "optimize_enabled", "truthy": True},
            ),
            make_field(
                "optimize_min_radius_mm",
                "Minimum radius (mm)",
                visible={"prop": "optimize_enabled", "truthy": True},
            ),
            make_field(
                "optimize_radius_weight",
                "Bend radius penalty",
                visible={"prop": "optimize_enabled", "truthy": True},
            ),
            make_field(
                "optimize_max_iterations",
                "Max iterations",
                visible={"prop": "optimize_enabled", "truthy": True},
            ),
            make_field(
                "optimize_cost_tolerance",
                "Cost tolerance",
                visible={"prop": "optimize_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="material",
        title="Material",
        fields=(
            make_field("material_thickness_mm", "Thickness (mm)"),
            make_field("material_min_bend_radius_mm", "Min bend radius (mm)"),
            make_field("material_max_bend_angle_deg", "Max bend angle (deg)"),
            make_field("material_min_segment_mm", "Min segment (mm)"),
            make_field("material_kerf_mm", "Kerf (mm)"),
            make_field("material_k_factor", "K-factor"),
        ),
    ),
    Section(
        id="simplify",
        title="Simplify",
        fields=(
            make_field("simplify_enabled"),
            make_field(
                "simplify_tolerance_mm",
                "Tolerance (mm)",
                visible={"prop": "simplify_enabled", "truthy": True},
            ),
            make_field(
                "simplify_preserve_corners_deg",
                "Preserve corners (deg)",
                visible={"prop": "simplify_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="densify",
        title="Densify",
        fields=(
            make_field("densify_enabled"),
            make_field(
                "densify_max_spacing_mm",
                "Max spacing (mm)",
                visible={"prop": "densify_enabled", "truthy": True},
            ),
            make_field(
                "densify_max_angle_step_deg",
                "Max angle step (deg)",
                visible={"prop": "densify_enabled", "truthy": True},
            ),
            make_field(
                "densify_chord_tolerance_mm",
                "Chord tolerance (mm)",
                visible={"prop": "densify_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="resample",
        title="Resample",
        fields=(
            make_field("resample_enabled"),
            make_field(
                "resample_spacing_mm",
                "Spacing (mm)",
                visible={"prop": "resample_enabled", "truthy": True},
            ),
            make_field(
                "resample_adaptive",
                "Adaptive spacing",
                visible={"prop": "resample_enabled", "truthy": True},
            ),
            make_field(
                "resample_min_spacing_mm",
                "Minimum spacing (mm)",
                visible={"prop": "resample_enabled", "truthy": True},
            ),
            make_field(
                "resample_chord_tolerance_mm",
                "Chord tolerance (mm)",
                visible={"prop": "resample_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="offsets",
        title="Cut offsets",
        fields=(
            make_field("inset_enabled"),
            make_field(
                "inset_x_mode", "X cuts", visible={"prop": "inset_enabled", "truthy": True}
            ),
            make_field(
                "inset_y_mode", "Y cuts", visible={"prop": "inset_enabled", "truthy": True}
            ),
            make_field(
                "inset_z_mode", "Z cuts", visible={"prop": "inset_enabled", "truthy": True}
            ),
            make_field(
                "inset_auto",
                "At least material radius",
                visible={"prop": "inset_enabled", "truthy": True},
            ),
            make_field(
                "inset_amount_mm",
                "Offset (mm)",
                visible={"prop": "inset_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="shrink",
        title="Section shrink",
        fields=(
            make_field("shrink_enabled"),
            make_field(
                "shrink_percent",
                "Shrink (%)",
                visible={"prop": "shrink_enabled", "truthy": True},
            ),
            make_field(
                "shrink_mode",
                "Shrink profile",
                visible={"prop": "shrink_enabled", "truthy": True},
            ),
            make_field(
                "shrink_smooth_iterations",
                "Smooth iterations",
                visible={"prop": "shrink_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="contacts",
        title="Contacts",
        fields=(
            make_field("contacts_enabled"),
            make_field(
                "contacts_gap_mm",
                "Contact gap (mm)",
                visible={"prop": "contacts_enabled", "truthy": True},
            ),
            make_field(
                "contact_marker_mm",
                "Contact marker",
                visible={"prop": "contacts_enabled", "truthy": True},
            ),
            make_field(
                "contacts_include_same",
                "Same pass too",
                visible={"prop": "contacts_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="performance",
        title="Performance",
        fields=(
            make_field("threads", "Worker threads"),
            make_field("use_background", "Background processing"),
            make_field("show_all_layers", "Show all layers"),
        ),
    ),
    Section(
        id="output",
        title="Output",
        fields=(
            make_field("build_curves", "Build curves in scene"),
            make_field(
                "curve_radius_mm",
                "Curve radius (mm)",
                visible={"prop": "build_curves", "truthy": True},
            ),
            make_field("check_self_intersections", "Check self-intersections"),
        ),
    ),
    Section(
        id="fillet",
        group="legacy",
        title="Fillet corners",
        fields=(
            make_field("fillet_enabled"),
            make_field(
                "fillet_radius_mm", "Radius (mm)", visible={"prop": "fillet_enabled", "truthy": True}
            ),
            make_field(
                "fillet_min_turn_deg",
                "Min turn (deg)",
                visible={"prop": "fillet_enabled", "truthy": True},
            ),
            make_field(
                "fillet_arc_segments",
                "Arc segments",
                visible={"prop": "fillet_enabled", "truthy": True},
            ),
            make_field(
                "fillet_chord_tolerance_mm",
                "Chord tolerance (mm)",
                visible={"prop": "fillet_enabled", "truthy": True},
            ),
            make_field(
                "fillet_mode", "If it does not fit", visible={"prop": "fillet_enabled", "truthy": True}
            ),
            make_field(
                "fillet_check_material",
                "Check material radius",
                visible={"prop": "fillet_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="cut_thin",
        group="legacy",
        title="Cut thin sections",
        fields=(
            make_field("cut_thin_enabled"),
            make_field(
                "cut_thin_min_width_mm",
                "Min width (mm)",
                visible={"prop": "cut_thin_enabled", "truthy": True},
            ),
            make_field(
                "cut_thin_corner_turn_deg",
                "Min corner turn (deg)",
                visible={"prop": "cut_thin_enabled", "truthy": True},
            ),
            make_field(
                "cut_thin_max_removed_ratio",
                "Max removed ratio",
                visible={"prop": "cut_thin_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="trim_tight",
        group="legacy",
        title="Trim tight corners",
        fields=(
            make_field("trim_tight_enabled"),
            make_field(
                "trim_tight_radius_mm",
                "Fillet radius (mm)",
                visible={"prop": "trim_tight_enabled", "truthy": True},
            ),
            make_field(
                "trim_tight_min_turn_deg",
                "Min corner turn (deg)",
                visible={"prop": "trim_tight_enabled", "truthy": True},
            ),
            make_field(
                "trim_tight_max_removed_ratio",
                "Max removed ratio",
                visible={"prop": "trim_tight_enabled", "truthy": True},
            ),
            make_field(
                "trim_tight_action",
                "If it does not fit",
                visible={"prop": "trim_tight_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="smooth",
        group="legacy",
        title="Smooth curve approx",
        fields=(
            make_field("smooth_curve_enabled"),
            make_field(
                "smooth_curve_mode",
                "Fit mode",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
            make_field(
                "smooth_curve_tension",
                "Curve tension",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
            make_field(
                "smooth_curve_max_deviation_mm",
                "Max deviation (mm)",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
            make_field(
                "smooth_curve_chord_tolerance_mm",
                "Chord tolerance (mm)",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
            make_field(
                "smooth_curve_max_spacing_mm",
                "Max spacing (mm)",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
            make_field(
                "smooth_curve_segments_per_span",
                "Segments per span",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
            make_field(
                "smooth_curve_preserve_corners_deg",
                "Preserve corners (deg)",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
            make_field(
                "smooth_curve_inertia_smoothing",
                "Inertia passes",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
            make_field(
                "smooth_curve_inertia",
                "Overall inertia",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
            make_field(
                "smooth_curve_use_material_min_radius",
                "Use material min radius",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
            make_field(
                "smooth_curve_min_radius_mm",
                "Min radius (mm)",
                visible={"prop": "smooth_curve_enabled", "truthy": True},
            ),
        ),
    ),
    Section(
        id="curvature",
        group="legacy",
        title="Limit curvature",
        fields=(
            make_field("limit_curvature_enabled"),
            make_field(
                "limit_curvature_use_material",
                "Use material minimum",
                visible={"prop": "limit_curvature_enabled", "truthy": True},
            ),
            make_field(
                "limit_curvature_min_radius_mm",
                "Minimum radius (mm)",
                visible={"prop": "limit_curvature_enabled", "truthy": True},
            ),
            make_field(
                "limit_curvature_max_iterations",
                "Max iterations",
                visible={"prop": "limit_curvature_enabled", "truthy": True},
            ),
            make_field(
                "limit_curvature_weight",
                "Weight",
                visible={"prop": "limit_curvature_enabled", "truthy": True},
            ),
            make_field(
                "limit_curvature_strict",
                "Fail if not converged",
                visible={"prop": "limit_curvature_enabled", "truthy": True},
            ),
        ),
    ),

)

GUI_SCHEMA_FIELDS: tuple[Field, ...] = tuple(
    field for section in SECTIONS for field in section.fields
)


def _field_text(settings, item: Field) -> str:
    """Localized label: the schema label, else the RNA property name."""

    if item.label:
        return tr(item.label)
    try:
        return tr(settings.bl_rna.properties[item.prop].name)
    except (AttributeError, KeyError):
        return item.prop


def is_visible(settings, item: Field) -> bool:
    return all(condition.evaluate(settings) for condition in item.visible_when)


def draw_sections(layout, settings, sections: tuple[Section, ...] = SECTIONS, boxed: bool = True) -> None:
    """Draw fields from the schema.

    ``boxed`` adds the section title box, which is redundant inside a sub-panel.
    A broken field is shown inline instead of aborting the whole panel draw:
    Blender would otherwise silently truncate the panel and hide everything
    below it.
    """

    for section in sections:
        container = layout.box() if boxed else layout
        if boxed:
            container.label(text=tr(section.title))
        for item in section.fields:
            try:
                if not is_visible(settings, item):
                    continue
                row = container.row()
                row.prop(settings, item.prop, text=_field_text(settings, item))
            except Exception as exc:  # noqa: BLE001 - surface, never hide
                traceback.print_exc()
                container.label(text=f"{item.prop}: {exc}", icon="ERROR")
