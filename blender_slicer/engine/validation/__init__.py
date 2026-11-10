"""Validation stages: envelope, limits, material and geometric invariants."""

from __future__ import annotations

from .invariants import SELF_INTERSECTION_LIMIT, contour_invariants, final_invariants
from .limits import check_envelope, check_limits, check_material

__all__ = [
    "SELF_INTERSECTION_LIMIT",
    "contour_invariants",
    "final_invariants",
    "check_envelope",
    "check_limits",
    "check_material",
]
