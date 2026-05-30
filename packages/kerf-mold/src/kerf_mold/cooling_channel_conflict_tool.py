"""
kerf_mold.cooling_channel_conflict_tool
=========================================
LLM tool wrapper for injection-mold cooling-channel conflict verification.

Tool: mold_verify_cooling_channels
  Verify that a cooling-channel layout satisfies Menges 2001 §6.5 design rules:
  channel-channel spacing, channel-ejector clearance, wall-clearance, and
  mold-base bounds.

Returns per-conflict detail with type, location, gap_mm, severity (1-5), and
a human-readable description.

References
----------
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001 — §6.5 Cooling-channel design rules.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.cooling_channel_conflict import (
    CavityWall,
    CoolingChannel3D,
    CoolingConflictReport,
    EjectorPin3D,
    MoldBbox,
    verify_cooling_channels,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_VERIFY_SPEC = ToolSpec(
    name="mold_verify_cooling_channels",
    description=(
        "Verify the cooling-channel layout in an injection-mold cavity for "
        "geometric conflicts (Menges 2001 §6.5 design rules).\n\n"
        "Four conflict classes are detected:\n"
        "  1. CHANNEL_SPACING  — channels closer than min_spacing_factor × diameter "
        "(Menges §6.5: >=2x bore diameter c-t-c).\n"
        "  2. CHANNEL_EJECTOR  — channel intersects or approaches an ejector-pin path "
        "(Yu-Fan 2003 §10.3).\n"
        "  3. WALL_CLEARANCE   — channel too close to a cavity-face plane (risk of "
        "thin-wall breakthrough).\n"
        "  4. MOLD_BOUNDS      — channel exits the mold-base bounding box.\n\n"
        "Returns: {ok, n_conflicts, conflicts:[{conflict_type, channel_a, channel_b, "
        "location_mm, gap_mm, min_required_mm, severity, description}], "
        "scope_warnings, summary}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "channels": {
                "type": "array",
                "description": (
                    "Straight cooling channels.  Each: "
                    "{start:[x,y,z], end:[x,y,z], diameter_mm?, label?, curved?}. "
                    "All coordinates in mm."
                ),
                "items": {"type": "object"},
                "minItems": 1,
            },
            "ejector_pins": {
                "type": "array",
                "description": (
                    "Ejector pins as 3-D axis segments.  Each: "
                    "{start:[x,y,z], end:[x,y,z], diameter_mm?, label?}. "
                    "Omit to skip ejector-channel checks."
                ),
                "items": {"type": "object"},
            },
            "mold_bbox": {
                "type": "object",
                "description": (
                    "Mold-base bounding box: "
                    "{x_min, x_max, y_min, y_max, z_min, z_max} in mm. "
                    "Required for MOLD_BOUNDS checks."
                ),
                "properties": {
                    "x_min": {"type": "number"},
                    "x_max": {"type": "number"},
                    "y_min": {"type": "number"},
                    "y_max": {"type": "number"},
                    "z_min": {"type": "number"},
                    "z_max": {"type": "number"},
                },
                "required": ["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"],
            },
            "cavity_walls": {
                "type": "array",
                "description": (
                    "Cavity-face planes for WALL_CLEARANCE checks.  Each: "
                    "{normal:[nx,ny,nz], point_on_wall:[x,y,z], label?}. "
                    "normal must be a unit outward vector.  "
                    "Omit to skip wall-clearance checks."
                ),
                "items": {"type": "object"},
            },
            "min_spacing_factor": {
                "type": "number",
                "description": (
                    "Multiplier on channel radius for minimum edge-to-edge clearance. "
                    "Default 2.0 (Menges 2001 §6.5 rule: 2x diameter c-t-c)."
                ),
            },
        },
        "required": ["channels", "mold_bbox"],
    },
)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_xyz(raw: Any, name: str) -> tuple:
    """Parse [x, y, z] or (x, y, z) -> (float, float, float)."""
    try:
        if len(raw) != 3:
            raise ValueError(f"{name} must have 3 components")
        return (float(raw[0]), float(raw[1]), float(raw[2]))
    except (TypeError, KeyError) as exc:
        raise ValueError(f"Cannot parse {name}: {exc}") from exc


def _parse_channels(raw: list) -> list:
    channels = []
    for i, rc in enumerate(raw):
        try:
            start = _parse_xyz(rc["start"], f"channels[{i}].start")
            end = _parse_xyz(rc["end"], f"channels[{i}].end")
            channels.append(CoolingChannel3D(
                start=start,
                end=end,
                diameter_mm=float(rc.get("diameter_mm", 10.0)),
                label=str(rc.get("label", f"ch{i + 1}")),
                curved=bool(rc.get("curved", False)),
            ))
        except Exception as exc:
            raise ValueError(f"channels[{i}]: {exc}") from exc
    return channels


def _parse_ejector_pins(raw: list) -> list:
    pins = []
    for i, rp in enumerate(raw):
        try:
            start = _parse_xyz(rp["start"], f"ejector_pins[{i}].start")
            end = _parse_xyz(rp["end"], f"ejector_pins[{i}].end")
            pins.append(EjectorPin3D(
                start=start,
                end=end,
                diameter_mm=float(rp.get("diameter_mm", 4.76)),
                label=str(rp.get("label", f"pin{i + 1}")),
            ))
        except Exception as exc:
            raise ValueError(f"ejector_pins[{i}]: {exc}") from exc
    return pins


def _parse_mold_bbox(raw: dict) -> MoldBbox:
    return MoldBbox(
        x_min=float(raw["x_min"]),
        x_max=float(raw["x_max"]),
        y_min=float(raw["y_min"]),
        y_max=float(raw["y_max"]),
        z_min=float(raw["z_min"]),
        z_max=float(raw["z_max"]),
    )


def _parse_cavity_walls(raw: list) -> list:
    walls = []
    for i, rw in enumerate(raw):
        try:
            normal = _parse_xyz(rw["normal"], f"cavity_walls[{i}].normal")
            point = _parse_xyz(rw["point_on_wall"], f"cavity_walls[{i}].point_on_wall")
            walls.append(CavityWall(
                normal=normal,
                point_on_wall=point,
                label=str(rw.get("label", f"wall{i + 1}")),
            ))
        except Exception as exc:
            raise ValueError(f"cavity_walls[{i}]: {exc}") from exc
    return walls


def _conflict_to_dict(c) -> dict:
    return {
        "conflict_type": c.conflict_type,
        "channel_a": c.channel_a,
        "channel_b": c.channel_b,
        "location_mm": list(c.location_mm),
        "gap_mm": c.gap_mm,
        "min_required_mm": c.min_required_mm,
        "severity": c.severity,
        "description": c.description,
    }


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_verify_cooling_channels(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # --- Parse channels ---
    raw_channels = a.get("channels", [])
    if not raw_channels:
        return err_payload("channels must be a non-empty list", "BAD_ARGS")
    try:
        channels = _parse_channels(raw_channels)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    # --- Parse ejector pins (optional) ---
    ejector_pins = []
    if a.get("ejector_pins"):
        try:
            ejector_pins = _parse_ejector_pins(a["ejector_pins"])
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

    # --- Parse mold bbox ---
    raw_bbox = a.get("mold_bbox")
    if not raw_bbox:
        return err_payload("mold_bbox is required", "BAD_ARGS")
    try:
        bbox = _parse_mold_bbox(raw_bbox)
    except (KeyError, ValueError, TypeError) as exc:
        return err_payload(f"mold_bbox: {exc}", "BAD_ARGS")

    # --- Parse cavity walls (optional) ---
    cavity_walls = []
    if a.get("cavity_walls"):
        try:
            cavity_walls = _parse_cavity_walls(a["cavity_walls"])
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

    factor = float(a.get("min_spacing_factor", 2.0))

    try:
        report: CoolingConflictReport = verify_cooling_channels(
            channels=channels,
            ejector_pins=ejector_pins,
            cavity_bbox=bbox,
            cavity_walls=cavity_walls,
            min_spacing_factor=factor,
        )
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    # Build severity summary
    sev_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for c in report.conflicts:
        sev_counts[c.severity] = sev_counts.get(c.severity, 0) + 1

    type_counts: dict = {}
    for c in report.conflicts:
        type_counts[c.conflict_type] = type_counts.get(c.conflict_type, 0) + 1

    return ok_payload({
        "ok": True,
        "n_channels": report.n_channels,
        "n_ejector_pins": report.n_ejector_pins,
        "n_cavity_walls": report.n_cavity_walls,
        "n_conflicts": len(report.conflicts),
        "severity_counts": sev_counts,
        "conflict_type_counts": type_counts,
        "conflicts": [_conflict_to_dict(c) for c in report.conflicts],
        "scope_warnings": report.scope_warnings,
        "summary": (
            f"{len(report.conflicts)} conflict(s) detected across "
            f"{report.n_channels} channel(s), "
            f"{report.n_ejector_pins} ejector pin(s), "
            f"{report.n_cavity_walls} cavity wall(s). "
            f"Severity 5={sev_counts[5]}, 4={sev_counts[4]}, "
            f"3={sev_counts[3]}, 2={sev_counts[2]}, 1={sev_counts[1]}."
        ),
    })
