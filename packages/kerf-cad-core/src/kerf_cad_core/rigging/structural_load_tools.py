"""
kerf_cad_core.rigging.structural_load_tools
=============================================
LLM tool wrappers for Braceworks-equivalent rigging structural-load analysis.

Registers the following tools with the Kerf tool registry:

  rigging_analyze_structural_load   — full truss + cable rigging analysis
  rigging_cable_catenary_tension    — single catenary cable tension calculation

All tools are pure-Python + numpy; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
BS 7905-1:2002  — Lifting equipment for performance, broadcast and similar
                  applications.
ANSI E1.2-2012  — Entertainment Technology: Aluminium Trusses and Towers.
DIN 18800-1:2008 — Steel structures: design and construction.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.rigging.structural_load import (
    TrussSegment,
    RiggingPoint,
    CableSpan,
    analyze_rigging_load,
    cable_catenary_tension,
)


# ---------------------------------------------------------------------------
# Tool: rigging_analyze_structural_load
# ---------------------------------------------------------------------------

_analyze_structural_load_spec = ToolSpec(
    name="rigging_analyze_structural_load",
    description=(
        "Braceworks-equivalent structural-load analysis for truss and rigging "
        "cable systems (entertainment staging, broadcast, architectural).\n"
        "\n"
        "Computes for each truss segment:\n"
        "  bending_moment_kN_m, shear_kN, deflection_mm, utilization_pct.\n"
        "\n"
        "Computes for each rigging cable:\n"
        "  tension_kN (catenary), sag_m, utilization_pct.\n"
        "\n"
        "Reports overloaded_segments and overloaded_cables (utilization > 100%), "
        "and overall_safety_factor.\n"
        "\n"
        "Standards: ANSI E1.2-2012, BS 7905-1/2:2002, DIN 18800-1:2008.\n"
        "\n"
        "HONEST: linear-elastic static only, no dynamic load factors.\n"
        "\n"
        "Returns {ok, segment_loads, cable_tensions, overloaded_segments, "
        "overloaded_cables, overall_safety_factor, honest_caveat}.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "description": (
                    "List of truss segment objects. Each has: "
                    "segment_id (str), start_pt ([x,y,z] m), end_pt ([x,y,z] m), "
                    "self_weight_per_m (N/m), max_uniform_load_per_m (N/m), "
                    "max_point_load (N)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "segment_id": {"type": "string"},
                        "start_pt": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "end_pt": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "self_weight_per_m": {"type": "number"},
                        "max_uniform_load_per_m": {"type": "number"},
                        "max_point_load": {"type": "number"},
                    },
                    "required": [
                        "segment_id", "start_pt", "end_pt",
                        "self_weight_per_m", "max_uniform_load_per_m", "max_point_load",
                    ],
                },
            },
            "points": {
                "type": "array",
                "description": (
                    "List of rigging point loads. Each has: "
                    "point_id (str), location ([x,y,z] m), point_load_n (N, downward)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "point_id": {"type": "string"},
                        "location": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "point_load_n": {"type": "number"},
                    },
                    "required": ["point_id", "location", "point_load_n"],
                },
            },
            "cables": {
                "type": "array",
                "description": (
                    "List of rigging cables. Each has: "
                    "cable_id (str), anchor_a ([x,y,z] m), anchor_b ([x,y,z] m), "
                    "breaking_strength_n (N), working_load_limit_n (N, typically breaking/5)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "cable_id": {"type": "string"},
                        "anchor_a": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "anchor_b": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "breaking_strength_n": {"type": "number"},
                        "working_load_limit_n": {"type": "number"},
                    },
                    "required": [
                        "cable_id", "anchor_a", "anchor_b",
                        "breaking_strength_n", "working_load_limit_n",
                    ],
                },
            },
        },
        "required": ["segments"],
    },
)


@register(_analyze_structural_load_spec, write=False)
async def run_rigging_analyze_structural_load(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("segments") is None:
        return json.dumps({"ok": False, "reason": "segments is required"})

    try:
        segs = []
        for s in a["segments"]:
            segs.append(TrussSegment(
                segment_id=s["segment_id"],
                start_pt=tuple(s["start_pt"]),
                end_pt=tuple(s["end_pt"]),
                self_weight_per_m=float(s["self_weight_per_m"]),
                max_uniform_load_per_m=float(s["max_uniform_load_per_m"]),
                max_point_load=float(s["max_point_load"]),
            ))

        pts = []
        for p in a.get("points", []):
            pts.append(RiggingPoint(
                point_id=p["point_id"],
                location=tuple(p["location"]),
                point_load_n=float(p["point_load_n"]),
            ))

        cabs = []
        for c in a.get("cables", []):
            cabs.append(CableSpan(
                cable_id=c["cable_id"],
                anchor_a=tuple(c["anchor_a"]),
                anchor_b=tuple(c["anchor_b"]),
                breaking_strength_n=float(c["breaking_strength_n"]),
                working_load_limit_n=float(c["working_load_limit_n"]),
            ))

        report = analyze_rigging_load(segs, pts, cabs)
        return ok_payload({
            "segment_loads": report.segment_loads,
            "cable_tensions": report.cable_tensions,
            "overloaded_segments": report.overloaded_segments,
            "overloaded_cables": report.overloaded_cables,
            "overall_safety_factor": report.overall_safety_factor,
            "honest_caveat": report.honest_caveat,
        })
    except Exception as exc:
        return err_payload(f"rigging load analysis error: {exc}", "ERROR")


# ---------------------------------------------------------------------------
# Tool: rigging_cable_catenary_tension
# ---------------------------------------------------------------------------

_catenary_tension_spec = ToolSpec(
    name="rigging_cable_catenary_tension",
    description=(
        "Compute anchor tension for a rigging cable using the catenary equation.\n"
        "\n"
        "y(x) = a·cosh(x/a) − a   where a = T_H / w.\n"
        "\n"
        "For sag/span < 5% uses the parabolic approximation T_H ≈ wL²/(8d). "
        "For larger sags uses Newton-Raphson exact catenary.\n"
        "\n"
        "Returns tension_n (anchor tension), tension_kN.\n"
        "\n"
        "References: Irvine (1981) Cable Structures; BS 7905-1:2002 Annex A.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "span_m": {
                "type": "number",
                "description": "Horizontal cable span (m). Must be > 0.",
            },
            "sag_m": {
                "type": "number",
                "description": "Mid-span sag (m, positive downward). Must be > 0.",
            },
            "weight_per_m_n": {
                "type": "number",
                "description": "Cable weight per unit length (N/m). Must be > 0.",
            },
        },
        "required": ["span_m", "sag_m", "weight_per_m_n"],
    },
)


@register(_catenary_tension_spec, write=False)
async def run_rigging_cable_catenary_tension(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("span_m", "sag_m", "weight_per_m_n"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    try:
        T = cable_catenary_tension(
            float(a["span_m"]),
            float(a["sag_m"]),
            float(a["weight_per_m_n"]),
        )
        return ok_payload({
            "tension_n": round(T, 3),
            "tension_kN": round(T / 1000.0, 6),
        })
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"catenary tension error: {exc}", "ERROR")
