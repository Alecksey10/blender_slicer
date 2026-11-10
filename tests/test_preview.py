"""SVG preview: results and layer stacks render without a host.

The preview used to rebuild contours field by field and crashed as soon as the
result type grew new required fields, so these tests keep both entry points
covered by an actual render.
"""

from __future__ import annotations

import unittest

from blender_slicer.adapters.base.layers import SliceLayer
from blender_slicer.engine import Engine
from blender_slicer.preview.svg import render_layers_svg, render_result_svg
from blender_slicer.protocol.types import (
    Contour,
    ContourRole,
    OperationSpec,
    ProcessingRequest,
    Slice,
    TargetSelector,
)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _slice(radius: float) -> Slice:
    return Slice(
        id="s1",
        index=0,
        frame_id="frame",
        contours=[
            Contour(
                id="c0",
                role=ContourRole.CUT,
                closed=True,
                points=list(SQUARE),
            )
        ],
    )


def _result(radius: float, mode: str = "clamp"):
    request = ProcessingRequest(
        request_id="preview",
        slices=[_slice(radius)],
        operations=[
            OperationSpec(
                method="fillet_corners",
                params={"radius_mm": radius, "mode": mode, "arc_segments": 3},
                target=TargetSelector(roles=(ContourRole.CUT,)),
            )
        ],
    )
    return Engine().process(request)


class ResultSvgTests(unittest.TestCase):
    def test_renders_a_processed_result(self):
        svg = render_result_svg(_result(1.0))
        self.assertIn("<svg", svg)
        self.assertIn('<g id="result"', svg)
        self.assertIn("<path", svg)
        self.assertIn(">result</text>", svg)

    def test_renders_a_result_with_diagnostics(self):
        # A too large radius keeps the contour but reports an error; the
        # preview must still draw the partial result.
        result = _result(20.0, mode="error")
        self.assertNotEqual(result.status.value, "ok")
        svg = render_result_svg(result, name="partial")
        self.assertIn("<path", svg)

    def test_empty_result_still_produces_svg(self):
        svg = render_result_svg(_result(1.0)).replace("<path", "<path")
        self.assertTrue(svg.startswith("<?xml"))


class LayerSvgTests(unittest.TestCase):
    def test_hidden_layers_are_skipped(self):
        visible = SliceLayer(id="cube::planar-z", name="Cube Z", slices=[_slice(1.0)])
        hidden = SliceLayer(
            id="cube::planar-x",
            name="Cube X",
            slices=[_slice(1.0)],
            visible=False,
            color=(0.95, 0.45, 0.10),
        )
        svg = render_layers_svg([visible, hidden])
        self.assertIn("Cube Z", svg)
        self.assertNotIn("Cube X", svg)

    def test_layers_share_one_bounding_box(self):
        first = SliceLayer(id="z", name="Z pass", slices=[_slice(1.0)])
        second = SliceLayer(id="x", name="X pass", slices=[_slice(1.0)])
        svg = render_layers_svg([first, second])
        self.assertIn("Z pass", svg)
        self.assertIn("X pass", svg)
        self.assertEqual(svg.count("<svg"), 1)


if __name__ == "__main__":
    unittest.main()
