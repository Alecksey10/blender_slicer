from __future__ import annotations

import bpy

from ...adapters.base.plan import SlicePlan
from ...spatial.contacts import ContactPoint
from ...spatial.frames import CoordinateFrame
from ...protocol.shapes import Slice
from . import slicing, visualization


class BlenderHost:
    """Blender implementation of the HostAdapter contract.

    It is created per call because both the ``context`` and the settings object
    are Blender-specific and short-lived.
    """

    name = "blender"

    def __init__(self, context, settings) -> None:
        self.context = context
        self.settings = settings

    def slice_mesh(self, plan: SlicePlan) -> tuple[list[Slice], dict[str, CoordinateFrame]]:
        return slicing.generate_slices(self.context, self.settings, plan)

    def _curves_enabled(self) -> bool:
        return bool(getattr(self.settings, "build_curves", True))

    def show_layers(self, layers) -> None:
        if not self._curves_enabled():
            # Only curves are optional; contact markers are diagnostics and
            # must survive this call.
            visualization.clear_layers(self.context)
            return
        visualization.build_layers(self.context, layers, self.settings)

    def show_contacts(self, contacts: list[ContactPoint]) -> None:
        # Contacts used to be drawn only when result curves were enabled, which
        # made Find Contacts appear to do nothing at all.
        visualization.build_contacts(self.context, contacts, self.settings)

    def clear_visuals(self) -> None:
        visualization.clear_collection(self.context)
