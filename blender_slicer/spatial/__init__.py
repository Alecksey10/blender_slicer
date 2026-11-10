"""Spatial package: coordinate frames, 3D vectors and cross-slice analysis.

Pure Python on purpose: this is the Coordinate Manager from the concept, shared
by every adapter and testable without Blender.
"""

from __future__ import annotations

from .contacts import ContactPoint, find_contacts
from .frames import CoordinateFrame, FrameStore, make_frame
from .vectors import (
    v3_add,
    v3_cross,
    v3_dist,
    v3_dot,
    v3_length,
    v3_lerp,
    v3_mul,
    v3_sub,
    v3_unit,
)

__all__ = [
    "CoordinateFrame",
    "FrameStore",
    "make_frame",
    "ContactPoint",
    "find_contacts",
    "v3_add",
    "v3_sub",
    "v3_mul",
    "v3_dot",
    "v3_cross",
    "v3_dist",
    "v3_length",
    "v3_lerp",
    "v3_unit",
]
