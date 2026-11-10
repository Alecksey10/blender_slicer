"""Slicer protocol: the data contract shared by engine, preview, adapters and app.

This package is intentionally free of Blender (``bpy``) and engine
dependencies; only the standard library is used.

Module map
----------
``units``        Point2/Vec3 and numeric predicates
``shapes``       Contour, Slice, FoldSpec, per-slice cut offset
``material``     MaterialProfile (thickness, bend radius, kerf)
``operations``   OperationSpec, TargetSelector, FailurePolicy, Limits
``request``      ProcessingRequest
``result``       ProcessingResult, SliceResult, metrics
``diagnostics``  Diagnostic, ErrorCode, ValidationReport
``version``      protocol / schema / engine versions
``geometry``     dependency-free 2D geometry kernel
``offset``       polygon/polyline offset (cut clearance)
``descriptor``   declarative method parameter descriptions
``json_codec``   JSON boundary
"""

from __future__ import annotations

from .descriptor import Choice, Condition, MethodDescriptor, ParamSpec
from .diagnostics import Diagnostic, ErrorCode, Severity, ValidationReport, diagnostic
from .errors import ConfigError, DomainError, SlicerError
from .geometry import bend_allowance_mm, collapse_collinear
from .json_codec import (
    canonical_json,
    dumps_request,
    dumps_result,
    loads_request,
    loads_result,
    request_from_dict,
    request_to_dict,
    result_from_dict,
    result_to_dict,
)
from .material import MaterialProfile
from .offset import offset_polyline
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
    # versioning
    "PROTOCOL_VERSION",
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "UNITS",
    # shapes
    "Contour",
    "ContourRole",
    "FoldSpec",
    "Slice",
    "Point2",
    "Vec3",
    # material and operations
    "MaterialProfile",
    "OperationSpec",
    "TargetSelector",
    "FailurePolicy",
    "RequestOptions",
    "Limits",
    # request / result
    "ProcessingRequest",
    "ProcessingResult",
    "SliceResult",
    "ContourResult",
    "EngineInfo",
    "ResultStatus",
    "ResultMetrics",
    "SliceMetrics",
    "ContourMetrics",
    # diagnostics
    "Diagnostic",
    "ErrorCode",
    "Severity",
    "ValidationReport",
    "diagnostic",
    "ConfigError",
    "DomainError",
    "SlicerError",
    # descriptors
    "Choice",
    "Condition",
    "MethodDescriptor",
    "ParamSpec",
    # geometry helpers
    "bend_allowance_mm",
    "collapse_collinear",
    "offset_polyline",
    # codec
    "canonical_json",
    "request_to_dict",
    "request_from_dict",
    "dumps_request",
    "loads_request",
    "result_to_dict",
    "result_from_dict",
    "dumps_result",
    "loads_result",
]
