"""Result visualization for Blender: one collection per layer, plus contacts.

Every visible layer gets its own collection and its own colour, so the vertical
and horizontal passes (and results of earlier runs) can be compared in one
viewport.  Objects carry custom properties with the layer and slice ids, which
makes them easy to script against.
"""

from __future__ import annotations

import bpy

from ...adapters.base.layers import SliceLayer
from ...protocol.shapes import ContourRole
from ...spatial.contacts import ContactPoint
from ...spatial.frames import CoordinateFrame

COLLECTION_NAME = "Slice Engine"
CONTACTS_NAME = "Contacts"


# --------------------------------------------------------------------- scene
def ensure_collection(context) -> bpy.types.Collection:
    scene = context.scene
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION_NAME)
    if scene.collection.children.get(coll.name) is None:
        scene.collection.children.link(coll)
    return coll


def _remove_collection(coll) -> None:
    for child in list(getattr(coll, "children", [])):
        _remove_collection(child)
    for obj in list(getattr(coll, "objects", [])):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(coll)


def clear_collection(context) -> None:
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None:
        return
    _remove_collection(coll)
    for curve in list(bpy.data.curves):
        if curve.users == 0 and curve.name.startswith("Slice_"):
            bpy.data.curves.remove(curve)
    for material in list(bpy.data.materials):
        if material.users == 0 and material.name.startswith("SliceLayer_"):
            bpy.data.materials.remove(material)


def clear_layers(context) -> None:
    """Remove result curves but keep contact markers."""

    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None:
        return
    for child in list(getattr(coll, "children", [])):
        if child.name != CONTACTS_NAME:
            _remove_collection(child)


def _safe(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name)
    return cleaned.strip("_") or "layer"


def _tint(color: tuple[float, float, float], amount: float) -> tuple[float, float, float, float]:
    """Mix a colour with white (amount > 0) or black (amount < 0)."""

    target = 1.0 if amount >= 0 else 0.0
    factor = abs(amount)
    return (
        color[0] + (target - color[0]) * factor,
        color[1] + (target - color[1]) * factor,
        color[2] + (target - color[2]) * factor,
        1.0,
    )


def _material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.diffuse_color = color
    try:
        material.use_nodes = True
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = color
    except Exception:
        pass
    return material


def _role_materials(layer: SliceLayer) -> dict[ContourRole, int]:
    prefix = f"SliceLayer_{_safe(layer.id)}"
    cut = _material(f"{prefix}_cut", (layer.color[0], layer.color[1], layer.color[2], 1.0))
    score = _material(f"{prefix}_score", _tint(layer.color, 0.15))
    guide = _material(f"{prefix}_guide", (0.6, 0.6, 0.6, 1.0))
    return {ContourRole.CUT: 0, ContourRole.SCORE: 1, ContourRole.GUIDE: 2}, (cut, score, guide)


def _new_curve_object(context, collection, name: str, layer: SliceLayer, settings) -> bpy.types.Object:
    curve = bpy.data.curves.new(name, type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    scale = max(1e-9, float(getattr(settings, "unit_scale_mm", 1000.0)))
    curve.bevel_depth = max(0.0, float(getattr(settings, "curve_radius_mm", 0.15)) / scale)
    curve.bevel_resolution = 0
    curve.use_fill_caps = True

    overrides = []

    def add(mat):
        curve.materials.append(mat)
        overrides.append(mat)

    _index_map, materials = _role_materials(layer)
    for material in materials:
        add(material)

    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    obj.show_in_front = True
    return obj


def _add_contour(obj, frame: CoordinateFrame, role: ContourRole, points, closed: bool) -> bool:
    if len(points) < 2:
        return False
    spline = obj.data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for index, point in enumerate(points):
        x, y, z = frame.to_3d(point)
        spline.points[index].co = (x, y, z, 1.0)
    spline.use_cyclic_u = bool(closed)
    spline.material_index = _role_index(role)
    return True


def _role_index(role: ContourRole) -> int:
    if role == ContourRole.SCORE:
        return 1
    if role == ContourRole.GUIDE:
        return 2
    return 0


def _iter_layer_slices(layer: SliceLayer):
    """Yield (index, frame_id, slice_id, changed, contours) for drawing."""

    if layer.result is not None:
        for slice_result in layer.result.slices:
            yield (
                slice_result.index,
                slice_result.frame_id,
                slice_result.slice_id,
                slice_result.changed,
                [(c.role, c.closed, c.points) for c in slice_result.contours],
            )
        return
    for slice_ in layer.slices:
        yield (
            slice_.index,
            slice_.frame_id,
            slice_.id,
            True,
            [(c.role, c.closed, c.points) for c in slice_.contours],
        )


def build_layers(context, layers: list[SliceLayer], settings) -> None:
    """Draw every visible layer; a layer's result wins over its source slices."""

    clear_collection(context)
    layers = [layer for layer in layers if layer.visible and layer.slices]
    if not layers:
        return
    root = ensure_collection(context)
    source_name = getattr(getattr(settings, "source_object", None), "name", "")

    for layer in layers:
        collection = bpy.data.collections.new(layer.name)
        root.children.link(collection)
        for index, frame_id, slice_id, changed, contours in _iter_layer_slices(layer):
            frame = layer.frames.get(frame_id or "")
            if frame is None:
                continue
            name = f"Slice_{_safe(layer.id)}_{index:03d}"
            obj = _new_curve_object(context, collection, name, layer, settings)
            count = 0
            for role, closed, points in contours:
                if _add_contour(obj, frame, role, points, closed):
                    count += 1
            if count == 0:
                bpy.data.objects.remove(obj, do_unlink=True)
                continue
            obj["slicer_layer_id"] = layer.id
            obj["slicer_layer_name"] = layer.name
            obj["slicer_slice_id"] = slice_id
            obj["slicer_frame_id"] = frame_id or ""
            obj["slicer_changed"] = bool(changed)
            obj["slicer_status"] = layer.status
            obj["slicer_source"] = layer.source_name or source_name


# ------------------------------------------------------------------ contacts
CONTACT_COLORS = {
    "intersection": (0.95, 0.05, 0.05),
    "near": (1.0, 0.55, 0.05),
}


def _marker_mesh(name: str, radius: float, color: tuple[float, float, float]):
    """Small solid octahedron, so contacts read as bold dots.

    Empties were nearly invisible at millimetre scale and cannot carry a
    material; a real mesh can be tinted and stays visible in solid view.
    """

    # The radius is part of the name: a cached mesh would otherwise keep the
    # size of the first run and ignore later marker-size changes.
    mesh_name = f"SlicerContact_{name}_{radius:.4f}"
    mesh = bpy.data.meshes.get(mesh_name)
    if mesh is None:
        mesh = bpy.data.meshes.new(mesh_name)
        r = max(1e-6, float(radius))
        verts = [
            (r, 0.0, 0.0),
            (-r, 0.0, 0.0),
            (0.0, r, 0.0),
            (0.0, -r, 0.0),
            (0.0, 0.0, r),
            (0.0, 0.0, -r),
        ]
        faces = [
            (0, 2, 4),
            (2, 1, 4),
            (1, 3, 4),
            (3, 0, 4),
            (2, 0, 5),
            (1, 2, 5),
            (3, 1, 5),
            (0, 3, 5),
        ]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        material = bpy.data.materials.get(mesh_name) or bpy.data.materials.new(mesh_name)
        material.diffuse_color = (*color, 1.0)
        mesh.materials.append(material)
    return mesh


def _scene_extent_mm(context, settings) -> float:
    """Rough model size, so markers stay visible on big models."""

    scale = max(1e-9, float(getattr(settings, "unit_scale_mm", 1000.0)))
    extent = 0.0
    for obj in getattr(getattr(context, "scene", None), "objects", ()):
        if obj.type != "MESH" or obj.get("slicer_contact_kind"):
            continue
        dimensions = getattr(obj, "dimensions", None)
        if dimensions is None:
            continue
        extent = max(extent, max(float(value) for value in dimensions) * scale)
    return extent


def build_contacts(context, contacts: list[ContactPoint], settings) -> None:
    root = ensure_collection(context)
    existing = root.children.get(CONTACTS_NAME)
    if existing is not None:
        _remove_collection(existing)
    if not contacts:
        return

    collection = bpy.data.collections.new(CONTACTS_NAME)
    root.children.link(collection)
    scale = max(1e-9, float(getattr(settings, "unit_scale_mm", 1000.0)))
    requested_mm = max(0.25, float(getattr(settings, "contact_marker_mm", 5.0)))
    # A fixed millimetre radius disappears on a two-metre model; never let a
    # marker be smaller than ~0.5% of the model.
    marker_mm = max(requested_mm, _scene_extent_mm(context, settings) * 0.005)
    for mesh in list(bpy.data.meshes):
        if mesh.name.startswith("SlicerContact_") and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    meshes = {
        kind: _marker_mesh(kind, marker_mm / scale, color)
        for kind, color in CONTACT_COLORS.items()
    }
    for index, contact in enumerate(contacts):
        kind = getattr(contact, "kind", "near")
        obj = bpy.data.objects.new(
            f"Contact_{index:03d}", meshes.get(kind, meshes["near"])
        )
        obj.location = contact.position
        obj.show_in_front = True
        obj["slicer_contact_kind"] = kind
        obj["slicer_contact_distance_mm"] = contact.distance_mm
        obj["slicer_contact_layers"] = f"{contact.layer_a} / {contact.layer_b}"
        obj["slicer_contact_slices"] = f"{contact.slice_a} / {contact.slice_b}"
        collection.objects.link(obj)
