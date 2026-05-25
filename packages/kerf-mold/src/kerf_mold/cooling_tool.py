"""
kerf_mold.cooling_tool — LLM tool wrapper for injection-mold cooling analysis.

Tool: mold_cooling_analysis
  Run a Dittus-Boelter cooling circuit thermal analysis and return
  Reynolds number, Nusselt number, heat-transfer coefficient, and
  cooling time estimate.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_cooling_analysis_spec = ToolSpec(
    name="mold_cooling_analysis",
    description=(
        "Injection-mold cooling circuit thermal analysis using the Dittus-Boelter "
        "correlation (Menges et al. 2001, §9).  "
        "Analyses one or more cooling channels in a series or parallel circuit.  "
        "Returns: Reynolds number, flow regime, Nusselt number, heat-transfer "
        "coefficient h [W/m²·K], pressure drop [Pa], coolant temperature rise [°C], "
        "and the Janeschitz-Kriegl cooling time estimate [s]."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "channels": {
                "type": "array",
                "description": (
                    "List of cooling channels. Each: "
                    "{diameter_mm, length_mm, distance_mm?, pitch_mm?, label?}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "diameter_mm": {"type": "number", "description": "Bore diameter (mm). Default 10."},
                        "length_mm": {"type": "number", "description": "Straight-run length (mm). Default 200."},
                        "distance_mm": {"type": "number", "description": "Depth from cavity surface (mm). Default 15."},
                        "pitch_mm": {"type": "number", "description": "Channel pitch (mm). Default 25."},
                        "label": {"type": "string"},
                    },
                },
                "minItems": 1,
            },
            "layout": {
                "type": "string",
                "enum": ["series", "parallel"],
                "description": "Circuit layout: 'series' (default) or 'parallel'.",
            },
            "flow_rate_lpm": {
                "type": "number",
                "description": "Total circuit coolant flow rate (litres/min). Default 5.0.",
            },
            "coolant_inlet_temp_c": {
                "type": "number",
                "description": "Coolant inlet temperature (°C). Default 20.0.",
            },
            "mould_surface_temp_c": {
                "type": "number",
                "description": "Target cavity surface temperature (°C). Default 60.0.",
            },
            "heat_load_W": {
                "type": "number",
                "description": "Total heat load from polymer (W). 0 = geometry-only analysis. Default 0.",
            },
            "part_thickness_mm": {
                "type": "number",
                "description": "Part wall thickness for cooling time estimate (mm). Default 3.0.",
            },
            "polymer": {
                "type": "string",
                "description": (
                    "Polymer grade for cooling time estimate. "
                    "Supported: PP, PE, ABS, PA6, PC, POM, PS, PVC. Default ABS."
                ),
            },
            "melt_temp_c": {
                "type": "number",
                "description": "Melt injection temperature (°C). Default 230.",
            },
            "ejection_temp_c": {
                "type": "number",
                "description": "Safe part ejection temperature (°C). Default 80.",
            },
        },
        "required": ["channels"],
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_cooling_analysis(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_mold.cooling import (
            CoolingChannel,
            CoolingCircuit,
            circuit_analysis,
            cooling_time,
            POLYMER_THERMAL_DIFFUSIVITY,
        )

        # Parse channels
        raw_channels = args.get("channels", [])
        if not raw_channels:
            return err_payload("channels must be a non-empty list", "BAD_ARGS")

        channels = []
        for i, ch in enumerate(raw_channels):
            try:
                channels.append(CoolingChannel(
                    diameter_mm=float(ch.get("diameter_mm", 10.0)),
                    length_mm=float(ch.get("length_mm", 200.0)),
                    distance_mm=float(ch.get("distance_mm", 15.0)),
                    pitch_mm=float(ch.get("pitch_mm", 25.0)),
                    label=str(ch.get("label", f"ch{i + 1}")),
                ))
            except (TypeError, ValueError) as exc:
                return err_payload(f"channels[{i}]: {exc}", "BAD_ARGS")

        layout = str(args.get("layout", "series"))
        flow_rate_lpm = float(args.get("flow_rate_lpm", 5.0))
        inlet_temp_c = float(args.get("coolant_inlet_temp_c", 20.0))
        mould_temp_c = float(args.get("mould_surface_temp_c", 60.0))
        heat_load_W = float(args.get("heat_load_W", 0.0))
        part_mm = float(args.get("part_thickness_mm", 3.0))
        polymer = str(args.get("polymer", "ABS"))
        melt_temp_c = float(args.get("melt_temp_c", 230.0))
        ejection_temp_c = float(args.get("ejection_temp_c", 80.0))

        # Build circuit
        try:
            circuit = CoolingCircuit(
                channels=channels,
                layout=layout,
                flow_rate_lpm=flow_rate_lpm,
                coolant_inlet_temp_c=inlet_temp_c,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        # Run circuit analysis
        result = circuit_analysis(
            circuit,
            mould_surface_temp_c=mould_temp_c,
            heat_load_W=heat_load_W,
        )

        # Run cooling time estimate
        ct_result = cooling_time(
            wall_thickness_mm=part_mm,
            polymer=polymer,
            melt_temp_c=melt_temp_c,
            mould_temp_c=mould_temp_c,
            ejection_temp_c=ejection_temp_c,
        )

        # Build per-channel summary
        channel_summary = [
            {
                "label": r.channel_label,
                "reynolds": round(r.reynolds, 1),
                "nusselt": round(r.nusselt, 3),
                "htc_W_m2K": round(r.htc_W_m2K, 2),
                "pressure_drop_pa": round(r.pressure_drop_pa, 2),
                "velocity_m_s": round(r.velocity_m_s, 4),
                "flow_regime": r.flow_regime,
            }
            for r in result.channels
        ]

        payload: dict[str, Any] = {
            "ok": True,
            "layout": layout,
            "n_channels": len(channels),
            "flow_rate_lpm": flow_rate_lpm,
            "coolant_inlet_temp_c": inlet_temp_c,
            "mould_surface_temp_c": mould_temp_c,
            "total_pressure_drop_kPa": round(result.total_pressure_drop_kPa, 4),
            "effective_htc_W_m2K": round(result.total_htc_W_m2K, 2),
            "coolant_temp_rise_c": round(result.coolant_temp_rise_c, 4),
            "channel_results": channel_summary,
            "cooling_time_s": round(ct_result.cooling_time_s, 3),
            "cooling_time_warnings": ct_result.warnings,
            "polymer": polymer,
            "part_thickness_mm": part_mm,
            "warnings": result.warnings,
        }

        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "COOLING_ERROR")
