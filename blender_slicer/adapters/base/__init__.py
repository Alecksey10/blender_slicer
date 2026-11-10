"""Adapter base package.

Host-independent building blocks shared by every GUI adapter:

``layers``        SliceLayer / LayerStore (several passes side by side)
``runtime``       RuntimeState (project memory, owned by the adapter)
``plan``          SlicePlan and the per-axis cut offset policy
``engine_client`` EngineClient (serial or multi-threaded calls)
``host``          HostAdapter protocol
``ui``            GUI schema model (sections, fields, conditions)
``visualization`` Design/Visualizer protocol
``export``        ExportManager (JSON, SVG)
``events``        EventBus and UI topics
"""

from __future__ import annotations

from .engine_client import EngineClient
from .events import BUS, EventBus
from .export import ExportManager
from .host import HostAdapter
from .layers import PALETTE, LayerStore, SliceLayer
from .plan import CutOffsetPolicy, SlicePlan
from .runtime import RUNTIME, RuntimeState
from .ui import Condition, Field, GuiSchema, Section
from .visualization import VisualStyle, Visualizer

__all__ = [
    "EngineClient",
    "EventBus",
    "BUS",
    "ExportManager",
    "HostAdapter",
    "PALETTE",
    "LayerStore",
    "SliceLayer",
    "CutOffsetPolicy",
    "SlicePlan",
    "RUNTIME",
    "RuntimeState",
    "Condition",
    "Field",
    "GuiSchema",
    "Section",
    "VisualStyle",
    "Visualizer",
]
