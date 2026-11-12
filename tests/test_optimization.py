"""Global curve optimizer (``optimize_curve``): kernel, method and client hooks."""

from __future__ import annotations

import math
import random
import unittest

from blender_slicer.engine import Engine
from blender_slicer.engine.progress import ProgressReporter
from blender_slicer.protocol.errors import Cancelled
from blender_slicer.protocol.geometry import optimize_curve, resample_by_count
from blender_slicer.protocol.geometry.optimization import _BandedSymmetric
from blender_slicer.protocol.types import (
    Contour,
    ContourRole,
    OperationSpec,
    ProcessingRequest,
    ResultStatus,
    Slice,
)

SQUARE = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]


def _dense_solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    n = len(rhs)
    a = [list(row) + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            for k in range(col, n + 1):
                a[row][k] -= factor * a[col][k]
    x = [0.0] * n
    for i in reversed(range(n)):
        total = a[i][n] - sum(a[i][j] * x[j] for j in range(i + 1, n))
        x[i] = total / a[i][i]
    return x


class BandedSolverTests(unittest.TestCase):
    def test_banded_solve_matches_dense(self):
        random.seed(7)
        size, band = 24, 3
        # SPD banded matrix: A = R^T R + n I with R banded.
        r = [[0.0] * size for _ in range(size)]
        for i in range(size):
            for offset in range(band + 1):
                if i + offset < size:
                    r[i][i + offset] = random.uniform(-1.0, 1.0)
        dense = [[0.0] * size for _ in range(size)]
        for i in range(size):
            for j in range(size):
                dense[i][j] = sum(r[k][i] * r[k][j] for k in range(size))
        for i in range(size):
            dense[i][i] += size

        banded = _BandedSymmetric(size, band)
        for i in range(size):
            for j in range(max(0, i - band), i + 1):
                banded.add(i, j, dense[i][j])
        banded.factor()

        rhs = [random.uniform(-5.0, 5.0) for _ in range(size)]
        expected = _dense_solve(dense, rhs)
        actual = banded.solve(rhs)
        for want, got in zip(expected, actual):
            self.assertAlmostEqual(want, got, places=9)


class ResampleTests(unittest.TestCase):
    def test_resample_by_count_is_exact(self):
        points = resample_by_count(SQUARE, True, 64)
        self.assertEqual(len(points), 64)

    def test_open_curve_keeps_its_endpoints(self):
        points = resample_by_count([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)], False, 41)
        self.assertEqual(len(points), 41)
        self.assertAlmostEqual(points[0][0], 0.0)
        self.assertAlmostEqual(points[0][1], 0.0)
        self.assertAlmostEqual(points[-1][0], 10.0)
        self.assertAlmostEqual(points[-1][1], 10.0)


class OptimizerKernelTests(unittest.TestCase):
    def test_sharp_corners_are_rounded_to_the_material_radius(self):
        points, stats = optimize_curve(
            SQUARE,
            True,
            count=120,
            data_weight=20.0,
            smooth=0.5,
            min_radius_mm=3.0,
            radius_weight=1000.0,
            max_iterations=60,
        )
        self.assertEqual(len(points), 120)
        self.assertGreater(stats["iterations"], 1)
        # A soft penalty leaves a few hundredths of excess; the old sequential
        # stages leave a sharp 90 degree corner (radius ~0.1 mm) instead.
        self.assertGreaterEqual(stats["min_radius_mm"], 3.0 * 0.9)
        # The rounded corner stays on the source contour (a hair of overshoot is
        # the price of a soft penalty; it must not become a bulge).
        max_x = max(p[0] for p in points)
        self.assertLessEqual(max_x, 20.05)
        self.assertGreater(max_x, 17.0)

    def test_result_does_not_depend_on_the_sampling_density(self):
        radii = []
        for count in (60, 150, 320):
            _points, stats = optimize_curve(
                SQUARE,
                True,
                count=count,
                data_weight=20.0,
                smooth=0.5,
                min_radius_mm=3.0,
                radius_weight=1000.0,
                max_iterations=60,
            )
            radii.append(stats["min_radius_mm"])
        self.assertLess(max(radii) - min(radii), 0.6)
        for radius in radii:
            self.assertGreater(radius, 2.4)

    def test_smoothing_removes_the_zigzag(self):
        jagged = [
            (math.cos(i * 0.4) * (10.0 + (1.0 if i % 2 else -1.0)),
             math.sin(i * 0.4) * (10.0 + (1.0 if i % 2 else -1.0)))
            for i in range(16)
        ]
        points, stats = optimize_curve(
            jagged,
            True,
            count=160,
            data_weight=0.5,
            smooth=5.0,
            min_radius_mm=0.0,
            max_iterations=60,
        )
        self.assertEqual(len(points), 160)
        self.assertGreater(stats["iterations"], 0)
        radii = [
            math.dist(points[i - 1], points[i]) for i in range(len(points))
        ]
        self.assertGreater(min(radii), 0.0)

    def test_progress_is_reported_and_cancel_stops_early(self):
        seen: list[float] = []
        points, stats = optimize_curve(
            SQUARE,
            True,
            count=100,
            min_radius_mm=2.0,
            max_iterations=50,
            progress=lambda info: seen.append(info["fraction"]),
        )
        self.assertTrue(seen)
        self.assertLessEqual(max(seen), 1.0)

        cancelled, cancel_stats = optimize_curve(
            SQUARE,
            True,
            count=100,
            max_iterations=50,
            cancel=lambda: True,
        )
        self.assertEqual(cancel_stats["iterations"], 0)
        self.assertEqual(cancel_stats["message"], "cancelled")
        self.assertEqual(len(cancelled), 100)

    def test_short_contours_are_returned_unchanged(self):
        points, stats = optimize_curve([(0.0, 0.0), (1.0, 0.0)], False, count=50)
        self.assertEqual(points, [(0.0, 0.0), (1.0, 0.0)])
        self.assertIn("too short", stats["message"])


def _request(method: str = "optimize_curve", params: dict | None = None) -> ProcessingRequest:
    return ProcessingRequest(
        request_id="optimize",
        slices=[
            Slice(
                id="s0",
                index=0,
                contours=[
                    Contour(
                        "s0.c0",
                        ContourRole.CUT,
                        True,
                        list(SQUARE),
                    )
                ],
            )
        ],
        operations=[OperationSpec(method=method, params=params or {})],
    )


def _noisy_square(count: int = 160, jitter: float = 0.4) -> list[tuple[float, float]]:
    """A 100 mm square sampled along its perimeter, with a wobble on every point."""

    points = []
    perimeter = 400.0
    for i in range(count):
        t = perimeter * i / count
        if t < 100.0:
            p = (t, 0.0)
        elif t < 200.0:
            p = (100.0, t - 100.0)
        elif t < 300.0:
            p = (100.0 - (t - 200.0), 100.0)
        else:
            p = (0.0, 100.0 - (t - 300.0))
        wobble = jitter * math.sin(12.9898 * (i + 1))
        other = jitter * math.sin(4.1414 * (i + 3))
        points.append((p[0] + wobble, p[1] + other))
    return points


def _rms_second_difference(points: list[tuple[float, float]]) -> float:
    n = len(points)
    total = 0.0
    for i in range(n):
        a, b, c = points[i - 1], points[i], points[(i + 1) % n]
        total += (a[0] - 2 * b[0] + c[0]) ** 2 + (a[1] - 2 * b[1] + c[1]) ** 2
    return math.sqrt(total / n)


class SmoothingLengthTests(unittest.TestCase):
    """``smooth`` is a length in millimetres, not an arbitrary weight.

    As a raw weight it was divided by the cube of the point spacing, so at a
    typical 2.5 mm sampling even 10000 was only ~13x the data weight and the
    control looked dead.  These guard the mapping.
    """

    def _fit(self, points, smooth, count=None):
        out, _stats = optimize_curve(
            points,
            True,
            count=count or len(points),
            data_weight=20.0,
            smooth=smooth,
            min_radius_mm=6.0,
            radius_weight=1000.0,
            max_iterations=60,
        )
        return out

    def test_raising_the_length_straightens_the_curve(self):
        points = _noisy_square()
        none = _rms_second_difference(self._fit(points, 0.0))
        mild = _rms_second_difference(self._fit(points, 2.0))
        strong = _rms_second_difference(self._fit(points, 8.0))
        self.assertLess(mild, none * 0.9)
        self.assertLess(strong, mild * 0.9)

    def test_zero_length_leaves_the_bending_term_out(self):
        points = _noisy_square()
        kwargs = dict(
            count=len(points),
            data_weight=20.0,
            min_radius_mm=6.0,
            radius_weight=1000.0,
            max_iterations=20,
        )
        _out, off = optimize_curve(points, True, smooth=0.0, **kwargs)
        self.assertEqual(off["smooth_cost"], 0.0)
        _out, on = optimize_curve(points, True, smooth=4.0, **kwargs)
        self.assertGreater(on["smooth_cost"], 0.0)

    def test_the_length_means_the_same_at_any_sampling(self):
        # rms of the second difference scales with ds^2, so compare curvature.
        results = []
        for count in (120, 240):
            points = _noisy_square(count=count)
            out = self._fit(points, 3.0, count=count)
            ds = 400.0 / count
            results.append(_rms_second_difference(out) / (ds * ds))
        self.assertAlmostEqual(results[0], results[1], delta=results[0] * 0.2)


class EngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()

    def test_method_is_registered_with_its_descriptor(self):
        method = self.engine.registry.get("optimize_curve")
        self.assertIsNotNone(method)
        names = {p.name for p in method.descriptor.params}
        self.assertEqual(
            names,
            {
                "sample_points",
                "data_weight",
                "smooth",
                "use_material_min_radius",
                "min_radius_mm",
                "radius_weight",
                "max_iterations",
                "cost_tolerance",
            },
        )

    def test_pipeline_runs_and_metrics_are_reported(self):
        result = self.engine.process(
            _request(
                params={
                    "sample_points": 90,
                    "min_radius_mm": 3.0,
                    "radius_weight": 1000.0,
                }
            )
        )
        self.assertEqual(result.status, ResultStatus.OK)
        contour = result.slices[0].contours[0]
        self.assertEqual(len(contour.points), 90)
        self.assertTrue(contour.closed)
        self.assertIsNotNone(contour.metrics.min_radius_mm)
        self.assertGreaterEqual(contour.metrics.min_radius_mm, 3.0 * 0.85)
        self.assertIsNotNone(contour.metrics.max_source_deviation_mm)
        self.assertLess(contour.metrics.max_source_deviation_mm, 5.0)

    def test_material_radius_is_used_when_requested(self):
        request = _request(
            params={
                "sample_points": 90,
                "use_material_min_radius": True,
                "min_radius_mm": 0.5,
                "radius_weight": 1000.0,
            }
        )
        request.material.min_bend_radius_mm = 2.5
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.OK)
        self.assertGreaterEqual(result.slices[0].contours[0].metrics.min_radius_mm, 2.2)

    def test_large_contours_get_enough_samples_automatically(self):
        big = Slice(
            id="s0",
            index=0,
            contours=[
                Contour(
                    "s0.c0",
                    ContourRole.CUT,
                    True,
                    [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)],
                )
            ],
        )
        request = ProcessingRequest(
            request_id="floor",
            slices=[big],
            operations=[
                OperationSpec(
                    method="optimize_curve",
                    params={
                        "sample_points": 40,
                        "use_material_min_radius": False,
                        "min_radius_mm": 6.0,
                        "max_iterations": 10,
                    },
                )
            ],
        )
        contour = self.engine.process(request).slices[0].contours[0]
        # 40 requested points would sample the 4 m contour every 100 mm.
        self.assertGreater(len(contour.points), 400)
        self.assertAlmostEqual(contour.metrics.min_radius_mm, 6.0, delta=0.6)

    def test_coarse_sampling_is_reported_as_under_sampled(self):
        # A 4 m contour sampled every 80 mm cannot resolve a 6 mm bend: the arc
        # degenerates into a chamfer, so the method must say so instead of
        # silently returning a fit that looks wrong.
        big = Slice(
            id="s0",
            index=0,
            contours=[
                Contour(
                    "s0.c0",
                    ContourRole.CUT,
                    True,
                    [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)],
                )
            ],
        )
        request = ProcessingRequest(
            request_id="coarse",
            slices=[big],
            operations=[
                OperationSpec(
                    method="optimize_curve",
                    params={
                        "sample_points": 50,
                        "use_material_min_radius": False,
                        "min_radius_mm": 6.0,
                    },
                )
            ],
        )
        result = self.engine.process(request)
        messages = [d.message for d in result.diagnostics]
        messages += [d.message for entry in result.slices for d in entry.diagnostics]
        self.assertTrue(any("under-sampled" in text for text in messages), messages)

    def test_reporter_receives_slice_progress(self):
        events: list[dict] = []
        reporter = ProgressReporter(callback=events.append)
        self.engine.process(_request(params={"sample_points": 80}), reporter)
        self.assertTrue(events)
        self.assertEqual(events[-1]["slices_total"], 1)
        self.assertEqual(events[-1]["slice_index"], 0)
        self.assertEqual(events[-1]["stage"], "optimize_curve")

    def test_cancel_raises_out_of_the_engine(self):
        with self.assertRaises(Cancelled):
            self.engine.process(
                _request(params={"sample_points": 80, "max_iterations": 200}),
                ProgressReporter(cancel_check=lambda: True),
            )

    def test_serial_and_parallel_runs_agree(self):
        params = {"sample_points": 80, "min_radius_mm": 2.0}
        serial = self.engine.process(_request(params=params))
        parallel = self.engine.process_parallel(_request(params=params), workers=4)
        self.assertEqual(
            serial.slices[0].contours[0].points,
            parallel.slices[0].contours[0].points,
        )


if __name__ == "__main__":
    unittest.main()
