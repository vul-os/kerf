"""
kerf_cad_core.fatigue.multiaxial_tools — LLM tool wrappers for multiaxial fatigue.

Registers four tools with the Kerf tool registry:

  fatigue_findley               — Findley critical-plane (high-cycle, stress-based)
  fatigue_swt3d                 — SWT 3D critical-plane (mean-stress sensitive)
  fatigue_brown_miller          — Brown-Miller critical-plane (shear-dominated)
  fatigue_multiaxial_critical_plane — unified dispatcher for all three methods

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Socie, D.F. & Marquis, G.B. "Multiaxial Fatigue", SAE International 2000.
Findley, W.N. (1959) Trans. ASME 81:301-317.
Smith, K.N., Watson, P. & Topper, T.H. (1970) J. Mater. 5:767-778.
Brown, M.W. & Miller, K.J. (1973) Proc. IMechE 187:745-755.
Dowling, N.E. "Mechanical Behavior of Materials", 4th ed., §14.8.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.fatigue.multiaxial import (
    findley_critical_plane,
    swt3d_critical_plane,
    brown_miller_critical_plane,
    multiaxial_life,
)


# ---------------------------------------------------------------------------
# Shared schema fragments
# ---------------------------------------------------------------------------

_STRESS_HISTORY_PROP = {
    "type": "array",
    "items": {
        "type": "array",
        "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "minItems": 3,
        "maxItems": 3,
    },
    "description": (
        "Time-ordered list of 3×3 stress tensors (Pa). "
        "Each element is [[σxx,σxy,σxz],[σyx,σyy,σyz],[σzx,σzy,σzz]]. "
        "Must have >= 2 time steps."
    ),
}

_STRAIN_HISTORY_PROP = {
    "type": "array",
    "items": {
        "type": "array",
        "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "minItems": 3,
        "maxItems": 3,
    },
    "description": (
        "Time-ordered list of 3×3 strain tensors (m/m, dimensionless). "
        "Same structure as stress_history. Must have same length as stress_history."
    ),
}

_N_PLANES_PROP = {
    "type": "integer",
    "description": "Number of candidate planes to search (default 200, range 50–2000).",
}

_TARGET_LIFE_PROP = {
    "type": "number",
    "description": "Target design life (cycles) for safety-factor output. Optional.",
}


# ---------------------------------------------------------------------------
# Tool: fatigue_findley
# ---------------------------------------------------------------------------

_findley_spec = ToolSpec(
    name="fatigue_findley",
    description=(
        "Findley critical-plane method for high-cycle multiaxial fatigue.\n"
        "\n"
        "Damage parameter per plane:\n"
        "  P_F = τ_a + k_F · σ_max\n"
        "where τ_a is shear amplitude and σ_max is peak normal stress.\n"
        "\n"
        "The critical plane maximises P_F. Life is estimated from the\n"
        "Basquin S-N curve (Sf_prime, b) treating P_F as the equivalent\n"
        "stress amplitude.\n"
        "\n"
        "material_props keys: Sf_prime (Pa), b (<0), k_F (default 0.25).\n"
        "\n"
        "Returns critical plane normal, P_F, N_cycles, safety factor.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stress_history": _STRESS_HISTORY_PROP,
            "material_props": {
                "type": "object",
                "description": (
                    "Material properties. Required: Sf_prime (Pa), b (<0). "
                    "Optional: k_F (Findley constant, default 0.25)."
                ),
                "properties": {
                    "Sf_prime": {"type": "number"},
                    "b": {"type": "number"},
                    "k_F": {"type": "number"},
                },
                "required": ["Sf_prime", "b"],
            },
            "n_planes": _N_PLANES_PROP,
            "target_life": _TARGET_LIFE_PROP,
        },
        "required": ["stress_history", "material_props"],
    },
)


@register(_findley_spec, write=False)
async def run_fatigue_findley(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("stress_history") is None:
        return json.dumps({"ok": False, "reason": "stress_history is required"})
    if a.get("material_props") is None:
        return json.dumps({"ok": False, "reason": "material_props is required"})

    kwargs: dict = {}
    if "n_planes" in a:
        kwargs["n_planes"] = int(a["n_planes"])
    if "target_life" in a:
        kwargs["target_life"] = float(a["target_life"])

    result = findley_critical_plane(
        a["stress_history"], a["material_props"], **kwargs
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: fatigue_swt3d
# ---------------------------------------------------------------------------

_swt3d_spec = ToolSpec(
    name="fatigue_swt3d",
    description=(
        "Smith-Watson-Topper (SWT) 3D critical-plane method.\n"
        "\n"
        "Damage parameter per plane:\n"
        "  P_SWT = σ_max,n · Δεn/2\n"
        "where σ_max,n is max normal stress and Δεn/2 is normal strain amplitude.\n"
        "\n"
        "Life from the SWT ε-N relation:\n"
        "  P_SWT = (Sf'^2/E)·(2N)^(2b) + Sf'·εf'·(2N)^(b+c)\n"
        "\n"
        "material_props keys: E (Pa), Sf_prime (Pa), b (<0), eps_f_prime, c (<0).\n"
        "\n"
        "Returns critical plane normal, P_SWT, N_cycles, safety factor.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stress_history": _STRESS_HISTORY_PROP,
            "strain_history": _STRAIN_HISTORY_PROP,
            "material_props": {
                "type": "object",
                "description": (
                    "Material properties. Required: E (Pa), Sf_prime (Pa), "
                    "b (<0), eps_f_prime, c (<0)."
                ),
                "properties": {
                    "E": {"type": "number"},
                    "Sf_prime": {"type": "number"},
                    "b": {"type": "number"},
                    "eps_f_prime": {"type": "number"},
                    "c": {"type": "number"},
                },
                "required": ["E", "Sf_prime", "b", "eps_f_prime", "c"],
            },
            "n_planes": _N_PLANES_PROP,
            "target_life": _TARGET_LIFE_PROP,
        },
        "required": ["stress_history", "strain_history", "material_props"],
    },
)


@register(_swt3d_spec, write=False)
async def run_fatigue_swt3d(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("stress_history", "strain_history", "material_props"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "n_planes" in a:
        kwargs["n_planes"] = int(a["n_planes"])
    if "target_life" in a:
        kwargs["target_life"] = float(a["target_life"])

    result = swt3d_critical_plane(
        a["stress_history"], a["strain_history"], a["material_props"], **kwargs
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: fatigue_brown_miller
# ---------------------------------------------------------------------------

_bm_spec = ToolSpec(
    name="fatigue_brown_miller",
    description=(
        "Brown-Miller critical-plane method for shear-dominated fatigue.\n"
        "\n"
        "Damage parameter per plane:\n"
        "  P_BM = Δγ_max/2 + S · Δεn/2\n"
        "where Δγ_max/2 is max shear strain amplitude and Δεn/2 is normal\n"
        "strain amplitude on that plane.\n"
        "\n"
        "Life from the uniaxial Coffin-Manson ε-N curve treating P_BM as\n"
        "the equivalent strain amplitude.\n"
        "\n"
        "material_props keys: E (Pa), Sf_prime (Pa), b (<0), eps_f_prime, c (<0).\n"
        "S_constant: Brown-Miller S factor (default 1.0).\n"
        "\n"
        "Returns critical plane normal, P_BM, N_cycles, safety factor.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "strain_history": _STRAIN_HISTORY_PROP,
            "material_props": {
                "type": "object",
                "description": (
                    "Material properties. Required: E (Pa), Sf_prime (Pa), "
                    "b (<0), eps_f_prime, c (<0)."
                ),
                "properties": {
                    "E": {"type": "number"},
                    "Sf_prime": {"type": "number"},
                    "b": {"type": "number"},
                    "eps_f_prime": {"type": "number"},
                    "c": {"type": "number"},
                },
                "required": ["E", "Sf_prime", "b", "eps_f_prime", "c"],
            },
            "S_constant": {
                "type": "number",
                "description": "Brown-Miller S constant (default 1.0, range 0–3).",
            },
            "n_planes": _N_PLANES_PROP,
            "target_life": _TARGET_LIFE_PROP,
        },
        "required": ["strain_history", "material_props"],
    },
)


@register(_bm_spec, write=False)
async def run_fatigue_brown_miller(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("strain_history", "material_props"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "n_planes" in a:
        kwargs["n_planes"] = int(a["n_planes"])
    if "target_life" in a:
        kwargs["target_life"] = float(a["target_life"])
    if "S_constant" in a:
        kwargs["S"] = float(a["S_constant"])

    result = brown_miller_critical_plane(
        a["strain_history"], a["material_props"], **kwargs
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: fatigue_multiaxial_critical_plane
# ---------------------------------------------------------------------------

_multiaxial_spec = ToolSpec(
    name="fatigue_multiaxial_critical_plane",
    description=(
        "Unified multiaxial critical-plane fatigue life estimator.\n"
        "\n"
        "Dispatches to one of three methods:\n"
        "  'findley'      — high-cycle, stress-based (needs stress_history)\n"
        "  'swt3d'        — mean-stress sensitive, ε-N (needs both histories)\n"
        "  'brown_miller' — shear-dominated, ε-N (needs strain_history)\n"
        "\n"
        "Searches n_planes candidate planes on the unit hemisphere and returns\n"
        "the critical plane orientation, damage parameter, life estimate (N),\n"
        "and safety factor vs target_life.\n"
        "\n"
        "material_props:\n"
        "  findley:      {Sf_prime, b, [k_F=0.25]}\n"
        "  swt3d:        {E, Sf_prime, b, eps_f_prime, c}\n"
        "  brown_miller: {E, Sf_prime, b, eps_f_prime, c}\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stress_history": _STRESS_HISTORY_PROP,
            "strain_history": _STRAIN_HISTORY_PROP,
            "method": {
                "type": "string",
                "enum": ["findley", "swt3d", "brown_miller"],
                "description": "Critical-plane method to use.",
            },
            "material_props": {
                "type": "object",
                "description": (
                    "Material properties dict. Keys depend on method — see "
                    "fatigue_findley / fatigue_swt3d / fatigue_brown_miller."
                ),
            },
            "n_planes": _N_PLANES_PROP,
            "target_life": _TARGET_LIFE_PROP,
            "S_bm": {
                "type": "number",
                "description": "Brown-Miller S constant (only used when method='brown_miller').",
            },
        },
        "required": ["method", "material_props"],
    },
)


@register(_multiaxial_spec, write=False)
async def run_fatigue_multiaxial_critical_plane(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("method") is None:
        return json.dumps({"ok": False, "reason": "method is required"})
    if a.get("material_props") is None:
        return json.dumps({"ok": False, "reason": "material_props is required"})

    kwargs: dict = {}
    if "strain_history" in a:
        kwargs["strain_history"] = a["strain_history"]
    if "n_planes" in a:
        kwargs["n_planes"] = int(a["n_planes"])
    if "target_life" in a:
        kwargs["target_life"] = float(a["target_life"])
    if "S_bm" in a:
        kwargs["S_bm"] = float(a["S_bm"])

    result = multiaxial_life(
        a.get("stress_history"),
        a["method"],
        a["material_props"],
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)
