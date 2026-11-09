"""Settings export/import as human-readable JSON.

The core request/result codec is intentionally separate: this module only
serialises Blender addon settings so a user can share a slice recipe.
"""

from __future__ import annotations

import json
from pathlib import Path

import bpy

from .runtime import RUNTIME

FORMAT = "blender_slicer.settings"
VERSION = 1

FLOAT_FIELDS = (
    "unit_scale_mm",
    "spacing_mm",
    "offset_mm",
    "angle_start_deg",
    "angle_end_deg",
    "material_thickness_mm",
    "material_min_bend_radius_mm",
    "material_max_bend_angle_deg",
    "material_min_segment_mm",
    "material_kerf_mm",
    "material_k_factor",
    "fillet_radius_mm",
    "fillet_min_turn_deg",
    "fillet_chord_tolerance_mm",
    "smooth_preserve_corners_deg",
    "smooth_max_deviation_mm",
    "smooth_weight",
    "simplify_tolerance_mm",
    "simplify_preserve_corners_deg",
    "densify_max_spacing_mm",
    "densify_max_angle_step_deg",
    "densify_chord_tolerance_mm",
    "resample_spacing_mm",
    "resample_min_spacing_mm",
    "resample_chord_tolerance_mm",
    "limit_curvature_min_radius_mm",
    "limit_curvature_weight",
    "curve_radius_mm",
)

INT_FIELDS = (
    "count",
    "fillet_arc_segments",
    "smooth_iterations",
    "limit_curvature_max_iterations",
)

BOOL_FIELDS = (
    "centered",
    "fillet_enabled",
    "fillet_check_material",
    "smooth_enabled",
    "simplify_enabled",
    "densify_enabled",
    "resample_enabled",
    "resample_adaptive",
    "limit_curvature_enabled",
    "limit_curvature_use_material",
    "limit_curvature_strict",
    "build_curves",
    "check_self_intersections",
)

ENUM_FIELDS = (
    "slice_mode",
    "axis",
    "fillet_mode",
    "smooth_algorithm",
)

VECTOR_FIELDS = ("origin_offset_mm",)

FIELDS = FLOAT_FIELDS + INT_FIELDS + BOOL_FIELDS + ENUM_FIELDS + VECTOR_FIELDS


def _plain(value):
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value]
    return value


def settings_to_dict(settings) -> dict:
    values = {}
    for name in FIELDS:
        if hasattr(settings, name):
            values[name] = _plain(getattr(settings, name))
    source = getattr(settings, "source_object", None)
    return {
        "format": FORMAT,
        "version": VERSION,
        "source_object": getattr(source, "name", "") if source else "",
        "settings": values,
    }


def export_settings(settings, filepath: str | Path) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = settings_to_dict(settings)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _coerce(name: str, value):
    if name in FLOAT_FIELDS:
        return float(value)
    if name in INT_FIELDS:
        return int(value)
    if name in BOOL_FIELDS:
        return bool(value)
    if name in ENUM_FIELDS:
        return str(value)
    if name in VECTOR_FIELDS:
        seq = list(value)
        if len(seq) != 3:
            raise ValueError(f"{name} must contain three numbers")
        return (float(seq[0]), float(seq[1]), float(seq[2]))
    return value


def import_settings(settings, filepath: str | Path) -> list[str]:
    path = Path(filepath)
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError("Settings file must contain a JSON object")

    values = payload.get("settings", payload)
    if not isinstance(values, dict):
        raise ValueError("The 'settings' entry must be a JSON object")

    warnings: list[str] = []
    for name, value in values.items():
        if name not in FIELDS:
            warnings.append(f"Unknown setting ignored: {name}")
            continue
        if not hasattr(settings, name):
            warnings.append(f"Setting not available in this version: {name}")
            continue
        try:
            setattr(settings, name, _coerce(name, value))
        except (TypeError, ValueError) as exc:
            warnings.append(f"Invalid value for {name}: {exc}")

    source_name = str(payload.get("source_object") or "")
    if source_name:
        source = bpy.data.objects.get(source_name)
        if source is not None and source.type == "MESH":
            settings.source_object = source
        else:
            warnings.append(f"Source mesh not found: {source_name}")

    settings.revision = int(settings.revision) + 1
    settings.dirty = True
    settings.status = "Settings imported"
    settings.status_detail = f"From {path.name}"
    RUNTIME.dirty = True
    return warnings
