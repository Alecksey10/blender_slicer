from __future__ import annotations

from dataclasses import dataclass, field

from ..core.frames import CoordinateFrame
from ..core.types import ProcessingResult, Slice


@dataclass
class RuntimeState:
    slices: list[Slice] = field(default_factory=list)
    frames: dict[str, CoordinateFrame] = field(default_factory=dict)
    result: ProcessingResult | None = None
    revision: int = -1
    source_name: str = ""
    collection_name: str = "Slice Engine"
    dirty: bool = True

    def clear(self) -> None:
        self.slices.clear()
        self.frames.clear()
        self.result = None
        self.revision = -1
        self.source_name = ""
        self.dirty = True

    @property
    def has_slices(self) -> bool:
        return bool(self.slices)


RUNTIME = RuntimeState()
