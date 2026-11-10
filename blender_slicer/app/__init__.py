"""Application package (composition root).

``controller`` — host-agnostic orchestration used by every adapter;
``main``       — standalone CLI composition root.
"""

from __future__ import annotations

from .controller import AppController, ProcessSummary, format_diagnostic, summarize

__all__ = ["AppController", "ProcessSummary", "format_diagnostic", "summarize"]
