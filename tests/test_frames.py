"""Tests for the coordinate frame boundary (3D <-> 2D)."""

from __future__ import annotations

import math
import random
import unittest

from blender_slicer.core.frames import (
    make_frame,
    v3_cross,
    v3_dot,
    v3_length,
    v3_mul,
    v3_sub,
)


class FrameTests(unittest.TestCase):
    def test_frame_basis_is_orthonormal(self):
        frame = make_frame((1.0, 1.0, 0.0), (0.0, 1.0, 0.0), (2.0, 3.0, 4.0), 1000.0, "f0")
        for vec in (frame.u, frame.v, frame.normal):
            self.assertAlmostEqual(v3_length(vec), 1.0)
        self.assertAlmostEqual(v3_dot(frame.u, frame.v), 0.0)
        self.assertAlmostEqual(v3_dot(frame.u, frame.normal), 0.0)
        self.assertAlmostEqual(v3_dot(frame.v, frame.normal), 0.0)

    def test_round_trip_3d_to_2d_and_back(self):
        frame = make_frame((0.3, -0.4, 0.866), (1.0, 0.0, 0.0), (1.5, -2.0, 0.25), 1000.0, "f1")
        rng = random.Random(11)
        for _ in range(50):
            p = (rng.uniform(-3, 3), rng.uniform(-3, 3), rng.uniform(-3, 3))
            # Only points already in the plane round-trip exactly.
            offset = v3_dot(v3_sub(p, frame.origin), frame.normal)
            in_plane = v3_sub(p, v3_mul(frame.normal, offset))
            back = frame.to_3d(frame.to_2d(in_plane))
            for a, b in zip(in_plane, back):
                self.assertAlmostEqual(a, b, places=9)

    def test_points_are_projected_onto_the_plane(self):
        frame = make_frame((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1000.0, "f7")
        self.assertEqual(frame.to_2d((1.0, 2.0, 500.0)), (1000.0, 2000.0))

    def test_projection_drops_the_normal_component(self):
        frame = make_frame((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1000.0, "f2")
        self.assertEqual(frame.to_2d((1.0, 2.0, 5.0)), (1000.0, 2000.0))

    def test_degenerate_normal_falls_back_to_z(self):
        frame = make_frame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1.0, "f3")
        self.assertAlmostEqual(v3_dot(frame.normal, (0.0, 0.0, 1.0)), 1.0)

    def test_u_hint_parallel_to_normal_falls_back(self):
        frame = make_frame((0.0, 0.0, 1.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 1.0, "f4")
        self.assertAlmostEqual(v3_dot(frame.u, (0.0, 0.0, 1.0)), 0.0)
        self.assertAlmostEqual(v3_length(v3_cross(frame.u, frame.v)), 1.0)

    def test_2d_units_are_millimetres(self):
        frame = make_frame((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1000.0, "f5")
        # One Blender unit equals 1000 mm.
        self.assertEqual(frame.to_2d((1.0, 0.0, 0.0)), (1000.0, 0.0))
        self.assertEqual(frame.to_3d((1000.0, 0.0)), (1.0, 0.0, 0.0))

    def test_distance_is_preserved_by_the_projection(self):
        frame = make_frame((0.4, 0.5, 0.77), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1000.0, "f6")
        a = (1.0, 2.0, 0.0)
        b = (4.0, -1.0, 0.0)
        d3 = v3_length(v3_sub(a, b))
        qa = frame.to_2d(a)
        qb = frame.to_2d(b)
        d2 = math.hypot(qa[0] - qb[0], qa[1] - qb[1])
        # Projection can only shorten a distance.
        self.assertLessEqual(d2, d3 * 1000.0 + 1e-9)


if __name__ == "__main__":
    unittest.main()
