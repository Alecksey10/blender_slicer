"""Multi-threaded processing of independent slices (README 0.2.1 #5)."""

from __future__ import annotations

import unittest

from blender_slicer.adapters.base.engine_client import EngineClient
from blender_slicer.engine import Engine
from blender_slicer.engine.parallel import (
    available_workers,
    merge_results,
    process_parallel,
    resolve_workers,
    split_request,
)
from blender_slicer.protocol.types import (
    Contour,
    ContourRole,
    FailurePolicy,
    OperationSpec,
    ProcessingRequest,
    ResultStatus,
    Slice,
)
from blender_slicer.protocol.json_codec import dumps_result

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _slice(index: int) -> Slice:
    shift = float(index)
    return Slice(
        id=f"s{index}",
        index=index,
        contours=[
            Contour(
                f"s{index}.c0",
                ContourRole.CUT,
                True,
                [(x + shift, y + shift) for x, y in SQUARE],
            )
        ],
    )


def _request(count: int = 8, **kwargs) -> ProcessingRequest:
    return ProcessingRequest(
        request_id="parallel",
        slices=[_slice(i) for i in range(count)],
        operations=[
            OperationSpec(
                method="fillet_corners",
                params={"radius_mm": 1.0, "mode": "clamp", "arc_segments": 3},
            ),
            OperationSpec(method="smooth", params={"iterations": 1}),
        ],
        **kwargs,
    )


class SplitTests(unittest.TestCase):
    def test_split_preserves_order_and_coverage(self):
        request = _request(7)
        chunks = split_request(request, 3)
        self.assertEqual(len(chunks), 3)
        ids = [slice_.id for chunk in chunks for slice_ in chunk.slices]
        self.assertEqual(ids, [slice_.id for slice_ in request.slices])
        self.assertEqual(sum(len(chunk.slices) for chunk in chunks), 7)

    def test_split_of_one_part_is_the_same_request(self):
        request = _request(4)
        self.assertEqual(split_request(request, 1), [request])

    def test_resolve_workers(self):
        self.assertEqual(resolve_workers(1), 1)
        self.assertEqual(resolve_workers(3), 3)
        self.assertGreaterEqual(available_workers(), 1)
        self.assertGreaterEqual(resolve_workers(0), 1)


class ParallelProcessingTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()

    def test_parallel_matches_serial(self):
        request = _request(8)
        serial = self.engine.process(request)
        parallel = process_parallel(self.engine, request, workers=4)
        self.assertEqual(dumps_result(serial), dumps_result(parallel))
        self.assertEqual(len(parallel.slices), 8)
        self.assertEqual(parallel.status, serial.status)

    def test_parallel_keeps_order(self):
        result = process_parallel(self.engine, _request(8), workers=4)
        self.assertEqual([s.slice_id for s in result.slices], [f"s{i}" for i in range(8)])

    def test_strict_policy_keeps_serial_semantics(self):
        request = _request(4, failure_policy=FailurePolicy.STRICT)
        request.operations = [
            OperationSpec(method="fillet_corners", params={"radius_mm": 50.0, "mode": "error"})
        ]
        serial = self.engine.process(request)
        parallel = process_parallel(self.engine, request, workers=4)
        self.assertEqual(serial.status, ResultStatus.ERROR)
        self.assertEqual(dumps_result(serial), dumps_result(parallel))

    def test_merge_results_sums_metrics(self):
        request = _request(4)
        chunks = split_request(request, 2)
        parts = [self.engine.process(chunk) for chunk in chunks]
        merged = merge_results(parts, request)
        self.assertEqual(merged.metrics.slices_in, 4)
        self.assertEqual(merged.metrics.points_out, sum(p.metrics.points_out for p in parts))
        self.assertEqual([s.slice_id for s in merged.slices], [s.id for s in request.slices])

    def test_client_reports_parallelism(self):
        serial = EngineClient(workers=1)
        parallel = EngineClient(workers=4)
        self.assertFalse(serial.parallel)
        self.assertTrue(parallel.parallel)
        self.assertEqual(serial.worker_count, 1)
        self.assertEqual(parallel.worker_count, 4)
        self.assertEqual(parallel.process(_request(4)).status, ResultStatus.OK)


if __name__ == "__main__":
    unittest.main()
