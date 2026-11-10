from __future__ import annotations

from dataclasses import dataclass, field

from ...protocol.descriptor import MethodDescriptor
from ...protocol.types import (
    Contour,
    Diagnostic,
    ErrorCode,
    MaterialProfile,
    Severity,
)


@dataclass
class MethodContext:
    material: MaterialProfile
    stage: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    slice_id: str | None = None
    contour_id: str | None = None
    slice_offset_mm: float = 0.0
    slice_metadata: dict = field(default_factory=dict)

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
