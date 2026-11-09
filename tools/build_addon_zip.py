#!/usr/bin/env python3
"""Build an installable Blender add-on archive from ``blender_slicer/``.

The archive has the package folder at its root (``blender_slicer/...``), which
is what Blender's "Install from Disk" expects.  Only ``*.py`` files are packed,
so ``__pycache__`` and the test suite never end up in the add-on.

    python3 tools/build_addon_zip.py [--out dist]
"""

from __future__ import annotations

import argparse
import importlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "blender_slicer"


def read_version() -> str:
    sys.path.insert(0, str(ROOT))
    try:
        module = importlib.import_module(PACKAGE)
        return ".".join(str(part) for part in module.bl_info["version"])
    finally:
        sys.path.remove(str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dist", help="output directory (default: dist)")
    args = parser.parse_args()

    version = read_version()
    target_dir = ROOT / args.out
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{PACKAGE}-{version}.zip"

    files = sorted(
        path
        for path in (ROOT / PACKAGE).rglob("*.py")
        if "__pycache__" not in path.parts
    )
    if not files:
        raise SystemExit(f"no python files found in {ROOT / PACKAGE}")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())

    print(f"{target.relative_to(ROOT)}  ({len(files)} files, {target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
