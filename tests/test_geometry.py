"""Unit tests for the pure 2D geometry kernel."""

from __future__ import annotations

import math
import random
import unittest

from blender_slicer.protocol.errors import DomainError
from blender_slicer.protocol.types import ErrorCode
from blender_slicer.protocol.geometry import (
    bend_allowance_mm,
    chaikin,
    collapse_collinear,
    count_self_intersections,
    cut_thin_sections,
    dedupe,
    densify,
    dist,
    fillet_corners,
    laplacian,
    limit_curvature,
    max_turn_deg,
    min_radius,
    point_in_polygon,
    point_to_polyline_distance,
    polyline_length,
    resample,
    _segments_strictly_intersect,
    sharp_corners,
    signed_area,
    simplify,
    tight_corners,
    trim_tight_corners,
    vertex_radius,
)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _has_point(points, target, tol=1e-9):
    return any(abs(p[0] - target[0]) <= tol and abs(p[1] - target[1]) <= tol for p in points)


def _brute_force_intersections(points, closed):
    """Reference implementation: the straightforward all-pairs loop."""
    n = len(points)
    if n < 4:
        return 0
    seg_count = n if closed else n - 1
    count = 0
    for i in range(seg_count):
        a = points[i]
        b = points[(i + 1) % n]
        for j in range(i + 1, seg_count):
            if j == i + 1:
                continue
            if closed and i == 0 and j == seg_count - 1:
                continue
            c = points[j]
            d = points[(j + 1) % n]
            if _segments_strictly_intersect(a, b, c, d):
                count += 1
    return count


class MeasurementTests(unittest.TestCase):
    def test_signed_area_and_orientation(self):
        self.assertAlmostEqual(signed_area(SQUARE), 100.0)
        self.assertAlmostEqual(signed_area(list(reversed(SQUARE))), -100.0)

    def test_polyline_length(self):
        self.assertAlmostEqual(polyline_length(SQUARE, True), 40.0)
        self.assertAlmostEqual(polyline_length(SQUARE, False), 30.0)

    def test_vertex_radius_of_right_angle(self):
        r = vertex_radius((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r, math.sqrt(2.0) / 2.0)

    def test_straight_vertex_has_no_radius(self):
        self.assertIsNone(vertex_radius((0.0, 0.0), (1.0, 0.0), (2.0, 0.0)))

    def test_min_radius_and_max_turn_of_square(self):
        self.assertAlmostEqual(min_radius(SQUARE, True), math.sqrt(2.0) / 2.0 * 10.0)
        self.assertAlmostEqual(max_turn_deg(SQUARE, True), 90.0)

    def test_point_in_polygon(self):
        self.assertTrue(point_in_polygon((5.0, 5.0), SQUARE))
        self.assertFalse(point_in_polygon((15.0, 5.0), SQUARE))
        # A point exactly on an edge counts as inside.
        self.assertTrue(point_in_polygon((0.0, 5.0), SQUARE))

    def test_point_to_polyline_distance(self):
        self.assertAlmostEqual(point_to_polyline_distance((5.0, 3.0), SQUARE, True), 3.0)

    def test_bend_allowance(self):
        expected = math.radians(90.0) * (2.0 + 0.42 * 3.0)
        self.assertAlmostEqual(bend_allowance_mm(90.0, 2.0, 3.0, 0.42), expected)


class DedupeTests(unittest.TestCase):
    def test_removes_consecutive_duplicates(self):
        points = [(0.0, 0.0), (0.0, 0.0), (1.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        self.assertEqual(dedupe(points, False), [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)])

    def test_drops_repeated_closing_point(self):
        points = SQUARE + [(0.0, 0.0)]
        self.assertEqual(len(dedupe(points, True)), 4)


class SelfIntersectionTests(unittest.TestCase):
    def test_square_has_none(self):
        self.assertEqual(count_self_intersections(SQUARE, True), 0)

    def test_bowtie_has_one(self):
        bowtie = [(0.0, 0.0), (4.0, 4.0), (4.0, 0.0), (0.0, 4.0)]
        self.assertEqual(count_self_intersections(bowtie, True), 1)

    def test_sweep_matches_brute_force_on_random_contours(self):
        rng = random.Random(20240517)
        for _ in range(40):
            points = [(rng.uniform(-5.0, 5.0), rng.uniform(-5.0, 5.0)) for _ in range(12)]
            for closed in (True, False):
                self.assertEqual(
                    count_self_intersections(points, closed),
                    _brute_force_intersections(points, closed),
                    f"mismatch for closed={closed} on {points}",
                )

    def test_sweep_matches_brute_force_on_random_walk(self):
        rng = random.Random(7)
        points = [(0.0, 0.0)]
        x, y = 0.0, 0.0
        for _ in range(120):
            x += rng.uniform(-1.0, 1.0)
            y += rng.uniform(-1.0, 1.0)
            points.append((x, y))
        for closed in (True, False):
            self.assertEqual(
                count_self_intersections(points, closed),
                _brute_force_intersections(points, closed),
            )

    def test_dense_convex_contour_is_cheap_and_clean(self):
        n = 3000
        circle = [
            (50.0 * math.cos(2 * math.pi * i / n), 50.0 * math.sin(2 * math.pi * i / n))
            for i in range(n)
        ]
        self.assertEqual(count_self_intersections(circle, True), 0)


class ResampleTests(unittest.TestCase):
    def test_open_line_uniform_spacing(self):
        points = resample([(0.0, 0.0), (10.0, 0.0)], False, 1.0)
        self.assertEqual(len(points), 11)
        for a, b in zip(points, points[1:]):
            self.assertAlmostEqual(dist(a, b), 1.0)

    def test_closed_loop_spacing_and_no_duplicate_end(self):
        points = resample(SQUARE, True, 1.0)
        self.assertEqual(len(points), 40)
        self.assertGreater(dist(points[0], points[-1]), 0.5)
        self.assertAlmostEqual(polyline_length(points, True), 40.0)

    def test_zero_spacing_returns_input(self):
        self.assertEqual(resample(SQUARE, True, 0.0), SQUARE)

    def test_adaptive_keeps_minimum_spacing(self):
        points = resample(SQUARE, True, 5.0, adaptive=True, min_spacing_mm=0.5)
        self.assertGreaterEqual(len(points), 8)
        self.assertGreater(dist(points[0], points[-1]), 0.5)


class SimplifyTests(unittest.TestCase):
    def test_removes_collinear_vertex(self):
        points = simplify([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (2.0, 1.0)], False, 0.01)
        self.assertEqual(points, [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0)])

    def test_keeps_shape_of_square_with_midpoints(self):
        dense = [
            (0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 5.0),
            (10.0, 10.0), (5.0, 10.0), (0.0, 10.0), (0.0, 5.0),
        ]
        points = simplify(dense, True, 0.01)
        self.assertLessEqual(len(points), 5)
        self.assertAlmostEqual(abs(signed_area(points)), 100.0)

    def test_zero_tolerance_is_a_noop(self):
        self.assertEqual(simplify(SQUARE, True, 0.0), SQUARE)


class SmoothTests(unittest.TestCase):
    def test_chaikin_rounds_corners(self):
        points = chaikin(SQUARE, True, 1)
        self.assertGreater(len(points), len(SQUARE))
        self.assertLess(abs(signed_area(points)), abs(signed_area(SQUARE)))

    def test_chaikin_preserves_a_single_anchor(self):
        points = chaikin(SQUARE, True, 2, {0})
        self.assertIn((0.0, 0.0), points)

    def test_chaikin_preserves_multiple_anchors(self):
        points = chaikin(SQUARE, True, 2, {0, 2})
        self.assertIn(SQUARE[0], points)
        self.assertIn(SQUARE[2], points)

    def test_chaikin_open_endpoints_fixed(self):
        line = [(0.0, 0.0), (5.0, 1.0), (10.0, 0.0)]
        points = chaikin(line, False, 2)
        self.assertEqual(points[0], line[0])
        self.assertEqual(points[-1], line[-1])

    def test_laplacian_keeps_endpoints_and_deviation_limit(self):
        line = [(0.0, 0.0), (5.0, 1.0), (10.0, 0.0)]
        points = laplacian(line, False, 10, 0.5, max_deviation_mm=0.05)
        self.assertEqual(points[0], line[0])
        self.assertEqual(points[-1], line[-1])
        for before, after in zip(line, points):
            self.assertLessEqual(dist(before, after), 0.05 + 1e-12)

    def test_sharp_corners_detects_square(self):
        self.assertEqual(len(sharp_corners(SQUARE, True, 70.0)), 4)


class FilletTests(unittest.TestCase):
    def test_right_angle_arc_is_geometrically_exact(self):
        points, warnings = fillet_corners(
            SQUARE, True, 2.0, 20.0, 3, mode="error", chord_tolerance_mm=0.05
        )
        self.assertEqual(warnings, [])
        # 4 corners x (4 arc segments + 1) points; corner vertices are gone.
        self.assertEqual(len(points), 20)
        self.assertFalse(_has_point(points, (10.0, 0.0)))
        self.assertTrue(_has_point(points, (8.0, 0.0)))
        self.assertTrue(_has_point(points, (10.0, 2.0)))

        center = (8.0, 2.0)
        arc = [p for p in points if 8.0 - 1e-9 <= p[0] <= 10.0 + 1e-9 and 0.0 - 1e-9 <= p[1] <= 2.0 + 1e-9]
        self.assertEqual(len(arc), 5)
        for p in arc:
            self.assertAlmostEqual(dist(p, center), 2.0)

    def test_radius_that_does_not_fit_clamps_with_warning(self):
        corner = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        points, warnings = fillet_corners(
            corner, False, 5.0, 20.0, 3, mode="clamp"
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("clamped", warnings[0]["message"])
        # start + 4 arc points (3 segments) + end
        self.assertEqual(len(points), 6)
        self.assertEqual(points[0], (0.0, 0.0))
        self.assertEqual(points[-1], (1.0, 1.0))
        self.assertTrue(_has_point(points, (0.5, 0.0)))
        self.assertTrue(_has_point(points, (1.0, 0.5)))

    def test_radius_that_does_not_fit_raises_in_error_mode(self):
        corner = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        with self.assertRaises(DomainError):
            fillet_corners(corner, False, 5.0, 20.0, 3, mode="error")

    def test_skip_mode_leaves_the_corner(self):
        corner = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        points, warnings = fillet_corners(corner, False, 5.0, 20.0, 3, mode="skip")
        self.assertEqual(warnings, [])
        self.assertEqual(points, corner)

    def test_collinear_vertex_is_untouched(self):
        line = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
        points, warnings = fillet_corners(line, False, 0.5, 20.0, 3)
        self.assertEqual(points, line)

    def test_near_collinear_mesh_noise_does_not_consume_corner_room(self):
        # A 0.0005 mm deviation on a 5 mm edge turns the vertex by ~0.006 deg.
        # It is mesh noise, not a corner: it must not halve the free room of
        # the real corner and make it clamp while an identical one does not.
        noisy = [(0.0, 0.0), (5.0, 0.0004), (10.0, 0.0), (10.0, 10.0)]
        points, warnings = fillet_corners(
            noisy, False, 4.0, 20.0, 3, mode="error"
        )
        self.assertEqual(warnings, [])
        self.assertTrue(_has_point(points, (6.0, 0.0)))
        self.assertTrue(_has_point(points, (10.0, 4.0)))

    def test_exact_fit_does_not_depend_on_float_noise(self):
        corner = [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0)]
        _, warnings = fillet_corners(
            corner, False, 2.5 + 1e-13, 20.0, 3, mode="clamp"
        )
        self.assertEqual(warnings, [])

    def test_material_minimum_radius_produces_warning(self):
        _, warnings = fillet_corners(
            SQUARE, True, 2.0, 20.0, 2, material_min_radius_mm=6.0
        )
        self.assertEqual(len(warnings), 4)
        self.assertTrue(all("below material" in w["message"] for w in warnings))


class TrimTightCornersTests(unittest.TestCase):
    def test_trims_a_tab_that_cannot_hold_the_radius(self):
        # 20x18 plate with a 2x1 mm tab: its corners need 4 mm of free room
        # for radius 4 and are cut off together with the join back to the body.
        contour = [
            (0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (12.0, 0.0),
            (16.0, 0.0), (20.0, 0.0), (20.0, 9.0), (20.0, 18.0),
            (19.0, 18.0), (19.0, 19.0), (17.0, 19.0), (17.0, 18.0),
            (12.0, 18.0), (6.0, 18.0), (0.0, 18.0), (0.0, 9.0),
        ]
        self.assertTrue(tight_corners(contour, True, 4.0))
        points, warnings = trim_tight_corners(contour, True, 4.0, 20.0, 0.5)
        self.assertLess(len(points), len(contour))
        self.assertNotIn((19.0, 19.0), points)
        self.assertNotIn((17.0, 19.0), points)
        self.assertEqual(tight_corners(points, True, 4.0), [])
        self.assertGreater(abs(signed_area(points)), 0.0)
        self.assertTrue(any(w["code"] == ErrorCode.I_INFO for w in warnings))

    def test_guard_keeps_a_small_contour_unchanged(self):
        square = [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)]
        points, warnings = trim_tight_corners(square, True, 4.0)
        self.assertEqual(points, square)
        self.assertTrue(any("kept unchanged" in w["message"] for w in warnings))

    def test_open_contour_endpoints_are_never_removed(self):
        line = [
            (0.0, 0.0), (5.0, 0.0), (5.0, 0.2),
            (5.2, 0.2), (5.2, 0.0), (10.0, 0.0),
        ]
        points, _ = trim_tight_corners(
            line, False, 2.0, min_turn_deg=20.0, max_removed_ratio=1.0
        )
        self.assertEqual(points[0], line[0])
        self.assertEqual(points[-1], line[-1])
        self.assertLess(len(points), len(line))
        self.assertTrue(all(abs(point[1]) <= 1e-9 for point in points))

    def test_ignore_reports_without_touching_geometry(self):
        corner = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        found = tight_corners(corner, False, 5.0)
        self.assertEqual(len(found), 1)
        self.assertLess(found[0][1], 5.0)


class DensifyAndCurvatureTests(unittest.TestCase):
    def test_densify_respects_max_spacing(self):
        points = densify(SQUARE, True, 2.0, 0.0, 0.05)
        self.assertGreaterEqual(len(points), 20)
        for a, b in zip(points, points[1:] + points[:1]):
            self.assertLessEqual(dist(a, b), 2.0 + 1e-9)

    def test_limit_curvature_removes_spike(self):
        spike = [(0.0, 0.0), (4.0, 0.0), (5.0, 2.0), (6.0, 0.0), (10.0, 0.0)]
        self.assertLess(min_radius(spike, False), 5.0)
        points, remaining = limit_curvature(spike, False, 5.0, 60, 0.5)
        self.assertEqual(remaining, 0)
        self.assertEqual(len(points), len(spike))
        self.assertLess(points[2][1], 2.0)
        # Every remaining corner now respects the minimum radius (or is straight).
        for i in range(1, len(points) - 1):
            r = vertex_radius(points[i - 1], points[i], points[i + 1])
            self.assertTrue(r is None or r >= 5.0 - 1e-9, r)

    def test_limit_curvature_keeps_endpoints(self):
        line = [(0.0, 0.0), (5.0, 0.1), (10.0, 0.0)]
        points, _ = limit_curvature(line, False, 2.0, 5, 0.5)
        self.assertEqual(points[0], line[0])
        self.assertEqual(points[-1], line[-1])


class CollinearInvarianceTests(unittest.TestCase):
    """Mesh triangulation adds points on straight edges; they must not matter."""

    def test_collinear_subdivision_does_not_change_the_fillet(self):
        plain = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        subdivided = [
            (0.0, 0.0),
            (0.05, 0.0),
            (5.0, 0.0),
            (10.0, 0.0),
            (10.0, 5.0),
            (10.0, 10.0),
            (5.0, 10.0),
            (0.0, 10.0),
            (0.0, 5.0),
        ]
        reference, warnings_a = fillet_corners(plain, True, 4.0, 20.0, 3, mode="error")
        result, warnings_b = fillet_corners(subdivided, True, 4.0, 20.0, 3, mode="error")
        self.assertEqual(warnings_a, [])
        self.assertEqual(warnings_b, [])
        self.assertEqual(len(result), len(reference))
        for point_a, point_b in zip(reference, result):
            self.assertAlmostEqual(point_a[0], point_b[0], places=9)
            self.assertAlmostEqual(point_a[1], point_b[1], places=9)
        self.assertAlmostEqual(min_radius(result, True), min_radius(reference, True), places=9)

    def test_collapse_keeps_real_corners_and_open_ends(self):
        self.assertEqual(
            collapse_collinear([(0.0, 0.0), (5.0, 0.0), (5.0, 5.0)], False),
            [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0)],
        )
        # A fully straight polyline has no corners to protect: it is kept as
        # written, and only redundant points inside a shape are removed.
        self.assertEqual(
            collapse_collinear([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)], False),
            [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)],
        )


class CutThinSectionsTests(unittest.TestCase):
    def test_thin_tab_is_cut_off(self):
        # A 10x4 rectangle with a thin 1mm x 1mm tab on the top edge.
        # min_width_mm=4: the tab's corners have both adjacent edges < 4mm,
        # so r_max = 0.5mm < 2mm => the tab is cut off.
        contour = [
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 4.0),
            (9.0, 4.0),
            (9.0, 5.0),  # thin tab tip
            (7.0, 5.0),
            (7.0, 4.0),
            (0.0, 4.0),
        ]
        result, warnings = cut_thin_sections(contour, True, min_width_mm=4.0)
        # Tab vertices are removed; the top edge becomes flat from x=10 to x=0.
        self.assertNotIn((9.0, 5.0), result)
        self.assertNotIn((7.0, 5.0), result)
        # The remaining contour is the 10x4 rectangle (5 points after dedupe
        # may keep a collinear point at (7,4) on the top edge).
        self.assertGreaterEqual(len(result), 4)
        self.assertTrue(any(abs(p[0] - 10.0) < 1e-9 and abs(p[1] - 4.0) < 1e-9 for p in result))
        self.assertTrue(any(abs(p[0] - 0.0) < 1e-9 and abs(p[1] - 4.0) < 1e-9 for p in result))
        self.assertGreater(len(warnings), 0)
        self.assertTrue(any("Cut" in w["message"] for w in warnings))

    def test_no_thin_sections_is_noop(self):
        square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        result, warnings = cut_thin_sections(square, True, min_width_mm=4.0)
        self.assertEqual(result, square)
        self.assertEqual(warnings, [])

    def test_small_min_width_does_not_cut(self):
        # A thin protrusion but min_width_mm is tiny => nothing is thin.
        contour = [
            (0.0, 0.0), (10.0, 0.0), (10.0, 4.0),
            (9.0, 4.0), (9.0, 5.0), (7.0, 5.0), (7.0, 4.0), (0.0, 4.0),
        ]
        result, warnings = cut_thin_sections(contour, True, min_width_mm=0.5)
        self.assertEqual(len(result), len(contour))
        self.assertEqual(warnings, [])

    def test_narrow_rectangle_is_not_cut(self):
        # A narrow 10x1 rectangle: corners have one long edge (10mm) so they
        # are not thin even though the contour is narrow overall.
        thin_rect = [
            (0.0, 0.0), (10.0, 0.0), (10.0, 1.0), (0.0, 1.0),
        ]
        result, warnings = cut_thin_sections(thin_rect, True, min_width_mm=4.0)
        self.assertEqual(result, thin_rect)
        self.assertEqual(warnings, [])

    def test_open_polyline_endpoints_are_never_cut(self):
        # Open line with a thin spike in the middle.
        line = [
            (0.0, 0.0), (5.0, 0.0), (5.0, 1.0), (6.0, 1.0), (6.0, 0.0), (10.0, 0.0),
        ]
        result, warnings = cut_thin_sections(line, False, min_width_mm=4.0)
        # Endpoints (0,0) and (10,0) are protected.
        self.assertEqual(result[0], (0.0, 0.0))
        self.assertEqual(result[-1], (10.0, 0.0))

    def test_corner_turn_threshold(self):
        # A nearly straight vertex should not be considered thin even if edges
        # are short.
        contour = [
            (0.0, 0.0), (10.0, 0.0), (10.5, 0.05), (11.0, 0.0), (20.0, 0.0),
            (20.0, 10.0), (0.0, 10.0),
        ]
        result, _ = cut_thin_sections(contour, True, min_width_mm=4.0, corner_turn_deg=80.0)
        # The shallow turn at (10.5, 0.05) is below 80 deg => not cut.
        self.assertTrue(any(abs(p[0] - 10.5) < 1e-9 and abs(p[1] - 0.05) < 1e-9 for p in result))

    def test_max_removed_ratio_protects_contour(self):
        # Many thin tabs: removing them all would exceed the ratio limit.
        # Build a contour with lots of short-edge corners.
        pts = []
        for i in range(20):
            pts.append((float(i), 0.0))
            pts.append((float(i), 1.0))
        result, warnings = cut_thin_sections(pts, True, min_width_mm=4.0, max_removed_ratio=0.1)
        # Nothing removed because ratio limit prevents it.
        self.assertEqual(len(result), len(pts))
        self.assertTrue(any("limit" in w["message"] or "kept unchanged" in w["message"] for w in warnings))


if __name__ == "__main__":
    unittest.main()
