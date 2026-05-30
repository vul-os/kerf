"""LLM tool wrappers for assembly-level interference detection.

Tools
-----
brep_assembly_interference
    Detect geometric interference (overlap) between two or more bodies in an
    assembly. Uses AABB broad-phase + Möller-1997 triangle-triangle narrow phase
    + boolean intersection volume (GK-18/GK-23) for exact volume measurement.

brep_check_clearance
    Check the minimum clearance gap between two or more bodies and flag pairs
    that are closer than a required minimum.

Both tools are pure-Python / NumPy; no OCCT dependency for the core algorithm.

Input format
------------
Bodies are specified as axis-aligned box descriptions (the native primitive
for the GK-18 boolean engine).  Each body dict has the form:

    {
      "id": "optional-label",
      "type": "box",            // only "box" supported in this integration
      "corner": [x, y, z],     // minimum corner (mm)
      "dx": float,              // x extent (mm)
      "dy": float,              // y extent (mm)
      "dz": float               // z extent (mm)
    }

Future: "cylinder" / "sphere" types will be added as GK-18 support widens.
"""

from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.assembly_interference import (
    AABB,
    InterferenceResult,
    AssemblyInterferenceReport,
    detect_interference_pair,
    detect_interference_assembly,
    compute_assembly_aabb,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BODY_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "description": "Optional label for this body (used in result keys).",
        },
        "type": {
            "type": "string",
            "enum": ["box"],
            "description": "Primitive type. Only 'box' is supported.",
        },
        "corner": {
            "type": "array",
            "items": {"type": "number"},
            "description": "Minimum corner of the box [x, y, z] (mm).",
        },
        "dx": {"type": "number", "description": "X extent of the box (mm)."},
        "dy": {"type": "number", "description": "Y extent of the box (mm)."},
        "dz": {"type": "number", "description": "Z extent of the box (mm)."},
    },
    "required": ["type", "corner", "dx", "dy", "dz"],
}


def _parse_body(spec: dict, idx: int):
    """Parse a body spec dict and return a (label, Body) tuple.

    Raises ValueError with a descriptive message on parse failure.
    """
    if not isinstance(spec, dict):
        raise ValueError(f"bodies[{idx}] must be an object")

    body_type = str(spec.get("type", "")).strip().lower()
    if body_type != "box":
        raise ValueError(
            f"bodies[{idx}]: unsupported type '{body_type}' "
            f"(only 'box' is supported)"
        )

    corner_raw = spec.get("corner")
    if not corner_raw or len(corner_raw) != 3:
        raise ValueError(f"bodies[{idx}]: corner must be [x, y, z]")
    try:
        corner = [float(x) for x in corner_raw]
    except (TypeError, ValueError):
        raise ValueError(f"bodies[{idx}]: corner values must be numbers")

    try:
        dx = float(spec["dx"])
        dy = float(spec["dy"])
        dz = float(spec["dz"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"bodies[{idx}]: {exc}")

    if dx <= 0 or dy <= 0 or dz <= 0:
        raise ValueError(
            f"bodies[{idx}]: dx/dy/dz must be positive; got ({dx}, {dy}, {dz})"
        )

    label = str(spec.get("id", f"body_{idx}"))
    body = box_to_body(corner, dx, dy, dz)
    return label, body


# ---------------------------------------------------------------------------
# brep_assembly_interference
# ---------------------------------------------------------------------------

_interference_spec = ToolSpec(
    name="brep_assembly_interference",
    description=(
        "Detect geometric interference (volume overlap) between bodies in an "
        "assembly.\n"
        "\n"
        "Each body is an axis-aligned box specified by its minimum corner and "
        "extents (dx, dy, dz in mm).  The tool performs:\n"
        "  1. AABB broad-phase: cheap rejection of clearly-disjoint pairs.\n"
        "  2. Möller 1997 triangle-triangle narrow phase: exact crossing test.\n"
        "  3. Boolean intersection (GK-18) + volume measurement (GK-23) for "
        "     pairs that pass the broad phase.\n"
        "\n"
        "Severity levels:\n"
        "  'none'          — disjoint (no interference).\n"
        "  'touch'         — coincident faces / zero-volume contact.\n"
        "  'overlap'       — genuine volume interpenetration.\n"
        "  'major_overlap' — overlap > 10 % of smaller body's volume.\n"
        "\n"
        "Returns a full pairwise matrix plus a list of critical pairs "
        "(severity == 'overlap' or 'major_overlap') and clearance warnings.\n"
        "\n"
        "Exactly 2 bodies → single-pair result returned as 'pair' key.\n"
        "3+ bodies → full assembly report returned as 'report' key."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bodies": {
                "type": "array",
                "description": "List of body specifications (minimum 2).",
                "items": _BODY_SCHEMA,
                "minItems": 2,
            },
            "tol": {
                "type": "number",
                "description": "Geometric tolerance in mm (default 1e-6).",
            },
            "clearance_min": {
                "type": "number",
                "description": (
                    "Minimum required clearance gap in mm (default 0). "
                    "Pairs within this distance but not interfering are "
                    "reported as clearance warnings."
                ),
            },
        },
        "required": ["bodies"],
    },
)


@register(_interference_spec, write=False)
async def run_brep_assembly_interference(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    bodies_raw = a.get("bodies")
    if not bodies_raw or not isinstance(bodies_raw, list):
        return err_payload("bodies is required (list of ≥2 body specs)", "BAD_ARGS")
    if len(bodies_raw) < 2:
        return err_payload("bodies must have at least 2 elements", "BAD_ARGS")

    tol = float(a.get("tol", 1e-6))
    clearance_min = float(a.get("clearance_min", 0.0))

    # Parse bodies
    labels = []
    bodies = []
    for idx, spec in enumerate(bodies_raw):
        try:
            label, body = _parse_body(spec, idx)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        labels.append(label)
        bodies.append(body)

    if len(bodies) == 2:
        # Pairwise result
        result = detect_interference_pair(bodies[0], bodies[1], tol=tol)
        return ok_payload({
            "mode": "pair",
            "body_a": labels[0],
            "body_b": labels[1],
            "pair": result.to_dict(),
            "message": (
                f"Interference between '{labels[0]}' and '{labels[1]}': "
                f"severity={result.severity!r}, "
                f"volume={result.intersection_volume:.6g} mm³."
            ),
        })

    # Assembly report
    report = detect_interference_assembly(bodies, tol=tol, clearance_min=clearance_min)

    # Enrich pair results with body labels
    pairs_labelled = []
    for i, j, res in report.pairs:
        pairs_labelled.append({
            "body_a": labels[i],
            "body_b": labels[j],
            "i": i,
            "j": j,
            "result": res.to_dict(),
        })

    critical = [
        {"i": i, "j": j, "body_a": labels[i], "body_b": labels[j]}
        for i, j in report.critical_pairs
    ]
    warnings = [
        {"i": i, "j": j, "body_a": labels[i], "body_b": labels[j]}
        for i, j in report.clearance_warnings
    ]

    assembly_aabb = compute_assembly_aabb(bodies)

    return ok_payload({
        "mode": "assembly",
        "n_bodies": report.n_bodies,
        "n_pairs_checked": report.n_pairs_checked,
        "total_pairs": len(report.pairs),
        "total_interference_volume": report.total_interference_volume,
        "critical_pairs": critical,
        "clearance_warnings": warnings,
        "pairs": pairs_labelled,
        "assembly_aabb": assembly_aabb.to_dict(),
        "body_labels": labels,
        "message": (
            f"{len(report.critical_pairs)} interfering pair(s) out of "
            f"{report.n_bodies} bodies; "
            f"total volume={report.total_interference_volume:.6g} mm³."
        ),
    })


# ---------------------------------------------------------------------------
# brep_check_clearance
# ---------------------------------------------------------------------------

_clearance_spec = ToolSpec(
    name="brep_check_clearance",
    description=(
        "Check minimum clearance gaps between bodies in an assembly and flag "
        "pairs that are closer than a required minimum distance.\n"
        "\n"
        "Performs AABB-based gap computation for all pairs. Pairs with AABB gap "
        "≤ min_clearance are reported as clearance violations.\n"
        "\n"
        "Also detects actual interference (overlap); overlapping pairs are "
        "reported separately from close-clearance pairs.\n"
        "\n"
        "Returns:\n"
        "  violations        — pairs with gap < min_clearance (not overlapping).\n"
        "  interfering       — pairs with actual volume overlap.\n"
        "  all_pairs         — full gap matrix.\n"
        "  assembly_aabb     — bounding box of the entire assembly.\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bodies": {
                "type": "array",
                "description": "List of body specifications (minimum 2).",
                "items": _BODY_SCHEMA,
                "minItems": 2,
            },
            "min_clearance": {
                "type": "number",
                "description": (
                    "Required minimum clearance gap in mm. "
                    "Pairs with gap < min_clearance are flagged (default 0.1)."
                ),
            },
            "tol": {
                "type": "number",
                "description": "Geometric tolerance in mm (default 1e-6).",
            },
        },
        "required": ["bodies"],
    },
)


@register(_clearance_spec, write=False)
async def run_brep_check_clearance(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    bodies_raw = a.get("bodies")
    if not bodies_raw or not isinstance(bodies_raw, list):
        return err_payload("bodies is required (list of ≥2 body specs)", "BAD_ARGS")
    if len(bodies_raw) < 2:
        return err_payload("bodies must have at least 2 elements", "BAD_ARGS")

    min_clearance = float(a.get("min_clearance", 0.1))
    tol = float(a.get("tol", 1e-6))

    labels = []
    bodies = []
    for idx, spec in enumerate(bodies_raw):
        try:
            label, body = _parse_body(spec, idx)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        labels.append(label)
        bodies.append(body)

    report = detect_interference_assembly(
        bodies, tol=tol, clearance_min=min_clearance
    )

    # Build gap matrix
    all_pairs = []
    violations = []
    interfering = []

    for i, j, res in report.pairs:
        entry = {
            "body_a": labels[i],
            "body_b": labels[j],
            "i": i,
            "j": j,
            "aabb_gap": res.aabb_gap,
            "interferes": res.interferes,
            "severity": res.severity,
            "intersection_volume": res.intersection_volume,
        }
        all_pairs.append(entry)

        if res.interferes and res.severity in ("overlap", "major_overlap"):
            interfering.append(entry)
        elif not res.interferes and res.aabb_gap <= min_clearance:
            violations.append(entry)

    assembly_aabb = compute_assembly_aabb(bodies)

    n_violations = len(violations)
    n_interfering = len(interfering)

    return ok_payload({
        "violations": violations,
        "interfering": interfering,
        "all_pairs": all_pairs,
        "assembly_aabb": assembly_aabb.to_dict(),
        "body_labels": labels,
        "min_clearance_mm": min_clearance,
        "n_violations": n_violations,
        "n_interfering": n_interfering,
        "message": (
            f"{n_violations} clearance violation(s) and "
            f"{n_interfering} interference(s) found among "
            f"{len(bodies)} bodies (min clearance = {min_clearance} mm)."
        ),
    })


__all__ = [
    "run_brep_assembly_interference",
    "run_brep_check_clearance",
]
