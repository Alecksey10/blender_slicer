"""Composition-root view of the application controller.

The implementation lives in :mod:`blender_slicer.adapters.base.controller` so a
host adapter can reach it without importing the composition root (which would
invert the dependency direction).  ``AppController`` is the "logic keeper" from
the concept: hosts provide a ``HostAdapter``, the controller owns the flow.
"""

from __future__ import annotations

from ..adapters.base.controller import (
    AppController,
    ProcessSummary,
    format_diagnostic,
    summarize,
)

__all__ = ["AppController", "ProcessSummary", "format_diagnostic", "summarize"]
