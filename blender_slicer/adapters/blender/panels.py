"""N-panel: a compact action panel, collapsible setting groups and layer list.

Blender clips a panel taller than the region, so actions live in the parent
panel and every settings group is a sub-panel opened on demand.  Sub-panels are
generated from ``ui_schema.SECTIONS``, so the layout keeps a single source of
truth.  The Layers panel lists every cutting pass the session holds, because
vertical and horizontal passes are meant to be compared together.
"""

from __future__ import annotations

from typing import Any

import bpy

from blender_slicer.adapters.base.runtime import RUNTIME
from .i18n import current_locale, tr
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
    bl_label = tr("Slice Engine")
    bl_idname = "SLICER_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slice"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        settings = getattr(context.scene, "slicer_settings", None)
        if settings is None:
            layout.label(text=tr("Settings are not registered"), icon="ERROR")
            return

        header = layout.row(align=True)
        header.label(text=settings.status or tr("Ready"), icon=_status_icon(settings))
        layout.label(text=settings.status_detail)

        if getattr(settings, "job_running", False):
            job = layout.box()
            job.label(
                text=settings.job_message or tr("Working..."), icon="TIME"
            )
            job.prop(settings, "job_progress", text=tr("Progress"), slider=True)
            row = job.row(align=True)
            row.enabled = not getattr(settings, "job_cancelling", False)
            row.operator("slicer.cancel", text=tr("Cancel"), icon="CANCEL")

        box = layout.box()
        box.label(text=tr("Actions"))
        row = box.row(align=True)
        row.scale_y = 1.4
        row.operator("slicer.run", text=tr("Run"), icon="PLAY")
        row = box.row(align=True)
        row.operator("slicer.generate", text=tr("Generate Slices"), icon="MESH_GRID")
        row.operator("slicer.process", text=tr("Process Slices"), icon="MOD_DISPLACE")
        row = box.row(align=True)
        row.operator("slicer.find_contacts", text=tr("Find Contacts"), icon="EMPTY_AXIS")
        row.operator("slicer.frame_contacts", text=tr("Frame Contacts"), icon="ZOOM_SELECTED")
        row = box.row(align=True)
        row.operator("slicer.clear", text=tr("Clear"), icon="TRASH")
        row = box.row(align=True)
        row.operator("slicer.export_settings", text=tr("Export Settings"), icon="EXPORT")
        row.operator("slicer.import_settings", text=tr("Import Settings"), icon="IMPORT")
        row = box.row(align=True)
        row.operator("slicer.export_slices", text=tr("Export Slices"), icon="FILE_TICK")

        stats = layout.box()
        stats.label(text=tr("Last result"))
        stats.label(
            text=tr("Slices: {slices}   Points: {points}", slices=settings.last_slices, points=settings.last_points)
        )
        stats.label(
            text=tr(
                "Errors: {errors}   Warnings: {warnings}",
                errors=settings.last_errors,
                warnings=settings.last_warnings,
            )
        )
        stats.label(
            text=tr(
                "Contacts: {contacts}   Layers: {layers}",
                contacts=settings.last_contacts,
                layers=len(RUNTIME.layers),
            )
        )
        if RUNTIME.dirty and RUNTIME.has_slices:
            stats.label(text=tr("Result is stale; regenerate slices"), icon="INFO")


class SLICER_PT_layers(bpy.types.Panel):
    bl_label = tr("Layers")
    bl_idname = "SLICER_PT_layers"
    bl_parent_id = "SLICER_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slice"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 90

    def draw(self, context):
        layout = self.layout
        settings = getattr(context.scene, "slicer_settings", None)
        if settings is None:
            layout.label(text=tr("Settings are not registered"), icon="ERROR")
            return
        layers = RUNTIME.layers.all_layers()
        if not layers:
            layout.label(text=tr("No slice plans yet"), icon="INFO")
            return
        for layer in layers:
            row = layout.row(align=True)
            icon = "HIDE_OFF" if layer.visible else "HIDE_ON"
            row.operator(
                "slicer.toggle_layer", text=layer.name, icon=icon, emboss=False
            ).layer_id = layer.id
            row.label(text=f"{layer.slice_count} s · {layer.status}")
        layout.operator("slicer.clear_layers", icon="TRASH")


def _section_panel(section, order: int, sections=None) -> type:
    """Build one collapsible sub-panel from the declarative UI schema."""

    sections = sections or (section,)

    def draw(self, context) -> None:
        settings = getattr(context.scene, "slicer_settings", None)
        if settings is None:
            self.layout.label(text=tr("Settings are not registered"), icon="ERROR")
            return
        if len(sections) == 1:
            draw_sections(self.layout, settings, sections, boxed=False)
            _optimizer_readout(self.layout, settings, sections[0].id)
            return
        draw_sections(self.layout, settings, sections, boxed=True)

    namespace: dict[str, Any] = {
        "__module__": __name__,
        "bl_label": tr(section.title),
        "bl_idname": f"SLICER_PT_{section.id}",
        "bl_parent_id": "SLICER_PT_main",
        "bl_space_type": "VIEW_3D",
        "bl_region_type": "UI",
        "bl_category": "Slice",
        "bl_options": set() if section.open else {"DEFAULT_CLOSED"},
        "bl_order": order,
        "draw": draw,
    }
    return type(f"SLICER_PT_{section.id}", (bpy.types.Panel,), namespace)


def _optimizer_readout(layout, settings, section_id: str) -> None:
    """Explain the solve in the panel: what it replaces and how it trades.

    The two weights are not intuitive as numbers, but their ratio is: it is how
    many millimetres of deviation one radian of extra bending is worth.
    """

    if section_id != "optimize" or not getattr(settings, "optimize_enabled", False):
        return
    box = layout.box()
    data = max(1e-9, float(getattr(settings, "optimize_data_weight", 20.0)))
    radius = max(0.0, float(getattr(settings, "optimize_radius_weight", 1000.0)))
    box.label(
        text=tr("Deviation per radian: {value} mm", value=f"{(radius / data) ** 0.5:.2f}")
    )
    box.label(text=tr("Replaces fillet, smoothing and curvature limiting"), icon="INFO")


def _grouped_panels() -> list[type]:
    """One panel per section, except grouped sections that share a panel."""

    panels: list[type] = []
    seen: dict[str, list] = {}
    for index, section in enumerate(SECTIONS):
        if not section.group:
            panels.append(_section_panel(section, index + 1))
            continue
        bucket = seen.setdefault(section.group, [])
        bucket.append(section)
        if len(bucket) > 1:
            continue
        title = "Legacy shaping" if section.group == "legacy" else section.title
        panels.append(
            _section_panel(
                _Renamed(section, f"{section.group}_group", title),
                index + 1,
                sections=bucket,
            )
        )
    return panels


class _Renamed:
    """A section view with its own id/title, used for grouped panels."""

    __slots__ = ("id", "title", "open")

    def __init__(self, section, panel_id: str, title: str) -> None:
        self.id = panel_id
        self.title = title
        self.open = section.open


SECTION_PANELS = tuple(_grouped_panels())


class SLICER_PT_report(bpy.types.Panel):
    bl_label = tr("Report")
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
            layout.label(text=tr("Settings are not registered"), icon="ERROR")
            return

        layout.label(text=settings.status or tr("Ready"), icon=_status_icon(settings))
        layout.label(text=settings.status_detail)
        layout.operator("slicer.show_report", text=tr("Show Report"), icon="TEXT")

        box = layout.box()
        lines = [line for line in settings.diagnostics_text.splitlines() if line.strip()]
        if not lines:
            box.label(text=tr("No diagnostics"), icon="CHECKMARK")
            return
        for line in lines[:20]:
            box.label(text=line)
        if len(lines) > 20:
            box.label(text=f"... and {len(lines) - 20} more")


class SLICER_PT_about(bpy.types.Panel):
    bl_label = tr("About")
    bl_idname = "SLICER_PT_about"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slice"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 101

    def draw(self, context):
        layout = self.layout
        layout.label(text=tr("Host-independent slicer core"))
        layout.label(text=tr("All engine coordinates are 2D millimetres"))
        layout.label(text=tr("1 Blender unit is configurable (default 1000 mm)"))
        layout.label(text=tr("Cut offsets: X outward, Z inward by default"))
        layout.label(text=tr("Interface language: {lang}", lang=current_locale()))


CLASSES = (SLICER_PT_main, *SECTION_PANELS, SLICER_PT_layers, SLICER_PT_report, SLICER_PT_about)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
