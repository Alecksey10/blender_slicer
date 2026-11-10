from __future__ import annotations

from ...engine.facade import Engine
from ...protocol.errors import ConfigError
from ...protocol.types import (
    ContourRole,
    FailurePolicy,
    Limits,
    MaterialProfile,
    OperationSpec,
    ProcessingRequest,
    ProcessingResult,
    RequestOptions,
    ResultStatus,
    Severity,
    TargetSelector,
)
from . import slicing, visualization
from blender_slicer.adapters.base.events import (
    BUS,
    TOPIC_PROCESS_COMPLETED,
    TOPIC_PROCESS_FAILED,
    TOPIC_PROCESS_STARTED,
    TOPIC_RESULT_CLEARED,
    TOPIC_SLICES_GENERATED,
    TOPIC_SETTINGS_CHANGED,
    TOPIC_UI_REDRAW,
)
from blender_slicer.adapters.base.runtime import RUNTIME


ENGINE = Engine()


def get_settings(context):
    settings = getattr(context.scene, "slicer_settings", None)
    if settings is None:
        raise ConfigError("Slice Engine settings are not registered")
    return settings


def validate_settings(settings) -> None:
    errors: list[str] = []
    if settings.source_object is None or settings.source_object.type != "MESH":
        errors.append("Select a mesh object")
    if settings.unit_scale_mm <= 0:
        errors.append("1 BU in mm must be positive")
    if settings.count < 1:
        errors.append("Slice count must be at least 1")
    if settings.slice_mode == "PLANAR" and settings.spacing_mm <= 0:
        errors.append("Slice spacing must be positive")
    if settings.slice_mode == "RADIAL":
        if abs(settings.angle_end_deg - settings.angle_start_deg) < 1e-6:
            errors.append("Radial angle range must be non-zero")
    if settings.material_thickness_mm <= 0:
        errors.append("Material thickness must be positive")
    if settings.material_min_bend_radius_mm <= 0:
        errors.append("Minimum bend radius must be positive")
    if not (0.0 <= settings.material_k_factor <= 1.0):
        errors.append("K-factor must be in [0, 1]")
    if settings.fillet_enabled:
        if settings.fillet_radius_mm < 0:
            errors.append("Fillet radius cannot be negative")
        if settings.fillet_arc_segments < 1:
            errors.append("Fillet arc segments must be >= 1")
    if settings.smooth_enabled and settings.smooth_iterations < 0:
        errors.append("Smooth iterations cannot be negative")
    if settings.simplify_enabled and settings.simplify_tolerance_mm < 0:
        errors.append("Simplify tolerance cannot be negative")
    if settings.densify_enabled and settings.densify_max_spacing_mm <= 0:
        errors.append("Densify spacing must be positive")
    if settings.resample_enabled and settings.resample_spacing_mm <= 0:
        errors.append("Resample spacing must be positive")
    if errors:
        raise ConfigError("; ".join(errors))


def material_from_settings(settings) -> MaterialProfile:
    return MaterialProfile(
        id="blender-custom",
        name="Blender material",
        thickness_mm=float(settings.material_thickness_mm),
        min_bend_radius_mm=float(settings.material_min_bend_radius_mm),
        max_bend_angle_deg=float(settings.material_max_bend_angle_deg),
        min_segment_mm=float(settings.material_min_segment_mm),
        kerf_mm=float(settings.material_kerf_mm),
        k_factor=float(settings.material_k_factor),
    )


def operations_from_settings(settings) -> list[OperationSpec]:
    operations: list[OperationSpec] = []
    if settings.fillet_enabled:
        operations.append(
            OperationSpec(
                method="fillet_corners",
                params={
                    "radius_mm": float(settings.fillet_radius_mm),
                    "min_turn_deg": float(settings.fillet_min_turn_deg),
                    "arc_segments": int(settings.fillet_arc_segments),
                    "chord_tolerance_mm": float(settings.fillet_chord_tolerance_mm),
                    "mode": settings.fillet_mode,
                    "check_material": bool(settings.fillet_check_material),
                },
            )
        )
    if settings.smooth_enabled:
        operations.append(
            OperationSpec(
                method="smooth",
                params={
                    "algorithm": settings.smooth_algorithm,
                    "iterations": int(settings.smooth_iterations),
                    "preserve_corners_deg": float(settings.smooth_preserve_corners_deg),
                    "max_deviation_mm": float(settings.smooth_max_deviation_mm),
                    "weight": float(settings.smooth_weight),
                },
            )
        )
    if settings.simplify_enabled:
        operations.append(
            OperationSpec(
                method="simplify",
                params={
                    "tolerance_mm": float(settings.simplify_tolerance_mm),
                    "preserve_corners_deg": float(settings.simplify_preserve_corners_deg),
                },
            )
        )
    if settings.densify_enabled:
        operations.append(
            OperationSpec(
                method="densify",
                params={
                    "max_spacing_mm": float(settings.densify_max_spacing_mm),
                    "max_angle_step_deg": float(settings.densify_max_angle_step_deg),
                    "chord_tolerance_mm": float(settings.densify_chord_tolerance_mm),
                },
            )
        )
    if settings.resample_enabled:
        operations.append(
            OperationSpec(
                method="resample",
                params={
                    "spacing_mm": float(settings.resample_spacing_mm),
                    "adaptive": bool(settings.resample_adaptive),
                    "min_spacing_mm": float(settings.resample_min_spacing_mm),
                    "chord_tolerance_mm": float(settings.resample_chord_tolerance_mm),
                },
            )
        )
    if settings.limit_curvature_enabled:
        operations.append(
            OperationSpec(
                method="limit_curvature",
                params={
                    "use_material_min_radius": bool(settings.limit_curvature_use_material),
                    "min_radius_mm": float(settings.limit_curvature_min_radius_mm),
                    "max_iterations": int(settings.limit_curvature_max_iterations),
                    "weight": float(settings.limit_curvature_weight),
                    "strict": bool(settings.limit_curvature_strict),
                },
            )
        )
    return operations


def build_request(settings) -> ProcessingRequest:
    return ProcessingRequest(
        schema_version="1.0",
        protocol_version="1.0",
        request_id=f"blender-{settings.revision}-{settings.count}",
        units="mm",
        material=material_from_settings(settings),
        operations=operations_from_settings(settings),
        slices=list(RUNTIME.slices),
        targets=TargetSelector(roles=(ContourRole.CUT,)),
        failure_policy=FailurePolicy.PER_SLICE,
        options=RequestOptions(
            return_unchanged=True,
            include_metrics=True,
            normalize_winding=True,
        ),
        limits=Limits(max_slices=512, max_points_per_contour=500_000),
        metadata={
            "host": "blender",
            "source": getattr(settings.source_object, "name", ""),
            "check_self_intersections": bool(settings.check_self_intersections),
        },
    )


def generate(context, settings) -> int:
    validate_settings(settings)
    slices, frames = slicing.generate_slices(context, settings)
    RUNTIME.slices = slices
    RUNTIME.frames = frames
    RUNTIME.result = None
    RUNTIME.revision = int(settings.revision)
    RUNTIME.source_name = getattr(settings.source_object, "name", "")
    RUNTIME.dirty = False

    settings.dirty = False
    settings.last_slices = len(slices)
    settings.last_points = sum(len(c.points) for s in slices for c in s.contours)
    settings.last_errors = 0
    settings.last_warnings = 0
    settings.status = f"Generated {len(slices)} slices"
    settings.status_detail = f"{settings.last_points} points, {len(frames)} frames"
    settings.diagnostics_text = ""

    if settings.build_curves:
        visualization.build_from_slices(context, RUNTIME.slices, RUNTIME.frames, settings)
    BUS.publish(
        TOPIC_SLICES_GENERATED,
        slices=RUNTIME.slices,
        frames=RUNTIME.frames,
        settings=settings,
        context=context,
    )
    BUS.publish(TOPIC_UI_REDRAW, context=context)
    return len(slices)


def process_current(context, settings) -> ProcessingResult:
    validate_settings(settings)
    if not RUNTIME.slices:
        raise ConfigError("Generate slices first")
    if RUNTIME.revision != int(settings.revision):
        raise ConfigError("Slices are outdated - generate them again")

    BUS.publish(TOPIC_PROCESS_STARTED, settings=settings, context=context)
    request = build_request(settings)
    result = ENGINE.process(request)
    RUNTIME.result = result
    _update_status(settings, result)
    if settings.build_curves:
        visualization.build_from_result(context, result, RUNTIME.frames, settings)
    if result.status == ResultStatus.ERROR:
        BUS.publish(TOPIC_PROCESS_FAILED, result=result, settings=settings, context=context)
    else:
        BUS.publish(TOPIC_PROCESS_COMPLETED, result=result, settings=settings, context=context)
    BUS.publish(TOPIC_UI_REDRAW, context=context)
    return result


def run(context, settings) -> ProcessingResult:
    generate(context, settings)
    return process_current(context, settings)


def clear(context, settings) -> None:
    RUNTIME.clear()
    visualization.clear_collection(context)
    settings.status = "Cleared"
    settings.status_detail = ""
    settings.diagnostics_text = ""
    settings.last_slices = 0
    settings.last_points = 0
    settings.last_errors = 0
    settings.last_warnings = 0
    settings.dirty = True
    BUS.publish(TOPIC_RESULT_CLEARED, settings=settings, context=context)
    BUS.publish(TOPIC_UI_REDRAW, context=context)


def on_settings_changed(settings=None, context=None, **kwargs) -> None:
    RUNTIME.dirty = True
    if settings is not None and RUNTIME.slices:
        settings.status = "Settings changed - generate slices"
        settings.status_detail = "The current result is stale"


def _update_status(settings, result: ProcessingResult) -> None:
    lines: list[str] = []
    errors = 0
    warnings = 0
    for d in result.diagnostics:
        lines.append(_format_diag(d))
        if d.severity == Severity.ERROR:
            errors += 1
        elif d.severity == Severity.WARNING:
            warnings += 1
    for slice_result in result.slices:
        for d in slice_result.diagnostics:
            lines.append(_format_diag(d))
            if d.severity == Severity.ERROR:
                errors += 1
            elif d.severity == Severity.WARNING:
                warnings += 1
    settings.last_slices = len(result.slices)
    settings.last_points = result.metrics.points_out
    settings.last_errors = errors
    settings.last_warnings = warnings
    settings.diagnostics_text = "\n".join(lines)
    settings.status = f"{result.status.value.upper()} - {result.metrics.slices_ok}/{result.metrics.slices_in} slices"
    settings.status_detail = (
        f"points {result.metrics.points_in} -> {result.metrics.points_out}, "
        f"errors {errors}, warnings {warnings}"
    )


def _format_diag(d) -> str:
    where = []
    if d.slice_id:
        where.append(d.slice_id)
    if d.contour_id:
        where.append(d.contour_id)
    prefix = f"[{d.severity.value.upper()}] {d.code.value}"
    if where:
        prefix += " " + "/".join(where)
    if d.stage:
        prefix += f" ({d.stage})"
    return f"{prefix}: {d.message}"


def _on_redraw(context=None, **_kwargs) -> None:
    """Refresh the N-panel right after a command, without waiting for the mouse."""
    area = getattr(context, "area", None)
    if area is not None and hasattr(area, "tag_redraw"):
        area.tag_redraw()


def subscribe_events() -> None:
    BUS.subscribe(TOPIC_SETTINGS_CHANGED, on_settings_changed)
    BUS.subscribe(TOPIC_UI_REDRAW, _on_redraw)


def unsubscribe_events() -> None:
    BUS.unsubscribe(TOPIC_SETTINGS_CHANGED, on_settings_changed)
    BUS.unsubscribe(TOPIC_UI_REDRAW, _on_redraw)
