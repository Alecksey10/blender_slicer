"""Blender adapter: settings -> plan/request -> controller -> events.

The adapter is intentionally thin.  It maps addon settings to host-independent
objects (``SlicePlan``, ``ProcessingRequest``), delegates to
:class:`blender_slicer.app.controller.AppController` and publishes UI events.
All geometry stays in the engine, all 3D in the host.
"""

from __future__ import annotations

from ...adapters.base.engine_client import EngineClient
from ...adapters.base.events import (
    BUS,
    TOPIC_PROCESS_COMPLETED,
    TOPIC_PROCESS_FAILED,
    TOPIC_PROCESS_STARTED,
    TOPIC_RESULT_CLEARED,
    TOPIC_SLICES_GENERATED,
    TOPIC_SETTINGS_CHANGED,
    TOPIC_UI_REDRAW,
)
from ...adapters.base.layers import SliceLayer
from ...adapters.base.plan import SlicePlan
from ...adapters.base.runtime import RUNTIME
from ...adapters.base.controller import AppController, ProcessSummary, format_diagnostic
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
    TargetSelector,
)
from ...spatial.contacts import ContactPoint
from . import slicing, visualization
from .host import BlenderHost

# Shared, stateless engine.  Its registry is read-only, so parallel calls are
# safe (see engine/parallel.py).
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
    if settings.material_kerf_mm < 0:
        errors.append("Kerf cannot be negative")
    if getattr(settings, "inset_enabled", False) and getattr(settings, "inset_amount_mm", 0.0) < 0:
        errors.append("Cut offset cannot be negative")
    if getattr(settings, "threads", 0) < 0:
        errors.append("Worker threads cannot be negative")
    if getattr(settings, "contacts_gap_mm", 0.0) < 0:
        errors.append("Contact gap cannot be negative")
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
    if bool(getattr(settings, "shrink_enabled", False)):
        # The per-slice ratio is attached by the controller; the engine applies
        # it and smooths the result before offsets and fillets.
        operations.append(
            OperationSpec(
                method="shrink_section",
                params={
                    "use_slice_ratio": True,
                    "ratio": 1.0,
                    "anchor": "centroid",
                    "smooth_iterations": int(
                        getattr(settings, "shrink_smooth_iterations", 2)
                    ),
                    "preserve_corners_deg": 70.0,
                },
                target=TargetSelector(roles=(ContourRole.CUT,)),
            )
        )
    if bool(getattr(settings, "inset_enabled", False)):
        # The signed distance lives on each slice (Slice.offset_mm); the engine
        # only applies it, so the host owns the axis policy.
        operations.append(
            OperationSpec(
                method="offset_contour",
                params={"use_slice_offset": True, "distance_mm": 0.0},
                target=TargetSelector(roles=(ContourRole.CUT,)),
            )
        )
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


def build_request(settings, slices=None) -> ProcessingRequest:
    plan = SlicePlan.from_settings(settings)
    slice_list = list(RUNTIME.slices if slices is None else slices)
    return ProcessingRequest(
        request_id=f"blender-{settings.revision}-{settings.count}",
        units="mm",
        material=material_from_settings(settings),
        operations=operations_from_settings(settings),
        slices=slice_list,
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
            "cut_offset_mm": plan.cut_offset_for(plan.axis),
            "threads": int(getattr(settings, "threads", 0) or 0),
        },
    )


def _controller(context, settings) -> AppController:
    threads = int(getattr(settings, "threads", 0) or 0)
    client = EngineClient(engine=ENGINE, workers=None if threads <= 0 else threads)
    return AppController(BlenderHost(context, settings), RUNTIME.layers, client)


def generate(context, settings) -> int:
    validate_settings(settings)
    plan = SlicePlan.from_settings(settings)
    layer = _controller(context, settings).generate(plan, revision=int(settings.revision))

    settings.dirty = False
    settings.last_slices = len(layer.slices)
    settings.last_points = layer.point_count
    settings.last_errors = 0
    settings.last_warnings = 0
    settings.last_contacts = 0
    settings.status = f"Generated {len(layer.slices)} slices"
    settings.status_detail = (
        f"{settings.last_points} points, {len(layer.frames)} frames · {layer.name}"
    )
    settings.diagnostics_text = ""
    RUNTIME.dirty = False
    BUS.publish(TOPIC_UI_REDRAW, context=context)
    return len(layer.slices)


def process_current(context, settings) -> ProcessingResult:
    validate_settings(settings)
    plan = SlicePlan.from_settings(settings)
    layer = _layer_for_plan(plan)
    if layer is None or not layer.slices:
        raise ConfigError("Generate slices first")
    if layer.revision != int(settings.revision):
        raise ConfigError("Slices are outdated - generate them again")

    BUS.publish(TOPIC_PROCESS_STARTED, settings=settings, context=context)
    summary = _controller(context, settings).process(build_request(settings, layer.slices), layer)
    _update_status(settings, summary)

    if getattr(settings, "contacts_enabled", False):
        contacts = _controller(context, settings).find_contacts(
            gap_mm=float(getattr(settings, "contacts_gap_mm", 1.0)),
            include_same_layer=bool(getattr(settings, "contacts_include_same", False)),
        )
        settings.last_contacts = len(contacts)
        settings.status_detail += f", contacts {len(contacts)}"

    if summary.result.status == ResultStatus.ERROR:
        BUS.publish(TOPIC_PROCESS_FAILED, result=summary.result, settings=settings, context=context)
    else:
        BUS.publish(
            TOPIC_PROCESS_COMPLETED, result=summary.result, settings=settings, context=context
        )
    BUS.publish(TOPIC_UI_REDRAW, context=context)
    return summary.result


def _layer_for_plan(plan: SlicePlan) -> SliceLayer | None:
    layer = RUNTIME.layers.get(plan.layer_id())
    if layer is not None:
        return layer
    active = RUNTIME.layers.active
    if active is not None and active.source_name == plan.model:
        return active
    return active


def run(context, settings) -> ProcessingResult:
    generate(context, settings)
    return process_current(context, settings)


def find_contacts(context, settings) -> list[ContactPoint]:
    validate_settings(settings)
    controller = _controller(context, settings)
    contacts = controller.find_contacts(
        gap_mm=float(getattr(settings, "contacts_gap_mm", 1.0)),
        include_same_layer=bool(getattr(settings, "contacts_include_same", False)),
    )
    settings.last_contacts = len(contacts)
    settings.status_detail = (
        f"{len(contacts)} contact(s) within {float(getattr(settings, 'contacts_gap_mm', 1.0)):.3f} mm"
    )
    BUS.publish(TOPIC_UI_REDRAW, context=context)
    return contacts


def set_layer_visible(context, settings, layer_id: str) -> bool:
    controller = _controller(context, settings)
    visible = controller.set_layer_visible(layer_id)
    BUS.publish(TOPIC_UI_REDRAW, context=context)
    return visible


def remove_layer(context, settings, layer_id: str) -> bool:
    removed = _controller(context, settings).remove_layer(layer_id)
    BUS.publish(TOPIC_UI_REDRAW, context=context)
    return removed


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
    settings.last_contacts = 0
    settings.dirty = True
    BUS.publish(TOPIC_RESULT_CLEARED, settings=settings, context=context)
    BUS.publish(TOPIC_UI_REDRAW, context=context)


def on_settings_changed(settings=None, context=None, **kwargs) -> None:
    RUNTIME.dirty = True
    if settings is not None and RUNTIME.slices:
        settings.status = "Settings changed - generate slices"
        settings.status_detail = "The current result is stale"


def _update_status(settings, summary: ProcessSummary) -> None:
    settings.last_slices = len(summary.result.slices)
    settings.last_points = summary.result.metrics.points_out
    settings.last_errors = summary.errors
    settings.last_warnings = summary.warnings
    settings.diagnostics_text = "\n".join(summary.lines)
    settings.status = summary.status_text
    settings.status_detail = summary.detail_text


def _format_diag(item) -> str:
    return format_diagnostic(item)


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
