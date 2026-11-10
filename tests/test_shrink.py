"""Section shrink (README 0.3): narrow wide sections without losing smoothness."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from blender_slicer.adapters.base.plan import SectionShrinkPolicy, SlicePlan
from blender_slicer.engine import Engine
from blender_slicer.engine.methods.base import MethodContext
from blender_slicer.engine.methods.shrink import ShrinkMethod
from blender_slicer.engine.registry import validate_params
from blender_slicer.protocol.shrink import bounds_center, shrink_points
from blender_slicer.protocol.types import (
    Contour,
    ContourRole,
    MaterialProfile,
    OperationSpec,
    ProcessingRequest,
    ResultStatus,
    Slice,
    TargetSelector,
)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _bbox(points):
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _slice(index: int, ratio: float, points=SQUARE) -> Slice:
    return Slice(
        id=f"s{index}",
        index=index,
        metadata={"shrink_ratio": ratio},
        contours=[Contour(f"c{index}", ContourRole.CUT, True, list(points))],
    )


class ShrinkGeometryTests(unittest.TestCase):
    def test_uniform_shrink_keeps_the_centre(self):
        points = shrink_points(SQUARE, 0.5)
        self.assertEqual(_bbox(points), (2.5, 2.5, 7.5, 7.5))
        self.assertEqual(bounds_center(points), (5.0, 5.0))

    def test_ratio_one_returns_the_input(self):
        self.assertEqual(shrink_points(SQUARE, 1.0), SQUARE)

    def test_bounds_anchor_centres_an_off_centre_shape(self):
        offset_square = [(10.0, 0.0), (20.0, 0.0), (20.0, 10.0), (10.0, 10.0)]
        points = shrink_points(offset_square, 0.5, anchor="bounds")
        self.assertEqual(_bbox(points), (12.5, 2.5, 17.5, 7.5))

    def test_open_polyline_shrinks_without_closing(self):
        line = [(0.0, 0.0), (10.0, 0.0)]
        self.assertEqual(shrink_points(line, 0.5, closed=False), [(2.5, 0.0), (7.5, 0.0)])


class ShrinkMethodTests(unittest.TestCase):
    def _context(self, ratio: float | None = None) -> MethodContext:
        metadata = {} if ratio is None else {"shrink_ratio": ratio}
        return MethodContext(
            material=MaterialProfile(id="pla", name="PLA", thickness_mm=3.0),
            stage="shrink_section",
            slice_metadata=metadata,
        )

    def _apply(self, params: dict, ctx: MethodContext) -> Contour:
        contour = Contour("c0", ContourRole.CUT, True, list(SQUARE))
        values = validate_params(ShrinkMethod.descriptor, params)
        return ShrinkMethod().apply_contour(contour, values, ctx)

    def test_method_shrinks_by_an_explicit_ratio(self):
        out = self._apply(
            {"use_slice_ratio": False, "ratio": 0.5, "smooth_iterations": 0},
            self._context(),
        )
        self.assertEqual(_bbox(out.points), (2.5, 2.5, 7.5, 7.5))
        self.assertTrue(out.closed)

    def test_method_prefers_the_per_slice_ratio(self):
        out = self._apply(
            {"use_slice_ratio": True, "ratio": 1.0, "smooth_iterations": 0},
            self._context(0.6),
        )
        self.assertAlmostEqual(_bbox(out.points)[0], 2.0, places=9)

    def test_ratio_one_leaves_the_contour_untouched(self):
        out = self._apply(
            {"use_slice_ratio": True, "smooth_iterations": 0}, self._context(1.0)
        )
        self.assertEqual(out.points, SQUARE)

    def test_collapsing_ratio_is_reported_not_applied(self):
        ctx = self._context(0.0)
        out = self._apply({"use_slice_ratio": True, "smooth_iterations": 0}, ctx)
        self.assertEqual(out.points, SQUARE)
        self.assertTrue(ctx.diagnostics)
        self.assertEqual(ctx.diagnostics[0].code.value, "E_CONSTRAINT_UNSATISFIED")

    def test_smoothing_rounds_a_shrunk_contour_without_opening_it(self):
        dense = [
            (
                5.0 + 5.0 * __import__("math").cos(i * 0.2),
                5.0 + 5.0 * __import__("math").sin(i * 0.2),
            )
            for i in range(32)
        ]
        contour = Contour("c0", ContourRole.CUT, True, dense)
        values = validate_params(
            ShrinkMethod.descriptor,
            {"use_slice_ratio": True, "smooth_iterations": 2},
        )
        out = ShrinkMethod().apply_contour(contour, values, self._context(0.8))
        self.assertTrue(out.closed)
        self.assertGreaterEqual(len(out.points), 3)
        self.assertGreater(_bbox(out.points)[0], _bbox(dense)[0])


class EngineShrinkTests(unittest.TestCase):
    def test_request_applies_each_slice_ratio(self):
        request = ProcessingRequest(
            request_id="shrink",
            slices=[_slice(0, 1.0), _slice(1, 0.5)],
            operations=[
                OperationSpec(
                    method="shrink_section",
                    params={"use_slice_ratio": True, "smooth_iterations": 0},
                    target=TargetSelector(roles=(ContourRole.CUT,)),
                )
            ],
        )
        result = Engine().process(request)
        self.assertEqual(result.status, ResultStatus.OK)
        first = _bbox(result.slices[0].contours[0].points)
        second = _bbox(result.slices[1].contours[0].points)
        self.assertEqual(first, (0.0, 0.0, 10.0, 10.0))
        self.assertEqual(second, (2.5, 2.5, 7.5, 7.5))


class ShrinkPolicyTests(unittest.TestCase):
    def test_disabled_policy_keeps_full_size(self):
        policy = SectionShrinkPolicy(enabled=False, percent=50.0)
        self.assertEqual(policy.ratio_for_index(0, 5), 1.0)
        self.assertEqual(policy.ratio_for_index(2, 5), 1.0)

    def test_uniform_policy_gives_every_slice_the_same_ratio(self):
        policy = SectionShrinkPolicy(enabled=True, percent=20.0, mode="uniform")
        self.assertAlmostEqual(policy.target_ratio, 0.8)
        for index in range(5):
            self.assertAlmostEqual(policy.ratio_for_index(index, 5), 0.8)

    def test_middle_policy_keeps_ends_and_shrinks_the_middle(self):
        policy = SectionShrinkPolicy(enabled=True, percent=20.0, mode="middle")
        ratios = [policy.ratio_for_index(i, 5) for i in range(5)]
        self.assertAlmostEqual(ratios[0], 1.0)
        self.assertAlmostEqual(ratios[-1], 1.0)
        self.assertAlmostEqual(ratios[2], 0.8)
        self.assertTrue(ratios[0] > ratios[1] > ratios[2])

    def test_ends_policy_is_the_mirror_image(self):
        policy = SectionShrinkPolicy(enabled=True, percent=20.0, mode="ends")
        ratios = [policy.ratio_for_index(i, 5) for i in range(5)]
        self.assertAlmostEqual(ratios[0], 0.8)
        self.assertAlmostEqual(ratios[2], 1.0)

    def test_plan_reads_shrink_settings(self):
        settings = SimpleNamespace(
            shrink_enabled=True,
            shrink_percent=30.0,
            shrink_mode="UNIFORM",
            shrink_smooth_iterations=3,
        )
        plan = SlicePlan.from_settings(settings)
        self.assertTrue(plan.shrink.enabled)
        self.assertAlmostEqual(plan.shrink_ratio_for(0, 4), 0.7)
        self.assertAlmostEqual(plan.shrink_ratio_for(3, 4), 0.7)

    def test_percent_is_clamped(self):
        self.assertAlmostEqual(
            SectionShrinkPolicy(enabled=True, percent=500.0).target_ratio, 0.1
        )


if __name__ == "__main__":
    unittest.main()
