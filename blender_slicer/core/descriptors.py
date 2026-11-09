from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .types import Limits

ParamType = Literal["float", "int", "bool", "string", "enum", "point_list", "json"]


@dataclass(frozen=True)
class Choice:
    value: str
    label: str


@dataclass(frozen=True)
class Condition:
    param: str
    op: Literal["eq", "ne", "in", "gt", "lt"]
    value: Any


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: ParamType
    title: str
    description: str = ""
    default: Any = None
    required: bool = False
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    choices: tuple[Choice, ...] = ()
    multiple: bool = False
    group: str = "general"
    order: int = 0
    advanced: bool = False
    visible_when: tuple[Condition, ...] = ()
    widget: str | None = None


@dataclass(frozen=True)
class MethodDescriptor:
    name: str
    version: str
    title: str
    description: str
    scope: Literal["contour", "slice", "bundle"] = "contour"
    params: tuple[ParamSpec, ...] = ()
    stability: str = "stable"
    tags: tuple[str, ...] = ()
    internal: bool = False

    def param(self, name: str) -> ParamSpec | None:
        for p in self.params:
            if p.name == name:
                return p
        return None


@dataclass(frozen=True)
class EngineDescriptor:
    name: str
    engine_version: str
    protocol_version: str
    schema_versions: tuple[str, ...]
    limits: Limits
    methods: tuple[MethodDescriptor, ...] = field(default_factory=tuple)
