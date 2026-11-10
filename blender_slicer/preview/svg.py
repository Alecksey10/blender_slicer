"""Render slice geometry to SVG.

Two entry points:

``render_result_svg(result)``      a processing result on its own;
``render_layers_svg(layers)``      every visible layer in one picture, which is
                                   how vertical and horizontal passes are
                                   checked together.

Coordinates are already millimetres in the slice plane; the renderer flips the
Y axis for the screen and computes one bounding box for all layers.
"""

from __future__ import annotations

from dataclasses import replace
from html import escape
from typing import Iterable

from ..protocol.result import ProcessingResult
from ..protocol.shapes import Slice

Number = float | int


def _fmt(value: Number) -> str:
    return f"{float(value):.4f}"


def _contour_path(points: list[tuple[float, float]], closed: bool, scale: float, ox: float, oy: float) -> str:
    if len(points) < 2:
        return ""
    parts = [f"M {_fmt(ox + points[0][0] * scale)} {_fmt(oy - points[0][1] * scale)}"]
    for x, y in points[1:]:
        parts.append(f"L {_fmt(ox + x * scale)} {_fmt(oy - y * scale)}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


def _collect(points: list[tuple[float, float]], out: list[tuple[float, float]]) -> None:
    out.extend(points)


def _bounds(slices: list[Slice]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for slice_ in slices:
        for contour in slice_.contours:
            for x, y in contour.points:
                xs.append(x)
                ys.append(y)
    if not xs:
        return 0.0, 0.0, 1.0, 1.0
    return min(xs), min(ys), max(xs), max(ys)


def _svg(
    groups: list[tuple[str, tuple[float, float, float], list[Slice]]],
    *,
    padding_mm: float = 2.0,
    background: str = "#ffffff",
) -> str:
    all_slices = [slice_ for _name, _color, slices in groups for slice_ in slices]
    min_x, min_y, max_x, max_y = _bounds(all_slices)
    width = max(1.0, max_x - min_x + padding_mm * 2.0)
    height = max(1.0, max_y - min_y + padding_mm * 2.0)
    scale = 1.0
    ox = -min_x + padding_mm
    oy = max_y + padding_mm

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_fmt(width)} {_fmt(height)}" '
            f'width="{_fmt(width)}mm" height="{_fmt(height)}mm">'
        ),
        f'<rect width="100%" height="100%" fill="{escape(background)}"/>',
    ]
    legend_y = padding_mm + 2.0
    for name, color, slices in groups:
        stroke = "#{:02x}{:02x}{:02x}".format(
            *(max(0, min(255, int(round(c * 255)))) for c in color)
        )
        parts.append(f'<g id="{escape(name)}" fill="none" stroke="{stroke}" stroke-width="0.3">')
        for slice_ in slices:
            for contour in slice_.contours:
                path = _contour_path(contour.points, contour.closed, scale, ox, oy)
                if path:
                    parts.append(f'<path d="{path}"/>')
        parts.append("</g>")
        parts.append(
            f'<text x="{_fmt(padding_mm)}" y="{_fmt(legend_y)}" font-size="1.6" '
            f'font-family="sans-serif" fill="{stroke}">{escape(name)}</text>'
        )
        legend_y += 3.0
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_result_svg(
    result: ProcessingResult,
    *,
    name: str = "result",
    color: tuple[float, float, float] = (0.12, 0.47, 0.71),
    padding_mm: float = 2.0,
    background: str = "#ffffff",
) -> str:
    slices = [
        Slice(
            id=slice_result.slice_id,
            index=slice_result.index,
            contours=[
                replace(contour, points=list(contour.points))
                for contour in slice_result.contours
            ],
            frame_id=slice_result.frame_id,
        )
        for slice_result in result.slices
    ]
    return _svg([(name, color, slices)], padding_mm=padding_mm, background=background)


def render_layers_svg(
    layers: Iterable,
    *,
    padding_mm: float = 2.0,
    background: str = "#ffffff",
) -> str:
    groups: list[tuple[str, tuple[float, float, float], list[Slice]]] = []
    for layer in layers:
        if not getattr(layer, "visible", True):
            continue
        slices = getattr(layer, "slices", [])
        if slices:
            groups.append((getattr(layer, "name", getattr(layer, "id", "layer")), getattr(layer, "color", (0.12, 0.47, 0.71)), slices))
    return _svg(groups, padding_mm=padding_mm, background=background)
