"""Blender adapter: settings -> plan/request -> controller -> events.

The adapter is intentionally thin.  It maps addon settings to host-independent
objects (``SlicePlan``, ``ProcessingRequest``), delegates to
:class:`blender_slicer.app.controller.AppController` and publishes UI events.
All geometry stays in the engine, all 3D in the host.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from . import jobs, slicing, visualization
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
    if (
        settings.slice_mode == "PLANAR"
        and not getattr(settings, "spacing_auto", False)
        and settings.spacing_mm <= 0
    ):
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
    if getattr(settings, "cut_thin_enabled", False):
        if getattr(settings, "cut_thin_min_width_mm", 0.0) <= 0:
            errors.append("Cut thin min width must be positive")
        if not (0.0 <= getattr(settings, "cut_thin_max_removed_ratio", 0.5) <= 1.0):
            errors.append("Cut thin max removed ratio must be in [0, 1]")
    if getattr(settings, "trim_tight_enabled", False):
        if getattr(settings, "trim_tight_radius_mm", 0.0) < 0:
            errors.append("Trim tight radius cannot be negative")
        if not (0.0 <= getattr(settings, "trim_tight_max_removed_ratio", 0.5) <= 1.0):
            errors.append("Trim tight max removed ratio must be in [0, 1]")
    if getattr(settings, "smooth_curve_enabled", False):
        if settings.smooth_curve_inertia < 0 or settings.smooth_curve_inertia > 1:
            errors.append("Curve inertia must be in [0, 1]")
        if settings.smooth_curve_tension < 0 or settings.smooth_curve_tension > 1:
            errors.append("Curve tension must be in [0, 1]")
        if settings.smooth_curve_max_deviation_mm < 0:
            errors.append("Max deviation cannot be negative")
        if settings.smooth_curve_chord_tolerance_mm < 0:
            errors.append("Chord tolerance cannot be negative")
        if settings.smooth_curve_max_spacing_mm < 0:
            errors.append("Max spacing cannot be negative")
        if settings.smooth_curve_segments_per_span < 2:
            errors.append("Segments per span must be >= 2")
        if not (0.0 <= settings.smooth_curve_preserve_corners_deg <= 180.0):
            errors.append("Preserve corners must be in [0, 180]")
        if settings.smooth_curve_inertia_smoothing < 0:
            errors.append("Inertia passes cannot be negative")
        if settings.smooth_curve_min_radius_mm < 0:
            errors.append("Min radius cannot be negative")
    if getattr(settings, "optimize_enabled", False):
        if getattr(settings, "optimize_points", 0) < 8:
            errors.append("Curve samples must be >= 8")
        if getattr(settings, "optimize_max_iterations", 0) < 1:
            errors.append("Optimizer iterations must be >= 1")
        for name in (
            "optimize_data_weight",
            "optimize_smooth",
            "optimize_min_radius_mm",
            "optimize_radius_weight",
            "optimize_cost_tolerance",
        ):
            if getattr(settings, name, 0.0) < 0:
                errors.append(f"{name} cannot be negative")
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


def _operation(method: str, params: dict) -> OperationSpec:
    """Build a cut-role operation; every Blender stage targets cut contours."""

    return OperationSpec(
        method=method,
        params=params,
        target=TargetSelector(roles=(ContourRole.CUT,)),
    )


def operations_from_settings(settings) -> list[OperationSpec]:
    # The global least-squares fit replaces the sequential shaping heuristics:
    # running both would fight over the same corners.
    optimize = bool(getattr(settings, "optimize_enabled", False))
    legacy_shaping = not optimize

    operations: list[OperationSpec] = []
    if bool(getattr(settings, "shrink_enabled", False)):
        # The per-slice ratio is attached by the controller; the engine applies
        # it and smooths the result before offsets and fillets.
        operations.append(
            _operation(
                "shrink_section",
                {
                    "use_slice_ratio": True,
                    "ratio": 1.0,
                    "anchor": "centroid",
                    "smooth_iterations": int(
                        getattr(settings, "shrink_smooth_iterations", 2)
                    ),
                    "preserve_corners_deg": 70.0,
                },
            )
        )
    if bool(getattr(settings, "inset_enabled", False)):
        # The signed distance lives on each slice (Slice.offset_mm); the engine
        # only applies it, so the host owns the axis policy.
        operations.append(
            _operation(
                "offset_contour",
                {"use_slice_offset": True, "distance_mm": 0.0},
            )
        )
    if legacy_shaping and bool(getattr(settings, "cut_thin_enabled", False)):
        operations.append(
            _operation(
                "cut_thin_sections",
                {
                    "min_width_mm": float(
                        getattr(settings, "cut_thin_min_width_mm", 8.0)
                    ),
                    "corner_turn_deg": float(
                        getattr(settings, "cut_thin_corner_turn_deg", 20.0)
                    ),
                    "max_removed_ratio": float(
                        getattr(settings, "cut_thin_max_removed_ratio", 0.5)
                    ),
                },
            )
        )
    if legacy_shaping and bool(getattr(settings, "trim_tight_enabled", False)):
        operations.append(
            _operation(
                "trim_tight_corners",
                {
                    "radius_mm": float(
                        getattr(settings, "trim_tight_radius_mm", 4.0)
                    ),
                    "min_turn_deg": float(
                        getattr(settings, "trim_tight_min_turn_deg", 20.0)
                    ),
                    "max_removed_ratio": float(
                        getattr(settings, "trim_tight_max_removed_ratio", 0.5)
                    ),
                    "action": str(
                        getattr(settings, "trim_tight_action", "trim")
                    ),
                },
            )
        )
    if legacy_shaping and settings.fillet_enabled:
        operations.append(
            _operation(
                "fillet_corners",
                {
                    "radius_mm": float(settings.fillet_radius_mm),
                    "min_turn_deg": float(settings.fillet_min_turn_deg),
                    "arc_segments": int(settings.fillet_arc_segments),
                    "chord_tolerance_mm": float(settings.fillet_chord_tolerance_mm),
                    "mode": settings.fillet_mode,
                    "check_material": bool(settings.fillet_check_material),
                },
            )
        )
    if legacy_shaping and getattr(settings, "smooth_curve_enabled", False):
        operations.append(
            _operation(
                "smooth_curve_approx",
                {
                    "use_material_min_radius": bool(
                        settings.smooth_curve_use_material_min_radius
                    ),
                    "min_radius_mm": float(settings.smooth_curve_min_radius_mm),
                    "mode": str(settings.smooth_curve_mode),
                    "tension": float(settings.smooth_curve_tension),
                    "max_deviation_mm": float(
                        settings.smooth_curve_max_deviation_mm
                    ),
                    "preserve_corners_deg": float(
                        settings.smooth_curve_preserve_corners_deg
                    ),
                    "chord_tolerance_mm": float(
                        settings.smooth_curve_chord_tolerance_mm
                    ),
                    "max_spacing_mm": float(settings.smooth_curve_max_spacing_mm),
                    "segments_per_span": int(
                        settings.smooth_curve_segments_per_span
                    ),
                    "inertia_smoothing": int(
                        settings.smooth_curve_inertia_smoothing
                    ),
                    "inertia": float(settings.smooth_curve_inertia),
                },
            )
        )
    if settings.simplify_enabled:
        operations.append(
            _operation(
                "simplify",
                {
                    "tolerance_mm": float(settings.simplify_tolerance_mm),
                    "preserve_corners_deg": float(settings.simplify_preserve_corners_deg),
                },
            )
        )
    if getattr(settings, "optimize_enabled", False):
        # Last shaping stage before the output density is set: one global fit
        # replaces corner-by-corner clamping, minimising deviation, bending
        # energy and the bend-radius violation together.  Running it after
        # simplify keeps the simplifier from re-sharpening the fitted bends.
        operations.append(
            _operation(
                "optimize_curve",
                {
                    "sample_points": int(getattr(settings, "optimize_points", 150)),
                    "data_weight": float(
                        getattr(settings, "optimize_data_weight", 20.0)
                    ),
                    "smooth": float(getattr(settings, "optimize_smooth", 2.0)),
                    "use_material_min_radius": bool(
                        getattr(settings, "optimize_use_material_min_radius", True)
                    ),
                    "min_radius_mm": float(
                        getattr(settings, "optimize_min_radius_mm", 6.0)
                    ),
                    "radius_weight": float(
                        getattr(settings, "optimize_radius_weight", 1000.0)
                    ),
                    "max_iterations": int(
                        getattr(settings, "optimize_max_iterations", 40)
                    ),
                    "cost_tolerance": float(
                        getattr(settings, "optimize_cost_tolerance", 1e-6)
                    ),
                },
            )
        )
    if settings.densify_enabled:
        operations.append(
            _operation(
                "densify",
                {
                    "max_spacing_mm": float(settings.densify_max_spacing_mm),
                    "max_angle_step_deg": float(settings.densify_max_angle_step_deg),
                    "chord_tolerance_mm": float(settings.densify_chord_tolerance_mm),
                },
            )
        )
    if settings.resample_enabled:
        operations.append(
            _operation(
                "resample",
                {
                    "spacing_mm": float(settings.resample_spacing_mm),
                    "adaptive": bool(settings.resample_adaptive),
                    "min_spacing_mm": float(settings.resample_min_spacing_mm),
                    "chord_tolerance_mm": float(settings.resample_chord_tolerance_mm),
                },
            )
        )
    if legacy_shaping and settings.limit_curvature_enabled:
        operations.append(
            _operation(
                "limit_curvature",
                {
                    "use_material_min_radius": bool(settings.limit_curvature_use_material),
                    "min_radius_mm": float(settings.limit_curvature_min_radius_mm),
                    "max_iterations": int(settings.limit_curvature_max_iterations),
                    "weight": float(settings.limit_curvature_weight),
                    "strict": bool(settings.limit_curvature_strict),
                },
            )
        )
    return operations

@dataclass(frozen=True)
class RequestTemplate:
    """A request without its slices, snapshotted on the UI thread.

    Reading RNA properties is a main-thread operation, so a background job gets
    this plain value and binds it to the slices it produced itself; the worker
    then never touches ``settings``.
    """

    request_id: str
    material: MaterialProfile
    operations: list[OperationSpec]
    targets: TargetSelector
    failure_policy: FailurePolicy
    options: RequestOptions
    limits: Limits
    metadata: dict

    def bind(self, slices) -> ProcessingRequest:
        return ProcessingRequest(
            request_id=self.request_id,
            units="mm",
            material=self.material,
            operations=self.operations,
            slices=list(slices),
            targets=self.targets,
            failure_policy=self.failure_policy,
            options=self.options,
            limits=self.limits,
            metadata=dict(self.metadata),
        )


def request_template(settings) -> RequestTemplate:
    plan = SlicePlan.from_settings(settings)
    return RequestTemplate(
        request_id=f"blender-{settings.revision}-{settings.count}",
        material=material_from_settings(settings),
        operations=operations_from_settings(settings),
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


def build_request(settings, slices=None) -> ProcessingRequest:
    return request_template(settings).bind(
        RUNTIME.slices if slices is None else slices
    )


def _controller(context, settings, workers=None) -> AppController:
    if workers is None:
        threads = int(getattr(settings, "threads", 0) or 0)
        workers = None if threads <= 0 else threads
    client = EngineClient(engine=ENGINE, workers=workers)
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
    detail = f"{settings.last_points} points, {len(layer.frames)} frames · {layer.name}"
    if getattr(settings, "spacing_auto", False) and layer.slices:
        effective = layer.slices[0].metadata.get("spacing_mm")
        if effective is not None:
            detail += f" · auto spacing {float(effective):.3f} mm"
    settings.status_detail = detail
    settings.diagnostics_text = ""
    RUNTIME.dirty = False
    BUS.publish(TOPIC_UI_REDRAW, context=context)
    return len(layer.slices)


def _process_target(context, settings) -> tuple[SliceLayer, ProcessingRequest]:
    """Validate the session and return the layer plus the engine request."""

    validate_settings(settings)
    plan = SlicePlan.from_settings(settings)
    layer = _layer_for_plan(plan)
    if layer is None or not layer.slices:
        raise ConfigError("Generate slices first")
    if layer.revision != int(settings.revision):
        raise ConfigError("Slices are outdated - generate them again")
    return layer, build_request(settings, layer.slices)


def process_current(context, settings) -> ProcessingResult:
    layer, request = _process_target(context, settings)
    BUS.publish(TOPIC_PROCESS_STARTED, settings=settings, context=context)
    controller = _controller(context, settings)
    summary = controller.process(request, layer)
    _finish_processing(context, settings, controller, summary)
    return summary.result


def start_process(context, settings) -> bool:
    """Process the existing slices in a worker thread."""

    return start_run(context, settings, regenerate=False)


def start_run(context, settings, regenerate: bool = False) -> bool:
    """Slice and process everything off the UI thread.

    Returns ``False`` when the host has no timers, so the caller can fall back
    to the blocking path.  Only two things happen before the job starts: the
    settings are snapshotted into plain values, and (when regenerating) the
    evaluated mesh is copied into a plain triangle soup.  Slicing, the engine
    and the progress bookkeeping then run in one worker thread, while the main
    thread is left with nothing but the status line and the viewport.
    """

    if not jobs.timer_available():
        return False
    validate_settings(settings)

    plan = SlicePlan.from_settings(settings)
    template = request_template(settings)
    geometry = None
    layer: SliceLayer | None = None
    if regenerate:
        # The only bpy touch of the job: read the evaluated mesh once.
        geometry = slicing.collect_geometry(context, settings.source_object)
    else:
        layer = _layer_for_plan(plan)
        if layer is None or not layer.slices:
            raise ConfigError("Generate slices first")
        if layer.revision != int(settings.revision):
            raise ConfigError("Slices are outdated - generate them again")

    # One worker thread: extra threads share the GIL and only add contention
    # with Blender's own thread.
    controller = _controller(context, settings, workers=1)
    BUS.publish(TOPIC_PROCESS_STARTED, settings=settings, context=context)

    def work(reporter):
        # No bpy call from here on: plain data in, plain data out.
        slices = frames = None
        if geometry is not None:
            slices, frames = slicing.build_slices(
                geometry[0],
                geometry[1],
                plan,
                progress=lambda done, total: reporter.update(
                    stage="slicing",
                    fraction=done / float(max(1, total)),
                    message=f"plane {done}/{total}",
                ),
                cancel=reporter.cancelled,
            )
        source = layer.slices if slices is None else slices
        result = controller.client.process(template.bind(source), reporter=reporter)
        return slices, frames, result

    def apply(payload) -> None:
        # Main thread: register the layer, publish, then draw in small steps.
        slices, frames, result = payload
        target = layer
        if slices is not None:
            target = controller.adopt_layer(
                plan, slices, frames, int(settings.revision)
            )
            settings.dirty = False
            RUNTIME.dirty = False
            settings.last_slices = len(slices)
            settings.last_points = sum(item.point_count for item in slices)
        # The host queues the drawing, so this publish is cheap: the curves
        # appear over the next timer ticks instead of in one blocking call.
        summary = controller.apply_result(result, target)
        _finish_processing(context, settings, controller, summary)

    def finish(error: str | None = None, cancelled: bool = False) -> None:
        settings.job_cancelling = False
        if cancelled:
            settings.status = "Cancelled"
            settings.status_detail = "Cancelled; the previous result is kept"
        elif error:
            settings.status = "Error"
            settings.status_detail = error
            settings.diagnostics_text = error
        BUS.publish(TOPIC_UI_REDRAW, context=context)

    try:
        started = jobs.start("run", work, apply=apply, finish=finish)
    except RuntimeError as exc:
        raise ConfigError(str(exc)) from exc
    if not started:
        return False

    settings.job_running = True
    settings.job_progress = 0.0
    settings.job_cancelling = False
    settings.job_message = "slicing" if regenerate else "processing slices"
    settings.status = "Working..."
    settings.status_detail = "Running in a background thread; press Cancel to stop"
    BUS.publish(TOPIC_UI_REDRAW, context=context)
    return True


def cancel_process(context, settings) -> bool:
    """Ask the running job to stop; the scene keeps the last good result."""

    if not jobs.JOBS.cancel():
        return False
    settings.job_cancelling = True
    settings.job_message = "cancelling..."
    settings.status = "Cancelling..."
    BUS.publish(TOPIC_UI_REDRAW, context=context)
    return True


def _finish_processing(context, settings, controller, summary: ProcessSummary) -> None:
    _update_status(settings, summary)
    settings.job_running = False
    settings.job_progress = 0.0

    if getattr(settings, "contacts_enabled", False):
        contacts = controller.find_contacts(
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


def _layer_for_plan(plan: SlicePlan) -> SliceLayer | None:
    layer = RUNTIME.layers.get(plan.layer_id())
    if layer is not None:
        return layer
    active = RUNTIME.layers.active
    if active is not None and active.source_name == plan.model:
        return active
    return active


def run(context, settings) -> ProcessingResult | None:
    """Generate slices, then process them (in the background when possible)."""

    if start_run(context, settings, regenerate=True):
        return None
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
    controller = _controller(context, settings)
    removed = controller.remove_layer(layer_id)
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
