"""Layers: several cutting passes side by side in the runtime state."""

from __future__ import annotations

import unittest

from blender_slicer.adapters.base.layers import PALETTE, LayerStore, SliceLayer
from blender_slicer.adapters.base.runtime import RuntimeState
from blender_slicer.protocol.shapes import Contour, ContourRole, Slice
from blender_slicer.spatial.frames import make_frame

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _slice(slice_id: str = "s0", index: int = 0) -> Slice:
    return Slice(
        id=slice_id,
        index=index,
        contours=[Contour(f"{slice_id}.c0", ContourRole.CUT, True, list(SQUARE))],
    )


def _layers_with(n: int) -> LayerStore:
    store = LayerStore()
    for i in range(n):
        store.put(SliceLayer(id=f"layer-{i}", name=f"Layer {i}", slices=[_slice()]))
    return store


class LayerStoreTests(unittest.TestCase):
    def test_put_makes_the_layer_active(self):
        store = _layers_with(2)
        self.assertEqual(len(store), 2)
        self.assertIsNotNone(store.active)
        self.assertEqual(store.active.id, "layer-1")
        self.assertEqual(store.visible_layers(), store.all_layers())

    def test_each_new_layer_gets_a_distinct_palette_colour(self):
        store = _layers_with(4)
        colors = {layer.color for layer in store}
        self.assertEqual(len(colors), 4)
        self.assertIn(next(iter(colors)), PALETTE)

    def test_replacing_a_layer_keeps_its_colour_and_visibility(self):
        store = _layers_with(2)
        existing = store.get("layer-0")
        existing.visible = False
        color = existing.color
        store.put(SliceLayer(id="layer-0", name="Renamed", slices=[_slice()]))
        replacement = store.get("layer-0")
        self.assertEqual(replacement.color, color)
        self.assertFalse(replacement.visible)
        self.assertEqual(replacement.name, "Renamed")
        self.assertEqual(len(store.visible_layers()), 1)

    def test_remove_and_clear(self):
        store = _layers_with(3)
        store.set_active("layer-1")
        self.assertTrue(store.remove("layer-1"))
        self.assertFalse(store.remove("missing"))
        self.assertEqual(len(store), 2)
        self.assertIsNotNone(store.active)
        self.assertNotEqual(store.active.id, "layer-1")
        store.clear()
        self.assertEqual(len(store), 0)
        self.assertFalse(store)
        self.assertIsNone(store.active)

    def test_toggle(self):
        store = _layers_with(1)
        layer = store.active
        self.assertTrue(layer.visible)
        self.assertFalse(layer.toggle())
        self.assertEqual(store.visible_layers(), [])


class RuntimeProxyTests(unittest.TestCase):
    def setUp(self):
        self.state = RuntimeState()
        self.frame = make_frame((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1.0, "f0")

    def test_assigning_slices_creates_a_default_layer(self):
        self.state.slices = [_slice()]
        self.assertTrue(self.state.has_slices)
        self.assertEqual(self.state.active.id, "default")
        self.assertEqual(self.state.slice_count if hasattr(self.state, "slice_count") else 1, 1)

    def test_frames_are_stored_on_the_active_layer(self):
        self.state.slices = [_slice()]
        self.state.frames = {"f0": self.frame}
        self.assertEqual(self.state.frames["f0"], self.frame)
        self.assertEqual(self.state.active.frames, {"f0": self.frame})
        self.assertEqual(len(self.state.frame_store), 1)

    def test_revision_and_source_are_proxied(self):
        self.state.slices = [_slice()]
        self.state.revision = 7
        self.state.source_name = "Cube"
        self.assertEqual(self.state.active.revision, 7)
        self.assertEqual(self.state.active.source_name, "Cube")

    def test_add_slices_creates_a_named_layer(self):
        layer = self.state.add_slices(
            [_slice()],
            {"f0": self.frame},
            layer_id="Cube::planar-x",
            name="Cube · planar X",
            axis="X",
            mode="planar",
            source_name="Cube",
            revision=3,
        )
        self.assertEqual(layer.id, "Cube::planar-x")
        self.assertEqual(layer.axis, "X")
        self.assertEqual(self.state.active.id, "Cube::planar-x")
        self.assertEqual(self.state.revision, 3)
        self.assertEqual(self.state.frames, {"f0": self.frame})

    def test_clear_drops_every_layer(self):
        self.state.slices = [_slice()]
        self.state.clear()
        self.assertFalse(self.state.has_slices)
        self.assertIsNone(self.state.active)
        self.assertEqual(self.state.frames, {})


if __name__ == "__main__":
    unittest.main()
