"""Blender addon entry point.

The addon intentionally avoids importing ``bpy`` at module import time.  This
keeps ``blender_slicer.protocol`` importable in a normal Python interpreter for
unit tests.  Blender's ``bpy`` is imported lazily by ``register()``.
"""
from __future__ import annotations

bl_info = {
    "name": "Slice Engine",
    "author": "Blender Slicer",
    "version": (0, 3, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Slice",
    "description": "Slice meshes into bendable 2D contours with cut offsets, contacts and a host-independent engine",
    "category": "Object",
}


def register() -> None:
    from .adapters.blender import register as register_host
    register_host()


def unregister() -> None:
    from .adapters.blender import unregister as unregister_host
    unregister_host()


if __name__ == "__main__":
    register()
