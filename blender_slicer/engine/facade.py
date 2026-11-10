"""Public facade of the logical engine.

The facade owns the request envelope: validation, failure policies, result
assembly.  Per-slice work is delegated to :class:`~.pipeline.runner.SliceRunner`,
and every validation rule lives in :mod:`~.validation`.

The engine is stateless and thread-safe as long as its registry is not mutated,
which is what lets the client process slices in parallel (see ``parallel.py``).
"""

from __future__ import annotations

import json
from dataclasses import asdict

from ..protocol.descriptor import EngineDescriptor, MethodDescriptor
from ..protocol.diagnostics import Diagnostic, ErrorCode, Severity, ValidationReport, diagnostic
from ..protocol.errors import DomainError
from ..protocol.operations import FailurePolicy
from ..protocol.request import ProcessingRequest
from ..protocol.result import EngineInfo, ProcessingResult, ResultMetrics, ResultStatus
from ..protocol.version import (
    ENGINE_NAME,
    ENGINE_VERSION,
    PROTOCOL_VERSION,
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
)
from .pipeline.runner import SliceRunner
from .registry import MethodRegistry, validate_params
from .validation.invariants import contour_invariants
from .validation.limits import check_envelope, check_limits, check_material

PROTOCOL_MAJOR = PROTOCOL_VERSION.split(".")[0]


class Engine:
    def __init__(self, registry: MethodRegistry | None = None) -> None:
        self.registry = registry or MethodRegistry.builtins()
        self.runner = SliceRunner(self.registry)

    # ------------------------------------------------------------------ API
    def descriptor(self) -> EngineDescriptor:
        return EngineDescriptor(
            name=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            protocol_version=PROTOCOL_VERSION,
            schema_versions=SUPPORTED_SCHEMA_VERSIONS,
            limits=self._default_limits(),
            methods=self.registry.all_descriptors(),
        )

    def descriptor_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(asdict(self.descriptor()), indent=indent, ensure_ascii=False)

    def process_json(self, payload: str | bytes) -> str:
        """JSON -> JSON boundary used by CLI/RPC style front ends.

        Malformed input is reported as a normal error result, never by raising a
        parser exception across the engine boundary.
        """
        from ..protocol.json_codec import dumps_result, loads_request

        try:
            request = loads_request(payload)
        except Exception as exc:  # JSONDecodeError, TypeError, KeyError, ...
            result = ProcessingResult(
                schema_version=SCHEMA_VERSION,
                protocol_version=PROTOCOL_VERSION,
                request_id="",
                status=ResultStatus.ERROR,
                engine=EngineInfo(),
                units="mm",
                slices=[],
                diagnostics=[
                    diagnostic(
                        Severity.ERROR, ErrorCode.E_SCHEMA, f"Invalid JSON request: {exc}"
                    )
                ],
            )
            return dumps_result(result)
        return dumps_result(self.process(request))

    def process_parallel(
        self, request: ProcessingRequest, workers: int | None = None
    ) -> ProcessingResult:
        """Process the request with a thread pool over independent slices.

        ``workers <= 1`` keeps the engine serial.  The result is identical to a
        serial run; the client decides whether parallelism is available at all.
        """
        from .parallel import process_parallel

        return process_parallel(self, request, workers)

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
                diagnostic(Severity.ERROR, ErrorCode.E_SCHEMA, "Request contains no slices")
            )
        diagnostics.extend(check_envelope(request))
        diagnostics.extend(check_material(request.material))
        diagnostics.extend(check_limits(request, counts))

        for op in request.operations:
            method = self.registry.get(op.method)
            if method is None:
                diagnostics.append(
                    diagnostic(
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
                    diagnostic(
                        Severity.ERROR,
                        exc.code,
                        exc.message,
                        stage=op.method,
                        details=exc.details,
                    )
                )

        for slice_ in request.slices:
            for contour in slice_.contours:
                diagnostics.extend(
                    contour_invariants(
                        contour,
                        slice_.id,
                        max_points=request.limits.max_points_per_contour,
                    )
                )

        ok = not any(d.severity == Severity.ERROR for d in diagnostics)
        return ValidationReport(ok=ok, diagnostics=diagnostics, counts=counts)

    def process(self, request: ProcessingRequest) -> ProcessingResult:
        report = self.validate(request)
        engine_info = EngineInfo()
        if not report.ok:
            return self._error_result(request, report.counts, report.diagnostics)

        results = []
        failed = 0
        partial = False
        points_out = 0
        for slice_ in request.slices:
            try:
                result, slice_failed, slice_partial = self.runner.run(slice_, request)
            except DomainError as exc:
                if request.failure_policy == FailurePolicy.STRICT:
                    return self._error_result(
                        request,
                        report.counts,
                        [SliceRunner.domain_diag(exc, slice_.id)],
                    )
                result, slice_failed, slice_partial = self.runner.failed(
                    slice_,
                    [SliceRunner.domain_diag(exc, slice_.id)],
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
            schema_version=SCHEMA_VERSION,
            protocol_version=PROTOCOL_VERSION,
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
    @staticmethod
    def _default_limits():
        from ..protocol.operations import Limits

        return Limits()

    @staticmethod
    def _error_result(
        request: ProcessingRequest, counts: dict[str, int], diagnostics: list[Diagnostic]
    ) -> ProcessingResult:
        return ProcessingResult(
            schema_version=SCHEMA_VERSION,
            protocol_version=PROTOCOL_VERSION,
            request_id=request.request_id,
            status=ResultStatus.ERROR,
            engine=EngineInfo(),
            units="mm",
            slices=[],
            diagnostics=diagnostics,
            metrics=ResultMetrics(
                slices_in=len(request.slices),
                slices_ok=0,
                slices_failed=len(request.slices),
                points_in=counts.get("points", 0),
                points_out=0,
            ),
            metadata=dict(request.metadata),
        )


def describe_methods(descriptor: EngineDescriptor) -> list[dict]:
    """Small JSON-friendly descriptor helper used by GUI adapters."""

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
