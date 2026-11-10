"""Standalone composition root (no GUI, no Blender).

Processes a request file through the same engine client the Blender add-on uses
and can export the result and an SVG preview:

    python -m blender_slicer.app.main --request request.json --out result.json \
        --svg preview.svg --workers 4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..adapters.base.engine_client import EngineClient
from ..adapters.base.export import ExportManager
from ..adapters.base.layers import SliceLayer
from ..protocol.json_codec import loads_request
from .controller import summarize


def build_client(workers: int | None = None) -> EngineClient:
    return EngineClient(workers=workers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slicer-app", description=__doc__)
    parser.add_argument("--request", required=True, help="request JSON file")
    parser.add_argument("--out", help="write the result JSON here")
    parser.add_argument("--svg", help="write an SVG preview here")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="worker threads (0 = auto, 1 = serial)",
    )
    args = parser.parse_args(argv)

    request = loads_request(Path(args.request).read_bytes())
    client = build_client(None if args.workers <= 0 else args.workers)
    result = client.process(request)
    summary = summarize(result)

    print(f"status: {summary.status_text}")
    print(summary.detail_text)
    for line in summary.lines[:20]:
        print(line)

    layer = SliceLayer(
        id="standalone",
        name="Standalone request",
        slices=list(request.slices),
        frames={},
        result=result,
        source_name=str(request.metadata.get("source", "")),
        axis=str(request.metadata.get("axis", "")),
        mode=str(request.metadata.get("mode", "")),
    )
    export = ExportManager()
    if args.out:
        export.export(args.out, [layer], result)
        print(f"written: {args.out}")
    if args.svg:
        export.export(args.svg, [layer], result)
        print(f"written: {args.svg}")
    return 0 if result.status.value != "error" else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
