"""Processing operations, target selectors and request-level options."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .shapes import ContourRole


class FailurePolicy(str, Enum):
    """What the engine does when a slice cannot be processed."""

    STRICT = "strict"
    PER_SLICE = "per_slice"
    BEST_EFFORT = "best_effort"


@dataclass
class TargetSelector:
    """Restricts an operation to a subset of slices/contours."""

    slice_ids: tuple[str, ...] | None = None
    slice_indices: tuple[int, ...] | None = None
    contour_ids: tuple[str, ...] | None = None
    roles: tuple[ContourRole, ...] | None = None
    tags_all: tuple[str, ...] = ()
    tags_any: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not any(
            (
                self.slice_ids,
                self.slice_indices,
                self.contour_ids,
                self.roles,
                self.tags_all,
                self.tags_any,
            )
        )


@dataclass
class OperationSpec:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    target: TargetSelector | None = None
    label: str | None = None


@dataclass
class RequestOptions:
    return_unchanged: bool = True
    include_metrics: bool = True
    include_point_tags: bool = False
    normalize_winding: bool = True
    strict_unknown_fields: bool = True
    max_source_deviation_mm: float | None = None


@dataclass
class Limits:
    max_slices: int = 256
    max_points_per_contour: int = 200_000
    max_total_points: int = 1_000_000
    max_operations: int = 32
