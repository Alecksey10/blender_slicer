"""Visualization contract for adapters.

The adapter decides how curves are drawn (Blender curve objects, Unreal splines,
Qt painter).  This module only carries the data and the style, so the
controller can ask for a redraw without knowing the toolkit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...spatial.contacts import ContactPoint
from .layers import SliceLayer


@dataclass(frozen=True)
class VisualStyle:
    curve_radius_mm: float = 0.15
    show_contacts: bool = True
    contact_radius_mm: float = 0.7
    show_markers: bool = True


class Visualizer(Protocol):
    def show_layers(self, layers: list[SliceLayer], style: VisualStyle) -> None: ...

    def show_contacts(self, contacts: list[ContactPoint], style: VisualStyle) -> None: ...

    def clear(self) -> None: ...
