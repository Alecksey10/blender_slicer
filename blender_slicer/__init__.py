"""Blender addon entry point.

The addon intentionally avoids importing ``bpy`` at module import time.  This
keeps ``blender_slicer.core`` importable in a normal Python interpreter for
unit tests.  Blender's ``bpy`` is imported lazily by ``register()``.
"""

from __future__ import annotations

bl_info = {
    "name": "Slice Engine",
    "author": "Blender Slicer",
    "version": (0, 2, 1),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Slice",
    "description": "Slice meshes into bendable 2D contours with a host-independent engine",
    "category": "Object",
}


def register() -> None:
    from .host import register as register_host

    register_host()


def unregister() -> None:
    from .host import unregister as unregister_host

    unregister_host()


if __name__ == "__main__":
    register()
