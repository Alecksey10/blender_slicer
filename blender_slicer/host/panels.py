"""N-panel: a compact action panel plus one collapsible sub-panel per section.

Blender clips a panel that is taller than the region, so putting the buttons
under nine boxes of settings made them unreachable on a normal screen.  The
actions now live in the parent panel and every settings group is a sub-panel
that is opened on demand.  Sub-panels are generated from ``ui_schema.SECTIONS``,
so the layout still has a single source of truth.
"""

from __future__ import annotations

from typing import Any

import bpy

from .runtime import RUNTIME
from .ui_schema import SECTIONS, draw_sections


def _status_icon(settings):
    if settings.last_errors:
        return "ERROR"
    if settings.last_warnings:
        return "INFO"
    if settings.status.startswith("Generated") or settings.status.startswith("OK"):
        return "CHECKMARK"
    return "TIME"


class SLICER_PT_main(bpy.types.Panel):
    bl_label = "Slice Engine"
    bl_idname = "SLICER_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slice"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        settings = getattr(context.scene, "slicer_settings", None)
        if settings is None:
            layout.label(text="Settings are not registered", icon="ERROR")
            return

        header = layout.row(align=True)
        header.label(text=settings.status or "Ready", icon=_status_icon(settings))
        layout.label(text=settings.status_detail)

        box = layout.box()
        box.label(text="Actions")
        row = box.row(align=True)
        row.scale_y = 1.4
        row.operator("slicer.run", icon="PLAY")
        row = box.row(align=True)
        row.operator("slicer.generate", icon="MESH_GRID")
        row.operator("slicer.process", icon="MOD_DISPLACE")
        row = box.row(align=True)
        row.operator("slicer.clear", icon="TRASH")
        row = box.row(align=True)
        row.operator("slicer.export_settings", icon="EXPORT")
        row.operator("slicer.import_settings", icon="IMPORT")

        stats = layout.box()
        stats.label(text="Last result")
        stats.label(text=f"Slices: {settings.last_slices}   Points: {settings.last_points}")
        stats.label(text=f"Errors: {settings.last_errors}   Warnings: {settings.last_warnings}")
        if RUNTIME.dirty and RUNTIME.slices:
            stats.label(text="Result is stale; regenerate slices", icon="INFO")


def _section_panel(section: dict[str, Any], order: int) -> type:
    """Build one collapsible sub-panel from the declarative UI schema."""

    def draw(self, context) -> None:
        settings = getattr(context.scene, "slicer_settings", None)
        if settings is None:
            self.layout.label(text="Settings are not registered", icon="ERROR")
            return
        draw_sections(self.layout, settings, (section,), boxed=False)

    namespace = {
        "__module__": __name__,
        "bl_label": section["title"],
        "bl_idname": f"SLICER_PT_{section['id']}",
        "bl_parent_id": "SLICER_PT_main",
        "bl_space_type": "VIEW_3D",
        "bl_region_type": "UI",
        "bl_category": "Slice",
        "bl_options": set() if section.get("open", False) else {"DEFAULT_CLOSED"},
        "bl_order": order,
        "draw": draw,
    }
    return type(f"SLICER_PT_{section['id']}", (bpy.types.Panel,), namespace)


SECTION_PANELS = tuple(
    _section_panel(section, index + 1) for index, section in enumerate(SECTIONS)
)


class SLICER_PT_report(bpy.types.Panel):
    bl_label = "Report"
    bl_idname = "SLICER_PT_report"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slice"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 100

    def draw(self, context):
        layout = self.layout
        settings = getattr(context.scene, "slicer_settings", None)
        if settings is None:
            layout.label(text="Settings are not registered", icon="ERROR")
            return

        layout.label(text=settings.status or "Ready", icon=_status_icon(settings))
        layout.label(text=settings.status_detail)
        layout.operator("slicer.show_report", icon="TEXT")

        box = layout.box()
        lines = [line for line in settings.diagnostics_text.splitlines() if line.strip()]
        if not lines:
            box.label(text="No diagnostics", icon="CHECKMARK")
            return
        for line in lines[:20]:
            box.label(text=line)
        if len(lines) > 20:
            box.label(text=f"... and {len(lines) - 20} more")


class SLICER_PT_about(bpy.types.Panel):
    bl_label = "About"
    bl_idname = "SLICER_PT_about"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slice"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 101

    def draw(self, context):
        layout = self.layout
        layout.label(text="Host-independent slicer core")
        layout.label(text="All engine coordinates are 2D millimetres")
        layout.label(text="1 Blender unit is configurable (default 1000 mm)")


CLASSES = (SLICER_PT_main, *SECTION_PANELS, SLICER_PT_report, SLICER_PT_about)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
