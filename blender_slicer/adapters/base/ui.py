"""GUI configuration model shared by every GUI adapter.

A host does not hard-code the interface: it receives sections and fields and
renders them with its own toolkit.  The engine still owns defaults and ranges
through ``MethodDescriptor``; this module only describes *layout*.

Example::

    Section("plan", "Slice plan", (Field("count"), Field("spacing_mm")), open=True)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Condition:
    prop: str
    op: str = "eq"  # eq | ne | truthy
    value: Any = None

    def evaluate(self, settings: Any) -> bool:
        current = getattr(settings, self.prop, None)
        if self.op == "eq":
            return current == self.value
        if self.op == "ne":
            return current != self.value
        if self.op == "truthy":
            return bool(current) == bool(self.value)
        return True


@dataclass(frozen=True)
class Field:
    prop: str
    label: str | None = None
    visible_when: tuple[Condition, ...] = ()


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    fields: tuple[Field, ...]
    open: bool = False
    #: Sections sharing a group are rendered inside one collapsible panel, so a
    #: host shows the primary controls and hides the alternatives behind it.
    group: str = ""


@dataclass(frozen=True)
class GuiSchema:
    sections: tuple[Section, ...] = field(default_factory=tuple)

    def visible_fields(self, settings: Any) -> list[Field]:
        out: list[Field] = []
        for section in self.sections:
            for item in section.fields:
                if all(condition.evaluate(settings) for condition in item.visible_when):
                    out.append(item)
        return out


class GuiBuilder(Protocol):
    """What a host toolkit must provide to render a schema."""

    def row(self): ...

    def prop(self, target: Any, name: str, text: str | None = None) -> None: ...

    def label(self, text: str) -> None: ...


def condition(spec: dict[str, Any]) -> Condition:
    """Translate the compact schema dict into a Condition."""

    if "equals" in spec:
        return Condition(spec["prop"], "eq", spec["equals"])
    if "not_equals" in spec:
        return Condition(spec["prop"], "ne", spec["not_equals"])
    if "truthy" in spec:
        return Condition(spec["prop"], "truthy", bool(spec["truthy"]))
    raise ValueError(f"unknown visibility condition: {spec!r}")


def make_field(
    prop: str,
    label: str | None = None,
    visible: dict[str, Any] | list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> Field:
    if visible is None:
        specs: list[dict[str, Any]] = []
    elif isinstance(visible, dict):
        specs = [visible]
    else:
        specs = list(visible)
    return Field(prop, label, tuple(condition(spec) for spec in specs))
