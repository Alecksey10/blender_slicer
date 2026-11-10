from __future__ import annotations

_REGISTERED = False


def register() -> None:
    global _REGISTERED
    if _REGISTERED:
        return

    import bpy

    if tuple(bpy.app.version[:2]) < (4, 0):
        raise RuntimeError(
            "Slice Engine requires Blender 4.0 or newer, "
            f"found {' '.join(str(v) for v in bpy.app.version[:2])}"
        )

    from . import adapter, operators, panels, properties

    properties.register()
    operators.register()
    panels.register()
    adapter.subscribe_events()
    _REGISTERED = True


def unregister() -> None:
    global _REGISTERED
    if not _REGISTERED:
        return

    from . import adapter, operators, panels, properties
    from blender_slicer.adapters.base.runtime import RUNTIME

    adapter.unsubscribe_events()
    panels.unregister()
    operators.unregister()
    properties.unregister()
    RUNTIME.clear()
    _REGISTERED = False
