"""Progress reporting and cancellation for long-running engine work.

The engine stays host-agnostic: it never knows about threads, Blender timers or
windows.  A host that wants a live monitor (and a Cancel button) passes a
:class:`ProgressReporter` to ``Engine.process``; methods that can take a while
report through :class:`~blender_slicer.engine.methods.base.MethodContext`.

A reporter is a plain frozen value, so it can be handed to a worker thread
without further locking: the *callbacks* own any shared state.

    reporter = ProgressReporter(callback=queue.put, cancel_check=stop.is_set)
    engine.process(request, reporter=reporter)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from ..protocol.errors import Cancelled


@dataclass(frozen=True)
class ProgressReporter:
    #: Receives ``{"fraction": float, "message": str, "stage": str, ...}``.
    callback: Callable[[dict[str, Any]], None] | None = None
    #: Returns True when the host wants the request to stop.
    cancel_check: Callable[[], bool] | None = None
    #: Number of slices of the whole request, for "slice 3 of 9" displays.
    slices_total: int = 0

    def derive(self, **overrides: Any) -> "ProgressReporter":
        """Same callbacks with extra context (used for the slice total)."""

        return replace(self, **overrides)

    def update(self, **payload: Any) -> None:
        if self.callback is None:
            return
        data = {"slices_total": self.slices_total}
        data.update({key: value for key, value in payload.items() if value is not None})
        try:
            self.callback(data)
        except Exception:  # noqa: BLE001 - a monitor must never break a run
            pass

    def cancelled(self) -> bool:
        if self.cancel_check is None:
            return False
        try:
            return bool(self.cancel_check())
        except Exception:  # noqa: BLE001 - treat a broken hook as "keep going"
            return False

    def check(self) -> None:
        if self.cancelled():
            raise Cancelled()
