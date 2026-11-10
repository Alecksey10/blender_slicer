"""Diagnostics and validation report types.

Errors never cross the engine boundary as exceptions: they become
``Diagnostic`` entries with a stable machine-readable ``ErrorCode``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
    E_FRAME = "E_FRAME"
    E_INTERNAL = "E_INTERNAL"
    I_INFO = "I_INFO"


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
class ValidationReport:
    ok: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


def diagnostic(
    severity: Severity,
    code: ErrorCode,
    message: str,
    *,
    stage: str | None = None,
    slice_id: str | None = None,
    contour_id: str | None = None,
    point_index: int | None = None,
    details: dict[str, Any] | None = None,
) -> Diagnostic:
    """Small factory used by the engine and its validation helpers."""

    return Diagnostic(
        severity=severity,
        code=code,
        message=message,
        stage=stage,
        slice_id=slice_id,
        contour_id=contour_id,
        point_index=point_index,
        details=details or {},
    )
