from __future__ import annotations

import traceback
from collections import defaultdict
from collections.abc import Callable
from typing import Any


class EventBus:
    """Tiny synchronous event bus.

    It is intentionally independent of bpy so the controller logic can be
    reasoned about (and tested) separately from Blender.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Callable[..., Any]) -> None:
        if handler not in self._handlers[topic]:
            self._handlers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Callable[..., Any]) -> None:
        if handler in self._handlers.get(topic, []):
            self._handlers[topic].remove(handler)

    def publish(self, topic: str, **payload: Any) -> None:
        for handler in list(self._handlers.get(topic, [])):
            try:
                handler(**payload)
            except Exception:
                # An event handler must never take down the UI.  Tracebacks still
                # go to Blender's console for debugging.
                traceback.print_exc()

    def clear(self) -> None:
        self._handlers.clear()


BUS = EventBus()

TOPIC_SETTINGS_CHANGED = "settings.changed"
TOPIC_SLICES_GENERATED = "slices.generated"
TOPIC_PROCESS_STARTED = "process.started"
TOPIC_PROCESS_COMPLETED = "process.completed"
TOPIC_PROCESS_FAILED = "process.failed"
TOPIC_RESULT_CLEARED = "result.cleared"
TOPIC_UI_REDRAW = "ui.redraw"
