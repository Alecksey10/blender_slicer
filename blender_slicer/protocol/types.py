"""Data types shared by the slicing engine and the Blender adapter.

The engine is intentionally independent of ``bpy``.  All coordinates that the
engine sees are 2D millimetres.  The Blender adapter owns the 3D <-> 2D frames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

Point2 = tuple[float, float]


class ContourRole(str, Enum):
    CUT = "cut"
    SCORE = "score"
    GUIDE = "guide"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ErrorCode(str, Enum):
    E_SCHEMA = "E_SCHEMA"
    E_PROTOCOL_VERSION = "E_PROTOCOL_VERSION"
    E_UNITS = "E_UNITS"
    E_NON_FINITE = "E_NON_FINITE"
    E_UNKNOWN_METHOD = "E_UNKNOWN_METHOD"
    E_PARAM = "E_PARAM"
    E_TARGET_EMPTY = "E_TARGET_EMPTY"
    E_GEOM_DEGENERATE = "E_GEOM_DEGENERATE"
    E_GEOM_OPEN = "E_GEOM_OPEN"
    E_GEOM_SELF_INTERSECTION = "E_GEOM_SELF_INTERSECTION"
    E_CONSTRAINT_UNSATISFIED = "E_CONSTRAINT_UNSATISFIED"
    E_LIMIT_EXCEEDED = "E_LIMIT_EXCEEDED"
    E_INTERNAL = "E_INTERNAL"
    I_INFO = "I_INFO"


class ResultStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"


class FailurePolicy(str, Enum):
    STRICT = "strict"
    PER_SLICE = "per_slice"
    BEST_EFFORT = "best_effort"


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

    def clone(self) -> "Slice":
        return Slice(
            id=self.id,
            index=self.index,
            contours=[c.clone() for c in self.contours],
            frame_id=self.frame_id,
            metadata=dict(self.metadata),
        )

    def contour(self, contour_id: str) -> Contour | None:
        for c in self.contours:
            if c.id == contour_id:
                return c
        return None


@dataclass
class MaterialProfile:
    id: str = "custom"
    name: str = "Custom"
    thickness_mm: float = 3.0
    min_bend_radius_mm: float = 6.0
    max_bend_angle_deg: float = 120.0
    min_segment_mm: float = 0.4
    kerf_mm: float = 0.0
    k_factor: float = 0.42
    extra: dict[str, float] = field(default_factory=dict)


@dataclass
class TargetSelector:
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


@dataclass
class ProcessingRequest:
    schema_version: str = "1.0"
    protocol_version: str = "1.0"
    request_id: str = ""
    units: str = "mm"
    material: MaterialProfile = field(default_factory=MaterialProfile)
    operations: list[OperationSpec] = field(default_factory=list)
    slices: list[Slice] = field(default_factory=list)
    targets: TargetSelector = field(default_factory=TargetSelector)
    failure_policy: FailurePolicy = FailurePolicy.PER_SLICE
    options: RequestOptions = field(default_factory=RequestOptions)
    limits: Limits = field(default_factory=Limits)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Diagnostic:
    severity: Severity
    code: ErrorCode
    message: str
    stage: str | None = None
    slice_id: str | None = None
    contour_id: str | None = None
    point_index: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContourMetrics:
    input_points: int = 0
    output_points: int = 0
    min_radius_mm: float | None = None
    max_turn_deg: float | None = None
    max_source_deviation_mm: float | None = None
    length_mm: float = 0.0
    self_intersections: int = 0


@dataclass
class SliceMetrics:
    input_points: int = 0
    output_points: int = 0
    input_contours: int = 0
    output_contours: int = 0
    stage_durations_ms: dict[str, float] = field(default_factory=dict)


@dataclass
class ResultMetrics:
    slices_in: int = 0
    slices_ok: int = 0
    slices_failed: int = 0
    points_in: int = 0
    points_out: int = 0


@dataclass
class ContourResult:
    id: str
    source_id: str | None
    role: ContourRole
    closed: bool
    points: list[Point2]
    parent_id: str | None
    tags: list[str]
    fold: FoldSpec | None
    changed: bool
    segment_tags: list[str] | None
    metrics: ContourMetrics


@dataclass
class SliceResult:
    slice_id: str
    index: int
    frame_id: str | None
    changed: bool
    contours: list[ContourResult]
    metrics: SliceMetrics
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class EngineInfo:
    name: str = "slicer-engine"
    version: str = "0.1.0"
    protocol_version: str = "1.0"


@dataclass
class ProcessingResult:
    schema_version: str
    protocol_version: str
    request_id: str
    status: ResultStatus
    engine: EngineInfo
    units: str
    slices: list[SliceResult]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    metrics: ResultMetrics = field(default_factory=ResultMetrics)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    ok: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
