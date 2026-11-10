"""Slice geometry: contours, folds and slices.

``Contour`` is a closed or open polyline in the local 2D frame of a slice.
``Slice.offset_mm`` is a signed cut clearance in millimetres attached by the
adapter to one slice: positive grows the contour outward, negative shrinks it.
The engine never decides *which* slices are outward; it only applies the value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .units import Point2


class ContourRole(str, Enum):
    CUT = "cut"
    SCORE = "score"
    GUIDE = "guide"


@dataclass
class FoldSpec:
    angle_deg: float
    direction: str = "up"
    radius_mm: float | None = None


@dataclass
class Contour:
    id: str
    role: ContourRole
    closed: bool
    points: list[Point2]
    parent_id: str | None = None
    tags: list[str] = field(default_factory=list)
    segment_tags: list[str] | None = None
    fold: FoldSpec | None = None

    def clone(self) -> "Contour":
        return Contour(
            id=self.id,
            role=self.role,
            closed=self.closed,
            points=list(self.points),
            parent_id=self.parent_id,
            tags=list(self.tags),
            segment_tags=list(self.segment_tags) if self.segment_tags else None,
            fold=FoldSpec(**vars(self.fold)) if self.fold else None,
        )


@dataclass
class Slice:
    id: str
    index: int
    contours: list[Contour]
    frame_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    offset_mm: float = 0.0

    def clone(self) -> "Slice":
        return Slice(
            id=self.id,
            index=self.index,
            contours=[c.clone() for c in self.contours],
            frame_id=self.frame_id,
            metadata=dict(self.metadata),
            offset_mm=self.offset_mm,
        )

    def contour(self, contour_id: str) -> Contour | None:
        for c in self.contours:
            if c.id == contour_id:
                return c
        return None

    @property
    def point_count(self) -> int:
        return sum(len(c.points) for c in self.contours)
