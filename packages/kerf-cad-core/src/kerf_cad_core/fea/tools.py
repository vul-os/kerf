"""
kerf_cad_core.fea.tools — LLM tool wrappers for the FEA solver.

Registers two tools with the Kerf tool registry:

  fea_solve_truss         — assemble and solve a 2-D pin-jointed truss
  fea_solve_bar_plastic   — 1-D bar with bilinear isotropic-hardening plasticity

All tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: "..."} — tools never raise.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.fea.solver import solve_truss, solve_bar_plastic


# ---------------------------------------------------------------------------
# Tool: fea_solve_truss
# ---------------------------------------------------------------------------

_fea_solve_truss_spec = ToolSpec(
    name="fea_solve_truss",
    description=(
        "Assemble and solve a 2-D pin-jointed linear elastic truss using the "
        "direct stiffness method.\n"
        "\n"
        "Provide node coordinates, element connectivity, support (boundary) "
        "conditions and applied nodal loads.  The solver assembles the global "
        "stiffness matrix, applies BCs, solves for displacements via Gaussian "
        "elimination (pure Python — no numpy), then back-calculates element "
        "axial forces, stresses and strains.\n"
        "\n"
        "Returns displacements (m), reactions (N), element_forces (N), "
        "element_stresses (Pa), element_strains, and any warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": "List of [x, y] node coordinates in metres.  At least 2 nodes.",
                "minItems": 2,
            },
            "elements": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": "List of [i, j] node-index pairs (0-based) for each bar element.",
                "minItems": 1,
            },
            "supports": {
                "type": "object",
                "description": (
                    "Dict mapping node index (string) → {ux: bool, uy: bool}. "
                    "True = that DOF is fixed.  Example: {'0': {'ux': true, 'uy': true}}."
                ),
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "ux": {"type": "boolean"},
                        "uy": {"type": "boolean"},
                    },
                },
            },
            "loads": {
                "type": "object",
                "description": (
                    "Dict mapping node index (string) → {fx: float, fy: float} in Newtons. "
                    "Absent nodes have zero load.  Example: {'2': {'fx': 1000.0, 'fy': 0.0}}."
                ),
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "fx": {"type": "number"},
                        "fy": {"type": "number"},
                    },
                },
            },
            "E": {
                "type": "number",
                "description": "Young's modulus (Pa).  Default 200e9 (steel).  Must be > 0.",
            },
            "A": {
                "type": "number",
                "description": "Cross-sectional area (m²).  Default 1e-4 m².  Must be > 0.",
            },
        },
        "required": ["nodes", "elements", "supports", "loads"],
    },
)


@register(_fea_solve_truss_spec, write=False)
async def run_fea_solve_truss(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    nodes = a.get("nodes")
    elements = a.get("elements")
    supports_raw = a.get("supports")
    loads_raw = a.get("loads")

    if nodes is None:
        return json.dumps({"ok": False, "reason": "nodes is required"})
    if elements is None:
        return json.dumps({"ok": False, "reason": "elements is required"})
    if supports_raw is None:
        return json.dumps({"ok": False, "reason": "supports is required"})
    if loads_raw is None:
        return json.dumps({"ok": False, "reason": "loads is required"})

    # JSON keys are strings; convert to int for supports/loads dicts
    try:
        supports = {int(k): v for k, v in supports_raw.items()}
        loads = {int(k): v for k, v in loads_raw.items()}
    except (ValueError, AttributeError) as exc:
        return json.dumps({"ok": False, "reason": f"supports/loads keys must be integers: {exc}"})

    kwargs: dict = {}
    if "E" in a:
        kwargs["E"] = a["E"]
    if "A" in a:
        kwargs["A"] = a["A"]

    result = solve_truss(nodes, elements, supports, loads, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fea_solve_bar_plastic
# ---------------------------------------------------------------------------

_fea_solve_bar_plastic_spec = ToolSpec(
    name="fea_solve_bar_plastic",
    description=(
        "Solve a 1-D uniaxial bar with bilinear isotropic-hardening plasticity.\n"
        "\n"
        "The bar is fixed at one end and loaded axially at the other.  The load "
        "is ramped from zero to `force` in `steps` equal increments.  At each "
        "step Newton-Raphson equilibrium iterations are performed using the "
        "consistent tangent modulus and a return-mapping radial correction:\n"
        "\n"
        "  σ_trial = σ_n + E × Δε\n"
        "  f_trial = |σ_trial| − (σ_y + H × α_n)\n"
        "  if f_trial > 0: Δγ = f_trial/(E+H);  α += Δγ;  σ corrected\n"
        "\n"
        "Returns per-step: displacement (m), stress (Pa), strain, "
        "plastic_strain, a `plastic` flag, convergence info and warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "length": {
                "type": "number",
                "description": "Bar length (m).  Must be > 0.",
            },
            "area": {
                "type": "number",
                "description": "Cross-sectional area (m²).  Must be > 0.",
            },
            "E": {
                "type": "number",
                "description": "Young's modulus (Pa).  Must be > 0.  Steel ≈ 200e9.",
            },
            "sigma_y": {
                "type": "number",
                "description": "Initial yield stress (Pa).  Must be > 0.",
            },
            "H": {
                "type": "number",
                "description": (
                    "Plastic hardening modulus (Pa).  Must be >= 0.  "
                    "H=0 → perfect plasticity.  H>0 → isotropic hardening."
                ),
            },
            "force": {
                "type": "number",
                "description": "Total applied axial force (N).  May be negative (compression).",
            },
            "steps": {
                "type": "integer",
                "description": "Number of equal load increments (default 20).  Must be >= 1.",
                "minimum": 1,
            },
        },
        "required": ["length", "area", "E", "sigma_y", "H", "force"],
    },
)


@register(_fea_solve_bar_plastic_spec, write=False)
async def run_fea_solve_bar_plastic(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("length", "area", "E", "sigma_y", "H", "force"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "steps" in a:
        kwargs["steps"] = a["steps"]

    result = solve_bar_plastic(
        length=a["length"],
        area=a["area"],
        E=a["E"],
        sigma_y=a["sigma_y"],
        H=a["H"],
        force=a["force"],
        **kwargs,
    )
    return ok_payload(result)
