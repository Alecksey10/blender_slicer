import traceback

import bpy
from bpy_extras.io_utils import ExportHelper, ImportHelper

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


class SLICER_OT_process(bpy.types.Operator):
    bl_idname = "slicer.process"
    bl_label = "Process Slices"
    bl_description = "Run the configured pipeline on the generated slices"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            result = adapter.process_current(context, _settings(context))
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
        try:
            result = adapter.run(context, _settings(context))
        except (SlicerError, ValueError) as exc:
            return _fail(self, exc)
        if result.status == ResultStatus.ERROR:
            self.report({"WARNING"}, "Processing failed; see the report")
        else:
            self.report({"INFO"}, f"Processing finished: {result.status.value}")
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


CLASSES = (
    SLICER_OT_generate,
    SLICER_OT_process,
    SLICER_OT_run,
    SLICER_OT_clear,
    SLICER_OT_show_report,
    SLICER_OT_export_settings,
    SLICER_OT_import_settings,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
