import traceback

import bpy
from bpy_extras.io_utils import ExportHelper, ImportHelper

from ...adapters.base.export import ExportManager
from ...adapters.base.runtime import RUNTIME
from ...protocol.errors import ConfigError, SlicerError
from ...protocol.types import ResultStatus
from . import adapter, settings_io


def _settings(context):
    settings = getattr(context.scene, "slicer_settings", None)
    if settings is None:
        raise ConfigError("Slice Engine settings are not registered")
    return settings


def _fail(operator, exc: Exception) -> set[str]:
    traceback.print_exc()
    operator.report({"ERROR"}, str(exc))
    return {"CANCELLED"}


class SLICER_OT_generate(bpy.types.Operator):
    bl_idname = "slicer.generate"
    bl_label = "Generate Slices"
    bl_description = "Intersect the source mesh with the configured planes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            count = adapter.generate(context, _settings(context))
        except (SlicerError, ValueError) as exc:
            return _fail(self, exc)
        self.report({"INFO"}, f"Generated {count} slices")
        return {"FINISHED"}


def _wants_background(settings) -> bool:
    return bool(getattr(settings, "use_background", True))


class SLICER_OT_process(bpy.types.Operator):
    bl_idname = "slicer.process"
    bl_label = "Process Slices"
    bl_description = (
        "Run the configured pipeline on the generated slices "
        "(in a background thread when enabled)"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            if _wants_background(settings) and adapter.start_process(context, settings):
                self.report({"INFO"}, "Processing started; use Cancel to stop it")
                return {"FINISHED"}
            result = adapter.process_current(context, settings)
        except (SlicerError, ValueError) as exc:
            return _fail(self, exc)
        if result.status == ResultStatus.ERROR:
            self.report({"WARNING"}, "Processing failed; see the report")
        else:
            self.report({"INFO"}, f"Processing finished: {result.status.value}")
        return {"FINISHED"}


class SLICER_OT_run(bpy.types.Operator):
    bl_idname = "slicer.run"
    bl_label = "Run"
    bl_description = "Generate slices and process them in one step"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            if _wants_background(settings) and adapter.start_run(
                context, settings, regenerate=True
            ):
                self.report({"INFO"}, "Working in the background; use Cancel to stop it")
                return {"FINISHED"}
            result = adapter.run(context, settings)
        except (SlicerError, ValueError) as exc:
            return _fail(self, exc)
        if result is None:
            return {"FINISHED"}
        if result.status == ResultStatus.ERROR:
            self.report({"WARNING"}, "Processing failed; see the report")
        else:
            self.report({"INFO"}, f"Processing finished: {result.status.value}")
        return {"FINISHED"}


class SLICER_OT_cancel(bpy.types.Operator):
    bl_idname = "slicer.cancel"
    bl_label = "Cancel"
    bl_description = "Stop the background job; the previous result is kept"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        if not adapter.cancel_process(context, settings):
            self.report({"INFO"}, "Nothing is running")
            return {"CANCELLED"}
        self.report({"INFO"}, "Cancelling...")
        return {"FINISHED"}


class SLICER_OT_clear(bpy.types.Operator):
    bl_idname = "slicer.clear"
    bl_label = "Clear"
    bl_description = "Remove generated curves and discard the current result"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            adapter.clear(context, _settings(context))
        except (SlicerError, ValueError) as exc:
            return _fail(self, exc)
        self.report({"INFO"}, "Cleared")
        return {"FINISHED"}


class SLICER_OT_show_report(bpy.types.Operator):
    bl_idname = "slicer.show_report"
    bl_label = "Show Report"
    bl_description = "Show the latest diagnostics in a popup"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        title = settings.status or "Slice report"

        def draw(menu, _context):
            layout = menu.layout
            layout.label(text=settings.status_detail)
            lines = [line for line in settings.diagnostics_text.splitlines() if line.strip()]
            if not lines:
                layout.label(text="No diagnostics", icon="CHECKMARK")
                return
            for line in lines[:30]:
                layout.label(text=line)
            if len(lines) > 30:
                layout.label(text=f"... and {len(lines) - 30} more")

        context.window_manager.popup_menu(draw, title=title, icon="TEXT")
        return {"FINISHED"}


class SLICER_OT_export_settings(bpy.types.Operator, ExportHelper):
    bl_idname = "slicer.export_settings"
    bl_label = "Export Settings"
    bl_description = "Save the slice recipe as JSON"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        try:
            settings_io.export_settings(_settings(context), self.filepath)
        except (OSError, ValueError) as exc:
            return _fail(self, exc)
        self.report({"INFO"}, f"Settings exported to {self.filepath}")
        return {"FINISHED"}


class SLICER_OT_import_settings(bpy.types.Operator, ImportHelper):
    bl_idname = "slicer.import_settings"
    bl_label = "Import Settings"
    bl_description = "Load a slice recipe from JSON"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        try:
            warnings = settings_io.import_settings(_settings(context), self.filepath)
        except (OSError, ValueError) as exc:
            return _fail(self, exc)
        if warnings:
            self.report({"WARNING"}, "; ".join(warnings[:3]))
        else:
            self.report({"INFO"}, "Settings imported")
        return {"FINISHED"}


class SLICER_OT_find_contacts(bpy.types.Operator):
    bl_idname = "slicer.find_contacts"
    bl_label = "Find Contacts"
    bl_description = "Mark points where slices of different passes meet"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            contacts = adapter.find_contacts(context, _settings(context))
        except (SlicerError, ValueError) as exc:
            return _fail(self, exc)
        self.report({"INFO"}, f"{len(contacts)} contact point(s)")
        return {"FINISHED"}


class SLICER_OT_frame_contacts(bpy.types.Operator):
    bl_idname = "slicer.frame_contacts"
    bl_label = "Frame Contacts"
    bl_description = "Select the contact markers and frame them in the viewport"
    bl_options = {"REGISTER"}

    def execute(self, context):
        root = bpy.data.collections.get("Slice Engine")
        collection = root.children.get("Contacts") if root is not None else None
        objects = [
            obj for obj in getattr(collection, "objects", ()) if obj.type == "MESH"
        ]
        if not objects:
            self.report({"WARNING"}, "No contact markers; run Find Contacts first")
            return {"CANCELLED"}
        for obj in context.view_layer.objects:
            obj.select_set(False)
        for obj in objects:
            obj.select_set(True)
        context.view_layer.objects.active = objects[0]
        area = next(
            (area for area in getattr(context.screen, "areas", ()) if area.type == "VIEW_3D"),
            None,
        )
        if area is None:
            return {"FINISHED"}
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        with context.temp_override(area=area, region=region):
            bpy.ops.view3d.view_selected()
        return {"FINISHED"}


class SLICER_OT_toggle_layer(bpy.types.Operator):
    bl_idname = "slicer.toggle_layer"
    bl_label = "Toggle Layer"
    bl_description = "Show or hide this cutting pass in the viewport"
    bl_options = {"REGISTER", "UNDO"}

    layer_id: bpy.props.StringProperty()

    def execute(self, context):
        try:
            visible = adapter.set_layer_visible(context, _settings(context), self.layer_id)
        except (SlicerError, ValueError) as exc:
            return _fail(self, exc)
        self.report({"INFO"}, "Visible" if visible else "Hidden")
        return {"FINISHED"}


class SLICER_OT_clear_layers(bpy.types.Operator):
    bl_idname = "slicer.clear_layers"
    bl_label = "Clear All Layers"
    bl_description = "Remove every cutting pass and its curves"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            adapter.clear(context, _settings(context))
        except (SlicerError, ValueError) as exc:
            return _fail(self, exc)
        self.report({"INFO"}, "All layers cleared")
        return {"FINISHED"}


class SLICER_OT_export_slices(bpy.types.Operator, ExportHelper):
    bl_idname = "slicer.export_slices"
    bl_label = "Export Slices"
    bl_description = "Write every visible layer as JSON or SVG"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json;*.svg", options={"HIDDEN"})

    def execute(self, context):
        try:
            layers = RUNTIME.layers.visible_layers()
            ExportManager().export(
                self.filepath,
                layers,
                RUNTIME.result,
                (),
            )
        except (OSError, ValueError) as exc:
            return _fail(self, exc)
        self.report({"INFO"}, f"Exported {len(layers)} layer(s) to {self.filepath}")
        return {"FINISHED"}


CLASSES = (
    SLICER_OT_generate,
    SLICER_OT_process,
    SLICER_OT_run,
    SLICER_OT_cancel,
    SLICER_OT_clear,
    SLICER_OT_show_report,
    SLICER_OT_export_settings,
    SLICER_OT_import_settings,
    SLICER_OT_find_contacts,
    SLICER_OT_frame_contacts,
    SLICER_OT_toggle_layer,
    SLICER_OT_clear_layers,
    SLICER_OT_export_slices,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
