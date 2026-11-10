"""Pipeline stages: selection, policies, per-slice state and the runner."""

from __future__ import annotations

from .policies import FailureDecision, final_failure, operation_failure
from .runner import SliceRunner
from .selection import select_contours
from .state import SliceState

__all__ = [
    "SliceRunner",
    "SliceState",
    "select_contours",
    "FailureDecision",
    "operation_failure",
    "final_failure",
]
