"""Mutable state of one slice during a single engine call.

The state never escapes the call: the runner copies the input slice, mutates the
copy and builds an immutable result at the end.
"""

from __future__ import annotations

from ...protocol.shapes import Contour, Slice


class SliceState:
    __slots__ = ("slice",)

    def __init__(self, slice_: Slice) -> None:
        self.slice = slice_

    @property
    def id(self) -> str:
        return self.slice.id

    @property
    def index(self) -> int:
        return self.slice.index

    @property
    def frame_id(self) -> str | None:
        return self.slice.frame_id

    @property
    def offset_mm(self) -> float:
        return self.slice.offset_mm

    @property
    def contours(self) -> list[Contour]:
        return self.slice.contours

    def clone(self) -> Slice:
        return self.slice.clone()

    def replace(self, contour: Contour) -> None:
        for index, existing in enumerate(self.slice.contours):
            if existing.id == contour.id:
                self.slice.contours[index] = contour
                return
        self.slice.contours.append(contour)
