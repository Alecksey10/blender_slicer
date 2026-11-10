"""Application controller: the "logic keeper" of the concept.

It wires a HostAdapter, the LayerStore and the EngineClient together and owns
the state transitions (generate -> process -> visualise -> analyse contacts).
It lives in the adapter base layer because every host uses it; ``app.controller``
re-exports it as part of the composition root.  It never imports ``bpy``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...protocol.diagnostics import Severity
from ...protocol.request import ProcessingRequest
from ...protocol.result import ProcessingResult, ResultStatus
from ...spatial.contacts import ContactPoint, find_contacts
from .engine_client import EngineClient
from .events import (
    BUS,
    TOPIC_PROCESS_COMPLETED,
    TOPIC_PROCESS_FAILED,
    TOPIC_PROCESS_STARTED,
    TOPIC_RESULT_CLEARED,
    TOPIC_SLICES_GENERATED,
    EventBus,
)
from .host import HostAdapter
from .layers import LayerStore, SliceLayer
from .plan import SlicePlan


@dataclass
class ProcessSummary:
    """Host-independent digest of a processing result, for GUI status lines."""

    result: ProcessingResult
    errors: int = 0
    warnings: int = 0
    lines: list[str] = field(default_factory=list)

    @property
    def status_text(self) -> str:
        metrics = self.result.metrics
        return f"{self.result.status.value.upper()} - {metrics.slices_ok}/{metrics.slices_in} slices"

    @property
    def detail_text(self) -> str:
        metrics = self.result.metrics
        return (
            f"points {metrics.points_in} -> {metrics.points_out}, "
            f"errors {self.errors}, warnings {self.warnings}"
        )


def format_diagnostic(item) -> str:
    where = []
    if item.slice_id:
        where.append(item.slice_id)
    if item.contour_id:
        where.append(item.contour_id)
    prefix = f"[{item.severity.value.upper()}] {item.code.value}"
    if where:
        prefix += " " + "/".join(where)
    if item.stage:
        prefix += f" ({item.stage})"
    return f"{prefix}: {item.message}"


def summarize(result: ProcessingResult) -> ProcessSummary:
    lines: list[str] = []
    errors = 0
    warnings = 0
    for entry in result.diagnostics:
        lines.append(format_diagnostic(entry))
        errors += entry.severity == Severity.ERROR
        warnings += entry.severity == Severity.WARNING
    for slice_result in result.slices:
        for entry in slice_result.diagnostics:
            lines.append(format_diagnostic(entry))
            errors += entry.severity == Severity.ERROR
            warnings += entry.severity == Severity.WARNING
    return ProcessSummary(result=result, errors=errors, warnings=warnings, lines=lines)


class AppController:
    def __init__(
        self,
        host: HostAdapter,
        store: LayerStore,
        client: EngineClient | None = None,
        events: EventBus | None = None,
    ) -> None:
        self.host = host
        self.store = store
        self.client = client or EngineClient()
        self.events = events if events is not None else BUS

    # ------------------------------------------------------------------ slices
    def generate(self, plan: SlicePlan, revision: int = 0) -> SliceLayer:
        slices, frames = self.host.slice_mesh(plan)
        for index, slice_ in enumerate(slices):
            # The adapter owns the distribution; the engine only applies it.
            slice_.metadata["shrink_ratio"] = plan.shrink_ratio_for(index, len(slices))
        layer = SliceLayer(
            id=plan.layer_id(),
            name=plan.layer_name(),
            slices=list(slices),
            frames=dict(frames),
            axis=plan.axis,
            mode=plan.mode,
            source_name=plan.model,
            revision=revision,
        )
        self.store.put(layer)
        self.host.show_layers(self.store.visible_layers())
        self.events.publish(TOPIC_SLICES_GENERATED, layer=layer, slices=layer.slices, frames=layer.frames)
        return layer

    # ---------------------------------------------------------------- process
    def process(self, request: ProcessingRequest, layer: SliceLayer | None = None) -> ProcessSummary:
        self.events.publish(TOPIC_PROCESS_STARTED, request=request, layer=layer)
        result = self.client.process(request)
        if layer is not None:
            layer.result = result
        summary = summarize(result)
        topic = (
            TOPIC_PROCESS_FAILED
            if result.status == ResultStatus.ERROR
            else TOPIC_PROCESS_COMPLETED
        )
        self.host.show_layers(self.store.visible_layers())
        self.events.publish(topic, result=result, layer=layer, summary=summary)
        return summary

    # ---------------------------------------------------------------- contacts
    def find_contacts(
        self, gap_mm: float = 1.0, include_same_layer: bool = False
    ) -> list[ContactPoint]:
        contacts = find_contacts(
            self.store.visible_layers(),
            gap_mm=gap_mm,
            include_same_layer=include_same_layer,
        )
        self.host.show_contacts(contacts)
        return contacts

    # ----------------------------------------------------------------- layers
    def set_layer_visible(self, layer_id: str, visible: bool | None = None) -> bool:
        layer = self.store.get(layer_id)
        if layer is None:
            return False
        layer.visible = (not layer.visible) if visible is None else bool(visible)
        self.host.show_layers(self.store.visible_layers())
        return layer.visible

    def remove_layer(self, layer_id: str) -> bool:
        removed = self.store.remove(layer_id)
        if removed:
            self.host.show_layers(self.store.visible_layers())
        return removed

    def clear(self) -> None:
        self.store.clear()
        self.host.clear_visuals()
        self.events.publish(TOPIC_RESULT_CLEARED)
