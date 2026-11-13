from __future__ import annotations

from dataclasses import dataclass, field

from ...protocol.descriptor import MethodDescriptor
from ...protocol.types import (
    Contour,
    Diagnostic,
    ErrorCode,
    MaterialProfile,
    Severity,
    Slice,
)
from ..progress import ProgressReporter

try:  # CoordinateFrame lives in the host-adapter layer; keep it optional.
    from ..spatial.frames import CoordinateFrame  # type: ignore
except Exception:  # pragma: no cover - host may not be installed
    CoordinateFrame = None  # type: ignore[assignment]


@dataclass
class MethodContext:
    material: MaterialProfile
    stage: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    slice_id: str | None = None
    contour_id: str | None = None
    slice_offset_mm: float = 0.0
    slice_metadata: dict = field(default_factory=dict)
    #: All slices of the current request (for cross-slice / cross-frame ops).
    all_slices: list[Slice] | None = None
    #: frame_id -> CoordinateFrame, for translating between 2D slice planes.
    slice_frames: dict | None = None
    #: Live monitor of a long method; ``None`` means "run silently".
    progress: ProgressReporter | None = None
    slice_index: int = -1
    slices_total: int = 0

    def report(self, fraction: float | None = None, message: str | None = None) -> None:
        """Report progress of the current stage to the host, if it listens."""

        if self.progress is None:
            return
        self.progress.update(
            fraction=fraction,
            message=message,
            stage=self.stage,
            slice_id=self.slice_id,
            contour_id=self.contour_id,
            slice_index=self.slice_index if self.slice_index >= 0 else None,
            slices_total=self.slices_total or None,
        )

    def check_cancel(self) -> None:
        """Raise ``Cancelled`` when the host asked to stop the request."""

        if self.progress is not None:
            self.progress.check()


    def warn(
        self,
        code: ErrorCode,
        message: str,
        *,
        point_index: int | None = None,
        details: dict | None = None,
    ) -> None:
        self.diagnostics.append(
            Diagnostic(
                severity=Severity.WARNING,
                code=code,
                message=message,
                stage=self.stage,
                slice_id=self.slice_id,
                contour_id=self.contour_id,
                point_index=point_index,
                details=details or {},
            )
        )

    def info(
        self,
        code: ErrorCode,
        message: str,
        *,
        point_index: int | None = None,
        details: dict | None = None,
    ) -> None:
        self.diagnostics.append(
            Diagnostic(
                severity=Severity.INFO,
                code=code,
                message=message,
                stage=self.stage,
                slice_id=self.slice_id,
                contour_id=self.contour_id,
                point_index=point_index,
                details=details or {},
            )
        )


class Method:
    descriptor: MethodDescriptor

    def apply_contour(
        self, contour: Contour, params: dict, ctx: MethodContext
    ) -> Contour:  # pragma: no cover - interface
        raise NotImplementedError


def with_points(contour: Contour, points: list[tuple[float, float]]) -> Contour:
    out = contour.clone()
    out.points = points
    return out


def emit_warnings(ctx: MethodContext, warnings: list[dict]) -> None:
    """Turn geometry-layer warning dicts into method diagnostics.

    Geometry helpers stay host-agnostic and return plain dicts; this is the
    single place where they become ``Diagnostic`` objects, so methods do not
    repeat the same severity/point/details mapping.
    """

    for warning in warnings:
        code = warning["code"]
        kwargs = {
            "point_index": warning.get("point_index"),
            "details": warning.get("details"),
        }
        if warning.get("severity") == "info" or code == ErrorCode.I_INFO:
            ctx.info(code, warning["message"], **kwargs)
        else:
            ctx.warn(code, warning["message"], **kwargs)
