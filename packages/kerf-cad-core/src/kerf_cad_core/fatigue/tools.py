"""
kerf_cad_core.fatigue.tools — LLM tool wrappers for general fatigue-life analysis.

Registers eight tools with the Kerf tool registry:

  fatigue_sn_cycles         — Basquin S-N stress-life cycles to failure
  fatigue_endurance_limit   — Modified endurance limit with Marin factors
  fatigue_strain_life       — Coffin-Manson-Basquin ε-N strain-life cycles
  fatigue_neuber_notch      — Neuber notch correction (elasto-plastic notch root)
  fatigue_mean_stress       — Mean-stress correction (Goodman/Gerber/Soderberg/Morrow/SWT)
  fatigue_miner_damage      — Palmgren-Miner cumulative damage from a load spectrum
  fatigue_rainflow_count    — ASTM E1049 four-point rainflow cycle counting
  fatigue_life              — Combined safety factor and predicted life summary

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Shigley's Mechanical Engineering Design, 10th ed., Ch. 6
Dowling, N.E. "Mechanical Behavior of Materials", 4th ed., Ch. 9-14
ASTM E1049-85(2017) — Rainflow cycle counting

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.fatigue.life import (
    sn_cycles,
    endurance_limit,
    strain_life_cycles,
    neuber_notch,
    mean_stress_correction,
    miner_damage,
    rainflow_count,
    fatigue_life,
)


# ---------------------------------------------------------------------------
# Tool: fatigue_sn_cycles
# ---------------------------------------------------------------------------

_sn_cycles_spec = ToolSpec(
    name="fatigue_sn_cycles",
    description=(
        "Compute cycles to fatigue failure using the Basquin stress-life (S-N) "
        "power-law for a given fully-reversed stress amplitude.\n"
        "\n"
        "Basquin equation (Shigley §6-7):\n"
        "  sigma_a = Sf' · (2N)^b\n"
        "  → N = (sigma_a / Sf')^(1/b) / 2\n"
        "\n"
        "Returns N_cycles and a flag for infinite life (N > 1e7).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma_a": {
                "type": "number",
                "description": "Alternating stress amplitude (Pa). Must be > 0.",
            },
            "Sf_prime": {
                "type": "number",
                "description": (
                    "Fatigue strength coefficient (Pa). Must be > 0. "
                    "Typical steel: Sf' ≈ 1.06 × Sut (Dowling empirical)."
                ),
            },
            "b": {
                "type": "number",
                "description": (
                    "Basquin exponent (dimensionless). Must be < 0. "
                    "Typical steel: b ≈ −0.085 (range −0.05 to −0.12)."
                ),
            },
        },
        "required": ["sigma_a", "Sf_prime", "b"],
    },
)


@register(_sn_cycles_spec, write=False)
async def run_sn_cycles(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("sigma_a", "Sf_prime", "b"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = sn_cycles(a["sigma_a"], a["Sf_prime"], a["b"])
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: fatigue_endurance_limit
# ---------------------------------------------------------------------------

_endurance_limit_spec = ToolSpec(
    name="fatigue_endurance_limit",
    description=(
        "Compute the modified endurance limit Se from the rotating-beam "
        "specimen endurance limit Se' using Marin surface/size/load/"
        "temperature/reliability/miscellaneous factors.\n"
        "\n"
        "Se = ka · kb · kc · kd · ke · kf · Se'\n"
        "\n"
        "Shigley §6-9 to §6-14.  All Marin factors default to 1.0 "
        "(ideal polished specimen at ambient temperature, 50% reliability, "
        "bending load).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Se_prime": {
                "type": "number",
                "description": (
                    "Rotating-beam specimen endurance limit (Pa). Must be > 0. "
                    "Steel empirical: Se' ≈ 0.5·Sut for Sut ≤ 1400 MPa."
                ),
            },
            "ka": {
                "type": "number",
                "description": "Surface factor (default 1.0 — polished). Shigley Eq. 6-19.",
            },
            "kb": {
                "type": "number",
                "description": "Size factor (default 1.0). Shigley Eq. 6-20.",
            },
            "kc": {
                "type": "number",
                "description": (
                    "Load factor (default 1.0 = bending). "
                    "0.85 = axial, 0.59 = torsion."
                ),
            },
            "kd": {
                "type": "number",
                "description": "Temperature factor (default 1.0 — ambient).",
            },
            "ke": {
                "type": "number",
                "description": (
                    "Reliability factor (default 1.0 = 50%). "
                    "ke=0.868 for 95%, 0.814 for 99%, 0.702 for 99.9%."
                ),
            },
            "kf": {
                "type": "number",
                "description": "Miscellaneous factor (default 1.0).",
            },
        },
        "required": ["Se_prime"],
    },
)


@register(_endurance_limit_spec, write=False)
async def run_endurance_limit(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("Se_prime") is None:
        return json.dumps({"ok": False, "reason": "Se_prime is required"})

    kwargs: dict = {}
    for k in ("ka", "kb", "kc", "kd", "ke", "kf"):
        if k in a:
            kwargs[k] = a[k]

    result = endurance_limit(a["Se_prime"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: fatigue_strain_life
# ---------------------------------------------------------------------------

_strain_life_spec = ToolSpec(
    name="fatigue_strain_life",
    description=(
        "Compute cycles to failure using the Coffin-Manson-Basquin "
        "strain-life (ε-N) equation:\n"
        "\n"
        "  eps_a = (Sf'/E)·(2N)^b + eps_f'·(2N)^c\n"
        "\n"
        "The first term is the elastic contribution (Basquin); the second "
        "is the plastic contribution (Coffin-Manson). Solved numerically "
        "by bisection.\n"
        "\n"
        "Returns N_cycles and elastic/plastic strain components at that life.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "eps_a": {
                "type": "number",
                "description": "Total strain amplitude (m/m). Must be > 0.",
            },
            "E": {
                "type": "number",
                "description": "Young's modulus (Pa). Must be > 0. Steel ≈ 200e9.",
            },
            "Sf_prime": {
                "type": "number",
                "description": "Fatigue strength coefficient (Pa). Must be > 0.",
            },
            "b": {
                "type": "number",
                "description": "Elastic fatigue exponent (< 0). Typical steel: −0.085.",
            },
            "eps_f_prime": {
                "type": "number",
                "description": (
                    "Fatigue ductility coefficient (m/m). Must be > 0. "
                    "Typical steel: 0.35–1.0."
                ),
            },
            "c": {
                "type": "number",
                "description": "Plastic fatigue exponent (< 0). Typical steel: −0.58.",
            },
        },
        "required": ["eps_a", "E", "Sf_prime", "b", "eps_f_prime", "c"],
    },
)


@register(_strain_life_spec, write=False)
async def run_strain_life(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("eps_a", "E", "Sf_prime", "b", "eps_f_prime", "c"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = strain_life_cycles(
        a["eps_a"], a["E"], a["Sf_prime"], a["b"], a["eps_f_prime"], a["c"]
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: fatigue_neuber_notch
# ---------------------------------------------------------------------------

_neuber_notch_spec = ToolSpec(
    name="fatigue_neuber_notch",
    description=(
        "Apply Neuber's notch correction to compute the notch root "
        "stress-strain product for elasto-plastic notch analysis.\n"
        "\n"
        "Neuber's rule:  sigma_local · eps_local = Kf² · S_nom · e_nom\n"
        "\n"
        "Returns the Neuber constant C, the elastic notch-root estimates "
        "(sigma_el = Kf·S_nom, eps_el = Kf·e_nom), and a plasticity flag.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "S_nom": {
                "type": "number",
                "description": "Nominal stress amplitude (Pa). Must be > 0.",
            },
            "e_nom": {
                "type": "number",
                "description": (
                    "Nominal strain amplitude (m/m). Must be > 0. "
                    "For elastic nominal: e_nom = S_nom / E."
                ),
            },
            "Kf": {
                "type": "number",
                "description": (
                    "Fatigue stress concentration factor (>= 1.0). Must be > 0."
                ),
            },
            "E": {
                "type": "number",
                "description": "Young's modulus (Pa). Must be > 0. Steel ≈ 200e9.",
            },
        },
        "required": ["S_nom", "e_nom", "Kf", "E"],
    },
)


@register(_neuber_notch_spec, write=False)
async def run_neuber_notch(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("S_nom", "e_nom", "Kf", "E"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = neuber_notch(a["S_nom"], a["e_nom"], a["Kf"], a["E"])
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: fatigue_mean_stress
# ---------------------------------------------------------------------------

_mean_stress_spec = ToolSpec(
    name="fatigue_mean_stress",
    description=(
        "Apply a mean-stress correction to compute the equivalent "
        "fully-reversed stress amplitude sigma_ar.\n"
        "\n"
        "Supported methods (Shigley §6-12; Dowling §9.6):\n"
        "  'goodman'   — modified Goodman (linear, default)\n"
        "  'gerber'    — Gerber parabolic (less conservative)\n"
        "  'soderberg' — Soderberg (most conservative, uses Sy)\n"
        "  'morrow'    — Morrow (requires Sf_prime)\n"
        "  'swt'       — Smith-Watson-Topper\n"
        "\n"
        "Returns sigma_ar, safety factor Se/sigma_ar, and fatigue_ok flag.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma_a": {
                "type": "number",
                "description": "Alternating stress amplitude (Pa). Must be >= 0.",
            },
            "sigma_m": {
                "type": "number",
                "description": (
                    "Mean stress (Pa). May be negative (compressive mean is beneficial)."
                ),
            },
            "Se": {
                "type": "number",
                "description": "Modified endurance limit (Pa). Must be > 0.",
            },
            "Sut": {
                "type": "number",
                "description": "Ultimate tensile strength (Pa). Must be > 0.",
            },
            "Sy": {
                "type": "number",
                "description": "Yield strength (Pa). Must be > 0.",
            },
            "method": {
                "type": "string",
                "enum": ["goodman", "gerber", "soderberg", "morrow", "swt"],
                "description": (
                    "Mean-stress correction method (default 'goodman')."
                ),
            },
            "Sf_prime": {
                "type": "number",
                "description": (
                    "Fatigue strength coefficient (Pa). Required only for method='morrow'."
                ),
            },
        },
        "required": ["sigma_a", "sigma_m", "Se", "Sut", "Sy"],
    },
)


@register(_mean_stress_spec, write=False)
async def run_mean_stress(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("sigma_a", "sigma_m", "Se", "Sut", "Sy"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "method" in a:
        kwargs["method"] = a["method"]
    if "Sf_prime" in a:
        kwargs["Sf_prime"] = a["Sf_prime"]

    result = mean_stress_correction(
        a["sigma_a"], a["sigma_m"], a["Se"], a["Sut"], a["Sy"], **kwargs
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: fatigue_miner_damage
# ---------------------------------------------------------------------------

_miner_damage_spec = ToolSpec(
    name="fatigue_miner_damage",
    description=(
        "Compute Palmgren-Miner linear cumulative damage D = Σ(n_i / N_i) "
        "from a load spectrum.\n"
        "\n"
        "Each block i has n_i applied cycles at stress amplitude sigma_a_i. "
        "N_i is the S-N life (Basquin) at sigma_a_i.\n"
        "\n"
        "Failure criterion: D >= 1.0 (Shigley §6-8).\n"
        "\n"
        "Returns total damage, remaining life (1−D), and per-block damage.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cycles": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Applied cycles for each stress block. All >= 0. "
                    "Same length as stress_amplitudes."
                ),
            },
            "stress_amplitudes": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Alternating stress amplitude (Pa) for each block. All > 0. "
                    "Same length as cycles."
                ),
            },
            "Sf_prime": {
                "type": "number",
                "description": "Fatigue strength coefficient (Pa). Must be > 0.",
            },
            "b": {
                "type": "number",
                "description": "Basquin exponent. Must be < 0.",
            },
        },
        "required": ["cycles", "stress_amplitudes", "Sf_prime", "b"],
    },
)


@register(_miner_damage_spec, write=False)
async def run_miner_damage(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("cycles", "stress_amplitudes", "Sf_prime", "b"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = miner_damage(a["cycles"], a["stress_amplitudes"], a["Sf_prime"], a["b"])
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: fatigue_rainflow_count
# ---------------------------------------------------------------------------

_rainflow_spec = ToolSpec(
    name="fatigue_rainflow_count",
    description=(
        "Perform ASTM E1049 four-point rainflow cycle counting on a "
        "stress or strain time history.\n"
        "\n"
        "The history is reduced to turning points (peaks and valleys), then "
        "cycles are extracted using the four-point ASTM E1049 sliding window. "
        "Residue half-cycles are handled by appending the residue to itself.\n"
        "\n"
        "Returns a list of counted cycles: {range, mean, count}.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "history": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Ordered stress or strain values (any units). "
                    "Must have at least 2 elements. Turning points are "
                    "extracted automatically."
                ),
            },
        },
        "required": ["history"],
    },
)


@register(_rainflow_spec, write=False)
async def run_rainflow(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("history") is None:
        return json.dumps({"ok": False, "reason": "history is required"})

    result = rainflow_count(a["history"])
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: fatigue_life
# ---------------------------------------------------------------------------

_fatigue_life_spec = ToolSpec(
    name="fatigue_life",
    description=(
        "Compute the fatigue safety factor and predicted S-N life for "
        "a fully-reversed stress amplitude.\n"
        "\n"
        "Returns:\n"
        "  n_fatigue           = Se / sigma_a  (endurance safety factor)\n"
        "  N_predicted (cycles) using Basquin at sigma_a × safety_factor\n"
        "  infinite_life flag   = True if sigma_a_design <= Se\n"
        "\n"
        "Warns if n_fatigue < 1 (finite-life regime) or sigma_a_design > Sut "
        "(static overload).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma_a": {
                "type": "number",
                "description": "Applied stress amplitude (Pa). Must be > 0.",
            },
            "Se": {
                "type": "number",
                "description": "Modified endurance limit (Pa). Must be > 0.",
            },
            "Sf_prime": {
                "type": "number",
                "description": "Fatigue strength coefficient (Pa). Must be > 0.",
            },
            "b": {
                "type": "number",
                "description": "Basquin exponent. Must be < 0.",
            },
            "Sut": {
                "type": "number",
                "description": "Ultimate tensile strength (Pa). Must be > 0.",
            },
            "safety_factor": {
                "type": "number",
                "description": (
                    "Design safety factor on sigma_a (default 1.0). "
                    "sigma_a_design = sigma_a × safety_factor is used for N prediction."
                ),
            },
        },
        "required": ["sigma_a", "Se", "Sf_prime", "b", "Sut"],
    },
)


@register(_fatigue_life_spec, write=False)
async def run_fatigue_life(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("sigma_a", "Se", "Sf_prime", "b", "Sut"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "safety_factor" in a:
        kwargs["safety_factor"] = a["safety_factor"]

    result = fatigue_life(
        a["sigma_a"], a["Se"], a["Sf_prime"], a["b"], a["Sut"], **kwargs
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)
