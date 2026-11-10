from __future__ import annotations

import bpy

from ...adapters.base.frames import CoordinateFrame
from ...protocol.types import ContourRole, ProcessingResult, Slice


COLLECTION_NAME = "Slice Engine"


def ensure_collection(context) -> bpy.types.Collection:
    scene = context.scene
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION_NAME)
    if scene.collection.children.get(coll.name) is None:
        scene.collection.children.link(coll)
    return coll


def clear_collection(context) -> None:
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is not None:
        for obj in list(coll.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
    for curve in list(bpy.data.curves):
        if curve.users == 0 and curve.name.startswith("Slice_"):
            bpy.data.curves.remove(curve)


def _material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    try:
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = color
    except Exception:
        pass
    return mat


def _material_index(role: ContourRole) -> int:
    if role == ContourRole.SCORE:
        return 1
    if role == ContourRole.GUIDE:
        return 2
    return 0


def _new_curve_object(
    context,
    coll,
    name: str,
    settings,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(name, type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    radius_mm = float(getattr(settings, "curve_radius_mm", 0.15))
    curve.bevel_depth = max(0.0, radius_mm / max(1e-9, float(settings.unit_scale_mm)))
    curve.bevel_resolution = 0
    curve.use_fill_caps = True

    curve.materials.append(_material("SliceCut", (0.12, 0.47, 0.71, 1.0)))
    curve.materials.append(_material("SliceScore", (1.0, 0.50, 0.05, 1.0)))
    curve.materials.append(_material("SliceGuide", (0.6, 0.6, 0.6, 1.0)))

    obj = bpy.data.objects.new(name, curve)
    coll.objects.link(obj)
    obj.show_in_front = True
    return obj


def _add_contour(
    obj: bpy.types.Object,
    frame: CoordinateFrame,
    role: ContourRole,
    points: list[tuple[float, float]],
    closed: bool,
) -> bool:
    if len(points) < 2:
        return False
    spline = obj.data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for i, p in enumerate(points):
        x, y, z = frame.to_3d(p)
        spline.points[i].co = (x, y, z, 1.0)
    spline.use_cyclic_u = bool(closed)
    spline.material_index = _material_index(role)
    return True


def build_from_slices(
    context,
    slices: list[Slice],
    frames: dict[str, CoordinateFrame],
    settings,
) -> None:
    clear_collection(context)
    coll = ensure_collection(context)
    for slice_ in slices:
        frame = frames.get(slice_.frame_id or "")
        if frame is None:
            continue
        obj = _new_curve_object(context, coll, f"Slice_{slice_.index:03d}", settings)
        count = 0
        for contour in slice_.contours:
            if _add_contour(obj, frame, contour.role, contour.points, contour.closed):
                count += 1
        if count == 0:
            bpy.data.objects.remove(obj, do_unlink=True)
            continue
        obj["slicer_slice_id"] = slice_.id
        obj["slicer_frame_id"] = slice_.frame_id or ""
        obj["slicer_source"] = getattr(settings.source_object, "name", "") if settings.source_object else ""


def build_from_result(
    context,
    result: ProcessingResult,
    frames: dict[str, CoordinateFrame],
    settings,
) -> None:
    clear_collection(context)
    coll = ensure_collection(context)
    for slice_result in result.slices:
        frame = frames.get(slice_result.frame_id or "")
        if frame is None:
            continue
        obj = _new_curve_object(context, coll, f"Slice_{slice_result.index:03d}", settings)
        count = 0
        for contour in slice_result.contours:
            if _add_contour(obj, frame, contour.role, contour.points, contour.closed):
                count += 1
        if count == 0:
            bpy.data.objects.remove(obj, do_unlink=True)
            continue
        obj["slicer_slice_id"] = slice_result.slice_id
        obj["slicer_frame_id"] = slice_result.frame_id or ""
        obj["slicer_changed"] = bool(slice_result.changed)
        obj["slicer_status"] = result.status.value
        obj["slicer_source"] = getattr(settings.source_object, "name", "") if settings.source_object else ""
