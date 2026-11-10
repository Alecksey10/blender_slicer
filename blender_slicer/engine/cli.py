"""Command line interface of the logical engine.

The engine has no host and no GUI; this CLI is the smallest way to inspect and
run it:

    python -m blender_slicer.engine.cli describe
    python -m blender_slicer.engine.cli validate request.json
    python -m blender_slicer.engine.cli process request.json --out result.json --workers 4
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..protocol.json_codec import dumps_result, loads_request, request_to_dict, result_to_dict
from .facade import Engine


def _read_request(path: str):
    return loads_request(Path(path).read_bytes())


def cmd_describe(args: argparse.Namespace) -> int:
    engine = Engine()
    payload = engine.descriptor_json(indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    request = _read_request(args.request)
    report = Engine().validate(request)
    print(json.dumps({"ok": report.ok, "counts": report.counts}, ensure_ascii=False))
    for item in report.diagnostics:
        print(f"{item.severity.value.upper():7} {item.code.value}: {item.message}")
    return 0 if report.ok else 1


def cmd_process(args: argparse.Namespace) -> int:
    request = _read_request(args.request)
    engine = Engine()
    result = engine.process_parallel(request, workers=args.workers)
    text = dumps_result(result)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"{args.out}: {result.status.value}, {len(result.slices)} slice(s)")
    else:
        print(text)
    if args.dump_request:
        Path(args.dump_request).write_text(
            json.dumps(request_to_dict(request), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return 0 if result.status.value != "error" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slicer-engine", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    describe = subparsers.add_parser("describe", help="print the engine descriptor as JSON")
    describe.add_argument("--out", help="write the descriptor to this file")
    describe.set_defaults(func=cmd_describe)

    validate = subparsers.add_parser("validate", help="validate a request file")
    validate.add_argument("request", help="request JSON")
    validate.set_defaults(func=cmd_validate)

    process = subparsers.add_parser("process", help="process a request file")
    process.add_argument("request", help="request JSON")
    process.add_argument("--out", help="write the result JSON here")
    process.add_argument("--dump-request", help="also save the parsed request")
    process.add_argument(
        "--workers",
        type=int,
        default=0,
        help="worker threads for independent slices (0 = auto, 1 = serial)",
    )
    process.set_defaults(func=cmd_process)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
