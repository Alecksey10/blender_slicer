"""Client of the logical engine, with optional multi-threaded processing.

The concept says the client owns the calls and the state transitions; the engine
only processes.  This client is that boundary: it takes a request, decides how
many workers the host can use and delegates to ``Engine.process_parallel``.
A host without threads passes ``workers=1`` and the very same request runs
serially.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...engine.facade import Engine
from ...engine.parallel import available_workers, resolve_workers
from ...protocol.result import ProcessingResult


@dataclass
class EngineClient:
    engine: Engine = field(default_factory=Engine)
    workers: int | None = None  # None/0 = automatic, 1 = serial

    @property
    def worker_count(self) -> int:
        return resolve_workers(self.workers)

    @property
    def parallel(self) -> bool:
        return self.worker_count > 1

    def process(self, request, reporter=None) -> ProcessingResult:
        """Process a request; ``reporter`` gives the host progress and cancel."""

        return self.engine.process_parallel(
            request, workers=self.workers, reporter=reporter
        )

    def validate(self, request):
        return self.engine.validate(request)

    def descriptor(self):
        return self.engine.descriptor()

    @classmethod
    def from_settings(cls, settings, **kwargs) -> "EngineClient":
        """``threads = 0`` means auto, ``1`` means "do not use threads"."""

        threads = int(getattr(settings, "threads", 0) or 0)
        return cls(workers=None if threads <= 0 else threads, **kwargs)


def worker_summary() -> str:
    count = available_workers()
    return f"{count} worker(s)" if count > 1 else "serial"
