"""Sheet-metal bend allowance."""

from __future__ import annotations

import math


def bend_allowance_mm(
    angle_deg: float, radius_mm: float, thickness_mm: float, k_factor: float
) -> float:
    return math.radians(abs(angle_deg)) * (radius_mm + k_factor * thickness_mm)
