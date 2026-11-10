"""Self-sufficient processing request.

The engine reads nothing but this object: material, operations, slices, limits
and options all travel inside the request, which makes it reproducible and
cacheable by the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .material import MaterialProfile
from .operations import FailurePolicy, Limits, OperationSpec, RequestOptions, TargetSelector
from .shapes import Slice
from .version import PROTOCOL_VERSION, SCHEMA_VERSION, UNITS


@dataclass
class ProcessingRequest:
    schema_version: str = SCHEMA_VERSION
    protocol_version: str = PROTOCOL_VERSION
    request_id: str = ""
    units: str = UNITS
    material: MaterialProfile = field(default_factory=MaterialProfile)
    operations: list[OperationSpec] = field(default_factory=list)
    slices: list[Slice] = field(default_factory=list)
    targets: TargetSelector = field(default_factory=TargetSelector)
    failure_policy: FailurePolicy = FailurePolicy.PER_SLICE
    options: RequestOptions = field(default_factory=RequestOptions)
    limits: Limits = field(default_factory=Limits)
    metadata: dict[str, Any] = field(default_factory=dict)
