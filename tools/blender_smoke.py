#!/usr/bin/env python3
"""Headless smoke test for the Slice Engine add-on, run *inside* Blender.

Two ways to run it (Blender 4.0+):

    # 1. verify the packed archive, i.e. exactly what "Install from Disk" gets
    python3 tools/build_addon_zip.py
    blender --background --factory-startup --python-exit-code 1 \
        --python tools/blender_smoke.py -- --zip dist/blender_slicer-0.2.1.zip

    # 2. verify the working tree without touching the user add-on directory
    blender --background --factory-startup --python-exit-code 1 \
        --python tools/blender_smoke.py -- --source

Every check prints PASS/FAIL; the script ends with ``RESULT: N checks passed``
and a zero exit status, or raises (exit status 1 via ``--python-exit-code``)
after listing the failures.  Panels are not drawn headless, so the GUI itself
still needs a manual look — this script checks the data behind it (RNA
properties, operators, panels registration) and the whole slicing pipeline.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    ok = bool(condition)
    CHECKS.append((name, ok, detail))
    suffix = "" if ok or not detail else f"  [{detail}]"
    print(f"{'PASS' if ok else 'FAIL'}  {name}{suffix}", flush=True)
    return ok


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="blender_smoke.py")
    parser.add_argument("--zip", type=Path, help="add-on archive built by tools/build_addon_zip.py")
    parser.add_argument("--source", action="store_true", help="register the add-on from this repository")
    parser.add_argument("--keep", action="store_true", help="keep the installed add-on enabled afterwards")
    return parser.parse_args(argv)


def install_zip(bpy, archive: Path) -> None:
    if not archive.is_file():
        raise SystemExit(f"archive not found: {archive}")
    try:
        bpy.ops.preferences.addon_install(filepath=str(archive), overwrite=True)
    except TypeError:  # older/odd signatures without `overwrite`
        bpy.ops.preferences.addon_install(filepath=str(archive))
    bpy.ops.preferences.addon_enable(module="blender_slicer")


def register_source() -> None:
    for entry in list(sys.path):
        if Path(entry or ".").resolve() == REPO:
            return  # already importable
    sys.path.insert(0, str(REPO))


def run_checks(bpy, addon, settings_io, ui_schema, operators, panels, RUNTIME) -> None:
    check("Blender 4.0 or newer", tuple(bpy.app.version[:2]) >= (4, 0), bpy.app.version_string)
    print(f"      add-on imported from {addon.__file__}", flush=True)

    scene = bpy.context.scene
    if not check("Scene.slicer_settings is registered", hasattr(scene, "slicer_settings")):
        return
    settings = scene.slicer_settings
    rna = settings.bl_rna.properties

    missing = [name for name in settings_io.FIELDS if name not in rna]
    check("every exported setting became an RNA property", not missing, ", ".join(missing))

    missing_ui = [
        item.prop
        for section in ui_schema.SECTIONS
        for item in section.fields
        if item.prop not in rna
    ]
    check("every GUI field became an RNA property", not missing_ui, ", ".join(missing_ui))

    missing_ops = [
        cls.bl_idname
        for cls in operators.CLASSES
        if not hasattr(bpy.ops.slicer, cls.bl_idname.split(".", 1)[1])
    ]
    check("all operators are registered", not missing_ops, ", ".join(missing_ops))

    missing_panels = [cls.bl_idname for cls in panels.CLASSES if not hasattr(bpy.types, cls.bl_idname)]
    check("all panels are registered", not missing_panels, ", ".join(missing_panels))

    # ---------------------------------------------------------- geometry pass
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    source = bpy.context.active_object
    if not check("source cube created", source is not None and source.type == "MESH"):
        return

    settings.source_object = source
    settings.unit_scale_mm = 1000.0
    settings.slice_mode = "PLANAR"
    settings.axis = "Z"
    settings.count = 3
    settings.spacing_mm = 100.0
    settings.centered = True
    settings.fillet_enabled = True
    settings.fillet_radius_mm = 20.0
    settings.fillet_arc_segments = 4
    settings.fillet_mode = "clamp"
    settings.smooth_enabled = False
    settings.simplify_enabled = False
    settings.densify_enabled = True
    settings.densify_max_spacing_mm = 5.0
    settings.build_curves = True

    outcome = bpy.ops.slicer.run()
    check("bpy.ops.slicer.run() finished", "FINISHED" in outcome, str(outcome))
    check("three planar slices generated", len(RUNTIME.slices) == 3, str(len(RUNTIME.slices)))
    check(
        "result is usable (status starts with OK/PARTIAL)",
        settings.status.split(" ")[0] in {"OK", "PARTIAL"},
        settings.status,
    )
    print(f"      status: {settings.status} / {settings.status_detail}", flush=True)

    collection = bpy.data.collections.get("Slice Engine")
    curves = list(collection.objects) if collection is not None else []
    splines = sum(len(obj.data.splines) for obj in curves if obj.type == "CURVE")
    check("curves landed in the 'Slice Engine' collection", len(curves) >= 3, str(len(curves)))
    check("curve objects contain splines", splines >= 3, str(splines))
    check("2D points were produced", settings.last_points > 0, str(settings.last_points))

    # ----------------------------------------------------------- radial pass
    settings.slice_mode = "RADIAL"
    settings.count = 4
    settings.angle_start_deg = 0.0
    settings.angle_end_deg = 90.0
    outcome = bpy.ops.slicer.run()
    radial = len(RUNTIME.slices)
    check("radial fan produced slices", "FINISHED" in outcome and 0 < radial <= 4, str(radial))
    check(
        "radial slices have contours",
        all(slice_.contours for slice_ in RUNTIME.slices),
        str([len(s.contours) for s in RUNTIME.slices]),
    )

    # ------------------------------------------------------- failure handling
    settings.slice_mode = "PLANAR"
    settings.count = 2
    settings.spacing_mm = 250.0
    settings.fillet_mode = "error"
    settings.fillet_radius_mm = 900.0  # cannot fit into a 1000 mm square
    outcome = bpy.ops.slicer.run()
    check("impossible fillet does not crash the operator", "FINISHED" in outcome, str(outcome))
    check("impossible fillet is reported", settings.last_errors > 0, settings.status)
    check(
        "report text explains the failure",
        "E_CONSTRAINT_UNSATISFIED" in settings.diagnostics_text,
        settings.diagnostics_text[:120],
    )

    # ------------------------------------------------------- settings recipe
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "recipe.json"
        settings.fillet_radius_mm = 15.0
        settings_io.export_settings(settings, path)
        settings.fillet_radius_mm = 1.0
        warnings = settings_io.import_settings(settings, path)
        check("settings export/import round-trip", not warnings and settings.fillet_radius_mm == 15.0,
              f"{warnings} radius={settings.fillet_radius_mm}")

    # ---------------------------------------------------------------- clear
    outcome = bpy.ops.slicer.clear()
    collection = bpy.data.collections.get("Slice Engine")
    remaining = 0 if collection is None else len(collection.objects)
    check("clear removes curves", "FINISHED" in outcome and remaining == 0, str(remaining))
    check("clear drops the cached slices", not RUNTIME.slices, settings.status)


def main() -> int:
    import bpy

    args = parse_args()
    print(f"Blender {bpy.app.version_string} / Python {sys.version.split()[0]}", flush=True)

    if args.zip:
        for entry in list(sys.path):
            if Path(entry or ".").resolve() == REPO:
                sys.path.remove(entry)  # do not let the source tree shadow the archive
        archive = args.zip if args.zip.is_absolute() else (REPO / args.zip)
        install_zip(bpy, archive)
    else:
        register_source()
        importlib.import_module("blender_slicer").register()

    addon = importlib.import_module("blender_slicer")
    modules = {
        name: importlib.import_module(f"blender_slicer.adapters.blender.{name}")
        for name in ("operators", "panels", "settings_io", "ui_schema")
    }
    runtime_module = importlib.import_module("blender_slicer.adapters.base.runtime")

    if args.zip:
        check(
            "add-on loaded from the archive, not the source tree",
            not Path(addon.__file__).resolve().is_relative_to(REPO),
            str(addon.__file__),
        )

    try:
        run_checks(
            bpy,
            addon,
            modules["settings_io"],
            modules["ui_schema"],
            modules["operators"],
            modules["panels"],
            runtime_module.RUNTIME,
        )
    finally:
        scene = getattr(bpy.context, "scene", None)
        try:
            if args.zip:
                bpy.ops.preferences.addon_disable(module="blender_slicer")
            else:
                addon.unregister()
        except Exception as exc:  # noqa: BLE001 - report, never hide
            print(f"FAIL  add-on unregister: {exc}", flush=True)
            CHECKS.append(("add-on unregister", False, str(exc)))
        if scene is not None:
            check(
                "unregister removes Scene.slicer_settings",
                not hasattr(scene, "slicer_settings"),
                "property survived unregister",
            )
        if args.zip:
            try:
                if args.keep:
                    bpy.ops.preferences.addon_enable(module="blender_slicer")
                else:
                    bpy.ops.preferences.addon_remove(module="blender_slicer")
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL  add-on cleanup: {exc}", flush=True)
                CHECKS.append(("add-on cleanup", False, str(exc)))

    failed = [entry for entry in CHECKS if not entry[1]]
    print(f"\nRESULT: {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed", flush=True)
    if failed:
        for name, _ok, detail in failed:
            print(f"  FAILED: {name}  {detail}", flush=True)
        raise RuntimeError(f"{len(failed)} Blender smoke checks failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
