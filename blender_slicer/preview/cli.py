"""Preview CLI: render a saved result to SVG without Blender.

    python -m blender_slicer.preview.cli result.json --out preview.svg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..protocol.json_codec import loads_result
from .svg import render_result_svg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slicer-preview", description=__doc__)
    parser.add_argument("result", help="result JSON produced by the engine or an export")
    parser.add_argument("--out", default="preview.svg", help="output SVG path")
    args = parser.parse_args(argv)

    payload = loads_result(Path(args.result).read_bytes())
    path = Path(args.out)
    path.write_text(render_result_svg(payload), encoding="utf-8")
    print(f"{path}: {len(payload.slices)} slice(s), status {payload.status.value}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
