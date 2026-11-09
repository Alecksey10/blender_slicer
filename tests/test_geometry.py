"""Unit tests for the pure 2D geometry kernel."""

from __future__ import annotations

import math
import random
import unittest

from blender_slicer.core.errors import DomainError
from blender_slicer.core.geometry import (
    bend_allowance_mm,
    chaikin,
    count_self_intersections,
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

    def test_material_minimum_radius_produces_warning(self):
        _, warnings = fillet_corners(
            SQUARE, True, 2.0, 20.0, 2, material_min_radius_mm=6.0
        )
        self.assertEqual(len(warnings), 4)
        self.assertTrue(all("below material" in w["message"] for w in warnings))


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


if __name__ == "__main__":
    unittest.main()
