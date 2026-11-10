"""Expand a TargetSelector into concrete contours of one slice."""

from __future__ import annotations

from ...protocol.operations import TargetSelector
from ...protocol.shapes import Contour, Slice


def select_contours(slice_: Slice, selector: TargetSelector | None) -> list[Contour]:
    if selector is None or selector.is_empty():
        return list(slice_.contours)
    if selector.slice_ids is not None and slice_.id not in selector.slice_ids:
        return []
    if selector.slice_indices is not None and slice_.index not in selector.slice_indices:
        return []
    selected: list[Contour] = []
    for contour in slice_.contours:
        if selector.contour_ids is not None and contour.id not in selector.contour_ids:
            continue
        if selector.roles is not None and contour.role not in selector.roles:
            continue
        if selector.tags_all and not all(tag in contour.tags for tag in selector.tags_all):
            continue
        if selector.tags_any and not any(tag in contour.tags for tag in selector.tags_any):
            continue
        selected.append(contour)
    return selected
