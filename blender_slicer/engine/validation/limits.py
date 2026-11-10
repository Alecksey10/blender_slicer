"""Request-level limits and protocol checks."""

from __future__ import annotations

import math

from ...protocol.diagnostics import Diagnostic, ErrorCode, Severity, diagnostic
from ...protocol.material import MaterialProfile
from ...protocol.request import ProcessingRequest
from ...protocol.version import PROTOCOL_VERSION, SUPPORTED_SCHEMA_VERSIONS, UNITS


def check_envelope(request: ProcessingRequest) -> list[Diagnostic]:
    """Protocol version, schema version and units of measure."""

    out: list[Diagnostic] = []
    if request.protocol_version.split(".")[0] != PROTOCOL_VERSION.split(".")[0]:
        out.append(
            diagnostic(
                Severity.ERROR,
                ErrorCode.E_PROTOCOL_VERSION,
                f"Unsupported protocol version {request.protocol_version}",
            )
        )
    if request.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        out.append(
            diagnostic(
                Severity.ERROR,
                ErrorCode.E_SCHEMA,
                f"Unsupported schema version {request.schema_version}",
            )
        )
    if request.units != UNITS:
        out.append(
            diagnostic(Severity.ERROR, ErrorCode.E_UNITS, f"Only mm is supported, got {request.units!r}")
        )
    return out


def check_material(material: MaterialProfile) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for name, value in (
        ("thickness_mm", material.thickness_mm),
        ("min_bend_radius_mm", material.min_bend_radius_mm),
        ("max_bend_angle_deg", material.max_bend_angle_deg),
        ("min_segment_mm", material.min_segment_mm),
    ):
        if not math.isfinite(float(value)) or float(value) <= 0:
            out.append(
                diagnostic(
                    Severity.ERROR,
                    ErrorCode.E_PARAM,
                    f"Material {name} must be a positive finite number",
                    details={"value": value},
                )
            )
    if not (0.0 <= material.k_factor <= 1.0):
        out.append(
            diagnostic(Severity.ERROR, ErrorCode.E_PARAM, "Material k_factor must be in [0, 1]")
        )
    if material.kerf_mm < 0:
        out.append(
            diagnostic(Severity.ERROR, ErrorCode.E_PARAM, "Material kerf_mm cannot be negative")
        )
    return out


def check_limits(request: ProcessingRequest, counts: dict[str, int]) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    limits = request.limits
    if len(request.slices) > limits.max_slices:
        out.append(
            diagnostic(Severity.ERROR, ErrorCode.E_LIMIT_EXCEEDED, "Too many slices", details=counts)
        )
    if len(request.operations) > limits.max_operations:
        out.append(
            diagnostic(
                Severity.ERROR, ErrorCode.E_LIMIT_EXCEEDED, "Too many operations", details=counts
            )
        )
    if counts.get("points", 0) > limits.max_total_points:
        out.append(
            diagnostic(
                Severity.ERROR, ErrorCode.E_LIMIT_EXCEEDED, "Too many points", details=counts
            )
        )
    return out
