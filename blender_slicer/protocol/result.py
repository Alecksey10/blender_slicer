"""Processing result types: geometry, metrics and diagnostics per slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .diagnostics import Diagnostic
from .shapes import ContourRole, FoldSpec
from .units import Point2
from .version import ENGINE_NAME, ENGINE_VERSION, PROTOCOL_VERSION


class ResultStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"


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
    name: str = ENGINE_NAME
    version: str = ENGINE_VERSION
    protocol_version: str = PROTOCOL_VERSION


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
