"""Iterations of cutting passes, kept side by side.

One layer is one slice plan (a model + a direction): "cube / planar-Z" and
"cube / planar-X" are two layers of the same project.  Keeping them separate is
what allows the viewport (and the preview) to show the vertical and horizontal
passes at the same time, each with its own colour and its own result.

Layers live in the adapter's RuntimeState; the engine never sees them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...protocol.result import ProcessingResult
from ...protocol.shapes import Slice
from ...spatial.frames import CoordinateFrame

# Distinct, reasonably colour-blind friendly line colours.
PALETTE: tuple[tuple[float, float, float], ...] = (
    (0.12, 0.47, 0.71),
    (0.95, 0.45, 0.10),
    (0.35, 0.70, 0.30),
    (0.65, 0.30, 0.75),
    (0.90, 0.75, 0.15),
    (0.20, 0.65, 0.70),
    (0.80, 0.25, 0.40),
    (0.55, 0.55, 0.60),
)


@dataclass
class SliceLayer:
    id: str
    name: str
    slices: list[Slice] = field(default_factory=list)
    frames: dict[str, CoordinateFrame] = field(default_factory=dict)
    result: ProcessingResult | None = None
    visible: bool = True
    axis: str = ""
    mode: str = ""
    source_name: str = ""
    revision: int = -1
    color: tuple[float, float, float] = PALETTE[0]

    @property
    def slice_count(self) -> int:
        return len(self.slices)

    @property
    def point_count(self) -> int:
        return sum(slice_.point_count for slice_ in self.slices)

    @property
    def has_result(self) -> bool:
        return self.result is not None

    @property
    def status(self) -> str:
        return self.result.status.value if self.result is not None else "not processed"

    def contour_count(self) -> int:
        if self.result is not None:
            return sum(len(s.contours) for s in self.result.slices)
        return sum(len(s.contours) for s in self.slices)

    def toggle(self) -> bool:
        self.visible = not self.visible
        return self.visible


class LayerStore:
    """Ordered collection of layers with one active layer."""

    def __init__(self) -> None:
        self._layers: dict[str, SliceLayer] = {}
        self._active_id: str | None = None
        self._color_index = 0

    def put(self, layer: SliceLayer) -> SliceLayer:
        existing = self._layers.get(layer.id)
        if existing is not None:
            layer.color = existing.color
            layer.visible = existing.visible
        else:
            layer.color = self.next_color()
        self._layers[layer.id] = layer
        self._active_id = layer.id
        return layer

    def get(self, layer_id: str | None) -> SliceLayer | None:
        if not layer_id:
            return None
        return self._layers.get(layer_id)

    def remove(self, layer_id: str) -> bool:
        if layer_id not in self._layers:
            return False
        del self._layers[layer_id]
        if self._active_id == layer_id:
            self._active_id = next(iter(self._layers), None)
        return True

    def clear(self) -> None:
        self._layers.clear()
        self._active_id = None
        self._color_index = 0

    @property
    def active(self) -> SliceLayer | None:
        return self._layers.get(self._active_id) if self._active_id else None

    def set_active(self, layer_id: str) -> SliceLayer | None:
        layer = self._layers.get(layer_id)
        if layer is not None:
            self._active_id = layer_id
        return layer

    @property
    def active_id(self) -> str | None:
        return self._active_id

    def visible_layers(self) -> list[SliceLayer]:
        return [layer for layer in self._layers.values() if layer.visible]

    def all_layers(self) -> list[SliceLayer]:
        return list(self._layers.values())

    def next_color(self) -> tuple[float, float, float]:
        color = PALETTE[self._color_index % len(PALETTE)]
        self._color_index += 1
        return color

    def __iter__(self):
        return iter(self._layers.values())

    def __len__(self) -> int:
        return len(self._layers)

    def __bool__(self) -> bool:
        return bool(self._layers)

    def __contains__(self, layer_id: object) -> bool:
        return layer_id in self._layers
