"""Declarative description of a slice plan and of cut offsets.

A ``SlicePlan`` is what the user configured: model, direction, count, spacing
and the per-axis cut offset policy.  Adapters build it from their own settings
and the controller uses it for layer identity.  It is host independent, so the
offset rules are testable without Blender.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

OFFSET_NONE = "none"
OFFSET_OUTWARD = "outward"
OFFSET_INWARD = "inward"

AXES = ("X", "Y", "Z")


@dataclass(frozen=True)
class CutOffsetPolicy:
    """Signed clearance attached to every slice of a cutting pass.

    X cuts are outward (they wrap the part), Z cuts are inward (they sit inside
    the wrap), Y is left alone by default.  The magnitude is never smaller than
    the material cross-section radius, so neighbouring parts still have room to
    be welded.
    """

    enabled: bool = False
    x_mode: str = OFFSET_OUTWARD
    y_mode: str = OFFSET_NONE
    z_mode: str = OFFSET_INWARD
    auto: bool = True
    amount_mm: float = 0.5
    thickness_mm: float = 3.0
    kerf_mm: float = 0.15

    @property
    def minimum_mm(self) -> float:
        return max(0.0, self.thickness_mm) * 0.5 + max(0.0, self.kerf_mm)

    @property
    def magnitude_mm(self) -> float:
        if self.auto:
            return self.minimum_mm
        return max(float(self.amount_mm), self.minimum_mm)

    def mode_for_axis(self, axis: str) -> str:
        axis = (axis or "Z").upper()
        if axis == "X":
            return self.x_mode
        if axis == "Y":
            return self.y_mode
        return self.z_mode

    def distance_for_axis(self, axis: str) -> float:
        if not self.enabled:
            return 0.0
        mode = self.mode_for_axis(axis)
        if mode == OFFSET_OUTWARD:
            return self.magnitude_mm
        if mode == OFFSET_INWARD:
            return -self.magnitude_mm
        return 0.0

    @classmethod
    def from_settings(cls, settings: Any) -> "CutOffsetPolicy":
        return cls(
            enabled=bool(getattr(settings, "inset_enabled", False)),
            x_mode=str(getattr(settings, "inset_x_mode", OFFSET_OUTWARD)).lower(),
            y_mode=str(getattr(settings, "inset_y_mode", OFFSET_NONE)).lower(),
            z_mode=str(getattr(settings, "inset_z_mode", OFFSET_INWARD)).lower(),
            auto=bool(getattr(settings, "inset_auto", True)),
            amount_mm=float(getattr(settings, "inset_amount_mm", 0.5)),
            thickness_mm=float(getattr(settings, "material_thickness_mm", 3.0)),
            kerf_mm=float(getattr(settings, "material_kerf_mm", 0.0)),
        )


@dataclass(frozen=True)
class SectionShrinkPolicy:
    """How much each section shrinks, and how that changes along the stack.

    Wide tubes and wires get narrower cross-sections without a hard step: the
    ratio can stay uniform or be tapered smoothly towards the middle (or the
    ends) of the pass, and the engine smooths the result afterwards.
    """

    enabled: bool = False
    percent: float = 20.0
    mode: str = "middle"  # uniform | middle | ends
    smooth_iterations: int = 2

    @property
    def target_ratio(self) -> float:
        return min(1.0, max(0.01, 1.0 - max(0.0, min(90.0, float(self.percent))) / 100.0))

    def ratio_for_index(self, index: int, count: int) -> float:
        if not self.enabled:
            return 1.0
        target = self.target_ratio
        if count <= 2 or self.mode == "uniform":
            # A single slice (or a pair with no interior) gets the plain ratio;
            # otherwise a middle taper would shrink nothing at all.
            return target
        t = min(1.0, max(0.0, index / (count - 1)))
        wave = math.sin(math.pi * t)
        if self.mode == "ends":
            wave = 1.0 - wave
        elif self.mode != "middle":
            wave = 1.0
        return 1.0 - (1.0 - target) * wave

    @classmethod
    def from_settings(cls, settings: Any) -> "SectionShrinkPolicy":
        return cls(
            enabled=bool(getattr(settings, "shrink_enabled", False)),
            percent=float(getattr(settings, "shrink_percent", 20.0)),
            mode=str(getattr(settings, "shrink_mode", "MIDDLE")).lower(),
            smooth_iterations=int(getattr(settings, "shrink_smooth_iterations", 2)),
        )


@dataclass(frozen=True)
class SlicePlan:
    model: str = ""
    mode: str = "planar"
    axis: str = "Z"
    count: int = 20
    spacing_mm: float = 5.0
    offset_mm: float = 0.0
    centered: bool = True
    angle_start_deg: float = 0.0
    angle_end_deg: float = 360.0
    origin_offset_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    unit_scale_mm: float = 1000.0
    offsets: CutOffsetPolicy = field(default_factory=CutOffsetPolicy)
    shrink: SectionShrinkPolicy = field(default_factory=SectionShrinkPolicy)

    @classmethod
    def from_settings(cls, settings: Any) -> "SlicePlan":
        source = getattr(settings, "source_object", None)
        origin = getattr(settings, "origin_offset_mm", (0.0, 0.0, 0.0))
        return cls(
            model=getattr(source, "name", "") if source else "",
            mode=str(getattr(settings, "slice_mode", "PLANAR")).lower(),
            axis=str(getattr(settings, "axis", "Z")).upper(),
            count=int(getattr(settings, "count", 20)),
            spacing_mm=float(getattr(settings, "spacing_mm", 5.0)),
            offset_mm=float(getattr(settings, "offset_mm", 0.0)),
            centered=bool(getattr(settings, "centered", True)),
            angle_start_deg=float(getattr(settings, "angle_start_deg", 0.0)),
            angle_end_deg=float(getattr(settings, "angle_end_deg", 360.0)),
            origin_offset_mm=(float(origin[0]), float(origin[1]), float(origin[2])),
            unit_scale_mm=float(getattr(settings, "unit_scale_mm", 1000.0)),
            offsets=CutOffsetPolicy.from_settings(settings),
            shrink=SectionShrinkPolicy.from_settings(settings),
        )

    def layer_id(self, prefix: str = "") -> str:
        model = (self.model or "mesh").strip()
        base = f"{model}::{self.mode}-{self.axis.lower()}"
        return f"{prefix}{base}" if prefix else base

    def layer_name(self) -> str:
        model = self.model or "Mesh"
        mode = "radial" if self.mode == "radial" else "planar"
        return f"{model} · {mode} {self.axis}"

    def cut_offset_for(self, axis: str | None = None) -> float:
        return self.offsets.distance_for_axis(axis or self.axis)

    def shrink_ratio_for(self, index: int, count: int) -> float:
        return self.shrink.ratio_for_index(index, count)
