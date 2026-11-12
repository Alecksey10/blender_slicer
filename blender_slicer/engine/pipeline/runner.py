"""Per-slice pipeline: normalize -> operations -> final validation -> result."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...protocol.diagnostics import Diagnostic, ErrorCode, Severity, diagnostic
from ...protocol.errors import DomainError
from ...protocol.geometry import (
    count_self_intersections,
    max_turn_deg,
    min_radius,
    polyline_length,
    polyline_max_deviation,
)
from ...protocol.operations import FailurePolicy
from ...protocol.request import ProcessingRequest
from ...protocol.result import (
    ContourMetrics,
    ContourResult,
    SliceMetrics,
    SliceResult,
)
from ...protocol.shapes import Contour, Slice
from ..methods.base import MethodContext
from ..methods.normalize import normalize_slice
from ..registry import MethodRegistry, validate_params
from ..validation.invariants import SELF_INTERSECTION_LIMIT, final_invariants
from . import policies
from .selection import select_contours
from .state import SliceState

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..progress import ProgressReporter


class SliceRunner:
    """Runs the configured operation list over one slice.

    The runner knows nothing about a host, a request envelope or the result
    status of the whole batch; it only reports what happened to this slice.
    """

    def __init__(self, registry: MethodRegistry) -> None:
        self.registry = registry

    def run(
        self,
        slice_: Slice,
        request: ProcessingRequest,
        reporter: "ProgressReporter | None" = None,
    ) -> tuple[SliceResult, bool, bool]:
        original = slice_.clone()
        diagnostics: list[Diagnostic] = []
        try:
            state = SliceState(
                normalize_slice(original.clone(), request.material, request.options, diagnostics)
            )
        except DomainError as exc:
            if request.failure_policy == FailurePolicy.STRICT:
                raise
            return self.failed(original, [self.domain_diag(exc, slice_.id)])

        partial = False
        for op in request.operations:
            if not op.enabled:
                continue
            if reporter is not None:
                reporter.check()
            method = self.registry.get(op.method)
            if method is None:
                # Request validation should have caught this before the run.
                continue
            try:
                params = validate_params(method.descriptor, op.params)
            except DomainError as exc:
                if request.failure_policy == FailurePolicy.STRICT:
                    raise
                diagnostics.append(self.domain_diag(exc, slice_.id))
                return self.failed(original, diagnostics)

            selected = select_contours(state.slice, op.target or request.targets)
            if not selected:
                diagnostics.append(
                    diagnostic(
                        Severity.WARNING,
                        ErrorCode.E_TARGET_EMPTY,
                        f"Operation {op.method!r} matched no contours",
                        stage=op.method,
                        slice_id=slice_.id,
                    )
                )
                partial = True
                continue

            before = state.clone()
            stage_diagnostics: list[Diagnostic] = []
            try:
                for contour in selected:
                    context = MethodContext(
                        material=request.material,
                        stage=op.method,
                        diagnostics=stage_diagnostics,
                        slice_id=state.id,
                        contour_id=contour.id,
                        slice_offset_mm=state.offset_mm,
                        slice_metadata=dict(state.slice.metadata),
                        progress=reporter,
                        slice_index=state.index,
                        slices_total=reporter.slices_total if reporter is not None else 0,
                    )
                    state.replace(method.apply_contour(contour, params, context))
                diagnostics.extend(stage_diagnostics)
                if any(d.severity == Severity.ERROR for d in stage_diagnostics):
                    partial = True
            except DomainError as exc:
                diag = self.domain_diag(exc, slice_.id, op.method)
                if exc.contour_id is None and len(selected) == 1:
                    diag.contour_id = selected[0].id
                diagnostics.append(diag)
                if request.failure_policy == FailurePolicy.STRICT:
                    raise
                decision = policies.operation_failure(request.failure_policy)
                if decision.fail_slice:
                    return self.failed(original, diagnostics)
                state = SliceState(before)
                partial = True

        final_diagnostics = final_invariants(state.slice, request)
        diagnostics.extend(final_diagnostics)
        errors = [d for d in final_diagnostics if d.severity == Severity.ERROR]
        if errors:
            if request.failure_policy == FailurePolicy.STRICT:
                raise DomainError(
                    errors[0].code,
                    errors[0].message,
                    slice_id=state.id,
                    contour_id=errors[0].contour_id,
                )
            if request.failure_policy == FailurePolicy.PER_SLICE:
                return self.failed(original, diagnostics)
            partial = True

        return self.build_result(state.slice, original, diagnostics), False, partial

    # ------------------------------------------------------------- assembly
    def build_result(
        self, state: Slice, original: Slice, diagnostics: list[Diagnostic]
    ) -> SliceResult:
        by_id = {c.id: c for c in original.contours}
        contours: list[ContourResult] = []
        for contour in state.contours:
            source = by_id.get(contour.id)
            contours.append(
                ContourResult(
                    id=contour.id,
                    source_id=contour.id if source else None,
                    role=contour.role,
                    closed=contour.closed,
                    points=list(contour.points),
                    parent_id=contour.parent_id,
                    tags=list(contour.tags),
                    fold=contour.fold,
                    changed=(
                        source is None
                        or source.points != contour.points
                        or source.closed != contour.closed
                    ),
                    segment_tags=list(contour.segment_tags) if contour.segment_tags else None,
                    metrics=self.metrics(contour, source),
                )
            )
        return SliceResult(
            slice_id=state.id,
            index=state.index,
            frame_id=state.frame_id,
            changed=any(c.changed for c in contours),
            contours=contours,
            metrics=SliceMetrics(
                input_points=sum(len(c.points) for c in original.contours),
                output_points=sum(len(c.points) for c in state.contours),
                input_contours=len(original.contours),
                output_contours=len(state.contours),
            ),
            diagnostics=diagnostics,
        )

    def failed(self, original: Slice, diagnostics: list[Diagnostic]) -> tuple[SliceResult, bool, bool]:
        result = self.build_result(original.clone(), original, diagnostics)
        result.changed = False
        for contour in result.contours:
            contour.changed = False
        return result, True, True

    @staticmethod
    def metrics(contour: Contour, source: Contour | None) -> ContourMetrics:
        return ContourMetrics(
            input_points=len(source.points) if source else 0,
            output_points=len(contour.points),
            min_radius_mm=min_radius(contour.points, contour.closed),
            max_turn_deg=max_turn_deg(contour.points, contour.closed),
            max_source_deviation_mm=(
                polyline_max_deviation(contour.points, source.points, source.closed)
                if source is not None and source.points
                else None
            ),
            length_mm=polyline_length(contour.points, contour.closed),
            self_intersections=(
                count_self_intersections(contour.points, contour.closed)
                if len(contour.points) <= SELF_INTERSECTION_LIMIT
                else 0
            ),
        )

    @staticmethod
    def domain_diag(
        exc: DomainError, slice_id: str | None = None, stage: str | None = None
    ) -> Diagnostic:
        return diagnostic(
            Severity.ERROR,
            exc.code,
            exc.message,
            stage=exc.stage or stage,
            slice_id=exc.slice_id or slice_id,
            contour_id=exc.contour_id,
            point_index=exc.point_index,
            details=exc.details,
        )
