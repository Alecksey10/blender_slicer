"""Minimal stand-ins for ``bpy`` and ``mathutils``.

The engine never imports Blender; the host layer does.  These stubs let the
host layer be imported and exercised in a plain Python process, so the
3D -> 2D slicing pipeline and the settings -> operations mapping can be tested
without an installed Blender build.

The stubs are deliberately small: they implement exactly the surface the addon
uses (``Vector`` arithmetic, a fake evaluated mesh, property declarations and
class registration) and nothing else.
"""

from __future__ import annotations

import math
import sys
import types


class Vector:
    __slots__ = ("x", "y", "z")

    def __init__(self, seq=(0.0, 0.0, 0.0)):
        self.x = float(seq[0])
        self.y = float(seq[1])
        self.z = float(seq[2])

    def __add__(self, other: "Vector") -> "Vector":
        return Vector((self.x + other.x, self.y + other.y, self.z + other.z))

    def __sub__(self, other: "Vector") -> "Vector":
        return Vector((self.x - other.x, self.y - other.y, self.z - other.z))

    def __mul__(self, scalar: float) -> "Vector":
        return Vector((self.x * scalar, self.y * scalar, self.z * scalar))

    __rmul__ = __mul__

    def __truediv__(self, scalar: float) -> "Vector":
        return Vector((self.x / scalar, self.y / scalar, self.z / scalar))

    def __neg__(self) -> "Vector":
        return Vector((-self.x, -self.y, -self.z))

    @property
    def length(self) -> float:
        return math.sqrt(self.dot(self))

    def dot(self, other: "Vector") -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: "Vector") -> "Vector":
        return Vector(
            (
                self.y * other.z - self.z * other.y,
                self.z * other.x - self.x * other.z,
                self.x * other.y - self.y * other.x,
            )
        )

    def normalized(self) -> "Vector":
        n = self.length
        if n <= 1e-15:
            return Vector((0.0, 0.0, 0.0))
        return Vector((self.x / n, self.y / n, self.z / n))

    def lerp(self, other: "Vector", t: float) -> "Vector":
        return Vector(
            (
                self.x + (other.x - self.x) * t,
                self.y + (other.y - self.y) * t,
                self.z + (other.z - self.z) * t,
            )
        )

    def __getitem__(self, index: int) -> float:
        return (self.x, self.y, self.z)[index]

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Vector):
            return NotImplemented
        return all(abs(a - b) <= 1e-12 for a, b in zip(self, other))

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Vector(({self.x!r}, {self.y!r}, {self.z!r}))"


class Matrix:
    """Translation-only matrix with a ``@`` operator."""

    def __init__(self, translation=(0.0, 0.0, 0.0)) -> None:
        self.translation = Vector(translation)

    def __matmul__(self, other: Vector) -> Vector:
        return other + self.translation


class FakeVertex:
    def __init__(self, co) -> None:
        self.co = Vector(co)


class FakeTriangle:
    def __init__(self, vertices) -> None:
        self.vertices = tuple(vertices)


class FakeMesh:
    def __init__(self, verts, tris) -> None:
        self.vertices = [FakeVertex(v) for v in verts]
        self.loop_triangles = [FakeTriangle(t) for t in tris]

    def calc_loop_triangles(self) -> None:
        return None


CUBE_VERTS = (
    (-0.5, -0.5, -0.5),
    (0.5, -0.5, -0.5),
    (0.5, 0.5, -0.5),
    (-0.5, 0.5, -0.5),
    (-0.5, -0.5, 0.5),
    (0.5, -0.5, 0.5),
    (0.5, 0.5, 0.5),
    (-0.5, 0.5, 0.5),
)

CUBE_TRIS = (
    (0, 2, 1),
    (0, 3, 2),
    (4, 5, 6),
    (4, 6, 7),
    (0, 1, 5),
    (0, 5, 4),
    (3, 7, 6),
    (3, 6, 2),
    (0, 4, 7),
    (0, 7, 3),
    (1, 2, 6),
    (1, 6, 5),
)


class FakeMeshObject:
    type = "MESH"

    def __init__(self, verts=CUBE_VERTS, tris=CUBE_TRIS, translation=(0.0, 0.0, 0.0), name="Cube"):
        self.name = name
        self.matrix_world = Matrix(translation)
        self._mesh = FakeMesh(verts, tris)

    def evaluated_get(self, depsgraph):
        return self

    def to_mesh(self):
        return self._mesh

    def to_mesh_clear(self):
        return None


class FakeTimers:
    """Minimal ``bpy.app.timers``: callbacks the test can tick by hand."""

    def __init__(self) -> None:
        self.functions: list = []
        self.intervals: dict = {}

    def register(self, function, first_interval: float = 0.0, persistent: bool = False):
        if function in self.functions:
            return
        self.functions.append(function)
        self.intervals[function] = first_interval

    def unregister(self, function) -> None:
        if function in self.functions:
            self.functions.remove(function)
            self.intervals.pop(function, None)

    def is_registered(self, function) -> bool:
        return function in self.functions

    def tick(self) -> int:
        """Run every registered callback once; a ``None`` return unregisters."""

        alive = 0
        for function in list(self.functions):
            try:
                result = function()
            except Exception:  # noqa: BLE001 - mirrors Blender dropping it
                self.unregister(function)
                continue
            if result is None:
                self.unregister(function)
            else:
                alive += 1
        return alive


class FakeArea:
    def __init__(self) -> None:
        self.redraws = 0

    def tag_redraw(self) -> None:
        self.redraws += 1


class FakeContext:
    def __init__(self, scene=None, area=None, window_manager=None) -> None:
        self.scene = scene
        self.area = area
        self.window_manager = window_manager

    def evaluated_depsgraph_get(self):
        return object()


# --------------------------------------------------------------- bpy.data ---
class FakePoint:
    def __init__(self) -> None:
        self.co = (0.0, 0.0, 0.0, 1.0)


class FakePoints:
    def __init__(self) -> None:
        # A new spline already has one point, as in Blender.
        self.items: list[FakePoint] = [FakePoint()]

    def add(self, count: int) -> None:
        self.items.extend(FakePoint() for _ in range(max(0, int(count))))

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> FakePoint:
        return self.items[index]


class FakeSpline:
    def __init__(self, kind: str = "POLY") -> None:
        self.type = kind
        self.points = FakePoints()
        self.use_cyclic_u = False
        self.material_index = 0


class FakeSplines:
    def __init__(self) -> None:
        self.items: list[FakeSpline] = []

    def new(self, kind: str = "POLY") -> FakeSpline:
        spline = FakeSpline(kind)
        self.items.append(spline)
        return spline

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)


class FakeCurveData:
    """``bpy.data.curves`` entry: just enough for ``_new_curve_object``."""

    def __init__(self, name: str, type: str = "CURVE") -> None:
        self.name = name
        self.dimensions = "3D"
        self.resolution_u = 12
        self.bevel_depth = 0.0
        self.bevel_resolution = 0
        self.use_fill_caps = False
        self.splines = FakeSplines()
        self.materials: list = []
        self.users = 1


class FakeMaterialData:
    def __init__(self, name: str) -> None:
        self.name = name
        self.diffuse_color = (0.0, 0.0, 0.0, 1.0)
        self.use_nodes = False
        self.node_tree = types.SimpleNamespace(nodes=types.SimpleNamespace(get=lambda _n: None))
        self.users = 1


class FakeMeshData:
    def __init__(self, name: str) -> None:
        self.name = name
        self.verts: list = []
        self.faces: list = []
        self.materials: list = []
        self.users = 1

    def from_pydata(self, verts, edges, faces) -> None:
        self.verts = list(verts)
        self.faces = list(faces)

    def update(self) -> None:
        return None


class FakeLinked:
    """``collection.objects`` / ``collection.children``."""

    def __init__(self) -> None:
        self.items: list = []

    def link(self, item) -> None:
        self.items.append(item)

    def get(self, name: str):
        return next((item for item in self.items if item.name == name), None)

    def __iter__(self):
        return iter(list(self.items))

    def __len__(self) -> int:
        return len(self.items)


class FakeSceneCollection:
    def __init__(self, name: str = "Scene Collection") -> None:
        self.name = name
        self.children = FakeLinked()
        self.objects = FakeLinked()


class FakeCollection(FakeSceneCollection):
    def __init__(self, name: str = "Collection") -> None:
        super().__init__(name)


class FakeCurveObject:
    """Object with a curve datablock, as the visualization creates them."""

    type = "CURVE"

    def __init__(self, name: str, data=None) -> None:
        self.name = name
        self.data = data
        self.show_in_front = False
        self.location = (0.0, 0.0, 0.0)
        self.dimensions = (0.0, 0.0, 0.0)
        self._props: dict = {}

    def __setitem__(self, key, value) -> None:
        self._props[key] = value

    def __getitem__(self, key):
        return self._props[key]

    def get(self, key, default=None):
        return self._props.get(key, default)


class _Store:
    """``bpy.data.<something>``: name-keyed store with Blender's surface."""

    def __init__(self, factory) -> None:
        self._factory = factory
        self._items: dict = {}

    def get(self, name: str, default=None):
        return self._items.get(name, default)

    def new(self, name: str, *args, **kwargs):
        item = self._factory(name, *args, **kwargs)
        self._items[item.name] = item
        return item

    def remove(self, item, **kwargs) -> None:
        self._items.pop(item if isinstance(item, str) else getattr(item, "name", ""), None)

    def __iter__(self):
        return iter(list(self._items.values()))

    def __len__(self) -> int:
        return len(self._items)


def data_stores() -> types.SimpleNamespace:
    """Fresh ``bpy.data``; tests reset it to start with an empty blend."""

    return types.SimpleNamespace(
        collections=_Store(FakeCollection),
        objects=_Store(FakeCurveObject),
        curves=_Store(FakeCurveData),
        materials=_Store(FakeMaterialData),
        meshes=_Store(FakeMeshData),
    )


def make_settings(**overrides):
    """Return a settings namespace with the addon's default values."""

    from types import SimpleNamespace

    values = dict(
        source_object=None,
        unit_scale_mm=1000.0,
        slice_mode="PLANAR",
        axis="Z",
        count=3,
        spacing_mm=5.0,
        spacing_auto=False,
        offset_mm=0.0,
        centered=True,
        angle_start_deg=0.0,
        angle_end_deg=360.0,
        origin_offset_mm=(0.0, 0.0, 0.0),
        material_thickness_mm=3.0,
        material_min_bend_radius_mm=6.0,
        material_max_bend_angle_deg=120.0,
        material_min_segment_mm=0.4,
        material_kerf_mm=0.15,
        material_k_factor=0.42,
        fillet_enabled=True,
        fillet_radius_mm=4.0,
        fillet_min_turn_deg=20.0,
        fillet_arc_segments=3,
        fillet_chord_tolerance_mm=0.05,
        fillet_mode="clamp",
        fillet_check_material=True,
        cut_thin_enabled=False,
        cut_thin_min_width_mm=8.0,
        cut_thin_corner_turn_deg=20.0,
        cut_thin_max_removed_ratio=0.5,
        trim_tight_enabled=False,
        trim_tight_radius_mm=4.0,
        trim_tight_min_turn_deg=20.0,
        trim_tight_max_removed_ratio=0.5,
        trim_tight_action="trim",
        smooth_curve_enabled=True,
        smooth_curve_mode="approximate",
        smooth_curve_tension=0.4,
        smooth_curve_max_deviation_mm=0.2,
        smooth_curve_chord_tolerance_mm=0.05,
        smooth_curve_max_spacing_mm=0.0,
        smooth_curve_segments_per_span=8,
        smooth_curve_preserve_corners_deg=0.0,
        smooth_curve_inertia_smoothing=0,
        smooth_curve_inertia=0.0,
        smooth_curve_use_material_min_radius=False,
        smooth_curve_min_radius_mm=0.0,
        tube_path_enabled=False,
        tube_path_rod_radius_mm=3.0,
        tube_path_side="outer",
        tube_path_use_cross_sections=False,
        tube_path_cross_section_step_mm=5.0,
        tube_path_guide_group_tag="group_a",
        tube_path_contact_tolerance_mm=0.05,
        tube_path_tension=0.5,
        tube_path_arc_segments=8,
        simplify_enabled=True,
        simplify_tolerance_mm=0.05,
        simplify_preserve_corners_deg=70.0,
        densify_enabled=True,
        densify_max_spacing_mm=2.0,
        densify_max_angle_step_deg=12.0,
        densify_chord_tolerance_mm=0.05,
        resample_enabled=False,
        resample_spacing_mm=2.0,
        resample_adaptive=False,
        resample_min_spacing_mm=0.1,
        resample_chord_tolerance_mm=0.05,
        limit_curvature_enabled=False,
        limit_curvature_use_material=True,
        limit_curvature_min_radius_mm=6.0,
        limit_curvature_max_iterations=20,
        limit_curvature_weight=0.5,
        limit_curvature_strict=False,
        optimize_enabled=False,
        optimize_points=150,
        optimize_data_weight=20.0,
        optimize_smooth=2.0,
        optimize_use_material_min_radius=True,
        optimize_min_radius_mm=6.0,
        optimize_radius_weight=1000.0,
        optimize_max_iterations=40,
        optimize_cost_tolerance=1e-6,
        inset_enabled=False,
        inset_x_mode="OUTWARD",
        inset_y_mode="NONE",
        inset_z_mode="INWARD",
        inset_auto=True,
        inset_amount_mm=0.5,
        shrink_enabled=False,
        shrink_percent=20.0,
        shrink_mode="MIDDLE",
        shrink_smooth_iterations=2,
        contacts_enabled=False,
        contacts_gap_mm=1.0,
        contact_marker_mm=5.0,
        contacts_include_same=False,
        threads=0,
        use_background=True,
        show_all_layers=True,
        job_running=False,
        job_progress=0.0,
        job_message="",
        job_cancelling=False,
        last_contacts=0,
        build_curves=False,
        curve_radius_mm=0.15,
        check_self_intersections=True,
        revision=1,
        status="Ready",
        status_detail="",
        diagnostics_text="",
        dirty=True,
        last_slices=0,
        last_points=0,
        last_errors=0,
        last_warnings=0,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def install():
    """Install the fake modules into ``sys.modules`` (idempotent)."""

    existing = sys.modules.get("bpy")
    if existing is not None and getattr(existing, "_is_fake", False):
        return existing

    class _FakeProperty:
        """Stands in for a ``bpy.props`` definition object."""

        def __init__(self, kwargs) -> None:
            self.kwargs = kwargs

        @property
        def default(self):
            return self.kwargs.get("default", None)

        def __repr__(self) -> str:  # pragma: no cover - debug helper
            return f"_FakeProperty({self.kwargs.get('name', '')!r})"

    def _property(*_args, **kwargs):
        return _FakeProperty(kwargs)

    class Panel:
        pass

    class Operator:
        pass

    class PropertyGroup:
        pass

    class Object:
        type = "OBJECT"

    class Collection:
        pass

    class Material:
        pass

    class Curve:
        pass

    class Scene:
        pass

    types_ns = types.SimpleNamespace(
        Panel=Panel,
        Operator=Operator,
        PropertyGroup=PropertyGroup,
        Object=Object,
        Collection=Collection,
        Material=Material,
        Curve=Curve,
        Scene=Scene,
        Mesh=Object,
        NodeTree=object,
    )
    props = types.SimpleNamespace(
        FloatProperty=_property,
        IntProperty=_property,
        BoolProperty=_property,
        StringProperty=_property,
        EnumProperty=_property,
        PointerProperty=_property,
        FloatVectorProperty=_property,
        CollectionProperty=_property,
    )

    bpy = types.ModuleType("bpy")
    bpy._is_fake = True
    bpy.types = types_ns
    bpy.props = props
    bpy.app = types.SimpleNamespace(version=(4, 2, 0), timers=FakeTimers())
    bpy.utils = types.SimpleNamespace(
        register_class=lambda cls: None,
        unregister_class=lambda cls: None,
    )
    bpy.data = data_stores()

    extras = types.ModuleType("bpy_extras")
    io_utils = types.ModuleType("bpy_extras.io_utils")

    class ExportHelper:
        filepath = ""
        filename_ext = ""

    class ImportHelper:
        filepath = ""

    io_utils.ExportHelper = ExportHelper
    io_utils.ImportHelper = ImportHelper
    extras.io_utils = io_utils

    mathutils = types.ModuleType("mathutils")
    mathutils.Vector = Vector
    mathutils.Matrix = Matrix

    sys.modules["bpy"] = bpy
    sys.modules["bpy_extras"] = extras
    sys.modules["bpy_extras.io_utils"] = io_utils
    sys.modules["mathutils"] = mathutils
    return bpy


def uninstall() -> None:
    """Remove the stubs and any host modules imported against them."""

    for name in list(sys.modules):
        if name in {"bpy", "bpy_extras", "bpy_extras.io_utils", "mathutils"}:
            del sys.modules[name]
        elif name.startswith("blender_slicer.adapters.blender"):
            del sys.modules[name]
