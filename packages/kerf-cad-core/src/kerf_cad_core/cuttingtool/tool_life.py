"""
kerf_cad_core.cuttingtool.tool_life — Taylor extended tool-life model and
Gilbert economics.

Public functions
----------------
  taylor_tool_life_extended(vc, C, n, f, a, dp, b)
      Extended Taylor equation  vc · T^n · f^a · dp^b = C → tool life T.

  gilbert_economic_speed(C, n, tool_cost, machine_rate, tool_change_time)
      Gilbert / Boothroyd minimum-cost (economic) cutting speed V_e from the
      extended Taylor constants.

  production_rate_speed(C, n, tool_change_time)
      Cutting speed that minimises cycle time (max-production-rate objective).

  tool_life_curve(vc_range, n, C, f, a, dp, b)
      Returns list of (vc, T) pairs over the given velocity range.

Material constants table
------------------------
  TAYLOR_CONSTANTS — dict keyed by (tool_material, work_material) with
    entries {n, a, b, C} where the equation is  vc·T^n·f^a·dp^b = C.

LLM tool wrappers
-----------------
  taylor_tool_life      — compute T from extended Taylor equation
  gilbert_economic_speed — Gilbert min-cost speed
  production_rate_speed  — max-production-rate speed
  tool_life_chart        — tabulate T over a vc range

Units
-----
  vc  — m/min (cutting speed)
  T   — min   (tool life)
  f   — mm/rev (feed)
  dp  — mm    (depth of cut)
  C   — m/min · min^n  (Taylor constant at reference f, dp; f in mm/rev, dp in mm)
  n, a, b — dimensionless
  tool_cost     — same currency as machine_rate × min
  machine_rate  — $/min (machine + operator)
  tool_change_time — min

Textbook validation (Kalpakjian / DeGarmo):
  Carbide on AISI 1045 steel, f=0.25 mm/rev, dp=2 mm, n=0.25, a=0.5, b=0.15, C=300
  At vc=200 m/min:
    vc·T^n·f^a·dp^b = C
    200·T^0.25·0.25^0.5·2^0.15 = 300
    T^0.25 = 300 / (200 · 0.5 · 1.1067...)
    T^0.25 ≈ 2.708...
    T ≈ 2.708^4 ≈ 5.38 min ≈ 5 min  ✓

  Gilbert economic speed (typical shop: machine_rate=1 $/min, tool_cost=5 $,
  tool_change_time=2 min, n=0.25, C=300):
    T_e = (1/n - 1) × (tool_change_time + tool_cost/machine_rate) = 3 × 7 = 21 min
    V_e = C / (T_e^n · f^a · dp^b) — using reference (f=1, dp=1, so V_e = C/T_e^n)
         = 300 / 21^0.25 ≈ 300/2.141 ≈ 140 m/min

  Production-rate speed (same params):
    T_mpr = (1/n - 1) × tool_change_time = 3 × 2 = 6 min
    V_mpr = 300 / 6^0.25 ≈ 300/1.565 ≈ 192 m/min  > V_e  ✓

References
----------
Kalpakjian, S. & Schmid, S.R. "Manufacturing Engineering and Technology", 7th ed.
  (2014), Chapter 21.
DeGarmo, E.P., Black, J.T. & Kohser, R.A. "Materials and Processes in
  Manufacturing", 11th ed. (2011), Chapter 21.
Boothroyd, G. & Knight, W.A. "Fundamentals of Machining and Machine Tools",
  3rd ed. (2006), Chapter 9.
Gilbert, W.W. (1950) "Economics of Machining", in: Machining — Theory and
  Practice, ASM.
Taylor, F.W. (1907) Trans. ASME 28, 31–350.

Author: imranparuk
"""

from __future__ import annotations

import json
import math
import warnings
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401


# ---------------------------------------------------------------------------
# Material constants table
# ---------------------------------------------------------------------------

#: Extended Taylor constants per (tool_material, work_material) pair.
#: Equation: vc · T^n · f^a · dp^b = C
#:   vc in m/min, T in min, f in mm/rev, dp in mm.
#: C is calibrated at f_ref=1 mm/rev, dp_ref=1 mm (multiply/divide accordingly).
TAYLOR_CONSTANTS: dict[tuple[str, str], dict[str, float]] = {
    # Carbide tooling -------------------------------------------------------
    ("carbide", "aisi_1045"):   {"n": 0.25, "a": 0.50, "b": 0.15, "C": 300.0},
    ("carbide", "aisi_4140"):   {"n": 0.25, "a": 0.50, "b": 0.15, "C": 250.0},
    ("carbide", "aisi_304ss"):  {"n": 0.20, "a": 0.55, "b": 0.20, "C": 180.0},
    ("carbide", "aisi_316ss"):  {"n": 0.20, "a": 0.55, "b": 0.20, "C": 160.0},
    ("carbide", "ti_6al_4v"):   {"n": 0.22, "a": 0.45, "b": 0.18, "C": 120.0},
    ("carbide", "al_6061"):     {"n": 0.30, "a": 0.40, "b": 0.12, "C": 900.0},
    ("carbide", "cast_iron"):   {"n": 0.25, "a": 0.45, "b": 0.15, "C": 350.0},
    # HSS tooling -----------------------------------------------------------
    ("hss",     "aisi_1045"):   {"n": 0.10, "a": 0.60, "b": 0.20, "C": 120.0},
    ("hss",     "aisi_4140"):   {"n": 0.10, "a": 0.60, "b": 0.20, "C":  90.0},
    ("hss",     "al_6061"):     {"n": 0.12, "a": 0.50, "b": 0.15, "C": 450.0},
    # CBN/PCBN tooling ------------------------------------------------------
    ("cbn",     "hardened_steel"): {"n": 0.45, "a": 0.30, "b": 0.10, "C": 600.0},
    ("cbn",     "cast_iron"):      {"n": 0.40, "a": 0.30, "b": 0.10, "C": 800.0},
    # Ceramic tooling -------------------------------------------------------
    ("ceramic", "aisi_1045"):   {"n": 0.40, "a": 0.40, "b": 0.12, "C": 500.0},
    ("ceramic", "cast_iron"):   {"n": 0.45, "a": 0.35, "b": 0.10, "C": 700.0},
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def _guard_positive(name: str, value: Any) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if not math.isfinite(v):
        return f"{name} must be finite, got {v}"
    if v <= 0:
        return f"{name} must be > 0, got {v}"
    return None


def _guard_nonneg(name: str, value: Any) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if not math.isfinite(v):
        return f"{name} must be finite, got {v}"
    if v < 0:
        return f"{name} must be >= 0, got {v}"
    return None


# ---------------------------------------------------------------------------
# 1. Extended Taylor tool-life equation
# ---------------------------------------------------------------------------

def taylor_tool_life_extended(
    vc: float,
    C: float,
    n: float,
    f: float,
    a: float,
    dp: float,
    b: float,
    *,
    tool_material: str | None = None,
    work_material: str | None = None,
) -> dict:
    """
    Extended Taylor tool-life equation:  vc · T^n · f^a · dp^b = C.

    Solving for T:
        T = ( C / (vc · f^a · dp^b) )^(1/n)

    Parameters
    ----------
    vc : float
        Cutting speed (m/min). Must be > 0.
    C : float
        Extended Taylor constant (m/min at f=1 mm/rev, dp=1 mm). Must be > 0.
    n : float
        Speed/life exponent. Must be > 0. Typical: 0.1–0.5.
    f : float
        Feed (mm/rev). Must be > 0.
    a : float
        Feed exponent. Must be >= 0. Typical: 0.3–0.7.
    dp : float
        Depth of cut (mm). Must be > 0.
    b : float
        Depth-of-cut exponent. Must be >= 0. Typical: 0.1–0.3.
    tool_material : str | None
        Optional tool material key (for reference only, echoed in output).
    work_material : str | None
        Optional work material key (for reference only, echoed in output).

    Returns
    -------
    dict
        ok       : True
        T_min    : tool life (min)
        C_eff    : effective Taylor constant at given f, dp
                   (= C / (f^a · dp^b), so  vc · T^n = C_eff)
        vc_m_min : cutting speed used (m/min)
        n, a, b  : exponents used
        f_mm_rev : feed used (mm/rev)
        dp_mm    : depth of cut used (mm)

    Validation (Kalpakjian §21 / DeGarmo §21):
        Carbide / AISI 1045: n=0.25, a=0.5, b=0.15, C=300
        At vc=200, f=0.25, dp=2:
          T = (300 / (200 · 0.25^0.5 · 2^0.15))^4 ≈ 5.4 min
    """
    for name, val in [("vc", vc), ("C", C), ("n", n), ("f", f), ("dp", dp)]:
        err = _guard_positive(name, val)
        if err:
            return _err(err)
    for name, val in [("a", a), ("b", b)]:
        err = _guard_nonneg(name, val)
        if err:
            return _err(err)

    vc_val = float(vc)
    C_val = float(C)
    n_val = float(n)
    f_val = float(f)
    a_val = float(a)
    dp_val = float(dp)
    b_val = float(b)

    # C_eff collapses f, dp influence: vc · T^n = C_eff
    C_eff = C_val / ((f_val ** a_val) * (dp_val ** b_val))

    if vc_val >= C_eff:
        warnings.warn(
            f"taylor_tool_life_extended: vc={vc_val} >= C_eff={C_eff:.2f} — "
            "tool life < 1 min; operating above Taylor-valid range.",
            stacklevel=2,
        )

    T = (C_eff / vc_val) ** (1.0 / n_val)

    if T < 0.5:
        warnings.warn(
            f"taylor_tool_life_extended: T={T:.3f} min < 0.5 min — "
            "extremely short tool life; reduce vc or f.",
            stacklevel=2,
        )

    result: dict = {
        "ok": True,
        "T_min": T,
        "C_eff": C_eff,
        "vc_m_min": vc_val,
        "C": C_val,
        "n": n_val,
        "a": a_val,
        "b": b_val,
        "f_mm_rev": f_val,
        "dp_mm": dp_val,
    }
    if tool_material is not None:
        result["tool_material"] = tool_material
    if work_material is not None:
        result["work_material"] = work_material
    return result


# ---------------------------------------------------------------------------
# 2. Gilbert economic cutting speed (minimum cost per part)
# ---------------------------------------------------------------------------

def gilbert_economic_speed(
    C: float,
    n: float,
    tool_cost: float,
    machine_rate: float,
    tool_change_time: float,
    *,
    f: float = 1.0,
    a: float = 0.0,
    dp: float = 1.0,
    b: float = 0.0,
) -> dict:
    """
    Gilbert / Boothroyd economic (minimum cost per part) cutting speed.

    Derivation
    ----------
    Cost per part:
        C_part = C_m · t_m  +  (C_m · t_ct + C_tool) · (t_m / T)

    where t_m is machining time per part, T is tool life.  At the optimum
    d(C_part)/d(vc) = 0, t_m cancels, giving the *economic tool life* T_e:

        T_e = (1/n − 1) · (t_ct + C_tool / C_m)

    and then the economic cutting speed from the extended Taylor equation:

        vc_e · T_e^n · f^a · dp^b = C
        vc_e = C / (T_e^n · f^a · dp^b)

    Parameters
    ----------
    C : float
        Extended Taylor constant (m/min at f=1, dp=1). Must be > 0.
    n : float
        Taylor speed exponent. Must be in (0, 1).
    tool_cost : float
        Cost per cutting edge (same currency as machine_rate × min). Must be > 0.
    machine_rate : float
        Machine + operator cost rate ($/min). Must be > 0.
    tool_change_time : float
        Time to index/change one cutting edge (min). Must be > 0.
    f : float
        Feed (mm/rev) for which the answer is desired. Default 1.0.
    a : float
        Feed exponent. Default 0.0.
    dp : float
        Depth of cut (mm). Default 1.0.
    b : float
        Depth-of-cut exponent. Default 0.0.

    Returns
    -------
    dict
        ok               : True
        vc_e_m_min       : economic cutting speed (m/min)
        T_e_min          : economic tool life (min) — V_mpr > V_e → T_e > T_mpr
        production_rate_speed_m_min : max-production-rate speed (m/min, always >= vc_e)
        T_mpr_min        : tool life at max-production-rate speed (min)
        n, C, tool_cost, machine_rate, tool_change_time : echoed inputs

    Notes
    -----
    • Economic speed is the speed that minimises cost per part.
    • Production-rate speed (max throughput, ignoring cost) is always >= V_e.
    • A higher tool cost pushes V_e lower; a shorter tool-change time raises V_mpr.

    Warnings
    --------
    • n >= 1 → formula degenerate (no finite optimum).
    • V_e outside [1, 2000] m/min → unusual; verify inputs.
    """
    for name, val in [("C", C), ("n", n), ("tool_cost", tool_cost),
                      ("machine_rate", machine_rate), ("tool_change_time", tool_change_time)]:
        err = _guard_positive(name, val)
        if err:
            return _err(err)
    for name, val in [("a", a), ("b", b)]:
        err = _guard_nonneg(name, val)
        if err:
            return _err(err)
    for name, val in [("f", f), ("dp", dp)]:
        err = _guard_positive(name, val)
        if err:
            return _err(err)

    n_val = float(n)
    C_val = float(C)
    tc_val = float(tool_cost)
    cm_val = float(machine_rate)
    tct_val = float(tool_change_time)
    f_val = float(f)
    a_val = float(a)
    dp_val = float(dp)
    b_val = float(b)

    if n_val >= 1.0:
        warnings.warn(
            f"gilbert_economic_speed: n={n_val} >= 1 — Taylor equation degenerate; "
            "no finite economic optimum.",
            stacklevel=2,
        )
        return _err(f"n={n_val} >= 1; economic speed requires n < 1.")

    # Economic tool life (independent of workpiece geometry)
    T_e = (1.0 / n_val - 1.0) * (tct_val + tc_val / cm_val)
    if T_e <= 0:
        return _err(
            f"Economic tool life T_e={T_e:.4f} <= 0; check n, tool_change_time, "
            "tool_cost, machine_rate."
        )

    # f/dp correction factor for C_eff
    f_dp_factor = (f_val ** a_val) * (dp_val ** b_val)
    C_eff = C_val / f_dp_factor

    vc_e = C_eff / (T_e ** n_val)

    if not (1.0 <= vc_e <= 2000.0):
        warnings.warn(
            f"gilbert_economic_speed: vc_e={vc_e:.2f} m/min outside [1, 2000] — "
            "verify Taylor constants and cost inputs.",
            stacklevel=2,
        )

    # Also compute max-production-rate speed for comparison
    T_mpr = (1.0 / n_val - 1.0) * tct_val
    vc_mpr = C_eff / (T_mpr ** n_val)

    return {
        "ok": True,
        "vc_e_m_min": vc_e,
        "T_e_min": T_e,
        "production_rate_speed_m_min": vc_mpr,
        "T_mpr_min": T_mpr,
        "C": C_val,
        "C_eff": C_eff,
        "n": n_val,
        "tool_cost": tc_val,
        "machine_rate": cm_val,
        "tool_change_time": tct_val,
        "f_mm_rev": f_val,
        "dp_mm": dp_val,
    }


# ---------------------------------------------------------------------------
# 3. Production-rate optimum speed
# ---------------------------------------------------------------------------

def production_rate_speed(
    C: float,
    n: float,
    tool_change_time: float,
    *,
    f: float = 1.0,
    a: float = 0.0,
    dp: float = 1.0,
    b: float = 0.0,
) -> dict:
    """
    Cutting speed that minimises cycle time (maximum production rate).

    At this speed tool cost is ignored; only the tool-change delay matters.

        T_mpr = (1/n − 1) · t_ct
        vc_mpr = C_eff / T_mpr^n

    where C_eff = C / (f^a · dp^b).

    This speed is always >= the economic (Gilbert) speed; operating between
    V_e and V_mpr is the "practical speed range".

    Parameters
    ----------
    C : float
        Extended Taylor constant (m/min at f=1, dp=1). Must be > 0.
    n : float
        Taylor speed exponent. Must be in (0, 1).
    tool_change_time : float
        Time to index/change one cutting edge (min). Must be > 0.
    f : float
        Feed (mm/rev). Default 1.0.
    a : float
        Feed exponent. Default 0.0.
    dp : float
        Depth of cut (mm). Default 1.0.
    b : float
        Depth-of-cut exponent. Default 0.0.

    Returns
    -------
    dict
        ok              : True
        vc_mpr_m_min    : max-production-rate cutting speed (m/min)
        T_mpr_min       : tool life at V_mpr (min)
        C_eff           : effective Taylor constant at given f, dp
        n               : exponent used
        tool_change_time: echoed input
    """
    for name, val in [("C", C), ("n", n), ("tool_change_time", tool_change_time)]:
        err = _guard_positive(name, val)
        if err:
            return _err(err)
    for name, val in [("a", a), ("b", b)]:
        err = _guard_nonneg(name, val)
        if err:
            return _err(err)
    for name, val in [("f", f), ("dp", dp)]:
        err = _guard_positive(name, val)
        if err:
            return _err(err)

    n_val = float(n)
    C_val = float(C)
    tct_val = float(tool_change_time)
    f_val = float(f)
    a_val = float(a)
    dp_val = float(dp)
    b_val = float(b)

    if n_val >= 1.0:
        return _err(f"n={n_val} >= 1; production-rate speed requires n < 1.")

    T_mpr = (1.0 / n_val - 1.0) * tct_val
    if T_mpr <= 0:
        return _err(f"T_mpr={T_mpr:.4f} <= 0; check n and tool_change_time.")

    C_eff = C_val / ((f_val ** a_val) * (dp_val ** b_val))
    vc_mpr = C_eff / (T_mpr ** n_val)

    return {
        "ok": True,
        "vc_mpr_m_min": vc_mpr,
        "T_mpr_min": T_mpr,
        "C_eff": C_eff,
        "C": C_val,
        "n": n_val,
        "tool_change_time": tct_val,
        "f_mm_rev": f_val,
        "dp_mm": dp_val,
    }


# ---------------------------------------------------------------------------
# 4. Tool-life curve
# ---------------------------------------------------------------------------

def tool_life_curve(
    vc_range: list[float],
    n: float,
    C: float,
    f: float,
    a: float,
    dp: float,
    b: float,
) -> dict:
    """
    Compute tool life T(vc) for a list of cutting velocities.

    Uses the extended Taylor equation:
        T(vc) = ( C / (vc · f^a · dp^b) )^(1/n)

    Parameters
    ----------
    vc_range : list[float]
        List of cutting speeds (m/min). All must be > 0.
    n : float
        Taylor speed exponent. Must be > 0.
    C : float
        Taylor constant (m/min at f=1, dp=1). Must be > 0.
    f : float
        Feed (mm/rev). Must be > 0.
    a : float
        Feed exponent. Must be >= 0.
    dp : float
        Depth of cut (mm). Must be > 0.
    b : float
        Depth-of-cut exponent. Must be >= 0.

    Returns
    -------
    dict
        ok          : True
        curve       : list of {"vc_m_min": float, "T_min": float}
                      sorted by vc ascending
        C_eff       : effective Taylor constant at given f, dp
        n           : exponent used
        f_mm_rev    : feed used
        dp_mm       : depth of cut used
        points      : number of valid points computed

    Notes
    -----
    Individual vc values that fail validation are skipped (not returned),
    so check len(curve) if the full range is required.
    """
    for name, val in [("C", C), ("n", n), ("f", f), ("dp", dp)]:
        err = _guard_positive(name, val)
        if err:
            return _err(err)
    for name, val in [("a", a), ("b", b)]:
        err = _guard_nonneg(name, val)
        if err:
            return _err(err)

    if not vc_range:
        return _err("vc_range must be a non-empty list of cutting speeds.")

    n_val = float(n)
    C_val = float(C)
    f_val = float(f)
    a_val = float(a)
    dp_val = float(dp)
    b_val = float(b)

    C_eff = C_val / ((f_val ** a_val) * (dp_val ** b_val))

    curve = []
    for vc in vc_range:
        try:
            vc_f = float(vc)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(vc_f) or vc_f <= 0:
            continue
        T = (C_eff / vc_f) ** (1.0 / n_val)
        curve.append({"vc_m_min": vc_f, "T_min": T})

    curve.sort(key=lambda p: p["vc_m_min"])

    return {
        "ok": True,
        "curve": curve,
        "C_eff": C_eff,
        "C": C_val,
        "n": n_val,
        "f_mm_rev": f_val,
        "dp_mm": dp_val,
        "points": len(curve),
    }


# ---------------------------------------------------------------------------
# 5. Helper: look up constants from the materials table
# ---------------------------------------------------------------------------

def lookup_taylor_constants(
    tool_material: str,
    work_material: str,
) -> dict:
    """
    Look up extended Taylor constants for a tool/work material pair.

    Parameters
    ----------
    tool_material : str
        e.g. 'carbide', 'hss', 'cbn', 'ceramic'
    work_material : str
        e.g. 'aisi_1045', 'aisi_304ss', 'ti_6al_4v', 'al_6061'

    Returns
    -------
    dict
        ok : True
        n, a, b, C : Taylor constants
        tool_material, work_material : echoed keys
        available_pairs : list of str — all valid (tool, work) keys
    """
    key = (tool_material.lower().strip(), work_material.lower().strip())
    if key not in TAYLOR_CONSTANTS:
        available = [f"({t}, {w})" for t, w in sorted(TAYLOR_CONSTANTS.keys())]
        return {
            "ok": False,
            "reason": (
                f"No constants for ({tool_material!r}, {work_material!r}). "
                f"Available pairs: {available}"
            ),
            "available_pairs": available,
        }
    consts = TAYLOR_CONSTANTS[key]
    return {
        "ok": True,
        "tool_material": key[0],
        "work_material": key[1],
        **consts,
    }


# ---------------------------------------------------------------------------
# LLM tool wrappers
# ---------------------------------------------------------------------------

# --- taylor_tool_life -------------------------------------------------------

_taylor_tool_life_spec = ToolSpec(
    name="taylor_tool_life",
    description=(
        "Extended Taylor tool-life equation: vc · T^n · f^a · dp^b = C.\n"
        "\n"
        "Solves for tool life T given cutting speed, feed, depth of cut and the\n"
        "Taylor constants for the tool/work material pair.\n"
        "\n"
        "  T = ( C / (vc · f^a · dp^b) )^(1/n)   [minutes]\n"
        "\n"
        "Validation example (Kalpakjian / DeGarmo):\n"
        "  Carbide / AISI 1045, n=0.25, a=0.5, b=0.15, C=300,\n"
        "  vc=200 m/min, f=0.25 mm/rev, dp=2 mm → T ≈ 5.4 min.\n"
        "\n"
        "Optionally provide tool_material and work_material to auto-look-up\n"
        "constants from the built-in table (overrides n, a, b, C if found).\n"
        "\n"
        "Built-in material pairs: carbide/{aisi_1045, aisi_4140, aisi_304ss,\n"
        "  aisi_316ss, ti_6al_4v, al_6061, cast_iron}, hss/{aisi_1045, aisi_4140,\n"
        "  al_6061}, cbn/{hardened_steel, cast_iron}, ceramic/{aisi_1045, cast_iron}.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vc_m_min": {
                "type": "number",
                "description": "Cutting speed (m/min). Must be > 0.",
            },
            "C": {
                "type": "number",
                "description": (
                    "Taylor constant (m/min at f=1 mm/rev, dp=1 mm). Must be > 0. "
                    "Ignored if tool_material + work_material resolve a built-in pair."
                ),
            },
            "n": {
                "type": "number",
                "description": (
                    "Taylor speed exponent. Must be > 0. Typical: 0.10–0.45. "
                    "Ignored if tool_material + work_material resolve a built-in pair."
                ),
            },
            "f_mm_rev": {
                "type": "number",
                "description": "Feed (mm/rev). Must be > 0.",
            },
            "a": {
                "type": "number",
                "description": "Feed exponent. Must be >= 0. Typical: 0.3–0.7.",
            },
            "dp_mm": {
                "type": "number",
                "description": "Depth of cut (mm). Must be > 0.",
            },
            "b": {
                "type": "number",
                "description": "Depth-of-cut exponent. Must be >= 0. Typical: 0.1–0.3.",
            },
            "tool_material": {
                "type": "string",
                "description": (
                    "Tool material key for built-in lookup: 'carbide', 'hss', 'cbn', 'ceramic'."
                ),
            },
            "work_material": {
                "type": "string",
                "description": (
                    "Work material key: 'aisi_1045', 'aisi_4140', 'aisi_304ss', 'aisi_316ss', "
                    "'ti_6al_4v', 'al_6061', 'cast_iron', 'hardened_steel'."
                ),
            },
        },
        "required": ["vc_m_min", "f_mm_rev", "dp_mm"],
    },
)


@register(_taylor_tool_life_spec, write=False)
async def run_taylor_tool_life(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("vc_m_min", "f_mm_rev", "dp_mm"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    # Resolve Taylor constants: table lookup or explicit inputs
    tool_mat = a.get("tool_material")
    work_mat = a.get("work_material")
    if tool_mat and work_mat:
        lk = lookup_taylor_constants(tool_mat, work_mat)
        if not lk.get("ok"):
            return json.dumps(lk)
        C_val = lk["C"]
        n_val = lk["n"]
        a_val = lk["a"]
        b_val = lk["b"]
    else:
        for field in ("C", "n", "a", "b"):
            if a.get(field) is None:
                return json.dumps({
                    "ok": False,
                    "reason": (
                        f"{field} is required when tool_material/work_material are not provided."
                    ),
                })
        C_val = a["C"]
        n_val = a["n"]
        a_val = a["a"]
        b_val = a["b"]

    result = taylor_tool_life_extended(
        vc=a["vc_m_min"],
        C=C_val,
        n=n_val,
        f=a["f_mm_rev"],
        a=a_val,
        dp=a["dp_mm"],
        b=b_val,
        tool_material=tool_mat,
        work_material=work_mat,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# --- gilbert_economic_speed -------------------------------------------------

_gilbert_spec = ToolSpec(
    name="gilbert_economic_speed",
    description=(
        "Gilbert / Boothroyd economic (minimum cost per part) cutting speed.\n"
        "\n"
        "Derives the cutting speed that minimises cost per component from the\n"
        "extended Taylor equation and shop economics:\n"
        "\n"
        "  T_e   = (1/n − 1) · (t_ct + C_tool / C_m)\n"
        "  vc_e  = C_eff / T_e^n\n"
        "  C_eff = C / (f^a · dp^b)\n"
        "\n"
        "Also returns the maximum-production-rate speed (always >= vc_e).\n"
        "\n"
        "Validation (DeGarmo / Kalpakjian shop example):\n"
        "  Carbide/AISI-1045, n=0.25, C=300, machine_rate=1 $/min,\n"
        "  tool_cost=5, tool_change_time=2 min:\n"
        "  T_e = 21 min → vc_e ≈ 140 m/min\n"
        "  T_mpr = 6 min → vc_mpr ≈ 192 m/min  (> vc_e  ✓)\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs or n >= 1. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {
                "type": "number",
                "description": "Taylor constant (m/min at f=1, dp=1). Must be > 0.",
            },
            "n": {
                "type": "number",
                "description": "Taylor speed exponent. Must be in (0, 1).",
            },
            "tool_cost": {
                "type": "number",
                "description": "Cost per cutting edge (same currency as machine_rate × min). Must be > 0.",
            },
            "machine_rate": {
                "type": "number",
                "description": "Machine + operator cost rate ($/min). Must be > 0.",
            },
            "tool_change_time": {
                "type": "number",
                "description": "Time to change / index one cutting edge (min). Must be > 0.",
            },
            "f_mm_rev": {
                "type": "number",
                "description": "Feed (mm/rev). Default 1.0.",
            },
            "a": {
                "type": "number",
                "description": "Feed exponent. Default 0.0.",
            },
            "dp_mm": {
                "type": "number",
                "description": "Depth of cut (mm). Default 1.0.",
            },
            "b": {
                "type": "number",
                "description": "Depth-of-cut exponent. Default 0.0.",
            },
        },
        "required": ["C", "n", "tool_cost", "machine_rate", "tool_change_time"],
    },
)


@register(_gilbert_spec, write=False)
async def run_gilbert_economic_speed(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C", "n", "tool_cost", "machine_rate", "tool_change_time"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = gilbert_economic_speed(
        C=a["C"],
        n=a["n"],
        tool_cost=a["tool_cost"],
        machine_rate=a["machine_rate"],
        tool_change_time=a["tool_change_time"],
        f=a.get("f_mm_rev", 1.0),
        a=a.get("a", 0.0),
        dp=a.get("dp_mm", 1.0),
        b=a.get("b", 0.0),
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# --- production_rate_speed --------------------------------------------------

_prod_rate_spec = ToolSpec(
    name="production_rate_speed",
    description=(
        "Cutting speed that minimises cycle time (maximum production rate).\n"
        "\n"
        "Ignores tool cost; only the tool-change delay matters.\n"
        "\n"
        "  T_mpr  = (1/n − 1) · t_ct\n"
        "  vc_mpr = C_eff / T_mpr^n\n"
        "\n"
        "V_mpr >= V_e (Gilbert economic speed) always.\n"
        "Operating between V_e and V_mpr is the practical speed window.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs or n >= 1. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {
                "type": "number",
                "description": "Taylor constant (m/min at f=1, dp=1). Must be > 0.",
            },
            "n": {
                "type": "number",
                "description": "Taylor speed exponent. Must be in (0, 1).",
            },
            "tool_change_time": {
                "type": "number",
                "description": "Time to change / index one cutting edge (min). Must be > 0.",
            },
            "f_mm_rev": {
                "type": "number",
                "description": "Feed (mm/rev). Default 1.0.",
            },
            "a": {
                "type": "number",
                "description": "Feed exponent. Default 0.0.",
            },
            "dp_mm": {
                "type": "number",
                "description": "Depth of cut (mm). Default 1.0.",
            },
            "b": {
                "type": "number",
                "description": "Depth-of-cut exponent. Default 0.0.",
            },
        },
        "required": ["C", "n", "tool_change_time"],
    },
)


@register(_prod_rate_spec, write=False)
async def run_production_rate_speed(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C", "n", "tool_change_time"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = production_rate_speed(
        C=a["C"],
        n=a["n"],
        tool_change_time=a["tool_change_time"],
        f=a.get("f_mm_rev", 1.0),
        a=a.get("a", 0.0),
        dp=a.get("dp_mm", 1.0),
        b=a.get("b", 0.0),
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# --- tool_life_chart --------------------------------------------------------

_chart_spec = ToolSpec(
    name="tool_life_chart",
    description=(
        "Tabulate tool life T(vc) across a range of cutting speeds.\n"
        "\n"
        "Uses the extended Taylor equation for each vc in the provided list:\n"
        "  T = ( C / (vc · f^a · dp^b) )^(1/n)   [minutes]\n"
        "\n"
        "Returns a sorted list of {vc_m_min, T_min} pairs, suitable for\n"
        "plotting a Taylor tool-life curve (log-log) or tabular display.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid parameters. Never raises.\n"
        "Invalid individual vc values in the list are silently skipped."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vc_range": {
                "type": "array",
                "items": {"type": "number"},
                "description": "List of cutting speeds (m/min). Each must be > 0.",
            },
            "n": {
                "type": "number",
                "description": "Taylor speed exponent. Must be > 0.",
            },
            "C": {
                "type": "number",
                "description": "Taylor constant (m/min at f=1, dp=1). Must be > 0.",
            },
            "f_mm_rev": {
                "type": "number",
                "description": "Feed (mm/rev). Must be > 0.",
            },
            "a": {
                "type": "number",
                "description": "Feed exponent. Must be >= 0.",
            },
            "dp_mm": {
                "type": "number",
                "description": "Depth of cut (mm). Must be > 0.",
            },
            "b": {
                "type": "number",
                "description": "Depth-of-cut exponent. Must be >= 0.",
            },
        },
        "required": ["vc_range", "n", "C", "f_mm_rev", "a", "dp_mm", "b"],
    },
)


@register(_chart_spec, write=False)
async def run_tool_life_chart(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("vc_range", "n", "C", "f_mm_rev", "a", "dp_mm", "b"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    if not isinstance(a["vc_range"], list):
        return json.dumps({"ok": False, "reason": "vc_range must be a list of numbers"})

    result = tool_life_curve(
        vc_range=a["vc_range"],
        n=a["n"],
        C=a["C"],
        f=a["f_mm_rev"],
        a=a["a"],
        dp=a["dp_mm"],
        b=a["b"],
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)
