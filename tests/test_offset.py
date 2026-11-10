"""Cut offsets: the planar kernel, the per-axis policy and the engine method."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from blender_slicer.adapters.base.plan import (
    OFFSET_INWARD,
    OFFSET_NONE,
    OFFSET_OUTWARD,
    CutOffsetPolicy,
    SlicePlan,
)
from blender_slicer.engine import Engine
from blender_slicer.protocol.geometry import signed_area
from blender_slicer.protocol.offset import offset_polyline
from blender_slicer.protocol.types import (
    Contour,
    ContourRole,
    OperationSpec,
    ProcessingRequest,
    ResultStatus,
    Slice,
    TargetSelector,
)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _slice(offset_mm: float) -> Slice:
    return Slice(
        id="s0",
        index=0,
        offset_mm=offset_mm,
        contours=[Contour("c0", ContourRole.CUT, True, list(SQUARE))],
    )


def _request(slice_: Slice, params: dict) -> ProcessingRequest:
    return ProcessingRequest(
        request_id="offset",
        slices=[slice_],
        operations=[
            OperationSpec(
                method="offset_contour",
                params=params,
                target=TargetSelector(roles=(ContourRole.CUT,)),
            )
        ],
    )


class OffsetGeometryTests(unittest.TestCase):
    def test_miter_outward_grows_the_square(self):
        points, warnings = offset_polyline(SQUARE, True, 1.0, join="miter")
        self.assertEqual(warnings, [])
        self.assertAlmostEqual(signed_area(points), 144.0)
        xs = sorted({round(x, 6) for x, _y in points})
        self.assertEqual(xs, [-1.0, 11.0])

    def test_miter_inward_shrinks_the_square(self):
        points, warnings = offset_polyline(SQUARE, True, -1.0, join="miter")
        self.assertEqual(warnings, [])
        self.assertAlmostEqual(signed_area(points), 64.0)

    def test_round_join_keeps_the_same_bounds(self):
        points, warnings = offset_polyline(SQUARE, True, 1.0, join="round", arc_segments=6)
        self.assertEqual(warnings, [])
        self.assertAlmostEqual(min(x for x, _y in points), -1.0, places=9)
        self.assertAlmostEqual(max(x for x, _y in points), 11.0, places=9)
        self.assertAlmostEqual(min(y for _x, y in points), -1.0, places=9)
        self.assertAlmostEqual(max(y for _x, y in points), 11.0, places=9)
        # The arc adds points compared with the miter join.
        miter, _ = offset_polyline(SQUARE, True, 1.0, join="miter")
        self.assertGreater(len(points), len(miter))

    def test_outward_ignores_winding(self):
        clockwise = list(reversed(SQUARE))
        points, _warnings = offset_polyline(clockwise, True, 1.0, join="miter")
        self.assertAlmostEqual(signed_area(points), -144.0)

    def test_open_polyline_offset_goes_left(self):
        line = [(0.0, 0.0), (10.0, 0.0)]
        points, warnings = offset_polyline(line, False, 1.0)
        self.assertEqual(warnings, [])
        self.assertEqual(points, [(0.0, 1.0), (10.0, 1.0)])

    def test_zero_offset_returns_the_input(self):
        points, warnings = offset_polyline(SQUARE, True, 0.0)
        self.assertEqual(points, SQUARE)
        self.assertEqual(warnings, [])

    def test_too_large_inward_offset_is_reported(self):
        # A 10x1 strip cannot lose 1 mm from both long sides without folding
        # over itself, so the engine must say so instead of returning a
        # plausible-looking contour.
        rect = [(0.0, 0.0), (10.0, 0.0), (10.0, 1.0), (0.0, 1.0)]
        _contour, warnings = offset_polyline(rect, True, -2.0, join="miter")
        self.assertTrue(warnings)
        self.assertEqual(warnings[0]["code"], "E_CONSTRAINT_UNSATISFIED")

    def test_square_inward_offset_beyond_half_width_is_not_inverted(self):
        square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        contour, warnings = offset_polyline(square, True, -6.0, join="miter")
        self.assertEqual(len(contour), 4)
        self.assertNotIn("inverted", " ".join(w["message"] for w in warnings))


class CutOffsetPolicyTests(unittest.TestCase):
    def _settings(self, **overrides):
        values = dict(
            inset_enabled=True,
            inset_x_mode="OUTWARD",
            inset_y_mode="NONE",
            inset_z_mode="INWARD",
            inset_auto=True,
            inset_amount_mm=0.5,
            material_thickness_mm=3.0,
            material_kerf_mm=0.15,
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_default_axes(self):
        policy = CutOffsetPolicy.from_settings(self._settings())
        self.assertAlmostEqual(policy.minimum_mm, 1.65)
        self.assertAlmostEqual(policy.distance_for_axis("X"), 1.65)
        self.assertAlmostEqual(policy.distance_for_axis("Z"), -1.65)
        self.assertEqual(policy.distance_for_axis("Y"), 0.0)

    def test_manual_amount_is_never_below_the_material_radius(self):
        policy = CutOffsetPolicy.from_settings(self._settings(inset_auto=False, inset_amount_mm=0.2))
        self.assertAlmostEqual(policy.magnitude_mm, 1.65)
        policy = CutOffsetPolicy.from_settings(self._settings(inset_auto=False, inset_amount_mm=4.0))
        self.assertAlmostEqual(policy.magnitude_mm, 4.0)

    def test_disabled_policy_has_no_offset(self):
        policy = CutOffsetPolicy.from_settings(self._settings(inset_enabled=False))
        for axis in ("X", "Y", "Z"):
            self.assertEqual(policy.distance_for_axis(axis), 0.0)

    def test_modes_are_normalised(self):
        policy = CutOffsetPolicy(
            enabled=True,
            x_mode=OFFSET_INWARD,
            y_mode=OFFSET_OUTWARD,
            z_mode=OFFSET_NONE,
            thickness_mm=2.0,
            kerf_mm=0.0,
        )
        self.assertLess(policy.distance_for_axis("x"), 0)
        self.assertGreater(policy.distance_for_axis("y"), 0)
        self.assertEqual(policy.distance_for_axis("z"), 0.0)

    def test_plan_identity_is_stable_and_directional(self):
        plan = SlicePlan(model="Cube", mode="planar", axis="Z")
        other = SlicePlan(model="Cube", mode="planar", axis="X")
        self.assertEqual(plan.layer_id(), "Cube::planar-z")
        self.assertNotEqual(plan.layer_id(), other.layer_id())
        self.assertEqual(plan.layer_name(), "Cube · planar Z")

    def test_plan_from_settings(self):
        plan = SlicePlan.from_settings(self._settings())
        self.assertAlmostEqual(plan.cut_offset_for("X"), 1.65)
        self.assertAlmostEqual(plan.cut_offset_for("Z"), -1.65)


class OffsetOperationTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()

    def test_engine_applies_the_slice_offset(self):
        result = self.engine.process(
            _request(_slice(1.0), {"use_slice_offset": True, "join": "miter"})
        )
        self.assertEqual(result.status, ResultStatus.OK)
        contour = result.slices[0].contours[0]
        self.assertAlmostEqual(signed_area(contour.points), 144.0)
        self.assertTrue(contour.changed)

    def test_engine_applies_a_negative_slice_offset(self):
        result = self.engine.process(
            _request(_slice(-1.0), {"use_slice_offset": True, "join": "miter"})
        )
        self.assertEqual(result.status, ResultStatus.OK)
        self.assertAlmostEqual(signed_area(result.slices[0].contours[0].points), 64.0)

    def test_fixed_distance_wins_when_per_slice_offset_is_off(self):
        result = self.engine.process(
            _request(_slice(5.0), {"use_slice_offset": False, "distance_mm": 2.0, "join": "miter"})
        )
        self.assertAlmostEqual(signed_area(result.slices[0].contours[0].points), 196.0)

    def test_zero_offset_is_a_noop(self):
        result = self.engine.process(_request(_slice(0.0), {"use_slice_offset": True}))
        self.assertEqual(result.status, ResultStatus.OK)
        contour = result.slices[0].contours[0]
        self.assertFalse(contour.changed)
        self.assertEqual(contour.points, SQUARE)

    def test_method_is_in_the_descriptor(self):
        names = {method.name for method in self.engine.descriptor().methods}
        self.assertIn("offset_contour", names)


if __name__ == "__main__":
    unittest.main()
