"""Dependency rules of the project (checked with ``ast``, no imports needed).

The concept fixes the direction of dependencies:

    protocol  <-  spatial  <-  engine  <-  adapters/base  <-  adapters/<host>  <-  app

``protocol`` imports nothing but the standard library, the engine knows neither
a host nor a GUI, and ``bpy`` appears only in the Blender adapter.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "blender_slicer"

# Packages a layer must never import, as a prefix match.
FORBIDDEN = {
    "protocol": (
        "blender_slicer.engine",
        "blender_slicer.spatial",
        "blender_slicer.adapters",
        "blender_slicer.app",
        "blender_slicer.preview",
    ),
    "spatial": (
        "blender_slicer.engine",
        "blender_slicer.adapters",
        "blender_slicer.app",
        "blender_slicer.preview",
    ),
    "engine": (
        "blender_slicer.adapters",
        "blender_slicer.app",
        "blender_slicer.preview",
    ),
    "preview": (
        "blender_slicer.engine",
        "blender_slicer.adapters",
        "blender_slicer.app",
    ),
    "adapters": ("blender_slicer.app",),
    "app": (),
}

HOST_TOOLKITS = ("bpy", "bpy_extras", "mathutils")


def _python_files() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _package_parts(path: Path) -> list[str]:
    return list(path.relative_to(ROOT).with_suffix("").parts[:-1])


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _package_parts(path)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
            else:
                base = []
            module = ".".join(base + ([node.module] if node.module else []))
            if module:
                found.append(module)
    return found


class DependencyTests(unittest.TestCase):
    def test_no_layer_imports_a_forbidden_layer(self):
        violations: list[str] = []
        for path in _python_files():
            parts = path.relative_to(PACKAGE).parts
            if len(parts) < 2:
                continue
            layer = parts[0]
            forbidden = FORBIDDEN.get(layer, ())
            if not forbidden:
                continue
            for module in _imports(path):
                if module.startswith(forbidden):
                    violations.append(f"{path.relative_to(ROOT)}: {module}")
        self.assertEqual(violations, [])

    def test_bpy_is_confined_to_the_blender_adapter(self):
        violations: list[str] = []
        for path in _python_files():
            parts = path.relative_to(PACKAGE).parts
            if parts[:2] == ("adapters", "blender"):
                continue
            for module in _imports(path):
                if module.split(".")[0] in HOST_TOOLKITS:
                    violations.append(f"{path.relative_to(ROOT)}: {module}")
        self.assertEqual(violations, [])

    def test_protocol_is_host_free(self):
        for path in _python_files():
            parts = path.relative_to(PACKAGE).parts
            if parts[0] != "protocol":
                continue
            for module in _imports(path):
                self.assertFalse(
                    module.split(".")[0] in HOST_TOOLKITS,
                    f"{path.relative_to(ROOT)} imports {module}",
                )

    def test_legacy_shim_packages_are_gone(self):
        self.assertFalse((PACKAGE / "core").exists(), "blender_slicer/core is a legacy shim")
        self.assertFalse((PACKAGE / "host.py").exists(), "blender_slicer/host.py is a legacy shim")
        self.assertFalse(
            (PACKAGE / "adapters" / "base" / "frames.py").exists(),
            "frames moved to blender_slicer/spatial",
        )


if __name__ == "__main__":
    unittest.main()
