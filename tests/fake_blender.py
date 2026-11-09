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
        smooth_enabled=True,
        smooth_algorithm="chaikin",
        smooth_iterations=1,
        smooth_preserve_corners_deg=70.0,
        smooth_max_deviation_mm=0.2,
        smooth_weight=0.5,
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
    bpy.app = types.SimpleNamespace(version=(4, 2, 0))
    bpy.utils = types.SimpleNamespace(
        register_class=lambda cls: None,
        unregister_class=lambda cls: None,
    )
    bpy.data = types.SimpleNamespace(
        collections={},
        objects={},
        curves={},
        materials={},
    )

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
        elif name.startswith("blender_slicer.host"):
            del sys.modules[name]
