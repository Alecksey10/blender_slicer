"""Material profile of the sheet/stock being bent."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MaterialProfile:
    id: str = "custom"
    name: str = "Custom"
    thickness_mm: float = 3.0
    min_bend_radius_mm: float = 6.0
    max_bend_angle_deg: float = 120.0
    min_segment_mm: float = 0.4
    kerf_mm: float = 0.0
    k_factor: float = 0.42
    extra: dict[str, float] = field(default_factory=dict)

    @property
    def section_radius_mm(self) -> float:
        """Radius of the material cross-section (half the thickness)."""

        return max(0.0, float(self.thickness_mm)) * 0.5

    @property
    def clearance_mm(self) -> float:
        """Minimum clearance for an outward cut: section radius plus kerf."""

        return self.section_radius_mm + max(0.0, float(self.kerf_mm))
