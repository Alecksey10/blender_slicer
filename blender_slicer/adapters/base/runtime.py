"""Runtime state owned by an adapter: layers, frames, results and flags.

The engine is stateless; all memory of the session lives here.  One store can
hold several layers (cutting passes, iterations, other models), which is what
lets the viewport show them together.  The ``slices``/``frames``/``result``
properties proxy the active layer so simple hosts keep a simple API.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...protocol.shapes import Slice
from ...spatial.frames import CoordinateFrame, FrameStore
from .layers import LayerStore, SliceLayer


@dataclass
class RuntimeState:
    layers: LayerStore = field(default_factory=LayerStore)
    collection_name: str = "Slice Engine"
    dirty: bool = True

    # ------------------------------------------------------------ active layer
    @property
    def active(self) -> SliceLayer | None:
        return self.layers.active

    def layer(self, layer_id: str | None) -> SliceLayer | None:
        return self.layers.get(layer_id)

    def _ensure_active(self) -> SliceLayer:
        layer = self.layers.active
        if layer is None:
            layer = self.layers.put(SliceLayer(id="default", name="Default layer"))
        return layer

    def add_slices(
        self,
        slices: list[Slice],
        frames: dict[str, CoordinateFrame] | None = None,
        *,
        layer_id: str = "default",
        name: str | None = None,
        axis: str = "",
        mode: str = "",
        source_name: str = "",
        revision: int = -1,
    ) -> SliceLayer:
        layer = SliceLayer(
            id=layer_id,
            name=name or layer_id,
            slices=list(slices),
            frames=dict(frames or {}),
            axis=axis,
            mode=mode,
            source_name=source_name,
            revision=revision,
        )
        return self.layers.put(layer)

    # ---------------------------------------------------------------- proxies
    @property
    def slices(self) -> list[Slice]:
        layer = self.layers.active
        return layer.slices if layer is not None else []

    @slices.setter
    def slices(self, value: list[Slice]) -> None:
        self._ensure_active().slices = list(value)

    @property
    def frames(self) -> dict[str, CoordinateFrame]:
        layer = self.layers.active
        return layer.frames if layer is not None else {}

    @frames.setter
    def frames(self, value: dict[str, CoordinateFrame]) -> None:
        self._ensure_active().frames = dict(value)

    @property
    def result(self):
        layer = self.layers.active
        return layer.result if layer is not None else None

    @result.setter
    def result(self, value) -> None:
        self._ensure_active().result = value

    @property
    def revision(self) -> int:
        layer = self.layers.active
        return layer.revision if layer is not None else -1

    @revision.setter
    def revision(self, value: int) -> None:
        self._ensure_active().revision = int(value)

    @property
    def source_name(self) -> str:
        layer = self.layers.active
        return layer.source_name if layer is not None else ""

    @source_name.setter
    def source_name(self, value: str) -> None:
        self._ensure_active().source_name = str(value)

    # ------------------------------------------------------------------ state
    @property
    def has_slices(self) -> bool:
        return any(layer.slices for layer in self.layers)

    @property
    def frame_store(self) -> FrameStore:
        """All frames of all layers, for hosts that need one lookup table."""

        store = FrameStore()
        for layer in self.layers:
            store.update(layer.frames)
        return store

    def clear(self) -> None:
        self.layers.clear()
        self.dirty = True


RUNTIME = RuntimeState()
