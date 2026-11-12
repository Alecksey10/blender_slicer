"""Parallel processing of independent slices.

The engine holds no state between calls, so slices of one request can be
processed concurrently.  The client (adapter) owns the decision: it passes the
number of workers, or ``None`` for "use what the machine offers".  A machine
without threads simply runs serially through the same code path.

Splitting is only safe when slices are independent, which they are by design:
normalization, operations and validation are all per slice.  ``STRICT`` failure
policy is the one exception, because it aborts the whole request; that case is
kept serial so semantics do not change.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import TYPE_CHECKING

from ..protocol.operations import FailurePolicy
from ..protocol.request import ProcessingRequest
from ..protocol.result import EngineInfo, ProcessingResult, ResultMetrics, ResultStatus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .progress import ProgressReporter

MAX_AUTO_WORKERS = 8


def available_workers() -> int:
    try:
        return max(1, min(MAX_AUTO_WORKERS, os.cpu_count() or 1))
    except NotImplementedError:  # pragma: no cover - exotic platforms
        return 1


def resolve_workers(workers: int | None) -> int:
    if workers is None or workers <= 0:
        return available_workers()
    return int(workers)


def split_request(request: ProcessingRequest, parts: int) -> list[ProcessingRequest]:
    """Split a request into contiguous chunks, preserving slice order."""

    slices = list(request.slices)
    parts = max(1, min(parts, len(slices) or 1))
    if parts == 1 or len(slices) <= 1:
        return [request]
    chunk_size = (len(slices) + parts - 1) // parts
    return [
        replace(request, slices=slices[start : start + chunk_size])
        for start in range(0, len(slices), chunk_size)
    ]


def merge_results(
    parts: list[ProcessingResult], request: ProcessingRequest
) -> ProcessingResult:
    slices = [slice_result for part in parts for slice_result in part.slices]
    failed = sum(part.metrics.slices_failed for part in parts)
    metrics = ResultMetrics(
        slices_in=len(request.slices),
        slices_ok=max(0, len(slices) - failed),
        slices_failed=failed,
        points_in=sum(part.metrics.points_in for part in parts),
        points_out=sum(part.metrics.points_out for part in parts),
    )
    if slices and failed == len(slices):
        status = ResultStatus.ERROR
    elif failed or any(part.status == ResultStatus.PARTIAL for part in parts):
        status = ResultStatus.PARTIAL
    else:
        status = ResultStatus.OK

    engine = parts[0].engine if parts else EngineInfo()
    return ProcessingResult(
        schema_version=parts[0].schema_version if parts else request.schema_version,
        protocol_version=parts[0].protocol_version if parts else request.protocol_version,
        request_id=request.request_id,
        status=status,
        engine=engine,
        units="mm",
        slices=slices,
        diagnostics=[d for part in parts for d in part.diagnostics],
        metrics=metrics,
        metadata=dict(request.metadata),
    )


def process_parallel(
    engine,
    request: ProcessingRequest,
    workers: int | None = None,
    reporter: "ProgressReporter | None" = None,
) -> ProcessingResult:
    """Run ``engine.process`` over slices in a thread pool and merge the results."""

    worker_count = resolve_workers(workers)
    slices = request.slices
    if (
        worker_count <= 1
        or len(slices) <= 1
        or request.failure_policy == FailurePolicy.STRICT
    ):
        return engine.process(request, reporter)

    # Validate once so an invalid envelope is not reported once per chunk.
    if not engine.validate(request).ok:
        return engine.process(request, reporter)

    chunks = split_request(request, worker_count)
    if len(chunks) <= 1:
        return engine.process(request, reporter)
    if reporter is not None:
        # Every chunk must report against the whole request, not its own size.
        reporter = reporter.derive(slices_total=len(slices))
    with ThreadPoolExecutor(
        max_workers=min(worker_count, len(chunks)), thread_name_prefix="slicer"
    ) as pool:
        # A Cancelled raised inside a worker propagates out of list(); the pool
        # is shut down by the context manager, so the host thread returns to
        # its UI loop immediately.
        parts = list(pool.map(lambda chunk: engine.process(chunk, reporter), chunks))
    return merge_results(parts, request)
