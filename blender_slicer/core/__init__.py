"""Host-independent slicing engine.

Everything under ``blender_slicer.core`` is pure Python (standard library
only).  It can be imported, tested and embedded without Blender.
"""

from __future__ import annotations

from .engine import Engine, describe_methods
from .errors import ConfigError, DomainError, SlicerError
from .frames import CoordinateFrame, make_frame
from .json_codec import (
    dumps_request,
    dumps_result,
    loads_request,
    request_from_dict,
    request_to_dict,
    result_to_dict,
)
from .registry import MethodRegistry, validate_params
from .types import (
    Contour,
    ContourMetrics,
    ContourResult,
    ContourRole,
    Diagnostic,
    EngineInfo,
    ErrorCode,
    FailurePolicy,
    FoldSpec,
    Limits,
    MaterialProfile,
    OperationSpec,
    Point2,
    ProcessingRequest,
    ProcessingResult,
    RequestOptions,
    ResultMetrics,
    ResultStatus,
    Severity,
    Slice,
    SliceMetrics,
    SliceResult,
    TargetSelector,
    ValidationReport,
)

__all__ = [
    "Engine",
    "MethodRegistry",
    "validate_params",
    "describe_methods",
    "SlicerError",
    "DomainError",
    "ConfigError",
    "CoordinateFrame",
    "make_frame",
    "Point2",
    "ContourRole",
    "Severity",
    "ErrorCode",
    "ResultStatus",
    "FailurePolicy",
    "FoldSpec",
    "Contour",
    "Slice",
    "MaterialProfile",
    "TargetSelector",
    "OperationSpec",
    "RequestOptions",
    "Limits",
    "ProcessingRequest",
    "Diagnostic",
    "ContourMetrics",
    "SliceMetrics",
    "ResultMetrics",
    "ContourResult",
    "SliceResult",
    "EngineInfo",
    "ProcessingResult",
    "ValidationReport",
    "request_to_dict",
    "request_from_dict",
    "result_to_dict",
    "dumps_request",
    "loads_request",
    "dumps_result",
]
