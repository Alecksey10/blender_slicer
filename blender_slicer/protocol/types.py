"""Umbrella module for the contract types.

The actual definitions live in small focused modules (``units``, ``shapes``,
``material``, ``operations``, ``request``, ``result``, ``diagnostics``).  This
module keeps the historical ``from ..protocol.types import ...`` imports working
and gives newcomers one place to see the whole contract.
"""

from __future__ import annotations

from .diagnostics import Diagnostic, ErrorCode, Severity, ValidationReport, diagnostic
from .material import MaterialProfile
from .operations import (
    FailurePolicy,
    Limits,
    OperationSpec,
    RequestOptions,
    TargetSelector,
)
from .request import ProcessingRequest
from .result import (
    ContourMetrics,
    ContourResult,
    EngineInfo,
    ProcessingResult,
    ResultMetrics,
    ResultStatus,
    SliceMetrics,
    SliceResult,
)
from .shapes import Contour, ContourRole, FoldSpec, Slice
from .units import Point2, Vec3
from .version import (
    ENGINE_NAME,
    ENGINE_VERSION,
    PROTOCOL_VERSION,
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    UNITS,
)

__all__ = [
    "Contour",
    "ContourMetrics",
    "ContourResult",
    "ContourRole",
    "Diagnostic",
    "EngineInfo",
    "ErrorCode",
    "FailurePolicy",
    "FoldSpec",
    "Limits",
    "MaterialProfile",
    "OperationSpec",
    "Point2",
    "ProcessingRequest",
    "ProcessingResult",
    "RequestOptions",
    "ResultMetrics",
    "ResultStatus",
    "Severity",
    "Slice",
    "SliceMetrics",
    "SliceResult",
    "TargetSelector",
    "ValidationReport",
    "Vec3",
    "diagnostic",
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "PROTOCOL_VERSION",
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "UNITS",
]
