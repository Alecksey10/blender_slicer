"""Validating, pipeline, selector and failure-policy tests for the engine."""

from __future__ import annotations

import unittest

from blender_slicer.engine import (
    Contour,
    ContourRole,
    Engine,
    FailurePolicy,
    Limits,
    MaterialProfile,
    OperationSpec,
    ProcessingRequest,
    Slice,
    SliceResult,
    TargetSelector,
    dumps_result,
)
from blender_slicer.protocol.types import ErrorCode, ResultStatus, Severity

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
TINY_TRIANGLE = [(0.0, 0.0), (3.0, 0.0), (0.0, 3.0)]


def _slice(points, sid="s0", index=0, closed=True, role=ContourRole.CUT, contour_id=None):
    contour = Contour(
        id=contour_id or f"{sid}.c0",
        role=role,
        closed=closed,
        points=[(float(x), float(y)) for x, y in points],
    )
    return Slice(id=sid, index=index, contours=[contour])


def _request(slices, operations=(), policy=FailurePolicy.PER_SLICE, **kwargs):
    return ProcessingRequest(
        request_id="t",
        slices=list(slices),
        operations=list(operations),
        failure_policy=policy,
        **kwargs,
    )


def _codes(diagnostics):
    return [d.code for d in diagnostics]


def _contour(result: SliceResult, contour_id: str):
    for c in result.contours:
        if c.id == contour_id:
            return c
    raise AssertionError(f"contour {contour_id} not in result")


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()

    def test_valid_square_is_accepted(self):
        report = self.engine.validate(_request([_slice(SQUARE)]))
        self.assertTrue(report.ok, [d.message for d in report.diagnostics])
        self.assertEqual(report.counts["points"], 4)

    def test_empty_request_is_rejected(self):
        report = self.engine.validate(_request([]))
        self.assertFalse(report.ok)
        self.assertIn(ErrorCode.E_SCHEMA, _codes(report.diagnostics))

    def test_unknown_method_is_rejected(self):
        request = _request([_slice(SQUARE)], [OperationSpec(method="does_not_exist")])
        report = self.engine.validate(request)
        self.assertFalse(report.ok)
        self.assertIn(ErrorCode.E_UNKNOWN_METHOD, _codes(report.diagnostics))

    def test_wrong_parameter_type_is_rejected(self):
        request = _request(
            [_slice(SQUARE)],
            [OperationSpec(method="fillet_corners", params={"radius_mm": "wide"})],
        )
        report = self.engine.validate(request)
        self.assertFalse(report.ok)
        self.assertIn(ErrorCode.E_PARAM, _codes(report.diagnostics))

    def test_unknown_parameter_is_rejected(self):
        request = _request(
            [_slice(SQUARE)],
            [OperationSpec(method="smooth", params={"iterations": 1, "depth": 3})],
        )
        report = self.engine.validate(request)
        self.assertFalse(report.ok)
        self.assertIn(ErrorCode.E_PARAM, _codes(report.diagnostics))

    def test_out_of_range_parameter_is_rejected(self):
        request = _request(
            [_slice(SQUARE)],
            [OperationSpec(method="smooth", params={"iterations": 99})],
        )
        self.assertFalse(self.engine.validate(request).ok)

    def test_non_finite_coordinate_is_rejected(self):
        bad = [(0.0, 0.0), (float("nan"), 0.0), (1.0, 1.0)]
        report = self.engine.validate(_request([_slice(bad)]))
        self.assertFalse(report.ok)
        self.assertIn(ErrorCode.E_NON_FINITE, _codes(report.diagnostics))

    def test_zero_area_contour_is_rejected(self):
        report = self.engine.validate(_request([_slice([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])]))
        self.assertFalse(report.ok)
        self.assertIn(ErrorCode.E_GEOM_DEGENERATE, _codes(report.diagnostics))

    def test_too_few_points_is_rejected(self):
        report = self.engine.validate(_request([_slice([(0.0, 0.0)], closed=False)]))
        self.assertFalse(report.ok)
        self.assertIn(ErrorCode.E_GEOM_DEGENERATE, _codes(report.diagnostics))

    def test_two_point_open_polyline_is_valid(self):
        report = self.engine.validate(_request([_slice([(0.0, 0.0), (1.0, 0.0)], closed=False)]))
        self.assertTrue(report.ok, [d.message for d in report.diagnostics])

    def test_point_limit_is_enforced(self):
        request = _request([_slice(SQUARE)], limits=Limits(max_total_points=3))
        report = self.engine.validate(request)
        self.assertFalse(report.ok)
        self.assertIn(ErrorCode.E_LIMIT_EXCEEDED, _codes(report.diagnostics))

    def test_protocol_and_schema_versions(self):
        request = _request([_slice(SQUARE)], protocol_version="2.0")
        self.assertIn(ErrorCode.E_PROTOCOL_VERSION, _codes(self.engine.validate(request).diagnostics))
        request = _request([_slice(SQUARE)], schema_version="9.9")
        self.assertIn(ErrorCode.E_SCHEMA, _codes(self.engine.validate(request).diagnostics))

    def test_units_must_be_millimetres(self):
        request = _request([_slice(SQUARE)], units="cm")
        self.assertIn(ErrorCode.E_UNITS, _codes(self.engine.validate(request).diagnostics))

    def test_material_k_factor_range(self):
        request = _request([_slice(SQUARE)], material=MaterialProfile(k_factor=2.0))
        self.assertFalse(self.engine.validate(request).ok)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()

    def test_smooth_pipeline_changes_geometry(self):
        request = _request(
            [_slice(SQUARE)],
            [
                OperationSpec(
                    method="smooth",
                    params={"iterations": 2, "preserve_corners_deg": 180.0, "max_deviation_mm": 0.0},
                )
            ],
        )
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.OK)
        contour = _contour(result.slices[0], "s0.c0")
        self.assertTrue(contour.changed)
        self.assertGreater(len(contour.points), len(SQUARE))
        self.assertLess(abs(sum(p[0] for p in contour.points)), 1e6)

    def test_smooth_deviation_guard_vetoes_the_change(self):
        request = _request(
            [_slice(SQUARE)],
            [
                OperationSpec(
                    method="smooth",
                    params={"iterations": 2, "preserve_corners_deg": 180.0, "max_deviation_mm": 0.2},
                )
            ],
        )
        result = self.engine.process(request)
        contour = _contour(result.slices[0], "s0.c0")
        self.assertFalse(contour.changed)
        self.assertEqual(contour.points, SQUARE)
        self.assertIn(ErrorCode.E_CONSTRAINT_UNSATISFIED, _codes(result.slices[0].diagnostics))

    def test_metrics_are_reported(self):
        request = _request([_slice(SQUARE)], [OperationSpec(method="simplify", params={})])
        result = self.engine.process(request)
        contour = _contour(result.slices[0], "s0.c0")
        self.assertAlmostEqual(contour.metrics.length_mm, 40.0, places=6)
        self.assertIsNotNone(contour.metrics.min_radius_mm)
        self.assertEqual(contour.metrics.self_intersections, 0)

    def test_determinism(self):
        request = _request(
            [_slice(SQUARE)],
            [
                OperationSpec(method="fillet_corners", params={"radius_mm": 1.0, "mode": "clamp"}),
                OperationSpec(method="smooth", params={"iterations": 1}),
            ],
        )
        self.assertEqual(
            dumps_result(self.engine.process(request)),
            dumps_result(self.engine.process(request)),
        )

    def test_failed_slice_does_not_break_others(self):
        big_square = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
        good = _slice(big_square, "s0", 0)
        bad = _slice(TINY_TRIANGLE, "s1", 1)
        request = _request(
            [good, bad],
            [OperationSpec(method="fillet_corners", params={"radius_mm": 2.0, "mode": "error"})],
        )
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.PARTIAL)
        self.assertEqual(result.metrics.slices_failed, 1)
        self.assertEqual(result.metrics.slices_ok, 1)

        ok_contour = _contour(result.slices[0], "s0.c0")
        self.assertTrue(ok_contour.changed)
        self.assertGreater(len(ok_contour.points), len(big_square))

        failed_contour = _contour(result.slices[1], "s1.c0")
        self.assertEqual(failed_contour.points, TINY_TRIANGLE)
        self.assertFalse(failed_contour.changed)
        self.assertTrue(
            any(d.severity == Severity.ERROR for d in result.slices[1].diagnostics)
        )

    def test_strict_policy_aborts_everything(self):
        request = _request(
            [_slice(SQUARE, "s0"), _slice(TINY_TRIANGLE, "s1", 1)],
            [OperationSpec(method="fillet_corners", params={"radius_mm": 50.0, "mode": "error"})],
            policy=FailurePolicy.STRICT,
        )
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.ERROR)
        self.assertEqual(result.slices, [])
        self.assertTrue(any(d.severity == Severity.ERROR for d in result.diagnostics))

    def test_best_effort_keeps_failed_slice_untouched(self):
        request = _request(
            [_slice(SQUARE, "s0"), _slice(TINY_TRIANGLE, "s1", 1)],
            [OperationSpec(method="fillet_corners", params={"radius_mm": 50.0, "mode": "error"})],
            policy=FailurePolicy.BEST_EFFORT,
        )
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.PARTIAL)
        self.assertEqual(len(result.slices), 2)
        self.assertEqual(_contour(result.slices[1], "s1.c0").points, TINY_TRIANGLE)

    def test_self_intersection_is_reported(self):
        contour = [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (1.0, -1.0), (0.0, 3.0)]
        request = _request(
            [_slice(contour)],
            metadata={"check_self_intersections": True},
        )
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.ERROR)
        codes = _codes(result.slices[0].diagnostics)
        self.assertIn(ErrorCode.E_GEOM_SELF_INTERSECTION, codes)

    def test_disabled_operation_is_skipped(self):
        request = _request(
            [_slice(SQUARE)],
            [OperationSpec(method="smooth", params={"iterations": 5}, enabled=False)],
        )
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.OK)
        self.assertFalse(result.slices[0].changed)

    def test_cut_thin_sections_removes_thin_tab(self):
        # 20x18 square with a thin 1mm tab on top. min_width_mm=4 removes the
        # tab; main body corners have long edges so fillet radius 4 fits.
        contour = [
            (0.0, 0.0), (20.0, 0.0), (20.0, 18.0),
            (19.0, 18.0), (19.0, 19.0), (17.0, 19.0), (17.0, 18.0), (0.0, 18.0),
        ]
        request = _request(
            [_slice(contour)],
            [
                OperationSpec(
                    method="cut_thin_sections",
                    params={
                        "min_width_mm": 4.0,
                        "corner_turn_deg": 20.0,
                        "max_removed_ratio": 0.5,
                    },
                ),
                OperationSpec(method="fillet_corners", params={"radius_mm": 4.0, "mode": "error"}),
            ],
        )
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.OK, result.slices[0].diagnostics)
        out = _contour(result.slices[0], "s0.c0")
        self.assertTrue(out.changed)
        self.assertNotIn((19.0, 19.0), out.points)
        self.assertNotIn((17.0, 19.0), out.points)

    def test_cut_thin_sections_prevents_fillet_failure(self):
        # Without cut_thin_sections, the tab's tight corners make fillet
        # radius 4 fail (error mode).  With cut_thin_sections first, fillet
        # succeeds because the tab is gone and main body corners are wide.
        contour = [
            (0.0, 0.0), (20.0, 0.0), (20.0, 18.0),
            (19.0, 18.0), (19.0, 19.0), (17.0, 19.0), (17.0, 18.0), (0.0, 18.0),
        ]
        # Fillet alone should fail on this contour.
        request_fail = _request(
            [_slice(contour)],
            [OperationSpec(method="fillet_corners", params={"radius_mm": 4.0, "mode": "error"})],
        )
        result_fail = self.engine.process(request_fail)
        self.assertIn(result_fail.status, (ResultStatus.PARTIAL, ResultStatus.ERROR))

        # With cut_thin_sections first, fillet succeeds.
        request_ok = _request(
            [_slice(contour)],
            [
                OperationSpec(
                    method="cut_thin_sections",
                    params={"min_width_mm": 4.0, "corner_turn_deg": 20.0, "max_removed_ratio": 0.5},
                ),
                OperationSpec(method="fillet_corners", params={"radius_mm": 4.0, "mode": "error"}),
            ],
        )
        result_ok = self.engine.process(request_ok)
        self.assertEqual(result_ok.status, ResultStatus.OK)

    def test_trim_tight_corners_prevents_fillet_failure(self):
        contour = [
            (0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (12.0, 0.0),
            (16.0, 0.0), (20.0, 0.0), (20.0, 9.0), (20.0, 18.0),
            (19.0, 18.0), (19.0, 19.0), (17.0, 19.0), (17.0, 18.0),
            (12.0, 18.0), (6.0, 18.0), (0.0, 18.0), (0.0, 9.0),
        ]
        fillet = OperationSpec(
            method="fillet_corners", params={"radius_mm": 4.0, "mode": "error"}
        )
        result_fail = self.engine.process(_request([_slice(contour)], [fillet]))
        self.assertIn(result_fail.status, (ResultStatus.PARTIAL, ResultStatus.ERROR))

        request_ok = _request(
            [_slice(contour)],
            [
                OperationSpec(
                    method="trim_tight_corners",
                    params={
                        "radius_mm": 4.0,
                        "min_turn_deg": 20.0,
                        "max_removed_ratio": 0.5,
                        "action": "trim",
                    },
                ),
                fillet,
            ],
        )
        result_ok = self.engine.process(request_ok)
        self.assertEqual(result_ok.status, ResultStatus.OK, result_ok.slices[0].diagnostics)
        out = _contour(result_ok.slices[0], "s0.c0")
        self.assertNotIn((19.0, 19.0), out.points)
        self.assertNotIn((17.0, 19.0), out.points)

    def test_trim_tight_corners_can_ignore_the_contour(self):
        contour = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        request = _request(
            [_slice(contour)],
            [
                OperationSpec(
                    method="trim_tight_corners",
                    params={"radius_mm": 5.0, "action": "ignore"},
                )
            ],
        )
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.OK)
        out = _contour(result.slices[0], "s0.c0")
        self.assertEqual(out.points, contour)
        self.assertFalse(out.changed)
        self.assertIn(ErrorCode.I_INFO, _codes(result.slices[0].diagnostics))

    def test_cut_thin_sections_is_noop_on_regular_contour(self):
        request = _request(
            [_slice(SQUARE)],
            [OperationSpec(method="cut_thin_sections", params={"min_width_mm": 4.0})],
        )
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.OK)
        self.assertFalse(result.slices[0].changed)
        self.assertEqual(_contour(result.slices[0], "s0.c0").points, SQUARE)


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()
        self.slice = Slice(
            id="s0",
            index=0,
            contours=[
                Contour(id="s0.cut", role=ContourRole.CUT, closed=True, points=list(SQUARE)),
                Contour(
                    id="s0.score",
                    role=ContourRole.SCORE,
                    closed=False,
                    points=[(0.0, 5.0), (5.0, 5.0), (10.0, 5.0)],
                ),
            ],
        )

    def test_roles_selector(self):
        request = _request(
            [self.slice],
            [
                OperationSpec(
                    method="smooth",
                    params={"iterations": 2},
                    target=TargetSelector(roles=(ContourRole.SCORE,)),
                )
            ],
        )
        result = self.engine.process(request)
        self.assertEqual(_contour(result.slices[0], "s0.cut").points, SQUARE)
        self.assertTrue(_contour(result.slices[0], "s0.score").changed)

    def test_selector_that_matches_nothing_warns(self):
        request = _request(
            [self.slice],
            [
                OperationSpec(
                    method="smooth",
                    params={},
                    target=TargetSelector(tags_all=("missing",)),
                )
            ],
        )
        result = self.engine.process(request)
        self.assertEqual(result.status, ResultStatus.PARTIAL)
        self.assertFalse(result.slices[0].changed)
        self.assertIn(ErrorCode.E_TARGET_EMPTY, _codes(result.slices[0].diagnostics))

    def test_slice_ids_selector(self):
        other = Slice(
            id="s1",
            index=1,
            contours=[Contour(id="s1.c0", role=ContourRole.CUT, closed=True, points=list(SQUARE))],
        )
        request = _request(
            [self.slice, other],
            [
                OperationSpec(
                    method="smooth",
                    params={"iterations": 2, "preserve_corners_deg": 180.0, "max_deviation_mm": 0.0},
                    target=TargetSelector(slice_ids=("s1",)),
                )
            ],
        )
        result = self.engine.process(request)
        self.assertFalse(result.slices[0].changed)
        self.assertTrue(result.slices[1].changed)


if __name__ == "__main__":
    unittest.main()
