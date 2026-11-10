from __future__ import annotations

import math
from collections import defaultdict

import bpy
from mathutils import Vector

from ...protocol.errors import ConfigError
from ...spatial.frames import CoordinateFrame, make_frame
from ...protocol.types import Contour, ContourRole, Slice
from ...adapters.base.plan import SlicePlan


def axis_vector(name: str) -> Vector:
    if name == "X":
        return Vector((1.0, 0.0, 0.0))
    if name == "Y":
        return Vector((0.0, 1.0, 0.0))
    return Vector((0.0, 0.0, 1.0))


def default_u_hint(axis: Vector) -> Vector:
    # Pick the global axis least aligned with the slice normal.
    if abs(axis.x) < 0.9:
        return Vector((1.0, 0.0, 0.0))
    return Vector((0.0, 1.0, 0.0))


def world_triangles(context, obj) -> tuple[list[Vector], list[tuple[int, int, int]]]:
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    if mesh is None:
        raise ConfigError("Could not evaluate the source mesh")
    try:
        mesh.calc_loop_triangles()
        matrix = obj.matrix_world
        verts = [matrix @ v.co for v in mesh.vertices]
        tris = [tuple(t.vertices) for t in mesh.loop_triangles]
    finally:
        eval_obj.to_mesh_clear()
    if not verts or not tris:
        raise ConfigError("Source mesh has no triangles")
    return verts, tris


def bbox_center(verts: list[Vector]) -> Vector:
    if not verts:
        return Vector((0.0, 0.0, 0.0))
    lo = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
    hi = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
    return (lo + hi) * 0.5


def _plane_segments(
    verts: list[Vector],
    tris: list[tuple[int, int, int]],
    origin: Vector,
    normal: Vector,
    eps: float = 1e-6,
) -> list[tuple[Vector, Vector]]:
    out: list[tuple[Vector, Vector]] = []
    for ia, ib, ic in tris:
        va, vb, vc = verts[ia], verts[ib], verts[ic]
        da = normal.dot(va - origin)
        db = normal.dot(vb - origin)
        dc = normal.dot(vc - origin)
        pts: list[Vector] = []

        def add(p: Vector) -> None:
            for q in pts:
                if (q - p).length <= eps * 10:
                    return
            pts.append(p)

        for p, q, dp, dq in ((va, vb, da, db), (vb, vc, db, dc), (vc, va, dc, da)):
            if abs(dp) <= eps:
                add(p)
            if abs(dq) <= eps:
                add(q)
            if dp * dq < 0.0 and abs(dp - dq) > 1e-15:
                t = dp / (dp - dq)
                add(p.lerp(q, t))
        if len(pts) == 2:
            out.append((pts[0], pts[1]))
        # len > 2 means a coplanar triangle; its boundary is already covered by
        # neighbouring triangles, so skipping it avoids duplicate segments.
    return out


def _key(p: Vector, tol: float) -> tuple[int, int, int]:
    return (
        int(round(p.x / tol)),
        int(round(p.y / tol)),
        int(round(p.z / tol)),
    )


def chain_segments(
    segments: list[tuple[Vector, Vector]], tol: float = 1e-5
) -> list[tuple[list[Vector], bool]]:
    unique: list[tuple[Vector, Vector]] = []
    seen: set[tuple[tuple[int, int, int], tuple[int, int, int]]] = set()
    for a, b in segments:
        ka, kb = _key(a, tol), _key(b, tol)
        if ka == kb:
            continue
        pair = (ka, kb) if ka <= kb else (kb, ka)
        if pair in seen:
            continue
        seen.add(pair)
        unique.append((a, b))

    adjacency: dict[tuple[int, int, int], list[tuple[int, int]]] = defaultdict(list)
    for idx, (a, b) in enumerate(unique):
        adjacency[_key(a, tol)].append((idx, 0))
        adjacency[_key(b, tol)].append((idx, 1))

    used: set[int] = set()
    loops: list[tuple[list[Vector], bool]] = []
    for start in range(len(unique)):
        if start in used:
            continue
        a, b = unique[start]
        used.add(start)
        chain = [a, b]
        start_key = _key(a, tol)
        cur_key = _key(b, tol)
        closed = False

        while True:
            nxt = None
            for idx, endpoint in adjacency.get(cur_key, ()):
                if idx not in used:
                    nxt = (idx, endpoint)
                    break
            if nxt is None:
                break
            idx, endpoint = nxt
            used.add(idx)
            other = unique[idx][1 - endpoint]
            other_key = _key(other, tol)
            if other_key == start_key and len(chain) >= 3:
                closed = True
                break
            chain.append(other)
            cur_key = other_key

        if not closed:
            cur_key = start_key
            tail_key = _key(chain[-1], tol)
            while True:
                nxt = None
                for idx, endpoint in adjacency.get(cur_key, ()):
                    if idx not in used:
                        nxt = (idx, endpoint)
                        break
                if nxt is None:
                    break
                idx, endpoint = nxt
                used.add(idx)
                other = unique[idx][1 - endpoint]
                other_key = _key(other, tol)
                if other_key == tail_key and len(chain) >= 3:
                    closed = True
                    break
                chain.insert(0, other)
                cur_key = other_key

        if closed and len(chain) > 1 and _key(chain[0], tol) == _key(chain[-1], tol):
            chain.pop()
        if len(chain) >= (3 if closed else 2):
            loops.append((chain, closed))
    return loops


def _plan(
    plan: SlicePlan, center: Vector
) -> list[tuple[int, Vector, Vector, Vector, dict]]:
    """Return (index, origin, normal, u_hint, metadata) for each plane."""
    scale = max(1e-9, float(plan.unit_scale_mm))
    axis = axis_vector(plan.axis).normalized()
    mode = "RADIAL" if plan.mode == "radial" else "PLANAR"
    planes: list[tuple[int, Vector, Vector, Vector, dict]] = []
    count = max(1, int(plan.count))

    if mode == "RADIAL":
        u_hint = default_u_hint(axis).normalized()
        v_hint = axis.cross(u_hint).normalized()
        start = float(plan.angle_start_deg)
        end = float(plan.angle_end_deg)
        span = end - start
        if abs(span) < 1e-6:
            span = 360.0
        full = abs(span) >= 360.0 - 1e-6
        step = span / count if full else (span / (count - 1) if count > 1 else 0.0)
        for i in range(count):
            angle = math.radians(start + i * step)
            radial = (u_hint * math.cos(angle) + v_hint * math.sin(angle)).normalized()
            normal = axis.cross(radial).normalized()
            origin = center
            planes.append(
                (
                    i,
                    origin,
                    normal,
                    radial,
                    {"slice_mode": "radial", "angle_deg": math.degrees(angle)},
                )
            )
        return planes

    spacing_bu = float(plan.spacing_mm) / scale
    offset_bu = float(plan.offset_mm) / scale
    if plan.centered:
        start = -(count - 1) * spacing_bu * 0.5 + offset_bu
    else:
        start = offset_bu
    u_hint = default_u_hint(axis).normalized()
    for i in range(count):
        t = start + i * spacing_bu
        origin = center + axis * t
        offset_mm = (t + (count - 1) * spacing_bu * 0.5 if plan.centered else t) * scale
        planes.append(
            (
                i,
                origin,
                axis,
                u_hint,
                {"slice_mode": "planar", "offset_mm": offset_mm},
            )
        )
    return planes


def generate_slices(
    context, settings, plan: SlicePlan | None = None
) -> tuple[list[Slice], dict[str, CoordinateFrame]]:
    obj = settings.source_object
    if obj is None or obj.type != "MESH":
        raise ConfigError("Select a mesh object as the slice source")
    plan = plan or SlicePlan.from_settings(settings)
    scale = float(plan.unit_scale_mm)
    if scale <= 0:
        raise ConfigError("Unit scale must be positive")

    verts, tris = world_triangles(context, obj)
    center = bbox_center(verts) + Vector(plan.origin_offset_mm) / scale
    planes = _plan(plan, center)
    cut_offset_mm = plan.cut_offset_for(plan.axis)

    slices: list[Slice] = []
    frames: dict[str, CoordinateFrame] = {}
    for index, origin, normal, u_hint, metadata in planes:
        frame_id = f"f{index:03d}"
        frame = make_frame(
            (normal.x, normal.y, normal.z),
            (u_hint.x, u_hint.y, u_hint.z),
            (origin.x, origin.y, origin.z),
            scale,
            frame_id,
        )
        frames[frame_id] = frame
        segments = _plane_segments(verts, tris, origin, normal)
        loops = chain_segments(segments)
        contours: list[Contour] = []
        for j, (points, closed) in enumerate(loops):
            pts2d = [frame.to_2d((p.x, p.y, p.z)) for p in points]
            if closed and len(pts2d) < 3:
                continue
            if not closed and len(pts2d) < 2:
                continue
            contours.append(
                Contour(
                    id=f"s{index:03d}.c{j}",
                    role=ContourRole.CUT,
                    closed=closed,
                    points=pts2d,
                )
            )
        slices.append(
            Slice(
                id=f"s{index:03d}",
                index=index,
                contours=contours,
                frame_id=frame_id,
                metadata={**metadata, "cut_offset_mm": cut_offset_mm},
                offset_mm=cut_offset_mm,
            )
        )
    return slices, frames
