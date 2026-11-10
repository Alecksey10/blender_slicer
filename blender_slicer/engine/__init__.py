from __future__ import annotations

from .facade import Engine, describe_methods
from .registry import MethodRegistry, validate_params
from .methods import (
    BendCheckMethod, DensifyMethod, FilletMethod, LimitCurvatureMethod,
    Method, MethodContext, ResampleMethod, SimplifyMethod, SmoothMethod,
    with_points,
)
from ..protocol import (
    Contour, ContourMetrics, ContourResult, ContourRole, Diagnostic, EngineInfo,
    ErrorCode, FailurePolicy, FoldSpec, Limits, MaterialProfile, OperationSpec,
    Point2, ProcessingRequest, ProcessingResult, RequestOptions, ResultMetrics,
    ResultStatus, Severity, Slice, SliceMetrics, SliceResult, TargetSelector,
    ValidationReport, request_to_dict, request_from_dict, result_to_dict,
    dumps_request, loads_request, dumps_result,
)
from ..protocol.errors import ConfigError, DomainError, SlicerError
from ..adapters.base.frames import CoordinateFrame, make_frame

__all__ = [
    "Engine", "MethodRegistry", "validate_params", "describe_methods",
    "SlicerError", "DomainError", "ConfigError", "CoordinateFrame", "make_frame",
    "Point2", "ContourRole", "Severity", "ErrorCode", "ResultStatus",
    "FailurePolicy", "FoldSpec", "Contour", "Slice", "MaterialProfile",
    "TargetSelector", "OperationSpec", "RequestOptions", "Limits",
    "ProcessingRequest", "Diagnostic", "ContourMetrics", "SliceMetrics",
    "ResultMetrics", "ContourResult", "SliceResult", "EngineInfo",
    "ProcessingResult", "ValidationReport",
    "request_to_dict", "request_from_dict", "result_to_dict",
    "dumps_request", "loads_request", "dumps_result",
]
