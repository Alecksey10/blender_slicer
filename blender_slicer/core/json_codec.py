"""Dependency-free JSON codec for the core contract.

The Blender adapter uses this for debug exports and for reproducible requests.
It is deliberately explicit instead of a generic object serializer, so schema
changes are visible and testable.
"""

from __future__ import annotations

import json
from typing import Any

from .types import (
    Contour,
    ContourResult,
    ContourRole,
    Diagnostic,
    EngineInfo,
    ErrorCode,
    FailurePolicy,
    FoldSpec,
    Limits,
    MaterialProfile,
    OperationSpec,
    ProcessingRequest,
    ProcessingResult,
    RequestOptions,
    ResultMetrics,
    ResultStatus,
    Severity,
    Slice,
    SliceResult,
    TargetSelector,
)


def _fold_to_dict(fold: FoldSpec | None) -> dict | None:
    if fold is None:
        return None
    return {"angle_deg": fold.angle_deg, "direction": fold.direction, "radius_mm": fold.radius_mm}


def _fold_from_dict(data: dict | None) -> FoldSpec | None:
    if not data:
        return None
    return FoldSpec(
        angle_deg=float(data["angle_deg"]),
        direction=str(data.get("direction", "up")),
        radius_mm=float(data["radius_mm"]) if data.get("radius_mm") is not None else None,
    )


def _contour_to_dict(c: Contour) -> dict:
    return {
        "id": c.id,
        "role": c.role.value,
        "closed": c.closed,
        "points": [[p[0], p[1]] for p in c.points],
        "parent_id": c.parent_id,
        "tags": list(c.tags),
        "segment_tags": list(c.segment_tags) if c.segment_tags else None,
        "fold": _fold_to_dict(c.fold),
    }


def _contour_from_dict(data: dict) -> Contour:
    return Contour(
        id=str(data["id"]),
        role=ContourRole(data.get("role", "cut")),
        closed=bool(data["closed"]),
        points=[(float(p[0]), float(p[1])) for p in data.get("points", [])],
        parent_id=data.get("parent_id"),
        tags=list(data.get("tags") or []),
        segment_tags=list(data["segment_tags"]) if data.get("segment_tags") else None,
        fold=_fold_from_dict(data.get("fold")),
    )


def _slice_to_dict(s: Slice) -> dict:
    return {
        "id": s.id,
        "index": s.index,
        "frame_id": s.frame_id,
        "metadata": dict(s.metadata),
        "contours": [_contour_to_dict(c) for c in s.contours],
    }


def _slice_from_dict(data: dict) -> Slice:
    return Slice(
        id=str(data["id"]),
        index=int(data.get("index", 0)),
        frame_id=data.get("frame_id"),
        metadata=dict(data.get("metadata") or {}),
        contours=[_contour_from_dict(c) for c in data.get("contours", [])],
    )


def _target_to_dict(t: TargetSelector) -> dict:
    return {
        "slice_ids": list(t.slice_ids) if t.slice_ids is not None else None,
        "slice_indices": list(t.slice_indices) if t.slice_indices is not None else None,
        "contour_ids": list(t.contour_ids) if t.contour_ids is not None else None,
        "roles": [r.value for r in t.roles] if t.roles is not None else None,
        "tags_all": list(t.tags_all),
        "tags_any": list(t.tags_any),
    }


def _target_from_dict(data: dict | None) -> TargetSelector:
    data = data or {}
    roles = data.get("roles")
    return TargetSelector(
        slice_ids=tuple(data["slice_ids"]) if data.get("slice_ids") is not None else None,
        slice_indices=tuple(int(i) for i in data["slice_indices"])
        if data.get("slice_indices") is not None
        else None,
        contour_ids=tuple(data["contour_ids"]) if data.get("contour_ids") is not None else None,
        roles=tuple(ContourRole(r) for r in roles) if roles is not None else None,
        tags_all=tuple(data.get("tags_all") or ()),
        tags_any=tuple(data.get("tags_any") or ()),
    )


def _material_to_dict(m: MaterialProfile) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "thickness_mm": m.thickness_mm,
        "min_bend_radius_mm": m.min_bend_radius_mm,
        "max_bend_angle_deg": m.max_bend_angle_deg,
        "min_segment_mm": m.min_segment_mm,
        "kerf_mm": m.kerf_mm,
        "k_factor": m.k_factor,
        "extra": dict(m.extra),
    }


def _material_from_dict(data: dict) -> MaterialProfile:
    return MaterialProfile(
        id=str(data.get("id", "custom")),
        name=str(data.get("name", "Custom")),
        thickness_mm=float(data.get("thickness_mm", 3.0)),
        min_bend_radius_mm=float(data.get("min_bend_radius_mm", 6.0)),
        max_bend_angle_deg=float(data.get("max_bend_angle_deg", 120.0)),
        min_segment_mm=float(data.get("min_segment_mm", 0.4)),
        kerf_mm=float(data.get("kerf_mm", 0.0)),
        k_factor=float(data.get("k_factor", 0.42)),
        extra=dict(data.get("extra") or {}),
    )


def request_to_dict(request: ProcessingRequest) -> dict:
    return {
        "schema_version": request.schema_version,
        "protocol_version": request.protocol_version,
        "request_id": request.request_id,
        "units": request.units,
        "material": _material_to_dict(request.material),
        "operations": [
            {
                "method": op.method,
                "params": dict(op.params),
                "enabled": op.enabled,
                "target": _target_to_dict(op.target) if op.target else None,
                "label": op.label,
            }
            for op in request.operations
        ],
        "slices": [_slice_to_dict(s) for s in request.slices],
        "targets": _target_to_dict(request.targets),
        "failure_policy": request.failure_policy.value,
        "options": {
            "return_unchanged": request.options.return_unchanged,
            "include_metrics": request.options.include_metrics,
            "include_point_tags": request.options.include_point_tags,
            "normalize_winding": request.options.normalize_winding,
            "strict_unknown_fields": request.options.strict_unknown_fields,
            "max_source_deviation_mm": request.options.max_source_deviation_mm,
        },
        "limits": {
            "max_slices": request.limits.max_slices,
            "max_points_per_contour": request.limits.max_points_per_contour,
            "max_total_points": request.limits.max_total_points,
            "max_operations": request.limits.max_operations,
        },
        "metadata": dict(request.metadata),
    }


def request_from_dict(data: dict) -> ProcessingRequest:
    opts = data.get("options") or {}
    lim = data.get("limits") or {}
    return ProcessingRequest(
        schema_version=str(data.get("schema_version", "1.0")),
        protocol_version=str(data.get("protocol_version", "1.0")),
        request_id=str(data.get("request_id", "")),
        units=str(data.get("units", "mm")),
        material=_material_from_dict(data.get("material") or {}),
        operations=[
            OperationSpec(
                method=str(op["method"]),
                params=dict(op.get("params") or {}),
                enabled=bool(op.get("enabled", True)),
                target=_target_from_dict(op.get("target")) if op.get("target") else None,
                label=op.get("label"),
            )
            for op in data.get("operations", [])
        ],
        slices=[_slice_from_dict(s) for s in data.get("slices", [])],
        targets=_target_from_dict(data.get("targets")),
        failure_policy=FailurePolicy(data.get("failure_policy", "per_slice")),
        options=RequestOptions(
            return_unchanged=bool(opts.get("return_unchanged", True)),
            include_metrics=bool(opts.get("include_metrics", True)),
            include_point_tags=bool(opts.get("include_point_tags", False)),
            normalize_winding=bool(opts.get("normalize_winding", True)),
            strict_unknown_fields=bool(opts.get("strict_unknown_fields", True)),
            max_source_deviation_mm=opts.get("max_source_deviation_mm"),
        ),
        limits=Limits(
            max_slices=int(lim.get("max_slices", 256)),
            max_points_per_contour=int(lim.get("max_points_per_contour", 200_000)),
            max_total_points=int(lim.get("max_total_points", 1_000_000)),
            max_operations=int(lim.get("max_operations", 32)),
        ),
        metadata=dict(data.get("metadata") or {}),
    )


def dumps_request(request: ProcessingRequest, *, indent: int | None = 2) -> str:
    return json.dumps(request_to_dict(request), indent=indent, ensure_ascii=False)


def loads_request(payload: str | bytes) -> ProcessingRequest:
    return request_from_dict(json.loads(payload))


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _diagnostic_to_dict(d: Diagnostic) -> dict:
    return {
        "severity": d.severity.value,
        "code": d.code.value,
        "message": d.message,
        "stage": d.stage,
        "slice_id": d.slice_id,
        "contour_id": d.contour_id,
        "point_index": d.point_index,
        "details": dict(d.details),
    }


def result_to_dict(result: ProcessingResult) -> dict:
    return {
        "schema_version": result.schema_version,
        "protocol_version": result.protocol_version,
        "request_id": result.request_id,
        "status": result.status.value,
        "engine": {
            "name": result.engine.name,
            "version": result.engine.version,
            "protocol_version": result.engine.protocol_version,
        },
        "units": result.units,
        "slices": [
            {
                "slice_id": s.slice_id,
                "index": s.index,
                "frame_id": s.frame_id,
                "changed": s.changed,
                "contours": [
                    {
                        "id": c.id,
                        "source_id": c.source_id,
                        "role": c.role.value,
                        "closed": c.closed,
                        "parent_id": c.parent_id,
                        "tags": list(c.tags),
                        "fold": _fold_to_dict(c.fold),
                        "changed": c.changed,
                        "segment_tags": list(c.segment_tags) if c.segment_tags else None,
                        "points": [[p[0], p[1]] for p in c.points],
                        "metrics": {
                            "input_points": c.metrics.input_points,
                            "output_points": c.metrics.output_points,
                            "min_radius_mm": c.metrics.min_radius_mm,
                            "max_turn_deg": c.metrics.max_turn_deg,
                            "max_source_deviation_mm": c.metrics.max_source_deviation_mm,
                            "length_mm": c.metrics.length_mm,
                            "self_intersections": c.metrics.self_intersections,
                        },
                    }
                    for c in s.contours
                ],
                "metrics": {
                    "input_points": s.metrics.input_points,
                    "output_points": s.metrics.output_points,
                    "input_contours": s.metrics.input_contours,
                    "output_contours": s.metrics.output_contours,
                },
                "diagnostics": [_diagnostic_to_dict(d) for d in s.diagnostics],
            }
            for s in result.slices
        ],
        "diagnostics": [_diagnostic_to_dict(d) for d in result.diagnostics],
        "metrics": {
            "slices_in": result.metrics.slices_in,
            "slices_ok": result.metrics.slices_ok,
            "slices_failed": result.metrics.slices_failed,
            "points_in": result.metrics.points_in,
            "points_out": result.metrics.points_out,
        },
        "metadata": dict(result.metadata),
    }


def dumps_result(result: ProcessingResult, *, indent: int | None = 2) -> str:
    return json.dumps(result_to_dict(result), indent=indent, ensure_ascii=False)
