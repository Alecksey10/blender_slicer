"""Host Adapter contract.

Every environment (Blender, Unreal, Qt) implements these four operations; the
controller and the engine never touch ``bpy`` directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ...protocol.shapes import Slice
from ...spatial.contacts import ContactPoint
from ...spatial.frames import CoordinateFrame
from .layers import SliceLayer
from .plan import SlicePlan


@runtime_checkable
class HostAdapter(Protocol):
    name: str

    def slice_mesh(self, plan: SlicePlan) -> tuple[list[Slice], dict[str, CoordinateFrame]]:
        """Intersect the host mesh with the planned planes, in millimetres."""

    def show_layers(self, layers: list[SliceLayer]) -> None:
        """(Re)build the host visualization for every visible layer."""

    def show_contacts(self, contacts: list[ContactPoint]) -> None:
        """Draw contact points of the last contact analysis."""

    def clear_visuals(self) -> None:
        """Remove everything this adapter created in the host scene."""
