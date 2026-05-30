"""
kerf_mold.ejector_pin_tool — LLM tool wrappers for ejector pin layout planning.

Registers two tools:

  mold_plan_ejector_pins   — generate a pin layout grid + feature pins for a part.
  mold_pin_conflicts       — detect conflicts between pins and cooling channels / ribs.

Both tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Yu-Fan J. (2003) "Computer-aided design of plastic injection molds." §10.
SPI/ANSI B151.1 — Standard ejector pin sizes.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.ejector_pin_planner import (
    BossFeature,
    CoolingChannelXY,
    EjectorPin,
    PartGeometry,
    RibFeature,
    compute_ejection_force_distribution,
    compute_warpage_risk,
    detect_pin_conflicts,
    plan_ejector_pins,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_part_geometry(a: dict) -> tuple:
    """Parse a dict into a PartGeometry. Returns (PartGeometry, error_str)."""
    try:
        width = float(a.get("width_mm", 0))
        depth = float(a.get("depth_mm", 0))
        if width <= 0 or depth <= 0:
            return None, "width_mm and depth_mm must be > 0"

        ribs = []
        for i, r in enumerate(a.get("ribs", [])):
            try:
                ribs.append(RibFeature(
                    base_center_xy=(float(r["base_center_xy"][0]),
                                    float(r["base_center_xy"][1])),
                    width_mm=float(r.get("width_mm", 2.0)),
                    length_mm=float(r.get("length_mm", 20.0)),
                ))
            except Exception as exc:
                return None, f"ribs[{i}]: {exc}"

        bosses = []
        for i, b in enumerate(a.get("bosses", [])):
            try:
                bosses.append(BossFeature(
                    center_xy=(float(b["center_xy"][0]),
                               float(b["center_xy"][1])),
                    outer_diameter_mm=float(b.get("outer_diameter_mm", 6.0)),
                ))
            except Exception as exc:
                return None, f"bosses[{i}]: {exc}"

        thick_sections = []
        for t in a.get("thick_sections_xy", []):
            thick_sections.append((float(t[0]), float(t[1])))

        pg = PartGeometry(
            width_mm=width,
            depth_mm=depth,
            nominal_wall_mm=float(a.get("nominal_wall_mm", 2.0)),
            part_mass_kg=float(a.get("part_mass_kg", 0.1)),
            draft_angle_deg=float(a.get("draft_angle_deg", 1.5)),
            ribs=ribs,
            bosses=bosses,
            thick_sections_xy=thick_sections,
        )
        return pg, ""
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Tool: mold_plan_ejector_pins
# ---------------------------------------------------------------------------

_PLAN_SPEC = ToolSpec(
    name="mold_plan_ejector_pins",
    description=(
        "Plan ejector pin layout for an injection-molded part (Yu-Fan 2003 §10, "
        "SPI/ANSI B151.1 standard pin sizes).\n\n"
        "Places pins on a regular grid (spacing_mm) across the part footprint "
        "and inserts dedicated feature pins at bosses and rib midpoints.  "
        "Selects SPI standard diameter based on part area (3/16\" for small, "
        "1/4\" for medium, 5/16\" for large parts).  Checks total ejection force "
        "against force_per_pin_max_N and adds pins if needed.\n\n"
        "Returns: {ok, pins:[{position:[x,y], diameter_mm, location, "
        "force_required_N}], n_pins, base_diameter_mm, total_force_N, "
        "force_per_pin_max_N, warnings}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "width_mm": {
                "type": "number",
                "description": "Part footprint width (mm). Required.",
            },
            "depth_mm": {
                "type": "number",
                "description": "Part footprint depth (mm). Required.",
            },
            "nominal_wall_mm": {
                "type": "number",
                "description": "Nominal wall thickness (mm). Default 2.0.",
            },
            "part_mass_kg": {
                "type": "number",
                "description": "Estimated part mass (kg). Default 0.1.",
            },
            "draft_angle_deg": {
                "type": "number",
                "description": "Mean mold draft angle (degrees). Default 1.5.",
            },
            "ribs": {
                "type": "array",
                "description": (
                    "Rib features. Each: {base_center_xy:[x,y], "
                    "width_mm?, length_mm?}."
                ),
                "items": {"type": "object"},
            },
            "bosses": {
                "type": "array",
                "description": (
                    "Boss features. Each: {center_xy:[x,y], outer_diameter_mm?}."
                ),
                "items": {"type": "object"},
            },
            "thick_sections_xy": {
                "type": "array",
                "description": "Points marking thick/sink-risk regions: [[x,y], ...].",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                },
            },
            "spacing_mm": {
                "type": "number",
                "description": "Grid spacing between pins (mm). Default 20.0.",
            },
            "n_pins": {
                "oneOf": [
                    {"type": "integer", "minimum": 1},
                    {"type": "string", "enum": ["auto"]},
                ],
                "description": "'auto' (default) or integer target pin count.",
            },
            "force_per_pin_max_N": {
                "type": "number",
                "description": "Maximum force per pin (N). Default 500.",
            },
        },
        "required": ["width_mm", "depth_mm"],
    },
)


async def run_mold_plan_ejector_pins(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    pg, err = _parse_part_geometry(a)
    if pg is None:
        return err_payload(err, "BAD_ARGS")

    spacing = float(a.get("spacing_mm", 20.0))
    n_pins_raw = a.get("n_pins", "auto")
    n_pins = n_pins_raw if n_pins_raw == "auto" else int(n_pins_raw)
    force_max = float(a.get("force_per_pin_max_N", 500.0))

    try:
        pins = plan_ejector_pins(
            part_geometry=pg,
            n_pins=n_pins,
            spacing_mm=spacing,
            force_per_pin_max_N=force_max,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    # Compute force distribution
    dist = compute_ejection_force_distribution(pg, pins)

    # Build pin list for response
    pin_list = [
        {
            "position": list(p.position),
            "diameter_mm": p.diameter_mm,
            "location": p.location,
            "force_required_N": round(dist["pins"][i]["force_N"], 4) if i < len(dist["pins"]) else 0.0,
        }
        for i, p in enumerate(pins)
    ]

    from kerf_mold.ejector_pin_planner import _select_spi_diameter
    base_diam = _select_spi_diameter(pg.footprint_area_mm2)

    return ok_payload({
        "ok": True,
        "n_pins": len(pins),
        "base_diameter_mm": base_diam,
        "total_force_N": dist["total_force_N"],
        "mean_force_per_pin_N": dist["mean_force_N"],
        "force_per_pin_max_N": force_max,
        "pins": pin_list,
        "warnings": dist["warnings"],
    })


# ---------------------------------------------------------------------------
# Tool: mold_pin_conflicts
# ---------------------------------------------------------------------------

_CONFLICT_SPEC = ToolSpec(
    name="mold_pin_conflicts",
    description=(
        "Detect geometric conflicts between ejector pins and mold cooling channels "
        "or rib features (Yu-Fan 2003 §10.3 interference rules).\n\n"
        "A conflict is raised when:\n"
        "  - A pin centre is closer than (pin_radius + channel_radius) to a cooling "
        "channel centre.\n"
        "  - A pin centre falls inside the bounding box of a rib body.\n\n"
        "Also computes warpage risk from force non-uniformity.\n\n"
        "Returns: {ok, n_conflicts, conflicts:[{pin_index, pin_position, "
        "conflict_type, distance_mm, description}], warpage_risk, warnings}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pins": {
                "type": "array",
                "description": (
                    "Ejector pins — as returned by mold_plan_ejector_pins. "
                    "Each: {position:[x,y], diameter_mm, location}."
                ),
                "items": {"type": "object"},
            },
            "cooling_channels": {
                "type": "array",
                "description": (
                    "2-D projections of cooling channels onto the ejection plane. "
                    "Each: {center_xy:[x,y], diameter_mm, label?}."
                ),
                "items": {"type": "object"},
            },
            "ribs": {
                "type": "array",
                "description": (
                    "Rib features. Each: {base_center_xy:[x,y], width_mm, length_mm}."
                ),
                "items": {"type": "object"},
            },
            "part_geometry": {
                "type": "object",
                "description": (
                    "Part geometry for warpage risk computation. "
                    "{width_mm, depth_mm, part_mass_kg?, draft_angle_deg?, ...}"
                ),
            },
        },
        "required": ["pins"],
    },
)


async def run_mold_pin_conflicts(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # Parse pins
    raw_pins = a.get("pins", [])
    if not isinstance(raw_pins, list):
        return err_payload("pins must be a list", "BAD_ARGS")

    pins: list[EjectorPin] = []
    for i, rp in enumerate(raw_pins):
        try:
            pos = rp["position"]
            pins.append(EjectorPin(
                position=(float(pos[0]), float(pos[1])),
                diameter_mm=float(rp.get("diameter_mm", 4.76)),
                location=str(rp.get("location", "wall")),
                force_required_N=float(rp.get("force_required_N", 0.0)),
            ))
        except Exception as exc:
            return err_payload(f"pins[{i}]: {exc}", "BAD_ARGS")

    # Parse cooling channels
    channels: list[CoolingChannelXY] = []
    for i, rc in enumerate(a.get("cooling_channels", [])):
        try:
            cxy = rc["center_xy"]
            channels.append(CoolingChannelXY(
                center_xy=(float(cxy[0]), float(cxy[1])),
                diameter_mm=float(rc.get("diameter_mm", 10.0)),
                label=str(rc.get("label", f"ch{i + 1}")),
            ))
        except Exception as exc:
            return err_payload(f"cooling_channels[{i}]: {exc}", "BAD_ARGS")

    # Parse ribs
    ribs: list[RibFeature] = []
    for i, rr in enumerate(a.get("ribs", [])):
        try:
            bxy = rr["base_center_xy"]
            ribs.append(RibFeature(
                base_center_xy=(float(bxy[0]), float(bxy[1])),
                width_mm=float(rr.get("width_mm", 2.0)),
                length_mm=float(rr.get("length_mm", 20.0)),
            ))
        except Exception as exc:
            return err_payload(f"ribs[{i}]: {exc}", "BAD_ARGS")

    try:
        conflicts = detect_pin_conflicts(pins, channels, ribs)
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    conflict_list = [
        {
            "pin_index": c.pin_index,
            "pin_position": list(c.pin_position),
            "conflict_type": c.conflict_type,
            "distance_mm": c.distance_mm,
            "description": c.description,
        }
        for c in conflicts
    ]

    # Optional warpage risk
    warpage: dict = {}
    pg_raw = a.get("part_geometry")
    if pg_raw:
        pg, err = _parse_part_geometry(pg_raw)
        if pg is not None:
            warpage = compute_warpage_risk(pg, pins)

    return ok_payload({
        "ok": True,
        "n_conflicts": len(conflicts),
        "conflicts": conflict_list,
        "warpage_risk": warpage,
        "warnings": [c.description for c in conflicts] if conflicts else [],
    })
