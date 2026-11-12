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


def _purge_orphans() -> None:
    """Drop curve and material datablocks left behind by removed objects."""

    for curve in list(bpy.data.curves):
        if curve.users == 0 and curve.name.startswith("Slice_"):
            bpy.data.curves.remove(curve)
    for material in list(bpy.data.materials):
        if material.users == 0 and material.name.startswith("SliceLayer_"):
            bpy.data.materials.remove(material)


def clear_collection(context) -> None:
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None:
        return
    _remove_collection(coll)
    _purge_orphans()


def _doomed_children() -> tuple[list, list]:
    """Objects and collections of the previous result, children first.

    Collected up front so a host can remove them a few at a time instead of
    unlinking a thousand objects inside one timer tick.
    """

    objects: list = []
    collections: list = []
    root = bpy.data.collections.get(COLLECTION_NAME)
    if root is None:
        return objects, collections

    def walk(coll) -> None:
        for child in list(getattr(coll, "children", [])):
            walk(child)
        for obj in list(getattr(coll, "objects", [])):
            objects.append(obj)
        collections.append(coll)

    for child in list(getattr(root, "children", [])):
        walk(child)
    collections.append(root)
    return objects, collections


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


def _bevel_depth(settings) -> float:
    scale = max(1e-9, float(getattr(settings, "unit_scale_mm", 1000.0)))
    return max(0.0, float(getattr(settings, "curve_radius_mm", 0.15)) / scale)


def _new_curve_object(
    context, collection, name: str, layer: SliceLayer, settings, bevel: bool = True
) -> bpy.types.Object:
    curve = bpy.data.curves.new(name, type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    # A stepped builder passes ``bevel=False`` and sets the depth once the
    # curves are complete: rebuilding the bevel solid of a half-filled spline
    # on every redraw is what makes a big scene crawl while it is drawn.
    curve.bevel_depth = _bevel_depth(settings) if bevel else 0.0
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


class LayerBuilder:
    """Draws the viewport curves in small, resumable steps.

    Two levels of chunking matter: a scene can hold hundreds of slices *and* a
    single slice can carry hundreds of thousands of points, so a step writes a
    bounded number of points and may stop in the **middle of a contour**.  Even
    the removal of a previous result is batched.  A ``bpy.app.timers`` pump then
    spends a few milliseconds per tick and the window keeps painting; one
    blocking ``build_layers`` call is what used to freeze the interface.
    """

    #: Objects removed from the scene per step while clearing the old result.
    CLEAR_BATCH = 64

    def __init__(self, context, layers: list[SliceLayer], settings) -> None:
        self.context = context
        self.settings = settings
        self.layers = [layer for layer in layers if layer.visible and layer.slices]
        self.total = sum(
            len(points)
            for layer in self.layers
            for item in _iter_layer_slices(layer)
            for _role, _closed, points in item[4]
        )
        self.drawn = 0
        self.finished = False
        self._root = None
        self._collection = None
        self._source_name = ""
        self._queue = None
        self._slice: dict | None = None
        self._clear_done = False
        self._doomed: list | None = None
        self._doomed_collections: list = []

    @property
    def progress(self) -> float:
        if self.total <= 0:
            return 1.0
        return min(1.0, self.drawn / float(self.total))

    # ------------------------------------------------------------------ steps
    def step(self, budget: int = 600) -> bool:
        """Write at most ``budget`` points; ``True`` once everything is drawn."""

        if not self._clear_step():
            return False
        if self.finished:
            return True
        written = 0
        while written < budget:
            if self._slice is None and not self._start_next():
                self.finished = True
                return True
            written += self._write(budget - written)
        return False

    def run(self, budget: int = 600) -> None:
        while not self.step(budget):
            pass

    # ---------------------------------------------------------------- clearing
    def _clear_step(self) -> bool:
        """Remove the previous result in batches; ``True`` when the scene is clean."""

        if self._clear_done:
            return True
        if self._doomed is None:
            self._doomed, self._doomed_collections = _doomed_children()
            self._source_name = getattr(
                getattr(self.settings, "source_object", None), "name", ""
            )
        if self._doomed:
            batch = self._doomed[: self.CLEAR_BATCH]
            del self._doomed[: len(batch)]
            for obj in batch:
                bpy.data.objects.remove(obj, do_unlink=True)
            return False
        for coll in self._doomed_collections:
            bpy.data.collections.remove(coll)
        self._doomed_collections = []
        _purge_orphans()
        self._root = ensure_collection(self.context) if self.layers else None
        self._queue = iter(list(self._items()))
        self._clear_done = True
        if self.total > 20000:
            print(
                "[slicer] drawing %d points over %d layer(s) in steps"
                % (self.total, len(self.layers))
            )
        return True

    def _items(self):
        for layer in self.layers:
            yield layer, None
            for item in _iter_layer_slices(layer):
                yield layer, item

    def _start_next(self) -> bool:
        """Open the next drawable slice; ``False`` when the queue is done."""

        while True:
            try:
                layer, item = next(self._queue)
            except StopIteration:
                return False
            if item is None:
                self._collection = bpy.data.collections.new(layer.name)
                self._root.children.link(self._collection)
                continue
            if self._open_slice(layer, item):
                return True

    def _open_slice(self, layer: SliceLayer, item) -> bool:
        index, frame_id, slice_id, changed, contours = item
        frame = layer.frames.get(frame_id or "")
        if frame is None:
            return False
        self._slice = {
            "layer": layer,
            "index": index,
            "frame_id": frame_id,
            "slice_id": slice_id,
            "changed": changed,
            "frame": frame,
            "contours": contours,
            "next": 0,
            "obj": None,
            "spline": None,
            "points": (),
            "at": 0,
        }
        return self._open_contour()

    def _open_contour(self) -> bool:
        """Attach the next drawable contour; ``False`` when the slice is done."""

        state = self._slice
        layer = state["layer"]
        while state["next"] < len(state["contours"]):
            role, closed, points = state["contours"][state["next"]]
            if len(points) >= 2:
                if state["obj"] is None:
                    name = f"Slice_{_safe(layer.id)}_{state['index']:03d}"
                    state["obj"] = _new_curve_object(
                        self.context,
                        self._collection,
                        name,
                        layer,
                        self.settings,
                        bevel=False,
                    )
                spline = state["obj"].data.splines.new("POLY")
                spline.points.add(len(points) - 1)
                spline.use_cyclic_u = bool(closed)
                spline.material_index = _role_index(role)
                state["spline"] = spline
                state["points"] = points
                state["at"] = 0
                return True
            state["next"] += 1
        return False

    def _write(self, budget: int) -> int:
        """Write up to ``budget`` points of the open contour; returns the count."""

        state = self._slice
        points = state["points"]
        frame = state["frame"]
        spline = state["spline"]
        start = state["at"]
        stop = min(len(points), start + max(1, int(budget)))
        for index in range(start, stop):
            x, y, z = frame.to_3d(points[index])
            spline.points[index].co = (x, y, z, 1.0)
        state["at"] = stop
        written = stop - start
        self.drawn += written
        if stop >= len(points):
            state["next"] += 1
            if not self._open_contour():
                self._finish_slice()
        return written

    def _finish_slice(self) -> None:
        state = self._slice
        self._slice = None
        obj = state["obj"]
        if obj is None:
            return
        # Every point is in place: give the curve its thickness now, in one go.
        try:
            obj.data.bevel_depth = _bevel_depth(self.settings)
        except AttributeError:  # data swapped out from under us
            pass
        layer = state["layer"]
        obj["slicer_layer_id"] = layer.id
        obj["slicer_layer_name"] = layer.name
        obj["slicer_slice_id"] = state["slice_id"]
        obj["slicer_frame_id"] = state["frame_id"] or ""
        obj["slicer_changed"] = bool(state["changed"])
        obj["slicer_status"] = layer.status
        obj["slicer_source"] = layer.source_name or self._source_name


def build_layers(context, layers: list[SliceLayer], settings) -> None:
    """Draw every visible layer; a layer's result wins over its source slices."""

    LayerBuilder(context, layers, settings).run(budget=1 << 30)


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
