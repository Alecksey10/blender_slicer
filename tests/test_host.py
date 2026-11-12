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
                "smooth_curve_approx",
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

    def test_optimizer_option_is_mapped_and_validated(self):
        settings = fake_blender.make_settings(optimize_enabled=True)
        operations = adapter.operations_from_settings(settings)
        self.assertEqual(
            [op.method for op in operations],
            ["simplify", "optimize_curve", "densify"],
        )
        engine = Engine()
        for op in operations:
            params = validate_params(engine.registry.get(op.method).descriptor, op.params)
            self.assertEqual(
                set(params), {p.name for p in engine.registry.get(op.method).descriptor.params}
            )

    def test_optimizer_supersedes_the_sequential_shaping_stages(self):
        settings = fake_blender.make_settings(
            optimize_enabled=True,
            fillet_enabled=True,
            smooth_curve_enabled=True,
            cut_thin_enabled=True,
            trim_tight_enabled=True,
            limit_curvature_enabled=True,
        )
        names = [op.method for op in adapter.operations_from_settings(settings)]
        for legacy in (
            "fillet_corners",
            "smooth_curve_approx",
            "limit_curvature",
            "cut_thin_sections",
            "trim_tight_corners",
        ):
            self.assertNotIn(legacy, names)
        self.assertIn("optimize_curve", names)
        # Detail is restored after the fit, never before it.
        self.assertLess(names.index("simplify"), names.index("optimize_curve"))
        self.assertLess(names.index("optimize_curve"), names.index("densify"))

    def test_legacy_stages_run_with_the_optimizer_off(self):
        settings = fake_blender.make_settings(
            optimize_enabled=False, fillet_enabled=True, limit_curvature_enabled=True
        )
        names = [op.method for op in adapter.operations_from_settings(settings)]
        self.assertIn("fillet_corners", names)
        self.assertIn("limit_curvature", names)
        self.assertNotIn("optimize_curve", names)

    def test_optional_operations_can_be_disabled(self):
        settings = fake_blender.make_settings(
            fillet_enabled=False,
            smooth_curve_enabled=False,
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

    def labels(self):
        return [
            kwargs.get("text", args[0] if args else "")
            for name, args, kwargs in self.calls
            if name == "label"
        ]

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

        expected: list[str] = []
        grouped: set[str] = set()
        for section in SECTIONS:
            if not section.group:
                expected.append(section.title)
            elif section.group not in grouped:
                grouped.add(section.group)
                # Grouped sections share one collapsed "Legacy shaping" panel.
                expected.append("Legacy shaping")

        labels = [cls.bl_label for cls in self.panels.SECTION_PANELS]
        self.assertEqual(labels, expected)
        for cls in self.panels.SECTION_PANELS:
            self.assertEqual(cls.bl_parent_id, "SLICER_PT_main")
            self.assertTrue(cls.bl_idname.startswith("SLICER_PT_"))

    def test_optimizer_panel_is_open_near_the_top(self):
        panel = next(
            cls for cls in self.panels.SECTION_PANELS if cls.bl_idname == "SLICER_PT_optimize"
        )
        self.assertNotIn("DEFAULT_CLOSED", set(panel.bl_options))
        self.assertEqual(panel.bl_label, "Least-squares optimizer")
        # Right after Source and Slice plan: the solve is the main control.
        self.assertEqual(panel.bl_order, 3)

    def test_optimizer_panel_explains_the_trade(self):
        self.settings.optimize_enabled = True
        layout = self._draw(
            next(
                cls
                for cls in self.panels.SECTION_PANELS
                if cls.bl_idname == "SLICER_PT_optimize"
            )
        )
        texts = layout.labels()
        self.assertTrue(any("Deviation per radian" in text for text in texts), texts)
        self.assertIn("optimize_data_weight", [name for _obj, name in layout.props()])
        self.assertIn("optimize_radius_weight", [name for _obj, name in layout.props()])

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
        self.assertIn("spacing_auto", planar)
        self.assertIn("spacing_mm", planar)
        self.assertIn("centered", planar)
        self.assertNotIn("angle_start_deg", planar)

        self.settings.spacing_auto = True
        automatic = [name for _obj, name in self._draw(panel_class).props()]
        self.assertIn("spacing_auto", automatic)
        self.assertNotIn("spacing_mm", automatic)
        self.settings.spacing_auto = False

        self.settings.slice_mode = "RADIAL"
        radial = [name for _obj, name in self._draw(panel_class).props()]
        self.assertIn("angle_start_deg", radial)
        self.assertIn("angle_end_deg", radial)
        self.assertNotIn("spacing_mm", radial)

    def test_running_job_shows_progress_and_a_cancel_button(self):
        self.settings.job_running = True
        self.settings.job_message = "optimize_curve · slice 2/5 · iteration 3/40"
        self.settings.job_progress = 0.4
        layout = self._draw(self.panels.SLICER_PT_main)
        self.assertIn("slicer.cancel", layout.operators())
        self.assertIn("job_progress", [name for _obj, name in layout.props()])
        self.settings.job_running = False

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
            # Written by the main-thread job pump, never part of a recipe.
            "job_running",
            "job_progress",
            "job_message",
            "job_cancelling",
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

    def test_auto_spacing_distributes_slices_across_the_model(self):
        settings = fake_blender.make_settings(
            source_object=self.object, count=5, spacing_auto=True
        )
        slices, _ = slicing.generate_slices(self.context, settings)
        offsets = [s.metadata["offset_mm"] for s in slices]
        # Cube is 1000 mm tall; 5 slices -> 200 mm spacing, equal margins.
        # offset_mm is measured from the first slice, so it runs 0..800.
        self.assertAlmostEqual(slices[0].metadata["spacing_mm"], 200.0, places=6)
        self.assertEqual(len(offsets), 5)
        self.assertAlmostEqual(offsets[0], 0.0, places=6)
        self.assertAlmostEqual(offsets[-1], 800.0, places=6)
        for before, after in zip(offsets, offsets[1:]):
            self.assertAlmostEqual(after - before, 200.0, places=6)

    def test_auto_spacing_single_slice_is_centered(self):
        settings = fake_blender.make_settings(
            source_object=self.object, count=1, spacing_auto=True
        )
        slices, _ = slicing.generate_slices(self.context, settings)
        self.assertEqual(len(slices), 1)
        self.assertAlmostEqual(slices[0].metadata["offset_mm"], 0.0, places=6)

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


class BackgroundJobTests(unittest.TestCase):
    """The worker thread + main-thread pump behind the Cancel button."""

    def _pump_until_done(self, runner, timeout: float = 5.0) -> dict:
        import time

        deadline = time.perf_counter() + timeout
        state = runner.snapshot()
        while state["running"] and time.perf_counter() < deadline:
            state = runner.pump()
            time.sleep(0.005)
        return state

    def test_job_applies_its_result_on_the_pump(self):
        from blender_slicer.adapters.blender import jobs

        runner = jobs.JobRunner()
        applied: list[int] = []
        finished: list[dict] = []

        def work(reporter):
            reporter.update(fraction=0.5, stage="optimize_curve", slice_index=1, slices_total=4)
            return 42

        runner.start("test", work, apply=applied.append, finish=lambda **kw: finished.append(kw))
        state = self._pump_until_done(runner)

        self.assertEqual(applied, [42])
        self.assertEqual(finished, [{"error": None, "cancelled": False}])
        self.assertFalse(state["running"])
        self.assertAlmostEqual(state["progress"], 1.0)

    def test_progress_is_combined_across_slices(self):
        from blender_slicer.adapters.blender import jobs

        runner = jobs.JobRunner()
        seen: list[float] = []
        original = runner._on_progress

        def spy(data):
            original(data)
            seen.append(runner.snapshot()["progress"])

        runner._on_progress = spy

        def work(reporter):
            reporter.update(fraction=0.5, slice_index=1, slices_total=4)
            return None

        runner.start("test", work)
        self._pump_until_done(runner)
        # (1 + 0.5) / 4 of the whole request.
        self.assertTrue(seen)
        self.assertAlmostEqual(seen[-1], 0.375)

    def test_cancel_reaches_the_worker(self):
        import time

        from blender_slicer.adapters.blender import jobs

        runner = jobs.JobRunner()
        finished: list[dict] = []
        started = []

        def work(reporter):
            started.append(True)
            for _ in range(2000):
                reporter.check()
                time.sleep(0.005)
            return "never"

        runner.start("test", work, finish=lambda **kw: finished.append(kw))
        while not started:
            time.sleep(0.005)
        self.assertTrue(runner.cancel())
        self._pump_until_done(runner)
        self.assertEqual(finished, [{"error": None, "cancelled": True}])

    def test_second_job_is_rejected_while_one_runs(self):
        import time

        from blender_slicer.adapters.blender import jobs

        runner = jobs.JobRunner()
        started = []

        def work(reporter):
            started.append(True)
            time.sleep(0.05)
            return 1

        runner.start("test", work)
        while not started:
            time.sleep(0.005)
        with self.assertRaises(RuntimeError):
            runner.start("other", lambda reporter: None)
        self._pump_until_done(runner)

    def test_engine_cancel_travels_through_the_job(self):
        import time

        from blender_slicer.adapters.blender import jobs
        from blender_slicer.engine import Engine
        from blender_slicer.protocol.types import (
            Contour,
            ContourRole,
            OperationSpec,
            ProcessingRequest,
            Slice,
        )

        square = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
        request = ProcessingRequest(
            request_id="job-cancel",
            slices=[
                Slice(
                    id=f"s{index}",
                    index=index,
                    contours=[Contour(f"s{index}.c0", ContourRole.CUT, True, list(square))],
                )
                for index in range(8)
            ],
            operations=[
                OperationSpec(
                    method="optimize_curve",
                    params={"sample_points": 1200, "max_iterations": 500},
                )
            ],
        )
        engine = Engine()
        runner = jobs.JobRunner()
        finished: list[dict] = []

        def work(reporter):
            return engine.process(request, reporter)

        started = time.perf_counter()
        runner.start("process", work, finish=lambda **kw: finished.append(kw))
        # Cancel only once the engine is demonstrably working on a slice.
        deadline = time.perf_counter() + 5.0
        while runner.snapshot()["progress"] <= 0.0 and time.perf_counter() < deadline:
            time.sleep(0.002)
        self.assertTrue(runner.cancel())
        self._pump_until_done(runner, timeout=10.0)
        elapsed = time.perf_counter() - started

        self.assertEqual(finished, [{"error": None, "cancelled": True}])
        self.assertLess(elapsed, 8.0)

    def test_start_falls_back_when_the_host_has_no_timers(self):
        from blender_slicer.adapters.blender import jobs

        # Without ``app.timers`` the add-on must fall back to a synchronous run
        # instead of silently doing nothing.
        timers = bpy.app.timers
        bpy.app.timers = None
        try:
            self.assertFalse(jobs.timer_available())
            self.assertFalse(jobs.start("test", lambda reporter: None))
            self.assertFalse(jobs.start_chunked(lambda: True))
        finally:
            bpy.app.timers = timers
        self.assertIsNone(jobs.shutdown())


class ChunkedRunnerTests(unittest.TestCase):
    """Main-thread work that must not block one timer tick."""

    def test_steps_run_until_done_and_report_progress(self):
        from blender_slicer.adapters.blender import jobs

        runner = jobs.ChunkedRunner()
        done: list[str] = []
        state = {"step": 0}

        def step() -> bool:
            state["step"] += 1
            return state["step"] >= 4

        self.assertTrue(
            runner.start(
                step,
                finish=lambda: done.append("finished"),
                message="building",
                progress=lambda: state["step"] / 4.0,
            )
        )
        runner.advance()

        self.assertEqual(done, ["finished"])
        self.assertFalse(runner.active)
        self.assertEqual(runner.snapshot()["progress"], 1.0)

    def test_second_task_is_rejected_and_cancel_drops_it(self):
        from blender_slicer.adapters.blender import jobs

        runner = jobs.ChunkedRunner()
        finished: list[bool] = []
        self.assertTrue(runner.start(lambda: False, finish=lambda: finished.append(True)))
        self.assertFalse(runner.start(lambda: True))
        self.assertTrue(runner.cancel())
        runner.advance()
        self.assertEqual(finished, [])


class SlicingSplitTests(unittest.TestCase):
    """Slicing is bidirectionally split: bpy copy, then plain maths."""

    def test_build_slices_reproduces_generate_slices(self):
        from blender_slicer.adapters.base.plan import SlicePlan

        settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(), count=4
        )
        context = fake_blender.FakeContext()
        plan = SlicePlan.from_settings(settings)

        direct, direct_frames = slicing.generate_slices(context, settings, plan)
        verts, tris = slicing.collect_geometry(context, settings.source_object)
        split, split_frames = slicing.build_slices(verts, tris, plan)

        self.assertEqual(len(direct), len(split))
        self.assertEqual(set(direct_frames), set(split_frames))
        for expected, actual in zip(direct, split):
            self.assertEqual(
                [c.points for c in expected.contours],
                [c.points for c in actual.contours],
            )

    def test_build_slices_reports_progress_and_honours_cancel(self):
        from blender_slicer.adapters.base.plan import SlicePlan
        from blender_slicer.protocol.errors import Cancelled

        settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(), count=5
        )
        context = fake_blender.FakeContext()
        plan = SlicePlan.from_settings(settings)
        verts, tris = slicing.collect_geometry(context, settings.source_object)

        seen: list[tuple[int, int]] = []
        slicing.build_slices(verts, tris, plan, progress=lambda a, b: seen.append((a, b)))
        self.assertEqual(seen[0], (1, 5))
        self.assertEqual(seen[-1], (5, 5))

        with self.assertRaises(Cancelled):
            slicing.build_slices(verts, tris, plan, cancel=lambda: True)


def _pump_timers(timeout: float = 30.0) -> int:
    """Run the add-on's timer callbacks until no job or build is left."""

    import time

    from blender_slicer.adapters.blender import jobs

    ticks = 0
    deadline = time.perf_counter() + timeout
    while (jobs.JOBS.active or jobs.CHUNKS.active) and time.perf_counter() < deadline:
        bpy.app.timers.tick()
        ticks += 1
        time.sleep(0.002)
    return ticks


class LayerBuilderTests(unittest.TestCase):
    """Viewport drawing spread over timer steps."""

    def setUp(self):
        from types import SimpleNamespace

        RUNTIME.clear()
        bpy.data = fake_blender.data_stores()
        self.settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(), count=3, build_curves=True
        )
        scene = SimpleNamespace(
            slicer_settings=self.settings,
            collection=fake_blender.FakeSceneCollection(),
        )
        self.context = fake_blender.FakeContext(scene=scene)

    def tearDown(self):
        RUNTIME.clear()

    def test_generate_queues_the_drawing_instead_of_blocking(self):
        from blender_slicer.adapters.blender import jobs

        adapter.generate(self.context, self.settings)
        self.assertTrue(jobs.CHUNKS.active)
        self.assertEqual(len(list(bpy.data.objects)), 0)
        _pump_timers()
        self.assertFalse(jobs.CHUNKS.active)
        layer = RUNTIME.layers.active
        names = [obj.name for obj in bpy.data.objects if obj.name.startswith("Slice_")]
        self.assertEqual(len(names), len(layer.slices))

    def test_drawing_is_spread_over_several_steps(self):
        from blender_slicer.adapters.blender import visualization

        adapter.generate(self.context, self.settings)
        _pump_timers()
        layer = RUNTIME.layers.active
        self.assertIsNotNone(layer)
        self.settings.job_running = False
        points = sum(
            len(item_points)
            for item in visualization._iter_layer_slices(layer)
            for _role, _closed, item_points in item[4]
        )

        builder = visualization.LayerBuilder(self.context, [layer], self.settings)
        steps = 0
        while not builder.step(budget=2):
            steps += 1
            self.assertLess(steps, 500)

        # A tiny budget resumes in the middle of a contour, so it takes many
        # steps rather than one per slice.
        self.assertGreater(steps, len(layer.slices))
        self.assertLessEqual(steps, points)
        self.assertAlmostEqual(builder.progress, 1.0)
        names = [obj.name for obj in bpy.data.objects if obj.name.startswith("Slice_")]
        self.assertEqual(len(names), len(layer.slices))

    def test_bevel_is_applied_only_to_finished_curves(self):
        from blender_slicer.adapters.blender import visualization

        adapter.generate(self.context, self.settings)
        _pump_timers()
        layer = RUNTIME.layers.active
        # Start from an empty file so the very first step draws instead of
        # clearing the result the generate just made.
        bpy.data = fake_blender.data_stores()

        builder = visualization.LayerBuilder(self.context, [layer], self.settings)
        builder.step(budget=1)
        obj = next(iter(bpy.data.objects))
        self.assertEqual(obj.data.bevel_depth, 0.0)

        while not builder.step(budget=4):
            pass
        expected = self.settings.curve_radius_mm / self.settings.unit_scale_mm
        self.assertAlmostEqual(obj.data.bevel_depth, expected)


class BackgroundRunTests(unittest.TestCase):
    """Generate, process and draw, driven entirely by the timer pump."""

    def setUp(self):
        import time  # noqa: F401  (used by the helpers below)
        from types import SimpleNamespace

        self.time = time
        RUNTIME.clear()
        bpy.data = fake_blender.data_stores()
        self.settings = fake_blender.make_settings(
            source_object=fake_blender.FakeMeshObject(), count=3, build_curves=True
        )
        scene = SimpleNamespace(
            slicer_settings=self.settings,
            collection=fake_blender.FakeSceneCollection(),
        )
        self.context = fake_blender.FakeContext(scene=scene)
        bpy.context = self.context

    def tearDown(self):
        from blender_slicer.adapters.blender import jobs

        jobs.shutdown()
        RUNTIME.clear()
        if hasattr(bpy, "context"):
            del bpy.context

    def _pump(self, timeout: float = 30.0) -> int:
        return _pump_timers(timeout)

    def test_run_slices_processes_and_draws_from_the_pump(self):
        from blender_slicer.adapters.blender import adapter, jobs

        self.assertTrue(adapter.start_run(self.context, self.settings, regenerate=True))
        self.assertTrue(self.settings.job_running)
        self.assertGreater(self._pump(), 0)

        self.assertFalse(jobs.JOBS.active)
        self.assertFalse(jobs.CHUNKS.active)
        layer = RUNTIME.layers.active
        self.assertIsNotNone(layer)
        self.assertEqual(len(layer.slices), 3)
        self.assertIsNotNone(layer.result)
        self.assertEqual(layer.result.status, ResultStatus.OK)
        self.assertFalse(self.settings.job_running)
        self.assertTrue(self.settings.status.startswith("OK"))
        names = [obj.name for obj in bpy.data.objects if obj.name.startswith("Slice_")]
        self.assertEqual(len(names), 3)

    def test_process_without_generating_asks_for_slices(self):
        from blender_slicer.adapters.blender import adapter
        from blender_slicer.protocol.errors import ConfigError

        with self.assertRaises(ConfigError):
            adapter.start_run(self.context, self.settings, regenerate=False)


if __name__ == "__main__":
    unittest.main()
