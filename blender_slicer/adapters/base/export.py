"""Export Manager: write results and previews in host-independent formats.

Exporters are registered by file suffix, so a new format is one function and
one ``register`` call.  JSON keeps the full contract; SVG is the visual check
that all visible layers fit together.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from ...protocol.result import ProcessingResult
from ...protocol.json_codec import result_to_dict
from ...preview.svg import render_layers_svg
from ...spatial.contacts import ContactPoint
from .layers import SliceLayer

Writer = Callable[[Path, list[SliceLayer], ProcessingResult | None, Iterable[ContactPoint]], None]


def _write_json(
    path: Path,
    layers: list[SliceLayer],
    result: ProcessingResult | None,
    contacts: Iterable[ContactPoint],
) -> None:
    payload = {
        "format": "blender_slicer.export",
        "version": 1,
        "layers": [
            {
                "id": layer.id,
                "name": layer.name,
                "axis": layer.axis,
                "mode": layer.mode,
                "source": layer.source_name,
                "status": layer.status,
                "color": list(layer.color),
                "result": result_to_dict(layer.result) if layer.result else None,
            }
            for layer in layers
        ],
        "active_result": result_to_dict(result) if result is not None else None,
        "contacts": [contact.as_dict() for contact in contacts],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_svg(
    path: Path,
    layers: list[SliceLayer],
    result: ProcessingResult | None,
    contacts: Iterable[ContactPoint],
) -> None:
    path.write_text(render_layers_svg(layers), encoding="utf-8")


class ExportManager:
    def __init__(self) -> None:
        self._writers: dict[str, Writer] = {"json": _write_json, "svg": _write_svg}

    def register(self, suffix: str, writer: Writer) -> None:
        self._writers[suffix.lower().lstrip(".")] = writer

    def formats(self) -> tuple[str, ...]:
        return tuple(sorted(self._writers))

    def export(
        self,
        path: str | Path,
        layers: Iterable[SliceLayer],
        result: ProcessingResult | None = None,
        contacts: Iterable[ContactPoint] = (),
    ) -> Path:
        target = Path(path)
        suffix = target.suffix.lower().lstrip(".")
        writer = self._writers.get(suffix)
        if writer is None:
            raise ValueError(
                f"Unsupported export format {suffix!r}; available: {', '.join(self.formats())}"
            )
        layer_list = [layer for layer in layers]
        if not layer_list:
            raise ValueError("Nothing to export: no layers")
        target.parent.mkdir(parents=True, exist_ok=True)
        writer(target, layer_list, result, contacts)
        return target
