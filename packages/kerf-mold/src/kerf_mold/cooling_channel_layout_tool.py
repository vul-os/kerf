"""
kerf_mold.cooling_channel_layout_tool — LLM tool wrapper for cooling channel layout design.

Tool: mold_design_cooling_channel_layout
  Design the 3D routing layout of conventional (gun-drilled) or conformal cooling
  channels for an injection-mold cavity block.

References:
  Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
    Hanser 2001, §6.5 — cooling channel design rules; Table 6.4.
  Xu X., Sachs E., Allen S. (2001). *Polymer Engineering & Science* 41(7),
    1265–1279 — conformal cooling channel offset rules.
  Tang L.Q. et al. (1998). *Finite Elements in Analysis and Design* 26(3),
    229–251 — optimal cooling channel placement.

Wave 9C: Cimatron mold base + EDM electrode + wire EDM + cooling channel layout
"""
from __future__ import annotations

from typing import Any, Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.cooling_channel_layout import (
    MoldBlockSpec,
    design_cooling_channel_layout,
    BORE_DIAMETER_DEFAULT_MM,
    PITCH_FACTOR_STANDARD,
    WALL_CLEARANCE_FACTOR_STANDARD,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_design_cooling_channel_layout_spec = ToolSpec(
    name="mold_design_cooling_channel_layout",
    description=(
        "Design the 3D routing layout of cooling channels for an injection-mold "
        "cavity block.\n\n"
        "Two strategies:\n"
        "  'conventional' — Straight gun-drilled channels in a grid parallel to "
        "the parting plane. Industry standard for machined molds.\n"
        "  'conformal'    — Channel loop following the cavity-surface contour at "
        "a constant offset (Xu et al. 2001). For additive-manufactured inserts.\n\n"
        "Bore diameter is auto-selected from block size (Menges 2001 §6.5 Table 6.4) "
        "if not specified.\n\n"
        "Returns: {layout_type, total_channels, total_length_mm, "
        "estimated_heat_area_mm2, pitch_mm, bore_diameter_mm, clearance_mm, "
        "num_circuits, channels[{label, type, start_mm, end_mm, diameter_mm, "
        "length_mm, circuit_id}], warnings, honest_caveat}.\n\n"
        "HONEST: Positions are heuristic. Verify interference via "
        "mold_verify_cooling_channels; verify thermal performance via "
        "mold_compute_cooling_pressure_drop and mold_check_turbulent_re. "
        "Full cooling optimisation requires Moldflow / Moldex3D FEM simulation.\n\n"
        "Refs: Menges 2001 §6.5; Xu et al. (2001) PES 41(7) 1265; "
        "Tang et al. (1998) FEA 26(3) 229."
    ),
    input_schema={
        "type": "object",
        "required": [
            "block_x_min", "block_x_max",
            "block_y_min", "block_y_max",
            "block_z_min", "block_z_max",
            "cavity_depth_mm",
        ],
        "properties": {
            "block_x_min": {
                "type": "number",
                "description": "Mold block lower X extent (mm).",
            },
            "block_x_max": {
                "type": "number",
                "description": "Mold block upper X extent (mm). Must be > block_x_min.",
            },
            "block_y_min": {
                "type": "number",
                "description": "Mold block lower Y extent (mm).",
            },
            "block_y_max": {
                "type": "number",
                "description": "Mold block upper Y extent (mm). Must be > block_y_min.",
            },
            "block_z_min": {
                "type": "number",
                "description": "Mold block bottom Z (mm).",
            },
            "block_z_max": {
                "type": "number",
                "description": "Mold block top Z (mm; typically the parting plane). Must be > block_z_min.",
            },
            "cavity_depth_mm": {
                "type": "number",
                "description": "Depth of the deepest cavity feature measured from z_max (mm). Must be > 0.",
                "exclusiveMinimum": 0,
            },
            "cavity_surface_z": {
                "type": "number",
                "description": (
                    "Explicit Z coordinate of the deepest cavity surface (mm). "
                    "If omitted, derived as block_z_max - cavity_depth_mm."
                ),
            },
            "layout_type": {
                "type": "string",
                "enum": ["conventional", "conformal"],
                "description": (
                    "'conventional' — straight gun-drilled channels (default); "
                    "'conformal' — cavity-surface-offset channels for AM inserts."
                ),
                "default": "conventional",
            },
            "bore_diameter_mm": {
                "type": "number",
                "description": (
                    "Channel bore diameter (mm). Typical: 8–14 mm. "
                    "If omitted, auto-selected from block size (Menges 2001 §6.5 Table 6.4)."
                ),
                "exclusiveMinimum": 0,
            },
            "pitch_factor": {
                "type": "number",
                "description": (
                    "Conventional layout only. Pitch = pitch_factor × bore_diameter. "
                    "Typical: 3.5 (standard), 2.5 (aggressive), 5.0 (conservative). Default 3.5."
                ),
                "exclusiveMinimum": 0,
            },
            "clearance_factor": {
                "type": "number",
                "description": (
                    "Cavity surface clearance = clearance_factor × bore_diameter. "
                    "Menges 2001 §6.5 minimum 1.5; standard 2.0; maximum 3.0. Default 2.0."
                ),
                "exclusiveMinimum": 0,
            },
            "num_circuits": {
                "type": "integer",
                "description": "Number of independent cooling circuits (1 or 2). Default 2.",
                "minimum": 1,
                "maximum": 4,
            },
            "num_conformal_segments": {
                "type": "integer",
                "description": (
                    "Conformal layout only. Number of perimeter segments per loop. "
                    "Minimum 4 (rectangular). Default 8."
                ),
                "minimum": 4,
            },
            "pull_axis": {
                "type": "string",
                "enum": ["x", "y", "z"],
                "description": "Mold opening axis ('x', 'y', or 'z'). Default 'z'.",
                "default": "z",
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_design_cooling_channel_layout(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute cooling channel layout design and return a JSON string."""
    try:
        # Required fields
        block_x_min = args.get("block_x_min")
        block_x_max = args.get("block_x_max")
        block_y_min = args.get("block_y_min")
        block_y_max = args.get("block_y_max")
        block_z_min = args.get("block_z_min")
        block_z_max = args.get("block_z_max")
        cavity_depth_mm = args.get("cavity_depth_mm")

        required_fields = [
            ("block_x_min", block_x_min),
            ("block_x_max", block_x_max),
            ("block_y_min", block_y_min),
            ("block_y_max", block_y_max),
            ("block_z_min", block_z_min),
            ("block_z_max", block_z_max),
            ("cavity_depth_mm", cavity_depth_mm),
        ]
        for name, val in required_fields:
            if val is None:
                return err_payload(f"{name} is required", "BAD_ARGS")

        try:
            block_x_min = float(block_x_min)
            block_x_max = float(block_x_max)
            block_y_min = float(block_y_min)
            block_y_max = float(block_y_max)
            block_z_min = float(block_z_min)
            block_z_max = float(block_z_max)
            cavity_depth_mm = float(cavity_depth_mm)
        except (TypeError, ValueError) as exc:
            return err_payload(f"numeric conversion failed: {exc}", "BAD_ARGS")

        # Optional fields
        cavity_surface_z = args.get("cavity_surface_z")
        if cavity_surface_z is not None:
            try:
                cavity_surface_z = float(cavity_surface_z)
            except (TypeError, ValueError) as exc:
                return err_payload(f"cavity_surface_z: {exc}", "BAD_ARGS")

        layout_type = str(args.get("layout_type", "conventional"))
        if layout_type not in ("conventional", "conformal"):
            return err_payload(
                f"layout_type must be 'conventional' or 'conformal', got {layout_type!r}",
                "BAD_ARGS",
            )

        bore_diameter_mm = args.get("bore_diameter_mm")
        if bore_diameter_mm is not None:
            try:
                bore_diameter_mm = float(bore_diameter_mm)
            except (TypeError, ValueError) as exc:
                return err_payload(f"bore_diameter_mm: {exc}", "BAD_ARGS")

        pitch_factor = float(args.get("pitch_factor", PITCH_FACTOR_STANDARD))
        clearance_factor = float(args.get("clearance_factor", WALL_CLEARANCE_FACTOR_STANDARD))
        num_circuits = int(args.get("num_circuits", 2))
        num_conformal_segments = int(args.get("num_conformal_segments", 8))
        pull_axis = str(args.get("pull_axis", "z"))
        if pull_axis not in ("x", "y", "z"):
            return err_payload(f"pull_axis must be 'x', 'y', or 'z', got {pull_axis!r}", "BAD_ARGS")

        try:
            block = MoldBlockSpec(
                x_min=block_x_min,
                x_max=block_x_max,
                y_min=block_y_min,
                y_max=block_y_max,
                z_min=block_z_min,
                z_max=block_z_max,
                pull_axis=pull_axis,
                cavity_surface_z=cavity_surface_z,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        report = design_cooling_channel_layout(
            block=block,
            cavity_depth_mm=cavity_depth_mm,
            layout_type=layout_type,
            bore_diameter_mm=bore_diameter_mm,
            pitch_factor=pitch_factor,
            clearance_factor=clearance_factor,
            num_circuits=num_circuits,
            num_conformal_segments=num_conformal_segments,
        )

        return ok_payload({
            "ok": True,
            "reference": (
                "Menges G., Michaeli W., Mohren P. (2001). How to Make Injection Molds, 3rd ed., "
                "Hanser, §6.5. | Xu X., Sachs E., Allen S. (2001). Polymer Engineering & Science "
                "41(7), 1265–1279. | Tang L.Q. et al. (1998). Finite Elements in Analysis and "
                "Design 26(3), 229–251."
            ),
            **report.as_dict(),
        })

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "COOLING_LAYOUT_ERROR")
