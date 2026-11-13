import bpy

from blender_slicer.adapters.base.events import BUS, TOPIC_SETTINGS_CHANGED


def _poll_mesh(self, obj) -> bool:
    return obj is not None and obj.type == "MESH"


def _mark_dirty(self, context) -> None:
    self.revision = int(getattr(self, "revision", 0)) + 1
    self.dirty = True
    self.status = "Settings changed - generate slices"
    BUS.publish(TOPIC_SETTINGS_CHANGED, settings=self, context=context)


class SlicerSettings(bpy.types.PropertyGroup):
    # ------------------------------------------------------------- source
    source_object: bpy.props.PointerProperty(
        name="Source mesh",
        description="Mesh object to slice",
        type=bpy.types.Object,
        poll=_poll_mesh,
        update=_mark_dirty,
    )
    unit_scale_mm: bpy.props.FloatProperty(
        name="1 BU in mm",
        description="Conversion from Blender units to millimetres (1 m = 1000 mm)",
        default=1000.0,
        min=0.001,
        soft_max=10000.0,
        step=1.0,
        update=_mark_dirty,
    )

    # ------------------------------------------------------------ slice plan
    slice_mode: bpy.props.EnumProperty(
        name="Slice mode",
        items=(
            ("PLANAR", "Planar stack", "Parallel planes along an axis"),
            ("RADIAL", "Radial fan", "Planes rotating around an axis"),
        ),
        default="PLANAR",
        update=_mark_dirty,
    )
    axis: bpy.props.EnumProperty(
        name="Axis",
        items=(("X", "X", "X axis"), ("Y", "Y", "Y axis"), ("Z", "Z", "Z axis")),
        default="Z",
        update=_mark_dirty,
    )
    count: bpy.props.IntProperty(
        name="Count", default=20, min=1, max=512, step=1, update=_mark_dirty
    )
    spacing_mm: bpy.props.FloatProperty(
        name="Spacing", default=5.0, min=0.001, soft_max=1000.0, step=0.1,
        update=_mark_dirty,
    )
    spacing_auto: bpy.props.BoolProperty(
        name="Auto spacing",
        description=(
            "Distribute the slices evenly across the model along the active "
            "axis: spacing = model extent / count"
        ),
        default=False,
        update=_mark_dirty,
    )
    offset_mm: bpy.props.FloatProperty(
        name="Offset", default=0.0, step=0.1, update=_mark_dirty
    )
    centered: bpy.props.BoolProperty(
        name="Centered", default=True, update=_mark_dirty
    )
    angle_start_deg: bpy.props.FloatProperty(
        name="Start angle", default=0.0, min=-3600.0, max=3600.0, step=1.0,
        update=_mark_dirty,
    )
    angle_end_deg: bpy.props.FloatProperty(
        name="End angle", default=360.0, min=-3600.0, max=3600.0, step=1.0,
        update=_mark_dirty,
    )
    origin_offset_mm: bpy.props.FloatVectorProperty(
        name="Origin offset", default=(0.0, 0.0, 0.0), size=3, subtype="TRANSLATION",
        update=_mark_dirty,
    )

    # --------------------------------------------------------------- material
    material_thickness_mm: bpy.props.FloatProperty(
        name="Thickness", default=3.0, min=0.001, step=0.1, update=_mark_dirty
    )
    material_min_bend_radius_mm: bpy.props.FloatProperty(
        name="Min bend radius", default=6.0, min=0.001, step=0.1, update=_mark_dirty
    )
    material_max_bend_angle_deg: bpy.props.FloatProperty(
        name="Max bend angle", default=120.0, min=0.0, max=180.0, step=1.0,
        update=_mark_dirty,
    )
    material_min_segment_mm: bpy.props.FloatProperty(
        name="Min segment", default=0.4, min=0.0001, step=0.01, update=_mark_dirty
    )
    material_kerf_mm: bpy.props.FloatProperty(
        name="Kerf", default=0.15, min=0.0, step=0.01, update=_mark_dirty
    )
    material_k_factor: bpy.props.FloatProperty(
        name="K-factor", default=0.42, min=0.0, max=1.0, step=0.01, update=_mark_dirty
    )

    # ----------------------------------------------------------------- fillet
    fillet_enabled: bpy.props.BoolProperty(name="Fillet corners", default=True, update=_mark_dirty)
    fillet_radius_mm: bpy.props.FloatProperty(
        name="Radius", default=4.0, min=0.0, step=0.1, update=_mark_dirty
    )
    fillet_min_turn_deg: bpy.props.FloatProperty(
        name="Min turn", default=20.0, min=0.0, max=179.0, step=1.0,
        update=_mark_dirty,
    )
    fillet_arc_segments: bpy.props.IntProperty(
        name="Arc segments", default=3, min=1, max=64, step=1, update=_mark_dirty
    )
    fillet_chord_tolerance_mm: bpy.props.FloatProperty(
        name="Chord tolerance", default=0.05, min=0.0, step=0.01, update=_mark_dirty
    )
    fillet_mode: bpy.props.EnumProperty(
        name="If radius does not fit",
        items=(
            ("clamp", "Clamp and warn", "Use the largest radius that fits"),
            ("error", "Fail slice", "Return the slice unchanged with an error"),
            ("skip", "Skip corner", "Leave the sharp corner"),
        ),
        default="clamp",
        update=_mark_dirty,
    )
    fillet_check_material: bpy.props.BoolProperty(
        name="Check material radius", default=True, update=_mark_dirty
    )

    # -------------------------------------------------------- cut thin sections
    cut_thin_enabled: bpy.props.BoolProperty(
        name="Cut thin sections",
        description=(
            "Remove thin tabs/necks that are narrower than the fillet radius, "
            "so the fillet stage no longer fails on them. Runs before fillet."
        ),
        default=False,
        update=_mark_dirty,
    )
    cut_thin_min_width_mm: bpy.props.FloatProperty(
        name="Min width (mm)",
        description=(
            "Sections narrower than this are cut off. "
            "Set to 2 x fillet radius so corners have room on both sides."
        ),
        default=8.0,
        min=0.1,
        step=0.1,
        update=_mark_dirty,
    )
    cut_thin_corner_turn_deg: bpy.props.FloatProperty(
        name="Min corner turn",
        description="Only corners with a turn above this angle are considered",
        default=20.0,
        min=0.0,
        max=179.0,
        step=1.0,
        update=_mark_dirty,
    )
    cut_thin_max_removed_ratio: bpy.props.FloatProperty(
        name="Max removed ratio",
        description=(
            "Safety limit: if more than this fraction of vertices would be "
            "removed, the contour is kept unchanged."
        ),
        default=0.5,
        min=0.0,
        max=1.0,
        step=0.05,
        update=_mark_dirty,
    )

    # ------------------------------------------------------- trim tight corners
    trim_tight_enabled: bpy.props.BoolProperty(
        name="Trim tight corners",
        description=(
            "Cut sections that are too tight for the requested fillet radius "
            "and join the curve where the full radius fits. Runs before fillet; "
            "disable to keep the current clamp/skip behaviour."
        ),
        default=False,
        update=_mark_dirty,
    )
    trim_tight_radius_mm: bpy.props.FloatProperty(
        name="Fillet radius (mm)",
        description=(
            "Radius that must fit after trimming. Usually the same as the "
            "fillet radius."
        ),
        default=4.0,
        min=0.0,
        step=0.1,
        update=_mark_dirty,
    )
    trim_tight_min_turn_deg: bpy.props.FloatProperty(
        name="Min corner turn",
        description="Only corners with a turn above this angle are trimmed",
        default=20.0,
        min=0.0,
        max=179.0,
        step=1.0,
        update=_mark_dirty,
    )
    trim_tight_max_removed_ratio: bpy.props.FloatProperty(
        name="Max removed ratio",
        description=(
            "Safety limit: trimming stops before more than this fraction of "
            "the contour vertices is removed"
        ),
        default=0.5,
        min=0.0,
        max=1.0,
        step=0.05,
        update=_mark_dirty,
    )
    trim_tight_action: bpy.props.EnumProperty(
        name="If radius does not fit",
        items=(
            (
                "trim",
                "Trim the curve",
                "Cut the too-tight section and join across it",
            ),
            (
                "ignore",
                "Leave it to fillet",
                "Keep the contour; fillet clamps or skips the corner as before",
            ),
        ),
        default="trim",
        update=_mark_dirty,
    )

    # ------------------------------------------------- smooth curve approx
    smooth_curve_enabled: bpy.props.BoolProperty(
        name="Smooth curve approx", default=True, update=_mark_dirty
    )
    smooth_curve_mode: bpy.props.EnumProperty(
        name="Fit mode",
        items=(
            ("interpolate", "Interpolate", "Passes exactly through every point (corners kept)"),
            ("approximate", "Approximate", "Simplifies first, deviation bounded by max deviation"),
            ("hybrid", "Hybrid", "Light inertia blur, then interpolate"),
        ),
        default="approximate",
        update=_mark_dirty,
    )
    smooth_curve_tension: bpy.props.FloatProperty(
        name="Curve tension",
        description="0.0 = straight chords; 1.0 = tight Catmull-Rom curves",
        default=0.4,
        min=0.0,
        max=1.0,
        step=0.05,
        update=_mark_dirty,
    )
    smooth_curve_max_deviation_mm: bpy.props.FloatProperty(
        name="Max deviation (mm)",
        description="0 = exact fit; otherwise output stays within this of the source",
        default=0.2,
        min=0.0,
        step=0.01,
        update=_mark_dirty,
    )
    smooth_curve_chord_tolerance_mm: bpy.props.FloatProperty(
        name="Chord tolerance (mm)",
        description="Adaptive detail: smaller = more samples on tight curves, fewer on flat spans. 0 = uniform segments_per_span",
        default=0.05,
        min=0.0,
        step=0.01,
        update=_mark_dirty,
    )
    smooth_curve_max_spacing_mm: bpy.props.FloatProperty(
        name="Max spacing (mm)",
        description="0 disables",
        default=0.0,
        min=0.0,
        step=0.1,
        update=_mark_dirty,
    )
    smooth_curve_segments_per_span: bpy.props.IntProperty(
        name="Segments per span",
        description="Uniform samples per span when chord tolerance is 0",
        default=8,
        min=2,
        max=64,
        step=1,
        update=_mark_dirty,
    )
    smooth_curve_preserve_corners_deg: bpy.props.FloatProperty(
        name="Preserve corners (deg)",
        description="Turns sharper than this stay exact corners; spline is split there",
        default=0.0,
        min=0.0,
        max=180.0,
        step=1.0,
        update=_mark_dirty,
    )
    smooth_curve_inertia_smoothing: bpy.props.IntProperty(
        name="Inertia passes",
        description="Optional pre-blur; 0 keeps sharp features",
        default=0,
        min=0,
        max=10,
        step=1,
        update=_mark_dirty,
    )
    smooth_curve_inertia: bpy.props.FloatProperty(
        name="Overall inertia",
        description=(
            "0.0 = exact following of every point; 1.0 = degenerates into a "
            "best-fit circle; intermediate values blend progressively"
        ),
        default=0.0,
        min=0.0,
        max=1.0,
        step=0.05,
        update=_mark_dirty,
    )
    smooth_curve_use_material_min_radius: bpy.props.BoolProperty(
        name="Use material min bend radius", default=False, update=_mark_dirty
    )
    smooth_curve_min_radius_mm: bpy.props.FloatProperty(
        name="Min radius (mm)",
        default=0.0,
        min=0.0,
        step=0.1,
        update=_mark_dirty,
    )

    # -------------------------------------------------- tube path (group B)
    tube_path_enabled: bpy.props.BoolProperty(
        name="Tube path (group B)", default=False, update=_mark_dirty
    )
    tube_path_rod_radius_mm: bpy.props.FloatProperty(
        name="Rod radius (mm)",
        description="Radius of the rod/tube; centreline is offset by this from the guide",
        default=3.0,
        min=0.0,
        step=0.1,
        update=_mark_dirty,
    )
    tube_path_side: bpy.props.EnumProperty(
        name="Offset side",
        items=(
            ("outer", "Outer", "Rod centre to the left of travel (outside the guide)"),
            ("inner", "Inner", "Rod centre to the right of travel (inside the guide)"),
            ("center", "Center", "No offset — centreline follows the guide"),
        ),
        default="outer",
        update=_mark_dirty,
    )
    tube_path_use_cross_sections: bpy.props.BoolProperty(
        name="Use cross-sections",
        description="Build contact points in perpendicular planes across neighbouring slices",
        default=False,
        update=_mark_dirty,
    )
    tube_path_cross_section_step_mm: bpy.props.FloatProperty(
        name="Cross-section step (mm)",
        default=5.0,
        min=0.5,
        step=0.5,
        update=_mark_dirty,
    )
    tube_path_guide_group_tag: bpy.props.StringProperty(
        name="Guide group tag",
        description="Tag identifying group-A guide contours across slices",
        default="group_a",
        update=_mark_dirty,
    )
    tube_path_contact_tolerance_mm: bpy.props.FloatProperty(
        name="Contact tolerance (mm)",
        default=0.05,
        min=0.0,
        step=0.01,
        update=_mark_dirty,
    )
    tube_path_tension: bpy.props.FloatProperty(
        name="Curve tension",
        default=0.5,
        min=0.0,
        max=1.0,
        step=0.05,
        update=_mark_dirty,
    )
    tube_path_arc_segments: bpy.props.IntProperty(
        name="Arc segments",
        default=8,
        min=1,
        max=64,
        step=1,
        update=_mark_dirty,
    )

    # ---------------------------------------------------------------- simplify
    simplify_enabled: bpy.props.BoolProperty(name="Simplify", default=True, update=_mark_dirty)
    simplify_tolerance_mm: bpy.props.FloatProperty(
        name="Tolerance", default=0.05, min=0.0, step=0.01, update=_mark_dirty
    )
    simplify_preserve_corners_deg: bpy.props.FloatProperty(
        name="Preserve corners", default=70.0, min=0.0, max=180.0, step=1.0,
        update=_mark_dirty,
    )

    # ----------------------------------------------------------------- densify
    densify_enabled: bpy.props.BoolProperty(name="Densify", default=True, update=_mark_dirty)
    densify_max_spacing_mm: bpy.props.FloatProperty(
        name="Max spacing", default=2.0, min=0.001, step=0.1, update=_mark_dirty
    )
    densify_max_angle_step_deg: bpy.props.FloatProperty(
        name="Max angle step", default=12.0, min=0.0, max=180.0, step=1.0,
        update=_mark_dirty,
    )
    densify_chord_tolerance_mm: bpy.props.FloatProperty(
        name="Chord tolerance", default=0.05, min=0.0, step=0.01, update=_mark_dirty
    )

    # ---------------------------------------------------------------- resample
    resample_enabled: bpy.props.BoolProperty(name="Resample", default=False, update=_mark_dirty)
    resample_spacing_mm: bpy.props.FloatProperty(
        name="Spacing", default=2.0, min=0.001, step=0.1, update=_mark_dirty
    )
    resample_adaptive: bpy.props.BoolProperty(
        name="Adaptive spacing", default=False, update=_mark_dirty
    )
    resample_min_spacing_mm: bpy.props.FloatProperty(
        name="Minimum spacing", default=0.1, min=0.001, step=0.05, update=_mark_dirty
    )
    resample_chord_tolerance_mm: bpy.props.FloatProperty(
        name="Chord tolerance", default=0.05, min=0.0, step=0.01, update=_mark_dirty
    )

    # -------------------------------------------------------- limit curvature
    limit_curvature_enabled: bpy.props.BoolProperty(
        name="Limit curvature", default=False, update=_mark_dirty
    )
    limit_curvature_use_material: bpy.props.BoolProperty(
        name="Use material minimum", default=True, update=_mark_dirty
    )
    limit_curvature_min_radius_mm: bpy.props.FloatProperty(
        name="Minimum radius", default=6.0, min=0.001, step=0.1, update=_mark_dirty
    )
    limit_curvature_max_iterations: bpy.props.IntProperty(
        name="Max iterations", default=20, min=1, max=200, step=1, update=_mark_dirty
    )
    limit_curvature_weight: bpy.props.FloatProperty(
        name="Weight", default=0.5, min=0.05, max=1.0, step=0.05, update=_mark_dirty
    )
    limit_curvature_strict: bpy.props.BoolProperty(
        name="Fail if not converged", default=False, update=_mark_dirty
    )

    # ------------------------------------------------------------- optimizer
    optimize_enabled: bpy.props.BoolProperty(
        name="Optimize curve",
        description=(
            "Fit the contour with one constrained least-squares solve "
            "(data + bending energy + bend radius) instead of relying on the "
            "sequential shaping stages. While it is on, fillet, cut thin, "
            "trim tight, smoothing and curvature limiting are skipped: they "
            "would fight the global fit over the same corners."
        ),
        default=True,
        update=_mark_dirty,
    )
    optimize_points: bpy.props.IntProperty(
        name="Curve samples",
        description="Points the contour is resampled to before the solve",
        default=150,
        min=8,
        max=4000,
        step=1,
        update=_mark_dirty,
    )
    optimize_data_weight: bpy.props.FloatProperty(
        name="Data weight",
        description="Pull towards the measured points; higher keeps detail",
        default=20.0,
        min=0.0,
        soft_max=200.0,
        step=1.0,
        update=_mark_dirty,
    )
    optimize_smooth: bpy.props.FloatProperty(
        name="Smooth (length, mm)",
        description=(
            "Smoothing length of the 'smooth' term: the scale over which the "
            "fit may trade data for a straighter curve. 0 follows every "
            "measured wobble; 5-10 mm irons out noise while keeping corners."
        ),
        default=2.0,
        min=0.0,
        soft_max=50.0,
        step=0.5,
        update=_mark_dirty,
    )
    optimize_use_material_min_radius: bpy.props.BoolProperty(
        name="Use material min bend radius", default=True, update=_mark_dirty
    )
    optimize_min_radius_mm: bpy.props.FloatProperty(
        name="Minimum radius (mm)",
        default=6.0,
        min=0.0,
        step=0.1,
        update=_mark_dirty,
    )
    optimize_radius_weight: bpy.props.FloatProperty(
        name="Bend radius penalty",
        description=(
            "How hard a bend tighter than the minimum radius is punished; "
            "raise it to buy bendability with deviation"
        ),
        default=1000.0,
        min=0.0,
        soft_max=10000.0,
        step=10.0,
        update=_mark_dirty,
    )
    optimize_max_iterations: bpy.props.IntProperty(
        name="Max iterations", default=40, min=1, max=500, step=1, update=_mark_dirty
    )
    optimize_cost_tolerance: bpy.props.FloatProperty(
        name="Cost tolerance",
        description="Stop when one step improves the cost by less than this",
        default=1e-6,
        min=0.0,
        soft_max=1e-2,
        step=1e-7,
        precision=9,
        update=_mark_dirty,
    )

    # ------------------------------------------------------------ shrink
    shrink_enabled: bpy.props.BoolProperty(
        name="Shrink sections",
        description="Narrow wide sections (tubes/wires) while keeping them smooth",
        default=False,
        update=_mark_dirty,
    )
    shrink_percent: bpy.props.FloatProperty(
        name="Shrink (%)", default=20.0, min=0.0, max=90.0, step=1.0, update=_mark_dirty
    )
    shrink_mode: bpy.props.EnumProperty(
        name="Shrink profile",
        items=(
            ("UNIFORM", "Uniform", "Every section shrinks by the same amount"),
            ("MIDDLE", "Smooth middle", "Taper in and out around the middle of the pass"),
            ("ENDS", "Smooth ends", "Shrink the ends, keep the middle"),
        ),
        default="MIDDLE",
        update=_mark_dirty,
    )
    shrink_smooth_iterations: bpy.props.IntProperty(
        name="Smooth iterations",
        description="Smoothing applied after shrinking (0 keeps raw scaled points)",
        default=2,
        min=0,
        max=10,
        step=1,
        update=_mark_dirty,
    )

    # ------------------------------------------------------------ cut offsets
    inset_enabled: bpy.props.BoolProperty(
        name="Cut offsets",
        description="Give every cutting pass a signed clearance (for welding/assembly)",
        default=False,
        update=_mark_dirty,
    )
    inset_x_mode: bpy.props.EnumProperty(
        name="X cuts",
        items=(
            ("NONE", "No offset", "Cut exactly on the source surface"),
            ("OUTWARD", "Outward", "Grow the cut: this pass wraps the part"),
            ("INWARD", "Inward", "Shrink the cut: this pass sits inside the wrap"),
        ),
        default="OUTWARD",
        update=_mark_dirty,
    )
    inset_y_mode: bpy.props.EnumProperty(
        name="Y cuts",
        items=(
            ("NONE", "No offset", "Cut exactly on the source surface"),
            ("OUTWARD", "Outward", "Grow the cut"),
            ("INWARD", "Inward", "Shrink the cut"),
        ),
        default="NONE",
        update=_mark_dirty,
    )
    inset_z_mode: bpy.props.EnumProperty(
        name="Z cuts",
        items=(
            ("NONE", "No offset", "Cut exactly on the source surface"),
            ("OUTWARD", "Outward", "Grow the cut"),
            ("INWARD", "Inward", "Shrink the cut: this pass sits inside the wrap"),
        ),
        default="INWARD",
        update=_mark_dirty,
    )
    inset_auto: bpy.props.BoolProperty(
        name="At least material radius",
        description="Never offset by less than half the thickness plus kerf",
        default=True,
        update=_mark_dirty,
    )
    inset_amount_mm: bpy.props.FloatProperty(
        name="Offset", default=0.5, min=0.0, soft_max=20.0, step=0.1, update=_mark_dirty
    )

    # ---------------------------------------------------------------- contacts
    contacts_enabled: bpy.props.BoolProperty(
        name="Find contacts",
        description="Mark points where slices of different passes meet (for welding)",
        default=False,
        update=_mark_dirty,
    )
    contacts_gap_mm: bpy.props.FloatProperty(
        name="Contact gap", default=1.0, min=0.0, soft_max=20.0, step=0.1, update=_mark_dirty
    )
    contact_marker_mm: bpy.props.FloatProperty(
        name="Contact marker",
        description=(
            "Minimum radius of the bold contact markers in millimetres "
            "(they also scale up with large models)"
        ),
        default=5.0,
        min=0.25,
        soft_max=20.0,
        step=0.1,
        update=_mark_dirty,
    )
    contacts_include_same: bpy.props.BoolProperty(
        name="Same pass too", default=False, update=_mark_dirty
    )

    # ------------------------------------------------------------- performance
    threads: bpy.props.IntProperty(
        name="Worker threads",
        description="0 = automatic, 1 = no multithreading",
        default=0,
        min=0,
        max=64,
        step=1,
        update=_mark_dirty,
    )
    show_all_layers: bpy.props.BoolProperty(
        name="Show all layers",
        description="Draw every visible cutting pass at once",
        default=True,
        update=_mark_dirty,
    )
    use_background: bpy.props.BoolProperty(
        name="Background processing",
        description=(
            "Run processing in a worker thread so Blender stays responsive; "
            "progress is shown in the panel and the job can be cancelled"
        ),
        default=True,
        update=_mark_dirty,
    )

    # ------------------------------------------------------------------ output
    build_curves: bpy.props.BoolProperty(
        name="Build result curves", default=True, update=_mark_dirty
    )
    curve_radius_mm: bpy.props.FloatProperty(
        name="Curve radius", default=0.15, min=0.0, step=0.01, update=_mark_dirty
    )
    check_self_intersections: bpy.props.BoolProperty(
        name="Check self-intersections", default=True, update=_mark_dirty
    )

    # ------------------------------------------------------------ background job
    # Written only by the main-thread timer of ``jobs.py``; never editable.
    job_running: bpy.props.BoolProperty(name="Running", default=False)
    job_progress: bpy.props.FloatProperty(
        name="Progress", default=0.0, min=0.0, max=1.0, subtype="PERCENTAGE"
    )
    job_message: bpy.props.StringProperty(name="Job", default="")
    job_cancelling: bpy.props.BoolProperty(name="Cancelling", default=False)

    # ------------------------------------------------------------------ status
    status: bpy.props.StringProperty(name="Status", default="Ready")
    status_detail: bpy.props.StringProperty(name="Details", default="")
    diagnostics_text: bpy.props.StringProperty(name="Diagnostics", default="")
    dirty: bpy.props.BoolProperty(name="Dirty", default=True)
    revision: bpy.props.IntProperty(name="Revision", default=0)
    last_slices: bpy.props.IntProperty(name="Slices", default=0)
    last_points: bpy.props.IntProperty(name="Points", default=0)
    last_errors: bpy.props.IntProperty(name="Errors", default=0)
    last_warnings: bpy.props.IntProperty(name="Warnings", default=0)
    last_contacts: bpy.props.IntProperty(name="Contacts", default=0)


CLASSES = (SlicerSettings,)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.slicer_settings = bpy.props.PointerProperty(type=SlicerSettings)


def unregister() -> None:
    if hasattr(bpy.types.Scene, "slicer_settings"):
        del bpy.types.Scene.slicer_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
