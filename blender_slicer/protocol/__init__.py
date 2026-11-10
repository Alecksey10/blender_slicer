"""Slicer protocol: the data contract shared by engine, preview, adapters and app.

This package is intentionally free of Blender (``bpy``) and engine
dependencies; only the standard library is used.
"""
from __future__ import annotations

from .descriptor import Choice, Condition, MethodDescriptor, ParamSpec
from .errors import ConfigError, DomainError, SlicerError
from .geometry import bend_allowance_mm
from .json_codec import (
    canonical_json,
    dumps_request,
    loads_request,
    request_from_dict,
    request_to_dict,
    result_to_dict,
    dumps_result,
)
from .types import (
    Contour, ContourMetrics, ContourResult, ContourRole, Diagnostic, EngineInfo,
    ErrorCode, FailurePolicy, FoldSpec, Limits, MaterialProfile, OperationSpec,
    Point2, ProcessingRequest, ProcessingResult, RequestOptions, ResultMetrics,
    ResultStatus, Severity, Slice, SliceMetrics, SliceResult, TargetSelector,
    ValidationReport,
)

__all__ = [
    "Choice", "Condition", "Diagnostic", "EngineInfo", "ErrorCode",
    "Contour", "ContourRole", "FoldSpec", "Limits", "MaterialProfile",
    "OperationSpec", "ProcessingRequest", "ResultMetrics", "ResultStatus",
    "Severity", "Slice", "SliceMetrics", "SliceResult", "TargetSelector",
    "ValidationReport", "Point2", "ConfigError", "DomainError", "SlicerError",
]

# Public codec helpers (JSON contract boundary).
request_to_dict = request_to_dict
request_from_dict = request_from_dict
result_to_dict = result_to_dict
dumps_request = dumps_request
loads_request = loads_request
dumps_result = dumps_result
