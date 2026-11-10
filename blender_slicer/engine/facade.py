from __future__ import annotations

import json
import math
from dataclasses import asdict

from ..protocol.descriptor import EngineDescriptor, MethodDescriptor
from ..protocol.errors import DomainError
from ..protocol.geometry import (
    count_self_intersections,
    dist,
    max_turn_deg,
    min_radius,
    polyline_max_deviation,
    polyline_length,
    signed_area,
)
from .methods.base import MethodContext
from .methods.normalize import normalize_slice
from .registry import MethodRegistry, validate_params
from ..protocol.types import (
    Contour,
    ContourMetrics,
    ContourResult,
    Diagnostic,
    EngineInfo,
    ErrorCode,
    FailurePolicy,
    Limits,
    MaterialProfile,
    OperationSpec,
    ProcessingRequest,
    ProcessingResult,
    ResultMetrics,
    ResultStatus,
    Severity,
    Slice,
    SliceMetrics,
    SliceResult,
    TargetSelector,
    ValidationReport,
)

PROTOCOL_MAJOR = "1"
SCHEMA_VERSIONS = ("1.0",)
SELF_INTERSECTION_LIMIT = 5000


def _select_contours(slice_: Slice, selector: TargetSelector | None) -> list[Contour]:
    if selector is None or selector.is_empty():
        return list(slice_.contours)
    if selector.slice_ids is not None and slice_.id not in selector.slice_ids:
        return []
    if selector.slice_indices is not None and slice_.index not in selector.slice_indices:
        return []
    selected: list[Contour] = []
    for c in slice_.contours:
        if selector.contour_ids is not None and c.id not in selector.contour_ids:
            continue
        if selector.roles is not None and c.role not in selector.roles:
            continue
        if selector.tags_all and not all(t in c.tags for t in selector.tags_all):
            continue
        if selector.tags_any and not any(t in c.tags for t in selector.tags_any):
            continue
        selected.append(c)
    return selected


def _diag(
    severity: Severity,
    code: ErrorCode,
    message: str,
    *,
    stage: str | None = None,
    slice_id: str | None = None,
    contour_id: str | None = None,
    point_index: int | None = None,
    details: dict | None = None,
) -> Diagnostic:
    return Diagnostic(
        severity=severity,
        code=code,
        message=message,
        stage=stage,
        slice_id=slice_id,
        contour_id=contour_id,
        point_index=point_index,
        details=details or {},
    )


class Engine:
    def __init__(self, registry: MethodRegistry | None = None) -> None:
        self.registry = registry or MethodRegistry.builtins()

    # ------------------------------------------------------------------ API
    def descriptor(self) -> EngineDescriptor:
        return EngineDescriptor(
            name="slicer-engine",
            engine_version=EngineInfo().version,
            protocol_version=EngineInfo().protocol_version,
            schema_versions=SCHEMA_VERSIONS,
            limits=Limits(),
            methods=self.registry.all_descriptors(),
        )

    def descriptor_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(asdict(self.descriptor()), indent=indent, ensure_ascii=False)

    def process_json(self, payload: str | bytes) -> str:
        """JSON -> JSON boundary used by CLI/RPC style front ends.

        Malformed input is reported as a normal error result, never by raising
        a parser exception across the engine boundary.
        """
        from ..protocol.json_codec import dumps_result, loads_request

        try:
            request = loads_request(payload)
        except Exception as exc:  # JSONDecodeError, TypeError, KeyError, ...
            info = EngineInfo()
            result = ProcessingResult(
                schema_version="1.0",
                protocol_version=info.protocol_version,
                request_id="",
                status=ResultStatus.ERROR,
                engine=info,
                units="mm",
                slices=[],
                diagnostics=[
                    _diag(
                        Severity.ERROR,
                        ErrorCode.E_SCHEMA,
                        f"Invalid JSON request: {exc}",
                    )
                ],
            )
            return dumps_result(result)
        return dumps_result(self.process(request))

    def validate(self, request: ProcessingRequest) -> ValidationReport:
        diagnostics: list[Diagnostic] = []
        counts: dict[str, int] = {
            "slices": len(request.slices),
            "contours": sum(len(s.contours) for s in request.slices),
            "points": sum(len(c.points) for s in request.slices for c in s.contours),
            "operations": len(request.operations),
        }

        if not request.slices:
            diagnostics.append(
                _diag(Severity.ERROR, ErrorCode.E_SCHEMA, "Request contains no slices")
            )
        if request.protocol_version.split(".")[0] != PROTOCOL_MAJOR:
            diagnostics.append(
                _diag(
                    Severity.ERROR,
                    ErrorCode.E_PROTOCOL_VERSION,
                    f"Unsupported protocol version {request.protocol_version}",
                )
            )
        if request.schema_version not in SCHEMA_VERSIONS:
            diagnostics.append(
                _diag(
                    Severity.ERROR,
                    ErrorCode.E_SCHEMA,
                    f"Unsupported schema version {request.schema_version}",
                )
            )
        if request.units != "mm":
            diagnostics.append(
                _diag(Severity.ERROR, ErrorCode.E_UNITS, f"Only mm is supported, got {request.units!r}")
            )

        m = request.material
        for name, value in (
            ("thickness_mm", m.thickness_mm),
            ("min_bend_radius_mm", m.min_bend_radius_mm),
            ("max_bend_angle_deg", m.max_bend_angle_deg),
            ("min_segment_mm", m.min_segment_mm),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0:
                diagnostics.append(
                    _diag(
                        Severity.ERROR,
                        ErrorCode.E_PARAM,
                        f"Material {name} must be a positive finite number",
                        details={"value": value},
                    )
                )
        if not (0.0 <= m.k_factor <= 1.0):
            diagnostics.append(
                _diag(Severity.ERROR, ErrorCode.E_PARAM, "Material k_factor must be in [0, 1]")
            )

        if len(request.slices) > request.limits.max_slices:
            diagnostics.append(
                _diag(Severity.ERROR, ErrorCode.E_LIMIT_EXCEEDED, "Too many slices", details=counts)
            )
        if len(request.operations) > request.limits.max_operations:
            diagnostics.append(
                _diag(
                    Severity.ERROR,
                    ErrorCode.E_LIMIT_EXCEEDED,
                    "Too many operations",
                    details=counts,
                )
            )
        if counts["points"] > request.limits.max_total_points:
            diagnostics.append(
                _diag(
                    Severity.ERROR,
                    ErrorCode.E_LIMIT_EXCEEDED,
                    "Too many points",
                    details=counts,
                )
            )

        for op in request.operations:
            method = self.registry.get(op.method)
            if method is None:
                diagnostics.append(
                    _diag(
                        Severity.ERROR,
                        ErrorCode.E_UNKNOWN_METHOD,
                        f"Unknown method {op.method!r}",
                        stage=op.method,
                    )
                )
                continue
            try:
                validate_params(method.descriptor, op.params)
            except DomainError as exc:
                diagnostics.append(
                    _diag(
                        Severity.ERROR,
                        exc.code,
                        exc.message,
                        stage=op.method,
                        details=exc.details,
                    )
                )

        for slice_ in request.slices:
            if len(slice_.contours) > 0:
                for c in slice_.contours:
                    diagnostics.extend(self._validate_contour(c, slice_.id))
                    if len(c.points) > request.limits.max_points_per_contour:
                        diagnostics.append(
                            _diag(
                                Severity.ERROR,
                                ErrorCode.E_LIMIT_EXCEEDED,
                                "Contour exceeds max_points_per_contour",
                                slice_id=slice_.id,
                                contour_id=c.id,
                                details={"points": len(c.points)},
                            )
                        )

        ok = not any(d.severity == Severity.ERROR for d in diagnostics)
        return ValidationReport(ok=ok, diagnostics=diagnostics, counts=counts)

    def process(self, request: ProcessingRequest) -> ProcessingResult:
        report = self.validate(request)
        engine_info = EngineInfo()
        if not report.ok:
            return ProcessingResult(
                schema_version="1.0",
                protocol_version=engine_info.protocol_version,
                request_id=request.request_id,
                status=ResultStatus.ERROR,
                engine=engine_info,
                units="mm",
                slices=[],
                diagnostics=report.diagnostics,
                metrics=ResultMetrics(
                    slices_in=len(request.slices),
                    slices_ok=0,
                    slices_failed=len(request.slices),
                    points_in=report.counts.get("points", 0),
                    points_out=0,
                ),
                metadata=dict(request.metadata),
            )

        results: list[SliceResult] = []
        failed = 0
        partial = False
        points_out = 0
        for slice_ in request.slices:
            try:
                result, slice_failed, slice_partial = self._process_slice(slice_, request)
            except DomainError as exc:
                if request.failure_policy == FailurePolicy.STRICT:
                    diagnostic = _diag(
                        Severity.ERROR,
                        exc.code,
                        exc.message,
                        stage=exc.stage,
                        slice_id=exc.slice_id or slice_.id,
                        contour_id=exc.contour_id,
                        point_index=exc.point_index,
                        details=exc.details,
                    )
                    return ProcessingResult(
                        schema_version="1.0",
                        protocol_version=engine_info.protocol_version,
                        request_id=request.request_id,
                        status=ResultStatus.ERROR,
                        engine=engine_info,
                        units="mm",
                        slices=[],
                        diagnostics=[diagnostic],
                        metrics=ResultMetrics(
                            slices_in=len(request.slices),
                            slices_ok=0,
                            slices_failed=len(request.slices),
                            points_in=report.counts.get("points", 0),
                            points_out=0,
                        ),
                        metadata=dict(request.metadata),
                    )
                result, slice_failed, slice_partial = self._failed_slice(
                    slice_,
                    [
                        _diag(
                            Severity.ERROR,
                            exc.code,
                            exc.message,
                            stage=exc.stage,
                            slice_id=exc.slice_id or slice_.id,
                            contour_id=exc.contour_id,
                            point_index=exc.point_index,
                            details=exc.details,
                        )
                    ],
                )
            results.append(result)
            points_out += result.metrics.output_points
            if slice_failed:
                failed += 1
            if slice_partial:
                partial = True

        if failed == len(results) and results:
            status = ResultStatus.ERROR
        elif failed or partial:
            status = ResultStatus.PARTIAL
        else:
            status = ResultStatus.OK

        return ProcessingResult(
            schema_version="1.0",
            protocol_version=engine_info.protocol_version,
            request_id=request.request_id,
            status=status,
            engine=engine_info,
            units="mm",
            slices=results,
            diagnostics=[],
            metrics=ResultMetrics(
                slices_in=len(request.slices),
                slices_ok=len(results) - failed,
                slices_failed=failed,
                points_in=report.counts.get("points", 0),
                points_out=points_out,
            ),
            metadata=dict(request.metadata),
        )

    # ------------------------------------------------------------- internals
    def _validate_contour(self, contour: Contour, slice_id: str) -> list[Diagnostic]:
        out: list[Diagnostic] = []
        if len(contour.points) < (3 if contour.closed else 2):
            out.append(
                _diag(
                    Severity.ERROR,
                    ErrorCode.E_GEOM_DEGENERATE,
                    "Contour has too few points",
                    slice_id=slice_id,
                    contour_id=contour.id,
                )
            )
            return out
        for i, p in enumerate(contour.points):
            if not (math.isfinite(p[0]) and math.isfinite(p[1])):
                out.append(
                    _diag(
                        Severity.ERROR,
                        ErrorCode.E_NON_FINITE,
                        "Non-finite coordinate",
                        slice_id=slice_id,
                        contour_id=contour.id,
                        point_index=i,
                    )
                )
                break
        if contour.closed:
            if abs(signed_area(contour.points)) <= 1e-12:
                out.append(
                    _diag(
                        Severity.ERROR,
                        ErrorCode.E_GEOM_DEGENERATE,
                        "Closed contour has zero area",
                        slice_id=slice_id,
                        contour_id=contour.id,
                    )
                )
        return out

    def _process_slice(
        self, slice_: Slice, request: ProcessingRequest
    ) -> tuple[SliceResult, bool, bool]:
        original = slice_.clone()
        diagnostics: list[Diagnostic] = []
        try:
            state = normalize_slice(original.clone(), request.material, request.options, diagnostics)
        except DomainError as exc:
            if request.failure_policy == FailurePolicy.STRICT:
                raise
            return self._failed_slice(original, [self._domain_diag(exc, slice_.id)])

        partial = False
        for op in request.operations:
            if not op.enabled:
                continue
            method = self.registry.get(op.method)
            if method is None:
                # Validation should have caught this.
                continue
            try:
                params = validate_params(method.descriptor, op.params)
            except DomainError as exc:
                if request.failure_policy == FailurePolicy.STRICT:
                    raise
                diagnostics.append(self._domain_diag(exc, slice_.id))
                return self._failed_slice(original, diagnostics)

            selected = _select_contours(state, op.target or request.targets)
            if not selected:
                # A selector that misses everything is a configuration problem, but
                # for per-slice processing it is safer to leave the slice untouched.
                diagnostics.append(
                    _diag(
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
            ctx_diagnostics: list[Diagnostic] = []
            try:
                for contour in selected:
                    ctx = MethodContext(
                        material=request.material,
                        stage=op.method,
                        diagnostics=ctx_diagnostics,
                        slice_id=state.id,
                        contour_id=contour.id,
                    )
                    updated = method.apply_contour(contour, params, ctx)
                    for i, existing in enumerate(state.contours):
                        if existing.id == contour.id:
                            state.contours[i] = updated
                            break
                diagnostics.extend(ctx_diagnostics)
                if any(d.severity == Severity.ERROR for d in ctx_diagnostics):
                    partial = True
            except DomainError as exc:
                diag = self._domain_diag(exc, slice_.id, op.method)
                if exc.contour_id is None and len(selected) == 1:
                    diag.contour_id = selected[0].id
                diagnostics.append(diag)
                if request.failure_policy == FailurePolicy.STRICT:
                    raise
                if request.failure_policy == FailurePolicy.PER_SLICE:
                    return self._failed_slice(original, diagnostics)
                state = before
                partial = True

        final_diags = self._final_validate(state, request)
        diagnostics.extend(final_diags)
        final_errors = [d for d in final_diags if d.severity == Severity.ERROR]
        if final_errors:
            if request.failure_policy == FailurePolicy.STRICT:
                exc = DomainError(
                    final_errors[0].code,
                    final_errors[0].message,
                    slice_id=state.id,
                    contour_id=final_errors[0].contour_id,
                )
                raise exc
            if request.failure_policy == FailurePolicy.PER_SLICE:
                return self._failed_slice(original, diagnostics)
            partial = True

        result = self._build_slice_result(state, original, diagnostics)
        return result, False, partial

    def _final_validate(self, slice_: Slice, request: ProcessingRequest) -> list[Diagnostic]:
        out: list[Diagnostic] = []
        min_seg = request.material.min_segment_mm
        check_self = bool(request.metadata.get("check_self_intersections", True))
        for c in slice_.contours:
            out.extend(self._validate_contour(c, slice_.id))
            n = len(c.points)
            if n < 2:
                continue
            for i in range(n if c.closed else n - 1):
                d = dist(c.points[i], c.points[(i + 1) % n])
                if d < min_seg * 1e-3:
                    out.append(
                        _diag(
                            Severity.WARNING,
                            ErrorCode.E_GEOM_DEGENERATE,
                            f"Segment shorter than {min_seg:.4f} mm",
                            stage="validate",
                            slice_id=slice_.id,
                            contour_id=c.id,
                            point_index=i,
                            details={"length_mm": d},
                        )
                    )
                    break
            if check_self and n <= SELF_INTERSECTION_LIMIT:
                intersections = count_self_intersections(c.points, c.closed)
                if intersections:
                    out.append(
                        _diag(
                            Severity.ERROR,
                            ErrorCode.E_GEOM_SELF_INTERSECTION,
                            f"Contour has {intersections} self-intersection(s)",
                            stage="validate",
                            slice_id=slice_.id,
                            contour_id=c.id,
                            details={"count": intersections},
                        )
                    )
        return out

    def _build_slice_result(
        self, state: Slice, original: Slice, diagnostics: list[Diagnostic]
    ) -> SliceResult:
        by_id = {c.id: c for c in original.contours}
        contours: list[ContourResult] = []
        for c in state.contours:
            src = by_id.get(c.id)
            metrics = self._metrics(c, src)
            contours.append(
                ContourResult(
                    id=c.id,
                    source_id=c.id if src else None,
                    role=c.role,
                    closed=c.closed,
                    points=list(c.points),
                    parent_id=c.parent_id,
                    tags=list(c.tags),
                    fold=c.fold,
                    changed=(src is None or src.points != c.points or src.closed != c.closed),
                    segment_tags=list(c.segment_tags) if c.segment_tags else None,
                    metrics=metrics,
                )
            )
        in_points = sum(len(c.points) for c in original.contours)
        out_points = sum(len(c.points) for c in state.contours)
        return SliceResult(
            slice_id=state.id,
            index=state.index,
            frame_id=state.frame_id,
            changed=any(c.changed for c in contours),
            contours=contours,
            metrics=SliceMetrics(
                input_points=in_points,
                output_points=out_points,
                input_contours=len(original.contours),
                output_contours=len(state.contours),
            ),
            diagnostics=diagnostics,
        )

    def _failed_slice(self, original: Slice, diagnostics: list[Diagnostic]) -> tuple[SliceResult, bool, bool]:
        result = self._build_slice_result(original.clone(), original, diagnostics)
        result.changed = False
        for c in result.contours:
            c.changed = False
        return result, True, True

    def _metrics(self, c: Contour, src: Contour | None) -> ContourMetrics:
        length = polyline_length(c.points, c.closed)
        self_int = (
            count_self_intersections(c.points, c.closed)
            if len(c.points) <= SELF_INTERSECTION_LIMIT
            else 0
        )
        deviation = None
        if src is not None and src.points:
            deviation = polyline_max_deviation(c.points, src.points, src.closed)
        return ContourMetrics(
            input_points=len(src.points) if src else 0,
            output_points=len(c.points),
            min_radius_mm=min_radius(c.points, c.closed),
            max_turn_deg=max_turn_deg(c.points, c.closed),
            max_source_deviation_mm=deviation,
            length_mm=length,
            self_intersections=self_int,
        )

    @staticmethod
    def _domain_diag(
        exc: DomainError, slice_id: str | None = None, stage: str | None = None
    ) -> Diagnostic:
        return _diag(
            Severity.ERROR,
            exc.code,
            exc.message,
            stage=exc.stage or stage,
            slice_id=exc.slice_id or slice_id,
            contour_id=exc.contour_id,
            point_index=exc.point_index,
            details=exc.details,
        )


def describe_methods(descriptor: EngineDescriptor) -> list[dict]:
    """Small JSON-friendly descriptor helper used by the Blender GUI."""
    out = []
    for method in descriptor.methods:
        out.append(
            {
                "name": method.name,
                "title": method.title,
                "description": method.description,
                "scope": method.scope,
                "internal": method.internal,
                "stability": method.stability,
                "params": [
                    {
                        "name": p.name,
                        "title": p.title,
                        "type": p.type,
                        "default": p.default,
                        "min": p.min,
                        "max": p.max,
                        "step": p.step,
                        "unit": p.unit,
                        "choices": [{"value": c.value, "label": c.label} for c in p.choices],
                    }
                    for p in method.params
                ],
            }
        )
    return out
