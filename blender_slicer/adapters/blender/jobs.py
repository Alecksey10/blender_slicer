"""Background processing for the Blender add-on.

Blender's Python interface lives in the main thread: a long engine call freezes
the whole application, the viewport and the N-panel included.  A job therefore
splits in two halves:

* the *worker* thread runs the engine with a
  :class:`~blender_slicer.engine.progress.ProgressReporter`; its callbacks only
  write into a lock-protected record, so the worker never touches ``bpy``;
* a ``bpy.app.timers`` pump runs on the main thread, copies that record into
  scene properties (progress bar, message) and, when the worker is done, applies
  the result - building curves is a main-thread operation.

Because the worker polls the same ``threading.Event`` the Cancel button sets,
cancelling stops the request between slices and inside the optimizer instead of
waiting for the whole batch.
"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable

import bpy

from ...engine.progress import ProgressReporter
from ...protocol.errors import Cancelled

TICK_SECONDS = 0.1

#: Shown in the panel while ``ChunkedRunner`` draws curves.
BUILD_MESSAGE = "building curves"

#: A tick longer than this is logged: it is what a "frozen" window feels like.
SLOW_TICK_SECONDS = 0.25


class JobRunner:
    """One job at a time: start, observe, cancel, apply."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._active = False
        self._done = False
        self._progress = 0.0
        self._message = ""
        self._payload: Any = None
        self._error: str | None = None
        self._cancelled = False
        self._kind = ""
        self._apply: Callable[[Any], None] | None = None
        self._finish: Callable[..., None] | None = None

    # ------------------------------------------------------------------ state
    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._active,
                "progress": self._progress,
                "message": self._message,
                "kind": self._kind,
            }

    # ------------------------------------------------------------------ start
    def start(
        self,
        kind: str,
        work: Callable[[ProgressReporter], Any],
        *,
        apply: Callable[[Any], None] | None = None,
        finish: Callable[..., None] | None = None,
    ) -> None:
        with self._lock:
            if self._active:
                raise RuntimeError("a background job is already running")
            self._cancel = threading.Event()
            self._active = True
            self._done = False
            self._progress = 0.0
            self._message = ""
            self._payload = None
            self._error = None
            self._cancelled = False
            self._kind = kind
            self._apply = apply
            self._finish = finish
            cancel = self._cancel

        reporter = ProgressReporter(
            callback=self._on_progress, cancel_check=cancel.is_set
        )
        thread = threading.Thread(
            target=self._run, args=(work, reporter), name=f"slicer-{kind}", daemon=True
        )
        with self._lock:
            self._thread = thread
        thread.start()

    def cancel(self) -> bool:
        with self._lock:
            if not self._active:
                return False
            self._cancel.set()
            if not self._done:
                self._message = "cancelling..."
            return True

    # ----------------------------------------------------------------- worker
    def _on_progress(self, data: dict[str, Any]) -> None:
        with self._lock:
            fraction = data.get("fraction")
            if fraction is not None:
                value = float(fraction)
                index = data.get("slice_index")
                total = data.get("slices_total")
                if index is not None and total:
                    value = (float(index) + value) / float(total)
                self._progress = max(0.0, min(1.0, value))

            parts: list[str] = []
            if data.get("stage"):
                parts.append(str(data["stage"]))
            index = data.get("slice_index")
            total = data.get("slices_total")
            if index is not None and total:
                parts.append(f"slice {int(index) + 1}/{int(total)}")
            if data.get("message"):
                parts.append(str(data["message"]))
            if parts:
                self._message = " · ".join(parts)

    def _run(self, work: Callable[[ProgressReporter], Any], reporter: ProgressReporter) -> None:
        try:
            payload = work(reporter)
        except Cancelled:
            with self._lock:
                self._cancelled = True
        except BaseException as exc:  # noqa: BLE001 - reported to the UI
            traceback.print_exc()
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"
        else:
            with self._lock:
                self._payload = payload
        finally:
            with self._lock:
                self._done = True
                self._thread = None

    # ------------------------------------------------------------------- pump
    def pump(self) -> dict[str, Any]:
        """Main thread: apply a finished job and return the current state."""

        with self._lock:
            finished = self._done and self._active
            payload = self._payload
            error = self._error
            cancelled = self._cancelled
            apply = self._apply
            finish = self._finish
            if finished:
                self._active = False
                self._done = False
                self._payload = None
                self._error = None
                self._cancelled = False
                self._apply = None
                self._finish = None
            state = {
                "running": self._active,
                "progress": 1.0 if finished else self._progress,
                "message": self._message,
                "kind": self._kind,
            }

        if not finished:
            return state

        if error is None and not cancelled and apply is not None:
            try:
                apply(payload)
            except Exception as exc:  # noqa: BLE001 - keep the UI alive
                traceback.print_exc()
                error = f"{type(exc).__name__}: {exc}"
        if finish is not None:
            try:
                finish(error=error, cancelled=cancelled)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        return state


JOBS = JobRunner()


class ChunkedRunner:
    """A main-thread task sliced into small steps (viewport rebuilding).

    The worker thread cannot create Blender objects, so applying a result is
    main-thread work; on a hundred slices that apply used to be one long freeze
    right after the progress bar disappeared.  A step function returning ``True``
    when it is done lets the pump spend a fixed time budget per tick instead, so
    the window stays alive and the progress bar keeps moving.
    """

    def __init__(self) -> None:
        self._step: Callable[[], bool] | None = None
        self._finish: Callable[[], None] | None = None
        self._progress: Callable[[], float] | None = None
        self._message = ""
        self._value = 0.0
        self.active = False

    def start(
        self,
        step: Callable[[], bool],
        *,
        finish: Callable[[], None] | None = None,
        message: str = "",
        progress: Callable[[], float] | None = None,
    ) -> bool:
        if self.active:
            return False
        self._step = step
        self._finish = finish
        self._message = message
        self._progress = progress
        self._value = 0.0
        self.active = True
        return True

    def snapshot(self) -> dict[str, Any]:
        message = self._message() if callable(self._message) else self._message
        return {
            "active": self.active,
            "progress": self._value,
            "message": message,
        }

    def advance(self, budget_seconds: float = 0.02) -> None:
        """Main thread: run steps until the step or the time budget runs out."""

        if not self.active:
            return
        deadline = time.perf_counter() + max(0.001, float(budget_seconds))
        finished = False
        while time.perf_counter() < deadline:
            try:
                finished = bool(self._step())
            except Exception:  # noqa: BLE001 - keep the UI alive
                traceback.print_exc()
                finished = True
            if finished:
                break
            if self._progress is not None:
                try:
                    self._value = float(self._progress())
                except Exception:  # noqa: BLE001
                    pass
        if not finished:
            return
        self.active = False
        self._step = None
        self._progress = None
        self._value = 1.0
        finish = self._finish
        self._finish = None
        if finish is not None:
            try:
                finish()
            except Exception:  # noqa: BLE001 - reported to the console
                traceback.print_exc()

    def cancel(self) -> bool:
        if not self.active:
            return False
        self.active = False
        self._step = None
        self._finish = None
        self._progress = None
        return True


CHUNKS = ChunkedRunner()


# --------------------------------------------------------------------- timers
def timer_available() -> bool:
    return getattr(getattr(bpy, "app", None), "timers", None) is not None


def _context():
    return getattr(bpy, "context", None)


def _settings():
    context = _context()
    scene = getattr(context, "scene", None)
    return getattr(scene, "slicer_settings", None)


def _tag_redraw() -> None:
    context = _context()
    window_manager = getattr(context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()):
            if getattr(area, "type", "") in {"VIEW_3D", "PROPERTIES"}:
                try:
                    area.tag_redraw()
                except Exception:  # noqa: BLE001 - area may be gone
                    pass


def _sync_settings(settings, state: dict[str, Any]) -> None:
    if settings is None:
        return
    try:
        settings.job_running = bool(state["running"])
        settings.job_progress = float(state["progress"])
        settings.job_message = str(state["message"])
        if not state["running"]:
            settings.job_cancelling = False
    except AttributeError:  # settings from an older session
        pass


def _combined_state(state: dict[str, Any]) -> dict[str, Any]:
    """One state for the panel: a running job outranks a viewport rebuild."""

    chunk = CHUNKS.snapshot()
    if not chunk["active"]:
        return state
    if state["running"]:
        return {**state, "running": True}
    return {
        "running": True,
        "progress": float(chunk["progress"]),
        "message": str(chunk["message"]),
        "kind": "build",
    }


_slow_reported = 0.0


def _report_slow_tick(took: float, pumped: float, state: dict[str, Any]) -> None:
    """Log a tick that took long enough to be visible, once a second."""

    global _slow_reported
    now = time.perf_counter()
    if took < SLOW_TICK_SECONDS or now - _slow_reported < 1.0:
        return
    _slow_reported = now
    chunk = CHUNKS.snapshot()
    print(
        "[slicer] slow UI tick: %.2f s (job %.2f s, build %.2f s)"
        " progress %.0f%% %s"
        % (
            took,
            pumped,
            took - pumped,
            state["progress"] * 100.0,
            "running" if state["running"] else "idle",
        ),
        f"| chunk={'active' if chunk['active'] else 'off'}",
    )


def _tick():
    started = time.perf_counter()
    state = JOBS.pump()
    pumped = time.perf_counter() - started
    CHUNKS.advance()
    state = _combined_state(state)
    _sync_settings(_settings(), state)
    _tag_redraw()
    if state["running"]:
        _report_slow_tick(time.perf_counter() - started, pumped, state)
    return TICK_SECONDS if state["running"] else None


def _ensure_timer() -> None:
    timers = bpy.app.timers
    if not timers.is_registered(_tick):
        timers.register(_tick, first_interval=TICK_SECONDS, persistent=True)


def start(
    kind: str,
    work: Callable[[ProgressReporter], Any],
    *,
    apply: Callable[[Any], None] | None = None,
    finish: Callable[..., None] | None = None,
) -> bool:
    """Start a job; returns False when the host has no timer support."""

    if not timer_available():
        return False
    JOBS.start(kind, work, apply=apply, finish=finish)
    _ensure_timer()
    return True


def start_chunked(
    step: Callable[[], bool],
    *,
    finish: Callable[[], None] | None = None,
    message: str = "",
    progress: Callable[[], float] | None = None,
) -> bool:
    """Queue main-thread work for the pump; ``False`` when there is no timer."""

    if not timer_available():
        return False
    if not CHUNKS.start(step, finish=finish, message=message, progress=progress):
        return False
    _ensure_timer()
    return True


def shutdown() -> None:
    """Cancel the running job and drop the timer (add-on unload)."""

    JOBS.cancel()
    CHUNKS.cancel()
    timers = getattr(getattr(bpy, "app", None), "timers", None)
    if timers is None:
        return
    try:
        if timers.is_registered(_tick):
            timers.unregister(_tick)
    except (RuntimeError, ValueError):
        pass
