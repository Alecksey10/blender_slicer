"""Blender host layer tests, run against the ``bpy`` stubs.

These cover the parts that live outside the engine: mesh -> planes -> 2D
slicing, settings -> operation specs, and add-on registration.
"""

from __future__ import annotations

import unittest

from tests import fake_blender

fake_blender.install()

import bpy  # noqa: E402  (must come after the stubs are installed)

from blender_slicer.adapters.blender import (  # noqa: E402
    register as host_register,
    unregister as host_unregister,
)
from blender_slicer.engine import Engine  # noqa: E402
from blender_slicer.spatial.vectors import v3_dot, v3_sub  # noqa: E402
from blender_slicer.engine.registry import validate_params  # noqa: E402
from blender_slicer.protocol.types import (  # noqa: E402
    ContourRole,
    OperationSpec,
    ProcessingRequest,
    ResultStatus,
    TargetSelector,
)
from blender_slicer.adapters.blender import adapter, slicing  # noqa: E402
from blender_slicer.adapters.base.runtime import RUNTIME  # noqa: E402

CUBE_HALF_MM = 500.0


class RegistrationTests(unittest.TestCase):
    def test_register_and_unregister(self):
        host_register()
        try:
            self.assertTrue(hasattr(bpy.types.Scene, "slicer_settings"))
            self.assertTrue(hasattr(bpy.types, "Scene"))
        finally:
            host_unregister()
        self.assertFalse(hasattr(bpy.types.Scene, "slicer_settings"))

    def test_double_register_is_a_noop(self):
        host_register()
        try:
            host_register()
            self.assertTrue(hasattr(bpy.types.Scene, "slicer_settings"))
        finally:
            host_unregister()


class SettingsToOperationsTests(unittest.TestCase):
    def test_every_operation_matches_its_descriptor(self):
        settings = fake_blender.make_settings(
            resample_enabled=True, limit_curvature_enabled=True
        )
        operations = adapter.operations_from_settings(settings)
        names = [op.method for op in operations]
        self.assertEqual(
            names,
            [
                "fillet_corners",
                "smooth",
                "simplify",
                "densify",
                "resample",
                "limit_curvature",
            ],
        )
        engine = Engine()
        for op in operations:
            method = engine.registry.get(op.method)
            self.assertIsNotNone(method, op.method)
            # Raises DomainError on unknown names, wrong types or bad ranges.
            params = validate_params(method.descriptor, op.params)
            self.assertEqual(set(params), {p.name for p in method.descriptor.params})

    def test_optional_operations_can_be_disabled(self):
        settings = fake_blender.make_settings(
            fillet_enabled=False,
            smooth_enabled=False,
            simplify_enabled=False,
            densify_enabled=False,
        )
        self.assertEqual(adapter.operations_from_settings(settings), [])

    def test_validate_settings_reports_missing_source(self):
        settings = fake_blender.make_settings()
        with self.assertRaises(Exception):
            adapter.validate_settings(settings)

    def test_material_mapping_is_complete(self):
        settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(),
            material_thickness_mm=2.5,
            material_min_bend_radius_mm=4.0,
            material_k_factor=0.33,
        )
        material = adapter.material_from_settings(settings)
        self.assertEqual(material.thickness_mm, 2.5)
        self.assertEqual(material.min_bend_radius_mm, 4.0)
        self.assertAlmostEqual(material.k_factor, 0.33)

    def test_build_request_uses_engine_contract(self):
        settings = fake_blender.make_settings(source_object=fake_blender.FakeMeshObject())
        request = adapter.build_request(settings)
        self.assertIsInstance(request, ProcessingRequest)
        self.assertEqual(request.units, "mm")
        self.assertEqual(request.targets.roles, (ContourRole.CUT,))
        self.assertEqual(request.metadata["host"], "blender")


class _RecorderLayout:
    """Minimal stand-in for ``bpy.types.UILayout`` that records draw calls."""

    def __init__(self) -> None:
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self

        return call

    def operators(self):
        return [args[0] for name, args, _kwargs in self.calls if name == "operator" and args]

    def props(self):
        return [
            (args[0], args[1])
            for name, args, _kwargs in self.calls
            if name == "prop" and len(args) >= 2
        ]


class PanelDrawTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace

        from blender_slicer.adapters.blender import panels

        self.panels = panels
        self.settings = fake_blender.make_settings()
        self.context = fake_blender.FakeContext(
            scene=SimpleNamespace(slicer_settings=self.settings)
        )

    def _draw(self, panel_class):
        layout = _RecorderLayout()
        panel = panel_class()
        panel.layout = layout
        panel.draw(self.context)
        return layout

    def test_actions_are_drawn_first_in_the_main_panel(self):
        layout = self._draw(self.panels.SLICER_PT_main)
        operators = layout.operators()
        self.assertEqual(operators[0], "slicer.run")
        for operator in (
            "slicer.run",
            "slicer.generate",
            "slicer.process",
            "slicer.clear",
            "slicer.export_settings",
            "slicer.import_settings",
        ):
            self.assertIn(operator, operators)

    def test_every_schema_section_is_a_sub_panel_of_main(self):
        from blender_slicer.adapters.blender.ui_schema import SECTIONS

        labels = [cls.bl_label for cls in self.panels.SECTION_PANELS]
        self.assertEqual(labels, [section.title for section in SECTIONS])
        for cls in self.panels.SECTION_PANELS:
            self.assertEqual(cls.bl_parent_id, "SLICER_PT_main")
            self.assertTrue(cls.bl_idname.startswith("SLICER_PT_"))

    def test_sections_draw_only_existing_properties(self):
        for cls in self.panels.SECTION_PANELS:
            for settings_object, name in self._draw(cls).props():
                self.assertIs(settings_object, self.settings)
                self.assertTrue(hasattr(self.settings, name), f"{cls.bl_label}: {name}")

    def test_plan_fields_follow_the_slice_mode(self):
        panel_class = next(
            cls for cls in self.panels.SECTION_PANELS if cls.bl_idname == "SLICER_PT_plan"
        )
        planar = [name for _obj, name in self._draw(panel_class).props()]
        self.assertIn("spacing_mm", planar)
        self.assertIn("centered", planar)
        self.assertNotIn("angle_start_deg", planar)

        self.settings.slice_mode = "RADIAL"
        radial = [name for _obj, name in self._draw(panel_class).props()]
        self.assertIn("angle_start_deg", radial)
        self.assertIn("angle_end_deg", radial)
        self.assertNotIn("spacing_mm", radial)

    def test_no_field_reports_an_error(self):
        for cls in self.panels.CLASSES:
            errors = [
                kwargs.get("text", "")
                for name, _args, kwargs in self._draw(cls).calls
                if name == "label" and kwargs.get("icon") == "ERROR"
            ]
            self.assertEqual(errors, [], cls.bl_label)

    def test_all_panels_draw_without_raising(self):
        for cls in self.panels.CLASSES:
            with self.subTest(panel=cls.bl_label):
                self._draw(cls)


class SettingsCoverageTests(unittest.TestCase):
    """Guards against GUI, export and adapter drifting apart."""

    def test_ui_schema_refers_to_real_properties(self):
        from blender_slicer.adapters.blender.properties import SlicerSettings
        from blender_slicer.adapters.blender.ui_schema import SECTIONS

        annotations = SlicerSettings.__annotations__
        for section in SECTIONS:
            for item in section.fields:
                self.assertIn(item.prop, annotations, item.prop)

    def test_property_annotations_are_not_postponed(self):
        """Blender needs evaluated bpy.props objects in ``__annotations__``.

        A module-level ``from __future__ import annotations`` turns them into
        strings and the properties silently fail to register, so guard it.
        """
        from blender_slicer.adapters.blender import operators, properties

        for cls in (properties.SlicerSettings,) + operators.CLASSES:
            for name, value in getattr(cls, "__annotations__", {}).items():
                self.assertNotIsInstance(
                    value,
                    str,
                    f"{cls.__name__}.{name}: annotation is a string; "
                    "remove the postponed-annotations future import",
                )

    def test_every_editable_setting_is_exported(self):
        from blender_slicer.adapters.blender import settings_io
        from blender_slicer.adapters.blender.properties import SlicerSettings

        internal = {
            "source_object",
            "status",
            "status_detail",
            "diagnostics_text",
            "dirty",
            "revision",
            "last_slices",
            "last_points",
            "last_errors",
            "last_warnings",
            "last_contacts",
        }
        exported = set(settings_io.FIELDS)
        missing = sorted(
            name
            for name in SlicerSettings.__annotations__
            if not name.startswith("_") and name not in exported and name not in internal
        )
        self.assertEqual(missing, [], "settings missing from settings_io.FIELDS")

    def test_export_import_round_trip(self):
        import pathlib
        import tempfile

        from blender_slicer.adapters.blender import settings_io

        settings = fake_blender.make_settings()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = pathlib.Path(temp_dir) / "recipe.json"
            settings_io.export_settings(settings, path)
            target = fake_blender.make_settings(fillet_radius_mm=1.0)
            warnings = settings_io.import_settings(target, path)
        self.assertEqual(warnings, [])
        self.assertAlmostEqual(target.fillet_radius_mm, 4.0)
        self.assertTrue(target.dirty)


class SlicingTests(unittest.TestCase):
    def setUp(self):
        RUNTIME.clear()
        self.context = fake_blender.FakeContext()
        self.object = fake_blender.FakeMeshObject()

    def test_cube_is_cut_into_closed_millimetre_contours(self):
        settings = fake_blender.make_settings(source_object=self.object, count=3, spacing_mm=5.0)
        slices, frames = slicing.generate_slices(self.context, settings)

        self.assertEqual(len(slices), 3)
        self.assertEqual(len(frames), 3)
        for slice_ in slices:
            self.assertEqual(len(slice_.contours), 1)
            contour = slice_.contours[0]
            self.assertTrue(contour.closed)
            self.assertGreaterEqual(len(contour.points), 4)
            xs = [p[0] for p in contour.points]
            ys = [p[1] for p in contour.points]
            self.assertAlmostEqual(min(xs), -CUBE_HALF_MM, places=6)
            self.assertAlmostEqual(max(xs), CUBE_HALF_MM, places=6)
            self.assertAlmostEqual(min(ys), -CUBE_HALF_MM, places=6)
            self.assertAlmostEqual(max(ys), CUBE_HALF_MM, places=6)
            self.assertEqual(slice_.metadata["slice_mode"], "planar")
            self.assertIn(slice_.frame_id, frames)

    def test_slice_order_is_along_the_axis(self):
        settings = fake_blender.make_settings(source_object=self.object, count=3, spacing_mm=5.0)
        slices, _ = slicing.generate_slices(self.context, settings)
        offsets = [s.metadata["offset_mm"] for s in slices]
        self.assertEqual(offsets, sorted(offsets))

    def test_radial_mode_builds_rotated_planes(self):
        settings = fake_blender.make_settings(
            source_object=self.object,
            slice_mode="RADIAL",
            axis="Z",
            count=4,
            angle_start_deg=0.0,
            angle_end_deg=180.0,
        )
        slices, frames = slicing.generate_slices(self.context, settings)
        self.assertEqual(len(slices), 4)
        for slice_ in slices:
            self.assertEqual(slice_.metadata["slice_mode"], "radial")
        normals = {tuple(round(v, 6) for v in frames[s.frame_id].normal) for s in slices}
        self.assertEqual(len(normals), 4)

    def test_slicing_then_engine_round_trip(self):
        settings = fake_blender.make_settings(
            source_object=self.object,
            count=2,
            spacing_mm=5.0,
            fillet_radius_mm=20.0,
            fillet_arc_segments=4,
            densify_max_spacing_mm=10.0,
        )
        slices, frames = slicing.generate_slices(self.context, settings)
        RUNTIME.slices = slices
        RUNTIME.frames = frames

        request = adapter.build_request(settings)
        self.assertTrue(adapter.ENGINE.validate(request).ok)
        result = adapter.ENGINE.process(request)

        self.assertEqual(result.status, ResultStatus.OK)
        self.assertEqual(len(result.slices), 2)
        for slice_result in result.slices:
            contour = slice_result.contours[0]
            self.assertTrue(contour.changed)
            self.assertTrue(contour.closed)
            self.assertGreaterEqual(len(contour.points), 4)
            # 2D result points map back onto the original slice plane.
            frame = frames[slice_result.frame_id]
            for point in contour.points[:3]:
                back = frame.to_3d(point)
                offset = v3_dot(v3_sub(back, frame.origin), frame.normal)
                self.assertAlmostEqual(offset, 0.0, places=6)

    def tearDown(self):
        RUNTIME.clear()


class EventWiringTests(unittest.TestCase):
    def setUp(self):
        RUNTIME.clear()
        host_register()

    def tearDown(self):
        host_unregister()
        RUNTIME.clear()

    def test_generate_refreshes_the_panel(self):
        area = fake_blender.FakeArea()
        context = fake_blender.FakeContext(area=area)
        settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(),
            build_curves=False,
        )
        adapter.generate(context, settings)
        self.assertGreaterEqual(area.redraws, 1)
        self.assertEqual(settings.last_slices, 3)
        self.assertFalse(settings.dirty)

    def test_process_updates_status_text(self):
        area = fake_blender.FakeArea()
        context = fake_blender.FakeContext(area=area)
        settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(),
            build_curves=False,
        )
        adapter.generate(context, settings)
        result = adapter.process_current(context, settings)
        self.assertIn(result.status.value.upper(), settings.status)
        self.assertEqual(settings.last_errors, 0)
        self.assertIn("points", settings.status_detail)

    def test_clear_reports_clean_state(self):
        area = fake_blender.FakeArea()
        context = fake_blender.FakeContext(area=area)
        settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(),
            build_curves=False,
        )
        adapter.generate(context, settings)
        adapter.clear(context, settings)
        self.assertEqual(settings.last_slices, 0)
        self.assertEqual(settings.status, "Cleared")
        self.assertFalse(RUNTIME.has_slices)


class FilletConsistencyTests(unittest.TestCase):
    """README 0.2.1 #4: identical cube slices must get identical radii.

    A plane crossing a triangulated cube picks up extra points where it crosses
    triangle diagonals; near the top and bottom those points sit close to a
    corner.  Before the fix they consumed the corner room, so slices got
    different fillet radii and one of them caved inward.
    """

    def setUp(self):
        RUNTIME.clear()
        self.context = fake_blender.FakeContext()

    def tearDown(self):
        RUNTIME.clear()

    def test_every_cube_slice_gets_the_same_radius(self):
        settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(),
            count=5,
            spacing_mm=240.0,
            unit_scale_mm=1000.0,
        )
        slices, _frames = slicing.generate_slices(self.context, settings)
        request = ProcessingRequest(
            request_id="cube-radius",
            slices=slices,
            operations=[
                OperationSpec(
                    method="fillet_corners",
                    params={"radius_mm": 40.0, "mode": "error", "arc_segments": 4},
                )
            ],
            targets=TargetSelector(roles=(ContourRole.CUT,)),
        )
        result = Engine().process(request)
        self.assertEqual(result.status, ResultStatus.OK)
        radii = [
            contour.metrics.min_radius_mm
            for slice_result in result.slices
            for contour in slice_result.contours
        ]
        self.assertEqual(len(radii), 5)
        for radius in radii:
            self.assertIsNotNone(radius)
            self.assertAlmostEqual(radius, 40.0, places=6)
            self.assertAlmostEqual(radius, radii[0], places=9)

    def test_cut_offsets_are_attached_per_axis(self):
        settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(),
            inset_enabled=True,
            axis="Z",
            count=2,
            spacing_mm=100.0,
        )
        slices, _frames = slicing.generate_slices(self.context, settings)
        self.assertTrue(slices)
        for slice_ in slices:
            self.assertLess(slice_.offset_mm, 0.0)  # Z cuts are inward
            self.assertAlmostEqual(slice_.metadata["cut_offset_mm"], slice_.offset_mm)

        x_settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(),
            inset_enabled=True,
            axis="X",
            count=2,
            spacing_mm=100.0,
        )
        x_slices, _frames = slicing.generate_slices(self.context, x_settings)
        for slice_ in x_slices:
            self.assertGreater(slice_.offset_mm, 0.0)  # X cuts are outward


if __name__ == "__main__":
    unittest.main()
