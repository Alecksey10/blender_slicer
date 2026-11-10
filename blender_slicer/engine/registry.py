from __future__ import annotations

import math

from ..protocol.descriptor import MethodDescriptor, ParamSpec
from ..protocol.errors import DomainError
from .methods import (
    BendCheckMethod,
    DensifyMethod,
    FilletMethod,
    LimitCurvatureMethod,
    Method,
    ResampleMethod,
    SimplifyMethod,
    SmoothMethod,
)
from ..protocol.types import ErrorCode


INTERNAL_DESCRIPTORS = (
    MethodDescriptor(
        name="normalize",
        version="1.0",
        title="Normalize",
        description="Built-in stage: duplicates, closure, nesting and winding.",
        scope="slice",
        internal=True,
    ),
    MethodDescriptor(
        name="validate",
        version="1.0",
        title="Validate",
        description="Built-in final check of geometry and limits.",
        scope="slice",
        internal=True,
    ),
)


class MethodRegistry:
    def __init__(self) -> None:
        self._methods: dict[str, Method] = {}

    def register(self, method: Method) -> None:
        name = method.descriptor.name
        if name in self._methods:
            raise ValueError(f"Method {name!r} is already registered")
        self._methods[name] = method

    def get(self, name: str) -> Method | None:
        return self._methods.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._methods))

    def descriptors(self) -> tuple[MethodDescriptor, ...]:
        return tuple(self._methods[n].descriptor for n in self.names())

    def all_descriptors(self) -> tuple[MethodDescriptor, ...]:
        return INTERNAL_DESCRIPTORS + self.descriptors()

    @classmethod
    def builtins(cls) -> "MethodRegistry":
        registry = cls()
        for method in (
            FilletMethod(),
            SmoothMethod(),
            SimplifyMethod(),
            DensifyMethod(),
            ResampleMethod(),
            LimitCurvatureMethod(),
            BendCheckMethod(),
        ):
            registry.register(method)
        return registry


def validate_params(
    descriptor: MethodDescriptor, params: dict | None
) -> dict:
    """Return params with defaults, validating types and ranges.

    Deliberately small and dependency-free instead of pydantic/jsonschema.
    """
    given = dict(params or {})
    known = {p.name: p for p in descriptor.params}
    unknown = set(given) - set(known)
    if unknown:
        raise DomainError(
            ErrorCode.E_PARAM,
            f"{descriptor.name}: unknown parameter(s): {', '.join(sorted(unknown))}",
            details={"method": descriptor.name, "unknown": sorted(unknown)},
        )
    result: dict = {}
    for name, spec in known.items():
        if name not in given:
            if spec.required and spec.default is None:
                raise DomainError(
                    ErrorCode.E_PARAM,
                    f"{descriptor.name}.{name} is required",
                    details={"method": descriptor.name, "param": name},
                )
            result[name] = spec.default
            continue
        value = given[name]
        result[name] = _coerce(descriptor.name, spec, value)
    return result


def _coerce(method: str, spec: ParamSpec, value):
    try:
        if spec.type == "bool":
            if not isinstance(value, bool):
                raise TypeError("expected bool")
            return value
        if spec.type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("expected int")
            _check_range(method, spec, float(value))
            return value
        if spec.type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("expected number")
            f = float(value)
            if not math.isfinite(f):
                raise ValueError("expected finite number")
            _check_range(method, spec, f)
            return f
        if spec.type == "string":
            if not isinstance(value, str):
                raise TypeError("expected string")
            return value
        if spec.type == "enum":
            if not isinstance(value, str):
                raise TypeError("expected string")
            allowed = {c.value for c in spec.choices}
            if allowed and value not in allowed:
                raise ValueError(f"expected one of {sorted(allowed)}")
            return value
        if spec.type == "point_list":
            if not isinstance(value, (list, tuple)):
                raise TypeError("expected list of [x, y]")
            return value
        return value
    except (TypeError, ValueError) as exc:
        raise DomainError(
            ErrorCode.E_PARAM,
            f"{method}.{spec.name}: {exc}",
            details={"method": method, "param": spec.name, "value": repr(value)},
        ) from exc


def _check_range(method: str, spec: ParamSpec, value: float) -> None:
    if spec.min is not None and value < spec.min - 1e-12:
        raise ValueError(f"must be >= {spec.min}")
    if spec.max is not None and value > spec.max + 1e-12:
        raise ValueError(f"must be <= {spec.max}")
