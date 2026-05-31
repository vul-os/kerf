"""
kerf-cam plugin entry-point.

Registers:
  - FastAPI router  POST /run-cam
  - LLM tools       cam_run, cam_job_status  (via ctx.tools.register)
  - background worker for cam_jobs table     (via ctx.workers.register)

Heavy deps (opencamlib, pythonocc-core) are optional — the plugin still
loads and returns a mock toolpath when they are absent.
"""

from __future__ import annotations

from fastapi import FastAPI

# ── dependency gates ──────────────────────────────────────────────────────────

_OCL_AVAILABLE = False
try:
    import opencamlib  # noqa: F401
    _OCL_AVAILABLE = True
except ImportError:
    pass

_OCC_AVAILABLE = False
try:
    from OCC.Core.STEPControl import STEPControl_Reader  # noqa: F401
    _OCC_AVAILABLE = True
except ImportError:
    pass


# ── register ──────────────────────────────────────────────────────────────────

async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_cam.routes import router
    app.include_router(router)

    # Register LLM tools
    from kerf_cam.tools import (
        cam_run_spec, run_cam_run,
        cam_job_status_spec, run_cam_job_status,
    )
    ctx.tools.register("cam_run", cam_run_spec, run_cam_run)
    ctx.tools.register("cam_job_status", cam_job_status_spec, run_cam_job_status)

    # Tool database LLM tools (T7)
    from kerf_cam.tools.tool_db import (
        create_tool_spec, run_create_tool,
        update_tool_spec, run_update_tool,
        delete_tool_spec, run_delete_tool,
        list_tools_llm_spec, run_list_tools,
    )
    ctx.tools.register("create_tool", create_tool_spec, run_create_tool)
    ctx.tools.register("update_tool", update_tool_spec, run_update_tool)
    ctx.tools.register("delete_tool", delete_tool_spec, run_delete_tool)
    ctx.tools.register("list_tools", list_tools_llm_spec, run_list_tools)

    # Register background worker as a factory — WorkerRegistry.start_all()
    # calls `await factory()` and expects an awaitable returning the worker.
    from kerf_cam.worker import CAMWorker
    cam_worker = CAMWorker(
        pool=ctx.pool,
        storage_getter=lambda: ctx.storage,
        pyworker_url=getattr(ctx.config, "pyworker_url", "http://localhost:8090"),
    )

    async def _cam_factory():
        return cam_worker

    ctx.workers.register("cam", _cam_factory)

    # HSM adaptive strategies — pure-Python, always available (coverage sweep 2026-05-25)
    from kerf_cam.adaptive import (
        adaptive_pocket_spec, run_adaptive_pocket,
        trochoidal_slot_spec, run_trochoidal_slot,
        rest_machining_spec, run_rest_machining,
    )
    ctx.tools.register("adaptive_pocket",  adaptive_pocket_spec,  run_adaptive_pocket)
    ctx.tools.register("trochoidal_slot",  trochoidal_slot_spec,  run_trochoidal_slot)
    ctx.tools.register("rest_machining",   rest_machining_spec,   run_rest_machining)

    # G83 peck-drilling canned cycle — NIST RS-274/NGC §3.8.4 (2026-05-31)
    from kerf_cam.peck_drill_cycle import (
        cam_generate_peck_drill_cycle_spec,
        run_cam_generate_peck_drill_cycle,
    )
    ctx.tools.register(
        "cam_generate_peck_drill_cycle",
        cam_generate_peck_drill_cycle_spec,
        run_cam_generate_peck_drill_cycle,
    )

    # G84/G74 rigid tapping canned cycle — NIST RS-274/NGC §3.8.4 + MH 31e §1934
    from kerf_cam.tap_cycle import (
        cam_generate_tap_cycle_spec,
        run_cam_generate_tap_cycle,
    )
    ctx.tools.register(
        "cam_generate_tap_cycle",
        cam_generate_tap_cycle_spec,
        run_cam_generate_tap_cycle,
    )

    # G85/G86/G89 boring canned cycles — NIST RS-274/NGC §3.8.4 + MH 31e §1162
    from kerf_cam.boring_cycle import (
        cam_generate_boring_cycle_spec,
        run_cam_generate_boring_cycle,
    )
    ctx.tools.register(
        "cam_generate_boring_cycle",
        cam_generate_boring_cycle_spec,
        run_cam_generate_boring_cycle,
    )

    # Rigid-tap operation validator — Sandvik CoroPlus 2024 + MH 31e §1934
    from kerf_cam.rigid_tapping_check import (
        cam_check_rigid_tap_spec,
        run_cam_check_rigid_tap,
    )
    ctx.tools.register(
        "cam_check_rigid_tap",
        cam_check_rigid_tap_spec,
        run_cam_check_rigid_tap,
    )

    # Zig-zag face-mill toolpath — MH 31e §1136 + NIST RS-274/NGC §3.5
    from kerf_cam.face_mill_path import (
        cam_generate_face_mill_path_spec,
        run_cam_generate_face_mill_path,
    )
    ctx.tools.register(
        "cam_generate_face_mill_path",
        cam_generate_face_mill_path_spec,
        run_cam_generate_face_mill_path,
    )

    # Lead-in / lead-out arc/line segments — MH 31e §1131 + Fanuc §G41/G42
    from kerf_cam.lead_in_out import (
        cam_generate_lead_in_out_spec,
        run_cam_generate_lead_in_out,
    )
    ctx.tools.register(
        "cam_generate_lead_in_out",
        cam_generate_lead_in_out_spec,
        run_cam_generate_lead_in_out,
    )

    # Chip-load + chip-thinning calculator — MH 31e §1136 + Sandvik CoroPlus 2024
    from kerf_cam.chip_load_calc import (
        cam_compute_chip_load_spec,
        run_cam_compute_chip_load,
    )
    ctx.tools.register(
        "cam_compute_chip_load",
        cam_compute_chip_load_spec,
        run_cam_compute_chip_load,
    )

    # 3D parallel-offset surface milling — MH 31e §1139 + Held & Klingenstein (1991)
    from kerf_cam.offset_3d_path import (
        cam_generate_offset_3d_path_spec,
        run_cam_generate_offset_3d_path,
    )
    ctx.tools.register(
        "cam_generate_offset_3d_path",
        cam_generate_offset_3d_path_spec,
        run_cam_generate_offset_3d_path,
    )

    # Capabilities depend on available deps
    provides = [
        "cam.2_5d",
        "cam.adaptive-pocket",
        "cam.trochoidal-slot",
        "cam.rest-machining",
        "cam.g83-peck-drill",
        "cam.g84-g74-tap-cycle",
        "cam.g85-g86-g89-boring-cycles",
        "cam.face-mill-path",
        "cam.rigid-tap-check",
        "cam.lead-in-lead-out",
        "cam.chip-load-calc",
        "cam.3d-offset-path",
    ]   # pure-Python ops always available
    if _OCL_AVAILABLE:
        provides += ["cam.parallel-3d", "cam.waterline", "cam.lathe"]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="cam",
            version="0.1.0",
            provides=provides,
            depends=["cad-core"],
        )
    except ImportError:
        return {
            "name": "cam",
            "version": "0.1.0",
            "provides": provides,
            "depends": ["cad-core"],
        }
