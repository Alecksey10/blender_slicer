"""Tests for the JSON contract and its round-trip guarantees."""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from blender_slicer.core import (
    Contour,
    ContourRole,
    Engine,
    FailurePolicy,
    FoldSpec,
    MaterialProfile,
    OperationSpec,
    ProcessingRequest,
    Slice,
    TargetSelector,
    dumps_request,
    dumps_result,
    loads_request,
    request_from_dict,
    request_to_dict,
    result_to_dict,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "architecture" / "examples"


def _rich_request() -> ProcessingRequest:
    return ProcessingRequest(
        request_id="round-trip",
        material=MaterialProfile(id="pla", name="PLA", thickness_mm=3.0, k_factor=0.42),
        operations=[
            OperationSpec(
                method="fillet_corners",
                params={"radius_mm": 2.0, "mode": "clamp"},
                target=TargetSelector(roles=(ContourRole.CUT,), tags_any=("outer",)),
                label="corners",
            ),
            OperationSpec(method="smooth", params={"iterations": 2}, enabled=False),
        ],
        slices=[
            Slice(
                id="s0",
                index=0,
                frame_id="f0",
                metadata={"offset_mm": 0.0},
                contours=[
                    Contour(
                        id="s0.c0",
                        role=ContourRole.CUT,
                        closed=True,
                        points=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)],
                        tags=["outer"],
                        segment_tags=["cut", "cut", "cut"],
                    ),
                    Contour(
                        id="s0.c1",
                        role=ContourRole.SCORE,
                        closed=False,
                        points=[(0.0, 5.0), (10.0, 5.0)],
                        parent_id="s0.c0",
                        fold=FoldSpec(angle_deg=90.0, direction="up", radius_mm=2.0),
                    ),
                ],
            )
        ],
        targets=TargetSelector(roles=(ContourRole.CUT, ContourRole.SCORE)),
        failure_policy=FailurePolicy.BEST_EFFORT,
        metadata={"host": "test"},
    )


class JsonContractTests(unittest.TestCase):
    def test_request_round_trip_is_lossless(self):
        request = _rich_request()
        first = dumps_request(request)
        again = dumps_request(loads_request(first))
        self.assertEqual(first, again)

    def test_dataclass_round_trip(self):
        request = _rich_request()
        restored = request_from_dict(request_to_dict(request))
        self.assertEqual(dumps_request(restored), dumps_request(request))
        self.assertEqual(restored.slices[0].contours[1].fold.angle_deg, 90.0)
        self.assertEqual(restored.operations[0].target.tags_any, ("outer",))
        self.assertFalse(restored.operations[1].enabled)

    def test_unknown_fields_are_ignored_on_read(self):
        data = request_to_dict(_rich_request())
        data["future_field"] = {"anything": 1}
        request = request_from_dict(data)
        self.assertEqual(request.request_id, "round-trip")

    def test_result_json_has_no_non_finite_numbers(self):
        result = Engine().process(_rich_request())
        text = dumps_result(result)
        self.assertNotIn("NaN", text)
        self.assertNotIn("Infinity", text)
        json.loads(text)

    def test_example_request_parses_and_validates(self):
        path = EXAMPLES / "request.example.json"
        request = loads_request(path.read_bytes())
        report = Engine().validate(request)
        self.assertTrue(report.ok, [d.message for d in report.diagnostics])
        self.assertGreater(report.counts["slices"], 0)

    def test_example_request_processes_deterministically(self):
        request = loads_request((EXAMPLES / "request.example.json").read_bytes())
        engine = Engine()
        self.assertEqual(dumps_result(engine.process(request)), dumps_result(engine.process(request)))

    def test_material_example_parses(self):
        data = json.loads((EXAMPLES / "material.pla.example.json").read_text(encoding="utf-8"))
        self.assertEqual(data["id"], "pla-3mm")
        self.assertTrue(math.isfinite(data["thickness_mm"]))
        self.assertGreater(data["thickness_mm"], 0)


if __name__ == "__main__":
    unittest.main()
