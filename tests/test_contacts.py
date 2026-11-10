"""Contact analysis between cutting passes (README 0.2.1 #2)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from blender_slicer.protocol.shapes import Contour, ContourRole, Slice
from blender_slicer.spatial.contacts import find_contacts
from blender_slicer.spatial.frames import make_frame

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


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


if __name__ == "__main__":
    unittest.main()
