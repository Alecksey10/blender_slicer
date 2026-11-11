"""Uniform, adaptive and curvature-aware point resampling."""

from __future__ import annotations

import math

from ..types import Point2
from .core import EPS, dist, v_lerp, vertex_radius


def resample(
    points: list[Point2],
    closed: bool,
    spacing_mm: float,
    *,
    adaptive: bool = False,
    min_spacing_mm: float = 0.1,
    chord_tolerance_mm: float = 0.05,
) -> list[Point2]:
    if spacing_mm <= EPS or len(points) < 2:
        return list(points)
    n = len(points)
    out: list[Point2] = [points[0]]
    seg_count = n if closed else n - 1

    radii: list[float | None] = [None] * n
    if adaptive and n >= 3:
        for i in range(n):
            if not closed and (i == 0 or i == n - 1):
                radii[i] = None
            else:
                radii[i] = vertex_radius(points[(i - 1) % n], points[i], points[(i + 1) % n])

    for i in range(seg_count):
        a = points[i]
        b = points[(i + 1) % n]
        seg_len = dist(a, b)
        if seg_len <= EPS:
            continue
        local = spacing_mm
        if adaptive:
            for k in (i, (i + 1) % n):
                r = radii[k]
                if r:
                    chord = 2.0 * math.sqrt(max(0.0, 2.0 * r * chord_tolerance_mm - chord_tolerance_mm ** 2))
                    if chord > EPS:
                        local = min(local, chord)
            local = max(min_spacing_mm, local)
        nseg = max(1, int(math.ceil(seg_len / local)))
        for j in range(1, nseg + 1):
            p = v_lerp(a, b, j / nseg)
            if not out or dist(out[-1], p) > 1e-9:
                out.append(p)
    if closed and len(out) > 1 and dist(out[0], out[-1]) <= 1e-9:
        out.pop()
    return out


def _chord_for_radius(radius: float | None, tolerance: float) -> float | None:
    if not radius or radius <= 0 or tolerance <= 0:
        return None
    return 2.0 * math.sqrt(max(0.0, 2.0 * radius * tolerance - tolerance * tolerance))


def densify(
    points: list[Point2],
    closed: bool,
    max_spacing_mm: float,
    max_angle_step_deg: float = 0.0,
    chord_tolerance_mm: float = 0.05,
) -> list[Point2]:
    n = len(points)
    if n < 2:
        return list(points)
    seg_count = n if closed else n - 1
    radii = [None] * n
    for i in range(n):
        if not closed and (i == 0 or i == n - 1):
            radii[i] = None
        else:
            radii[i] = vertex_radius(points[(i - 1) % n], points[i], points[(i + 1) % n])

    out: list[Point2] = [points[0]]
    angle_step = math.radians(max(0.0, max_angle_step_deg))
    for i in range(seg_count):
        a = points[i]
        b = points[(i + 1) % n]
        seg_len = dist(a, b)
        if seg_len <= 1e-12:
            continue
        counts = [1]
        if max_spacing_mm > 0:
            counts.append(int(math.ceil(seg_len / max_spacing_mm)))
        for k in (i, (i + 1) % n):
            r = radii[k]
            chord = _chord_for_radius(r, chord_tolerance_mm)
            if chord:
                counts.append(int(math.ceil(seg_len / chord)))
            if r and angle_step > 0:
                chord_angle = 2.0 * r * math.sin(min(math.pi, angle_step) * 0.5)
                if chord_angle > 1e-9:
                    counts.append(int(math.ceil(seg_len / chord_angle)))
        steps = max(1, min(10000, max(counts)))
        for j in range(1, steps + 1):
            p = v_lerp(a, b, j / steps)
            if not out or dist(out[-1], p) > 1e-9:
                out.append(p)
    if closed and len(out) > 1 and dist(out[0], out[-1]) <= 1e-9:
        out.pop()
    return out
