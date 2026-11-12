from __future__ import annotations

from .types import ErrorCode


class SlicerError(Exception):
    """Base class for all addon errors."""


class DomainError(SlicerError):
    """A predictable error that becomes a Diagnostic instead of a traceback."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        stage: str | None = None,
        slice_id: str | None = None,
        contour_id: str | None = None,
        point_index: int | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.slice_id = slice_id
        self.contour_id = contour_id
        self.point_index = point_index
        self.details = details or {}


class ConfigError(SlicerError):
    """Invalid addon/project configuration."""


class Cancelled(SlicerError):
    """The host cancelled the running request.

    Deliberately *not* a :class:`DomainError`: a cancellation is not a property
    of the geometry, so it must never become a Diagnostic or be swallowed by a
    failure policy.  It travels straight up to the caller that asked to stop.
    """
