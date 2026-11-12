"""Contact analysis between cutting passes (README 0.2.1 #2)."""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from blender_slicer.protocol.result import (
    ContourMetrics,
    ContourResult,
    EngineInfo,
    ProcessingResult,
    ResultStatus,
    SliceMetrics,
    SliceResult,
)
from blender_slicer.protocol.shapes import Contour, ContourRole, Slice
from blender_slicer.spatial.contacts import (
    CONTACT_SIMPLIFY_MM,
    MAX_SEGMENTS_PER_CONTOUR,
    _chords,
    find_contacts,
)
from blender_slicer.spatial.frames import make_frame

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def dense_square(count: int, size: float = 10.0) -> list[tuple[float, float]]:
    """A square outline with ``count`` points, like a processed slice contour."""

    points: list[tuple[float, float]] = []
    for i in range(count):
        t = 4.0 * i / count
        if t < 1.0:
            p = (t * size, 0.0)
        elif t < 2.0:
            p = (size, (t - 1.0) * size)
        elif t < 3.0:
            p = (size - (t - 2.0) * size, size)
        else:
            p = (0.0, size - (t - 3.0) * size)
        points.append(p)
    return points


def point_segment_distance(p, a, b) -> float:
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    length2 = dx * dx + dy * dy + dz * dz
    if length2 <= 0.0:
        return math.dist(p, a)
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy + (p[2] - a[2]) * dz) / length2
    t = min(1.0, max(0.0, t))
    return math.dist(p, (a[0] + dx * t, a[1] + dy * t, a[2] + dz * t))


def make_layer(
    layer_id: str,
    *,
    origin=(0.0, 0.0, 0.0),
    normal=(0.0, 0.0, 1.0),
    u_hint=(1.0, 0.0, 0.0),
    points=SQUARE,
    index: int = 0,
):
    frame = make_frame(normal, u_hint, origin, 1.0, f"f-{layer_id}-{index}")
    slice_ = Slice(
        id=f"s-{layer_id}-{index}",
        index=index,
        frame_id=frame.id,
        contours=[Contour(f"c-{layer_id}-{index}", ContourRole.CUT, True, list(points))],
    )
    return SimpleNamespace(id=layer_id, slices=[slice_], frames={frame.id: frame})


class ContactTests(unittest.TestCase):
    def test_parallel_planes_are_not_in_contact_when_too_far(self):
        a = make_layer("a", origin=(0.0, 0.0, 0.0))
        b = make_layer("b", origin=(0.0, 0.0, 2.0))
        self.assertEqual(find_contacts([a, b], gap_mm=1.0), [])
        self.assertEqual(find_contacts([a, b], gap_mm=0.0), [])

    def test_parallel_planes_report_gap_and_midpoint(self):
        a = make_layer("a", origin=(0.0, 0.0, 0.0))
        b = make_layer("b", origin=(0.0, 0.0, 2.0))
        contacts = find_contacts([a, b], gap_mm=3.0)
        self.assertEqual(len(contacts), 1)
        contact = contacts[0]
        self.assertAlmostEqual(contact.distance_mm, 2.0)
        self.assertAlmostEqual(contact.position[2], 1.0)
        self.assertEqual(contact.layer_a, "a")
        self.assertEqual(contact.layer_b, "b")

    def test_crossing_passes_touch(self):
        vertical = make_layer("x-pass", normal=(1.0, 0.0, 0.0), u_hint=(0.0, 1.0, 0.0))
        horizontal = make_layer("z-pass", normal=(0.0, 0.0, 1.0), u_hint=(1.0, 0.0, 0.0))
        contacts = find_contacts([vertical, horizontal], gap_mm=0.5)
        # Overlapping edges produce several distinct crossings, not just one.
        self.assertGreaterEqual(len(contacts), 2)
        for contact in contacts:
            self.assertAlmostEqual(contact.distance_mm, 0.0, places=9)
            self.assertEqual(contact.kind, "intersection")
            self.assertAlmostEqual(contact.position[0], 0.0, places=9)
            self.assertAlmostEqual(contact.position[2], 0.0, places=9)

    def test_near_contacts_keep_one_representative_point(self):
        a = make_layer("a", origin=(0.0, 0.0, 0.0))
        b = make_layer("b", origin=(0.0, 0.0, 2.0))
        contacts = find_contacts([a, b], gap_mm=3.0)
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0].kind, "near")

    def test_intersections_are_deduplicated(self):
        vertical = make_layer("x-pass", normal=(1.0, 0.0, 0.0), u_hint=(0.0, 1.0, 0.0))
        horizontal = make_layer("z-pass", normal=(0.0, 0.0, 1.0), u_hint=(1.0, 0.0, 0.0))
        contacts = find_contacts([vertical, horizontal], gap_mm=0.5, merge_mm=0.5)
        positions = [contact.position for contact in contacts]
        for index, position in enumerate(positions):
            for other in positions[index + 1 :]:
                distance = sum((a - b) ** 2 for a, b in zip(position, other)) ** 0.5
                self.assertGreaterEqual(distance, 0.5 - 1e-9)
        closer = find_contacts([vertical, horizontal], merge_mm=0.01)
        self.assertLessEqual(len(contacts), len(closer))

    def test_three_layers_give_three_pairs(self):
        a = make_layer("a", origin=(0.0, 0.0, 0.0))
        b = make_layer("b", origin=(0.0, 0.0, 1.0))
        c = make_layer("c", origin=(0.0, 0.0, 2.0))
        contacts = find_contacts([a, b, c], gap_mm=5.0)
        self.assertEqual(len(contacts), 3)
        self.assertTrue(all(contact.distance_mm <= 5.0 for contact in contacts))

    def test_single_layer_needs_the_opt_in_flag(self):
        layer = make_layer("a")
        layer.slices.append(
            make_layer("a", origin=(0.0, 0.0, 1.0), index=1).slices[0]
        )
        layer.frames.update(make_layer("a", origin=(0.0, 0.0, 1.0), index=1).frames)
        self.assertEqual(find_contacts([layer], gap_mm=5.0), [])
        same = find_contacts([layer], gap_mm=5.0, include_same_layer=True)
        self.assertEqual(len(same), 1)
        self.assertAlmostEqual(same[0].distance_mm, 1.0)

    def test_empty_input_is_safe(self):
        self.assertEqual(find_contacts([]), [])


class DenseContourTests(unittest.TestCase):
    """Processed contours carry 150-2500 points; the search must still see all of them."""

    def test_thinning_covers_the_whole_contour(self):
        count = 2400
        ring = [
            (
                10.0 * math.cos(2.0 * math.pi * i / count),
                10.0 * math.sin(2.0 * math.pi * i / count),
                0.0,
            )
            for i in range(count)
        ]
        chords = _chords(ring, True)
        self.assertLessEqual(len(chords), MAX_SEGMENTS_PER_CONTOUR)
        # Every point of the ring must lie on (or within the thinning error of)
        # some chord: a stride that drops segments leaves holes.
        for point in ring[::11]:
            nearest = min(point_segment_distance(point, a, b) for a, b, _err in chords)
            self.assertLessEqual(nearest, CONTACT_SIMPLIFY_MM * 3.0)

    def test_crossing_dense_contours_are_reported_as_intersections(self):
        points = dense_square(1500)
        vertical = make_layer("x-pass", normal=(1.0, 0.0, 0.0), u_hint=(0.0, 1.0, 0.0), points=points)
        horizontal = make_layer("z-pass", normal=(0.0, 0.0, 1.0), u_hint=(1.0, 0.0, 0.0), points=points)
        contacts = find_contacts([vertical, horizontal], gap_mm=0.5, merge_mm=0.01)
        self.assertTrue(contacts)
        self.assertTrue(all(contact.kind == "intersection" for contact in contacts))
        for contact in contacts:
            self.assertLessEqual(contact.distance_mm, CONTACT_SIMPLIFY_MM)

    def test_dense_parallel_passes_stay_near_contacts(self):
        points = dense_square(1500)
        a = make_layer("a", points=points)
        b = make_layer("b", origin=(0.0, 0.0, 0.5), points=points)
        contacts = find_contacts([a, b], gap_mm=1.0)
        self.assertTrue(contacts)
        self.assertTrue(all(contact.kind == "near" for contact in contacts))
        self.assertAlmostEqual(contacts[0].distance_mm, 0.5, places=6)

    def test_processed_layers_are_matched_on_their_result(self):
        """The markers must sit on the curves the user sees, not on the source."""

        a = make_layer("a")
        a.result = _result_with_contour(a, [(x + 100.0, y) for x, y in SQUARE])
        b = make_layer("b")
        self.assertEqual(find_contacts([a, b], gap_mm=1.0), [])

        a.result = _result_with_contour(a, SQUARE)
        self.assertTrue(find_contacts([a, b], gap_mm=1.0))


def _result_with_contour(layer, points) -> ProcessingResult:
    frame_id = next(iter(layer.frames))
    return ProcessingResult(
        schema_version="1.1",
        protocol_version="1.1",
        request_id="test",
        status=ResultStatus.OK,
        engine=EngineInfo(),
        units="mm",
        slices=[
            SliceResult(
                slice_id="result-0",
                index=0,
                frame_id=frame_id,
                changed=True,
                contours=[
                    ContourResult(
                        id="result-contour",
                        source_id="source",
                        role=ContourRole.CUT,
                        closed=True,
                        points=list(points),
                        parent_id=None,
                        tags=[],
                        fold=None,
                        changed=True,
                        segment_tags=None,
                        metrics=ContourMetrics(),
                    )
                ],
                metrics=SliceMetrics(),
            )
        ],
    )


if __name__ == "__main__":
    unittest.main()
