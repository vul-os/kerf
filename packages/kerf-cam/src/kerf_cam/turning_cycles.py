"""
kerf_cam.turning_cycles — LLM tool wiring for Fanuc-dialect lathe canned cycles.

Wraps the kerf_cad_core.turning.cycles pure-Python engine to expose:

  cam_generate_turning_cycles
      Emit G71 (rough turning) + G70 (finish turning) G-code from a
      2-D turning profile, with optional G76 threading pass.

The tool is purely computational — no DB writes, no STEP parsing.

References
----------
* ISO 6983-1:2009 — Numerical control of machines — Part 1
* Fanuc Series 0i-TF Operator's Manual §14 (G71 outer-diameter roughing,
  G70 finishing, G76 threading cycle)
* Machinery's Handbook 31e §1148 — turning parameters + DOC selection
"""

from __future__ import annotations

import json
from typing import Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_generate_turning_cycles_spec = ToolSpec(
    name="cam_generate_turning_cycles",
    description=(
        "Generate Fanuc-dialect lathe G-code (G71 rough turning + G70 finish turning, "
        "optionally G76 threading) from a 2-D turning profile. "
        "Input: profile — list of [Z_mm, X_radius_mm] pairs (at least 2 points; "
        "Z monotone, X >= 0); stock_x_mm — stock radius; optional cutting params. "
        "Returns: gcode_lines (list of G-code strings), pass_count, warnings. "
        "G71 roughing: multi-pass peeling from stock OD to profile with U/W allowances. "
        "G70 finishing: single pass over the full profile. "
        "G76 threading: optional; provide pitch_mm, thread_depth_mm, and thread_z_start/end. "
        "Algorithm: CSS (G96) spindle control; feed in mm/rev; equal-depth roughing passes. "
        "References: Fanuc 0i-TF §14; ISO 6983-1; MH 31e §1148."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "profile": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 2,
                "description": (
                    "2-D turning profile as [[Z_mm, X_radius_mm], ...] pairs. "
                    "Z is axial position (mm, positive towards tailstock). "
                    "X is radius (mm, not diameter). Must be monotone in Z."
                ),
            },
            "stock_x_mm": {
                "type": "number",
                "description": "Stock radius in mm. Must be > max(X in profile).",
            },
            "css_m_per_min": {
                "type": "number",
                "description": (
                    "Constant surface speed in m/min. "
                    "Default 180 m/min (medium-carbon steel, uncoated carbide). "
                    "Aluminium: 300–500; Stainless: 80–150; Cast iron: 100–200."
                ),
            },
            "feed_mm_rev": {
                "type": "number",
                "description": "Feed per revolution in mm/rev. Default 0.20 mm/rev.",
            },
            "roughing_doc_mm": {
                "type": "number",
                "description": "Depth of cut per roughing pass (radial, mm). Default 2.0 mm.",
            },
            "finish_allowance_x_mm": {
                "type": "number",
                "description": "Radial finish allowance (U in G71) in mm. Default 0.25 mm.",
            },
            "finish_allowance_z_mm": {
                "type": "number",
                "description": "Axial finish allowance (W in G71) in mm. Default 0.05 mm.",
            },
            "rpm_min": {
                "type": "number",
                "description": "Minimum spindle RPM (CSS clamp). Default 50.",
            },
            "rpm_max": {
                "type": "number",
                "description": "Maximum spindle RPM (CSS clamp). Default 3500.",
            },
            "thread_pitch_mm": {
                "type": "number",
                "description": (
                    "Thread pitch in mm. When provided, a G76 threading pass is appended. "
                    "Example: 1.5 for M-series coarse thread."
                ),
            },
            "thread_depth_mm": {
                "type": "number",
                "description": (
                    "Total thread depth (radial, mm) for G76. "
                    "Example: 0.92 mm for M10×1.5 (ISO 68-1)."
                ),
            },
            "thread_z_start_mm": {
                "type": "number",
                "description": "Z start position for threading pass (mm). Defaults to profile Z start.",
            },
            "thread_z_end_mm": {
                "type": "number",
                "description": "Z end position for threading pass (mm). Defaults to profile Z end.",
            },
        },
        "required": ["profile", "stock_x_mm"],
    },
)


@register(cam_generate_turning_cycles_spec)
async def run_cam_generate_turning_cycles(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    profile_raw = a.get("profile")
    stock_x_mm = a.get("stock_x_mm")

    if not profile_raw:
        return err_payload("profile is required", "BAD_ARGS")
    if stock_x_mm is None:
        return err_payload("stock_x_mm is required", "BAD_ARGS")

    # Parse profile
    try:
        profile = [(float(p[0]), float(p[1])) for p in profile_raw]
    except (TypeError, IndexError, ValueError) as e:
        return err_payload(f"invalid profile format: {e}", "BAD_ARGS")

    if len(profile) < 2:
        return err_payload("profile must have at least 2 points", "BAD_ARGS")

    try:
        stock_x_mm = float(stock_x_mm)
    except (TypeError, ValueError) as e:
        return err_payload(f"invalid stock_x_mm: {e}", "BAD_ARGS")

    css = float(a.get("css_m_per_min", 180.0))
    feed = float(a.get("feed_mm_rev", 0.20))
    roughing_doc = float(a.get("roughing_doc_mm", 2.0))
    finish_x = float(a.get("finish_allowance_x_mm", 0.25))
    finish_z = float(a.get("finish_allowance_z_mm", 0.05))
    rpm_min = float(a.get("rpm_min", 50.0))
    rpm_max = float(a.get("rpm_max", 3500.0))

    thread_pitch = a.get("thread_pitch_mm")
    thread_depth = a.get("thread_depth_mm")
    thread_z_start = a.get("thread_z_start_mm")
    thread_z_end = a.get("thread_z_end_mm")

    try:
        from kerf_cad_core.turning.cycles import roughing_passes, finishing_pass, od_threading, emit_gcode
    except ImportError:
        # kerf_cad_core not installed — use the bundled cycles from routes
        try:
            from kerf_cam._turning_cycles_impl import roughing_passes, finishing_pass, od_threading, emit_gcode
        except ImportError:
            return err_payload(
                "kerf_cad_core.turning.cycles not available. "
                "Install kerf-cad-core: pip install kerf-cad-core",
                "ENGINE_UNAVAILABLE",
            )

    try:
        all_warnings: list[str] = []

        # G71 roughing passes
        rough_result = roughing_passes(
            profile,
            stock_x_mm,
            css_m_per_min=css,
            feed_mm_rev=feed,
            doc_mm=roughing_doc,
            finish_allowance_mm=finish_x,
            rpm_min=rpm_min,
            rpm_max=rpm_max,
        )
        all_warnings.extend(rough_result.warnings)
        if not rough_result.ok:
            return err_payload(f"G71 roughing failed: {rough_result.reason}", "ENGINE_ERROR")

        # G70 finishing pass
        finish_result = finishing_pass(
            profile,
            css_m_per_min=css,
            feed_mm_rev=float(a.get("finish_feed_mm_rev", feed * 0.4)),
            doc_mm=float(a.get("finish_doc_mm", 0.25)),
            rpm_min=rpm_min,
            rpm_max=rpm_max,
        )
        all_warnings.extend(finish_result.warnings)
        if not finish_result.ok:
            return err_payload(f"G70 finishing failed: {finish_result.reason}", "ENGINE_ERROR")

        # Optional G76 threading
        thread_lines: list[str] = []
        if thread_pitch is not None and thread_depth is not None:
            try:
                z_start_t = float(thread_z_start) if thread_z_start is not None else profile[0][0]
                z_end_t = float(thread_z_end) if thread_z_end is not None else profile[-1][0]
                thread_result = od_threading(
                    z_start_mm=z_start_t,
                    z_end_mm=z_end_t,
                    x_major_mm=float(max(p[1] for p in profile)),
                    pitch_mm=float(thread_pitch),
                    thread_depth_mm=float(thread_depth),
                    css_m_per_min=min(css * 0.5, 100.0),  # threading uses lower CSS
                    rpm_min=rpm_min,
                    rpm_max=min(rpm_max, 800.0),
                )
                all_warnings.extend(thread_result.warnings)
                if thread_result.ok:
                    thread_lines = thread_result.gcode
            except Exception as te:
                all_warnings.append(f"G76 threading skipped: {te}")

        # Build full G-code lines: roughing + finishing + optional threading + footer
        all_lines = (
            rough_result.gcode
            + ["(--- FINISHING PASS ---)"]
            + finish_result.gcode
        )
        if thread_lines:
            all_lines += ["(--- THREADING PASS ---)"] + thread_lines
        # Epilogue
        all_lines += ["M5", "M30"]

        pass_count = len(rough_result.passes) + len(finish_result.passes)
        if thread_lines:
            pass_count += 1

        return ok_payload({
            "gcode_lines": all_lines,
            "pass_count": pass_count,
            "roughing_passes": len(rough_result.passes),
            "finishing_passes": len(finish_result.passes),
            "has_threading": len(thread_lines) > 0,
            "warnings": all_warnings,
        })

    except Exception as e:
        return err_payload(str(e), "ENGINE_ERROR")
