"""
Inductor core saturation checker.

Given an inductor's core material, geometry (effective area A_e, magnetic path
length l_e, saturation flux density B_sat), turn count N, and peak DC + ripple
current I_peak, computes the peak flux density B_pk and checks whether the core
is saturated.

Design equations — Erickson "Power Electronics" §15 + McLyman "Transformer and
Inductor Design Handbook" §10:
---------------------------------------------------------------------------

  I_peak = I_dc + I_ripple_pp / 2        [A]

  B_pk = μ₀ · μ_r · N · I_peak / l_e    [T]   (Ampere's law, uniform path)

  where μ₀ = 4π × 10⁻⁷ H/m

  Unit conversion:
    l_e in mm → l_e_m = l_e_mm × 10⁻³   [m]

  saturation_margin_pct = (B_sat − B_pk) / B_sat × 100   [%]
    positive → not saturated (margin remaining)
    negative or zero → saturated (B_pk ≥ B_sat)

  saturated = B_pk >= B_sat

  recommended_max_I_dc_A:
    Solve B_pk = B_sat for I_peak: I_peak_max = B_sat × l_e / (μ₀ × μ_r × N)
    I_dc_max = I_peak_max − I_ripple_pp / 2   (must be positive)

TEMPERATURE DERATING
--------------------
Ferrite materials lose B_sat significantly with temperature. The model applies
a piecewise linear B_sat derating for ferrite cores only (materials whose name
starts with "ferrite"):

  ferrite derating factor:
    T ≤ 25°C  → 1.00 (reference)
    T = 100°C → 0.85 (−15%)
    T = 125°C → 0.75 (−25%)
    T = 150°C → 0.60 (−40%)
    T = 200°C → 0.50 (−50%)

  Intermediate temperatures are linearly interpolated. T > 200°C extrapolates
  linearly to avoid a cliff; the caveat warns when T > 150°C.

Powdered-iron and Sendust are significantly less temperature-sensitive (B_sat
drops ~5–10% from 25→100°C per Magnetics Inc. Powder Core Catalog §3) — the
derating for these materials is NOT applied in this model; the caveat notes it.

HONEST CAVEATS
--------------
1. FRINGING FLUX ignored — fringing around air gaps in gapped cores (boost
   inductors, flyback transformers) reduces the effective μ_r by the inverse of
   the gap factor and creates localised field spikes. Add a gap-fringing
   correction (Dowell/Erickson §15.3 Eq 15.17) for gapped cores; this model
   treats the core as a single closed magnetic path (no air gap).

2. μ_r assumed constant — real ferrite cores (e.g. 3C95, 3F36) exhibit strong
   permeability roll-off with H field WELL BEFORE B_sat is reached (the
   μ_r vs. H curve is highly nonlinear in the knee region). At I_peak values
   20–50% below saturation the apparent μ_r may already be half the initial
   value. This model uses the user-supplied (initial) μ_r at all operating
   points; actual B_pk at the same current will be lower than computed because
   flux density flattens out in the knee. The formula therefore gives a
   conservative (over-estimated) B_pk — safe for margin checks but can
   over-predict saturation at moderate flux densities.

3. Temperature derating for ferrite ONLY — powdered iron, Sendust, and NiFe50
   materials have their own derating curves (Magnetics Inc. §3; Micrometals
   catalog) that are NOT modelled here; assume B_sat is provided at the worst-
   case operating temperature.

4. A_e (effective area) is not used in the B_pk formula — it appears in the
   inductance formula L = μ₀·μ_r·N²·A_e/l_e and in flux Φ = B·A_e but is
   NOT needed to compute B_pk from Ampere's law. It is captured in the dataclass
   for completeness and may be used by callers for inductance estimation.

5. Winding resistance and copper losses are NOT modelled; at elevated current
   temperature rise from I²R increases core temperature and further reduces B_sat.

6. AC flux density (ripple) and hysteresis/Steinmetz core losses are NOT
   modelled. For high-frequency applications compute P_core = Cm·f^x·(ΔB/2)^y·V_e
   (Steinmetz) separately.

References
----------
R. W. Erickson & D. Maksimovic, "Fundamentals of Power Electronics", 3rd ed.,
    Springer, 2020, §15 (Inductor Design).
Colonel Wm. T. McLyman, "Transformer and Inductor Design Handbook", 4th ed.,
    CRC Press, 2011, §10 (Inductor Design).
Ferroxcube Application Note, "Design of Planar Power Transformers" (3C95 / 3F36
    B_sat datasheet values; see also Ferroxcube 3C95 datasheet Rev. 2020).
Magnetics Inc., "Powder Core Catalog", 2023, §3 (temperature effects, B_sat tables).
Micrometals, "Iron Powder Core Catalog", 2023 (powdered-iron material curves).

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# Physical constant
_MU0 = 4.0 * math.pi * 1e-7  # H/m — permeability of free space


# ── Dataclasses ────────────────────────────────────────────────────────────────

VALID_MATERIALS = frozenset(
    ["ferrite_3C95", "ferrite_3F36", "powdered_iron_-26", "sendust", "NiFe50"]
)


@dataclass
class InductorCoreSpec:
    """Core material and geometry specification for an inductor.

    Attributes
    ----------
    material : str
        Core material identifier.  One of:
        "ferrite_3C95" — MnZn ferrite, B_sat ≈ 500 mT @ 25°C (Ferroxcube).
        "ferrite_3F36" — MnZn ferrite, B_sat ≈ 380 mT @ 25°C (Ferroxcube).
        "powdered_iron_-26" — −26 material, B_sat ≈ 1400 mT (Micrometals).
        "sendust"          — Fe-Si-Al alloy, B_sat ≈ 1000 mT (Magnetics Inc.).
        "NiFe50"           — 50% NiFe permalloy, B_sat ≈ 1600 mT (typical).
        For custom materials supply your own B_sat_mT and mu_r.
    A_e_mm2 : float
        Effective cross-sectional area [mm²].  Used for inductance estimation;
        not required for the saturation check (Ampere's law uses l_e only).
    l_e_mm : float
        Effective magnetic path length [mm].  Must be > 0.
    B_sat_mT : float
        Saturation flux density [mT] at the reference temperature (25°C).
        Will be derated for ferrite materials when temperature_C > 25.
    mu_r : float
        Relative permeability of the core (initial, small-signal value).
        Must be > 0.  NOTE: μ_r is assumed constant in this model; real
        ferrite μ_r rolls off significantly before B_sat is reached.
    """
    material: str
    A_e_mm2: float
    l_e_mm: float
    B_sat_mT: float
    mu_r: float


@dataclass
class InductorCurrentSpec:
    """Electrical operating conditions for the inductor.

    Attributes
    ----------
    turns_N : int
        Number of turns.  Must be >= 1.
    I_dc_A : float
        DC bias (average) current [A].  Must be >= 0.
    I_ripple_peak_to_peak_A : float
        Peak-to-peak AC ripple current [A].  Must be >= 0.
        The peak current is: I_pk = I_dc + I_ripple_pp / 2.
    temperature_C : float
        Core / winding temperature [°C].  Default 25.0.
        Used for B_sat temperature derating (ferrite only).
    """
    turns_N: int
    I_dc_A: float
    I_ripple_peak_to_peak_A: float
    temperature_C: float = 25.0


@dataclass
class CoreSaturationReport:
    """Result of the inductor core saturation check.

    Attributes
    ----------
    B_peak_mT : float
        Computed peak flux density [mT].
        B_pk = μ₀·μ_r·N·I_pk / l_e   (Ampere's law, homogeneous path).
    B_sat_mT : float
        Effective saturation flux density [mT] at the operating temperature
        (B_sat_ref derated for ferrite if temperature > 25°C).
    saturation_margin_pct : float
        Margin to saturation [%].
        = (B_sat − B_pk) / B_sat × 100.
        Positive → not saturated; negative → saturated.
    saturated : bool
        True when B_pk >= B_sat (core is saturated or at the boundary).
    recommended_max_I_dc_A : float
        Maximum DC bias current [A] that keeps the core just below B_sat
        (B_pk = 0.99 × B_sat as a 1% guard-band):
        I_pk_max = 0.99 × B_sat × l_e / (μ₀ × μ_r × N)
        I_dc_max = I_pk_max − I_ripple_pp / 2  (floored at 0).
    honest_caveat : str
        Engineering caveats — fringing flux ignored, constant μ_r, temperature
        derating notes, reference standard deviations.
    """
    B_peak_mT: float
    B_sat_mT: float
    saturation_margin_pct: float
    saturated: bool
    recommended_max_I_dc_A: float
    honest_caveat: str


# ── Temperature derating ───────────────────────────────────────────────────────

# Piecewise linear B_sat derating for ferrite materials only.
# (T_°C, fraction_of_25C_B_sat) breakpoints
_FERRITE_BSAT_DERATING: list[tuple[float, float]] = [
    (25.0, 1.00),
    (100.0, 0.85),
    (125.0, 0.75),
    (150.0, 0.60),
    (200.0, 0.50),
]


def _ferrite_bsat_factor(temperature_C: float) -> float:
    """Return the B_sat derating factor for ferrite at temperature_C.

    Linear interpolation between the breakpoints in _FERRITE_BSAT_DERATING.
    Below 25°C returns 1.0 (conservative; real ferrites improve slightly at low T).
    Above 200°C extrapolates linearly from the last segment.
    """
    pts = _FERRITE_BSAT_DERATING
    if temperature_C <= pts[0][0]:
        return pts[0][1]
    for i in range(len(pts) - 1):
        t0, f0 = pts[i]
        t1, f1 = pts[i + 1]
        if t0 <= temperature_C <= t1:
            alpha = (temperature_C - t0) / (t1 - t0)
            return f0 + alpha * (f1 - f0)
    # Extrapolate beyond last point
    t0, f0 = pts[-2]
    t1, f1 = pts[-1]
    alpha = (temperature_C - t0) / (t1 - t0)
    return f0 + alpha * (f1 - f0)


# ── Validation ─────────────────────────────────────────────────────────────────


def _validate_inputs(core: InductorCoreSpec, current: InductorCurrentSpec) -> str | None:
    """Return an error string or None if inputs are valid."""
    if not isinstance(core, InductorCoreSpec):
        return "core must be an InductorCoreSpec instance"
    if not isinstance(current, InductorCurrentSpec):
        return "current must be an InductorCurrentSpec instance"

    if core.A_e_mm2 <= 0:
        return f"A_e_mm2 must be > 0, got {core.A_e_mm2}"
    if core.l_e_mm <= 0:
        return f"l_e_mm must be > 0, got {core.l_e_mm}"
    if core.B_sat_mT <= 0:
        return f"B_sat_mT must be > 0, got {core.B_sat_mT}"
    if core.mu_r <= 0:
        return f"mu_r must be > 0, got {core.mu_r}"

    if current.turns_N < 1:
        return f"turns_N must be >= 1, got {current.turns_N}"
    if current.I_dc_A < 0:
        return f"I_dc_A must be >= 0, got {current.I_dc_A}"
    if current.I_ripple_peak_to_peak_A < 0:
        return f"I_ripple_peak_to_peak_A must be >= 0, got {current.I_ripple_peak_to_peak_A}"

    return None


# ── Core calculation ───────────────────────────────────────────────────────────


def check_inductor_saturation(
    core: InductorCoreSpec,
    current: InductorCurrentSpec,
) -> CoreSaturationReport:
    """Check whether an inductor core is saturated at the given operating point.

    Formula (Ampere's law, uniform magnetic path):
        I_pk  = I_dc + I_ripple_pp / 2
        B_pk  = μ₀ · μ_r · N · I_pk / l_e   [T]
        saturated = B_pk >= B_sat

    Parameters
    ----------
    core : InductorCoreSpec
        Core material and geometry.
    current : InductorCurrentSpec
        Electrical operating conditions (turns, DC bias, ripple, temperature).

    Returns
    -------
    CoreSaturationReport
        B_peak_mT, B_sat_mT (derated if ferrite), saturation_margin_pct,
        saturated, recommended_max_I_dc_A, honest_caveat.

    Raises
    ------
    ValueError
        On invalid inputs.
    """
    err = _validate_inputs(core, current)
    if err:
        raise ValueError(err)

    # ── Unit conversions ──────────────────────────────────────────────────────
    l_e_m = core.l_e_mm * 1e-3          # mm → m

    # ── B_sat temperature derating ─────────────────────────────────────────────
    is_ferrite = core.material.lower().startswith("ferrite")
    if is_ferrite:
        derating_factor = _ferrite_bsat_factor(current.temperature_C)
    else:
        derating_factor = 1.0  # not modelled for other materials

    B_sat_eff_mT = core.B_sat_mT * derating_factor
    B_sat_eff_T = B_sat_eff_mT * 1e-3  # mT → T

    # ── Peak current ──────────────────────────────────────────────────────────
    I_pk = current.I_dc_A + current.I_ripple_peak_to_peak_A / 2.0

    # ── Peak flux density ─────────────────────────────────────────────────────
    # B = μ₀ · μ_r · N · I / l_e  (Ampere's law, closed toroid, uniform path)
    B_pk_T = _MU0 * core.mu_r * current.turns_N * I_pk / l_e_m
    B_pk_mT = B_pk_T * 1e3              # T → mT

    # ── Saturation check ──────────────────────────────────────────────────────
    saturated = B_pk_mT >= B_sat_eff_mT
    saturation_margin_pct = (B_sat_eff_mT - B_pk_mT) / B_sat_eff_mT * 100.0

    # ── Recommended max I_dc ──────────────────────────────────────────────────
    # Apply 1% guard-band: B_pk_max = 0.99 × B_sat_eff
    B_pk_max_T = 0.99 * B_sat_eff_T
    I_pk_max = B_pk_max_T * l_e_m / (_MU0 * core.mu_r * current.turns_N)
    I_dc_max = max(0.0, I_pk_max - current.I_ripple_peak_to_peak_A / 2.0)

    # ── Assemble honest caveat ─────────────────────────────────────────────────
    caveat_parts: list[str] = []

    # Summary line
    caveat_parts.append(
        f"Inductor core saturation check ({core.material}): "
        f"B_pk={B_pk_mT:.2f} mT, B_sat_eff={B_sat_eff_mT:.1f} mT "
        f"(ref={core.B_sat_mT:.1f} mT × derating={derating_factor:.3f}), "
        f"margin={saturation_margin_pct:.1f}%, "
        f"I_pk={I_pk:.4f} A (I_dc={current.I_dc_A} A + ripple/2={current.I_ripple_peak_to_peak_A / 2:.4f} A), "
        f"N={current.turns_N}, l_e={core.l_e_mm:.1f} mm, mu_r={core.mu_r:.0f}, T={current.temperature_C} °C. "
    )

    if saturated:
        caveat_parts.append(
            f"FAIL — CORE SATURATED: B_pk ({B_pk_mT:.2f} mT) >= B_sat_eff ({B_sat_eff_mT:.1f} mT). "
            f"Recommended max I_dc = {I_dc_max:.4f} A (1% guard-band below B_sat). "
        )
    else:
        caveat_parts.append(
            f"PASS — not saturated; {saturation_margin_pct:.1f}% margin. "
            f"Recommended max I_dc = {I_dc_max:.4f} A (1% guard-band below B_sat). "
        )

    # Ferrite derating note
    if is_ferrite:
        if current.temperature_C > 25.0:
            caveat_parts.append(
                f"FERRITE DERATING applied: B_sat reduced by {(1.0 - derating_factor) * 100:.1f}% "
                f"at T={current.temperature_C} °C (piecewise-linear model: "
                f"100°C→−15%, 125°C→−25%, 150°C→−40%, 200°C→−50%). "
            )
        if current.temperature_C > 150.0:
            caveat_parts.append(
                "WARNING: T > 150°C — B_sat derating is extrapolated beyond datasheet; "
                "verify against actual Ferroxcube datasheet curve. "
            )
    else:
        caveat_parts.append(
            f"NOTE: B_sat temperature derating NOT applied for {core.material} — "
            "powder-iron and NiFe alloys have their own thermal derating curves "
            "(Magnetics Inc. §3; Micrometals catalog); assume B_sat_mT is provided "
            "at the worst-case operating temperature. "
        )

    # Mandatory honest caveats
    caveat_parts.append(
        "HONEST: "
        "(1) FRINGING FLUX IGNORED — real gapped cores (boost/flyback inductors) "
        "have fringing fields that reduce effective μ_r and create localised "
        "field spikes near the gap; add Dowell/Erickson §15.3 gap fringing "
        "correction for gapped designs. "
        "(2) μ_r ASSUMED CONSTANT — actual ferrite μ_r (and soft magnetic alloys) "
        "rolls off substantially in the knee region of the B-H curve BEFORE B_sat "
        "is reached (may be 50% lower at 70-80% of B_sat); this model uses the "
        "user-supplied initial μ_r, giving a conservative (over-estimated) B_pk — "
        "the true B_pk is typically lower because flux flattens in the knee. "
        "For accurate results use the nonlinear B-H curve from the material datasheet. "
        "(3) FORMULA: B = μ₀·μ_r·N·I_pk/l_e (Ampere's law, closed uniform path, "
        "Erickson 3e §15 + McLyman §10). A_e is NOT used in the saturation formula "
        "(it appears in L = μ₀·μ_r·N²·A_e/l_e, not in the H-field calculation). "
        "(4) WINDING TEMPERATURE RISE from I²R heating is NOT modelled; elevated "
        "winding temperature increases core temperature beyond the ambient and further "
        "derate B_sat. "
        "(5) AC CORE LOSSES (hysteresis + eddy current) per Steinmetz "
        "P = Cm·f^x·(ΔB/2)^y·V_e are NOT computed here. "
        "Refs: Erickson 3e §15; McLyman 4e §10; Ferroxcube 3C95/3F36 datasheets; "
        "Magnetics Inc. Powder Core Catalog §3."
    )

    return CoreSaturationReport(
        B_peak_mT=round(B_pk_mT, 4),
        B_sat_mT=round(B_sat_eff_mT, 4),
        saturation_margin_pct=round(saturation_margin_pct, 4),
        saturated=saturated,
        recommended_max_I_dc_A=round(I_dc_max, 6),
        honest_caveat="".join(caveat_parts),
    )


# ── Dict-in / dict-out wrapper ────────────────────────────────────────────────


def check_inductor_saturation_from_dict(d: dict) -> dict:
    """Dict-in / dict-out wrapper for LLM / HTTP callers.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    Never raises.
    """
    try:
        core = InductorCoreSpec(
            material=str(d.get("material", "unknown")),
            A_e_mm2=float(d["A_e_mm2"]),
            l_e_mm=float(d["l_e_mm"]),
            B_sat_mT=float(d["B_sat_mT"]),
            mu_r=float(d["mu_r"]),
        )
        current = InductorCurrentSpec(
            turns_N=int(d["turns_N"]),
            I_dc_A=float(d["I_dc_A"]),
            I_ripple_peak_to_peak_A=float(d["I_ripple_peak_to_peak_A"]),
            temperature_C=float(d.get("temperature_C", 25.0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid spec: {exc}"}

    try:
        report = check_inductor_saturation(core, current)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "B_peak_mT": report.B_peak_mT,
        "B_sat_mT": report.B_sat_mT,
        "saturation_margin_pct": report.saturation_margin_pct,
        "saturated": report.saturated,
        "recommended_max_I_dc_A": report.recommended_max_I_dc_A,
        "honest_caveat": report.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────

_INDUCTOR_SAT_SPEC = ToolSpec(
    name="electronics_check_inductor_saturation",
    description=(
        "Check whether an inductor's magnetic core is saturated given the core "
        "material, geometry (A_e, l_e, B_sat), turn count N, and peak DC + ripple "
        "current.\n\n"
        "Formula (Ampere's law, closed uniform magnetic path):\n"
        "  I_pk   = I_dc + I_ripple_pp / 2\n"
        "  B_pk   = μ₀ · μ_r · N · I_pk / l_e     [l_e in metres]\n"
        "  margin = (B_sat − B_pk) / B_sat × 100   [%]\n\n"
        "Temperature derating: B_sat is reduced for ferrite materials above 25°C\n"
        "  (piecewise-linear: 100°C→−15%, 125°C→−25%, 150°C→−40%, 200°C→−50%\n"
        "  per Ferroxcube 3C95/3F36 datasheets). Not applied to powder-iron/Sendust/NiFe.\n\n"
        "Reports: B_peak_mT, B_sat_mT (derated), saturation_margin_pct, saturated,\n"
        "recommended_max_I_dc_A (1% guard-band), honest_caveat.\n\n"
        "HONEST: fringing flux around air gaps ignored; μ_r assumed constant "
        "(real ferrite μ_r rolls off in knee region BEFORE B_sat — model is "
        "conservative/over-estimates B_pk); non-ferrite B_sat derating NOT modelled; "
        "winding I²R heating NOT accounted for; AC core losses NOT computed.\n\n"
        "Refs: Erickson 'Power Electronics' 3e §15; McLyman 'Transformer and "
        "Inductor Design Handbook' 4e §10; Ferroxcube 3C95/3F36 datasheets.\n\n"
        "Input: { material, A_e_mm2, l_e_mm, B_sat_mT, mu_r, turns_N, I_dc_A, "
        "I_ripple_peak_to_peak_A, [temperature_C=25.0] }\n\n"
        "Returns: { ok, B_peak_mT, B_sat_mT, saturation_margin_pct, saturated, "
        "recommended_max_I_dc_A, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "material": {
                "type": "string",
                "description": (
                    "Core material identifier. "
                    "Supported: 'ferrite_3C95', 'ferrite_3F36', 'powdered_iron_-26', "
                    "'sendust', 'NiFe50'. "
                    "For custom materials provide B_sat_mT and mu_r explicitly."
                ),
            },
            "A_e_mm2": {
                "type": "number",
                "description": (
                    "Effective core cross-sectional area [mm²]. Must be > 0. "
                    "From the core datasheet (e.g. ETD49 → 211 mm²). "
                    "Not used in the saturation formula but captured for reference."
                ),
            },
            "l_e_mm": {
                "type": "number",
                "description": (
                    "Effective magnetic path length [mm]. Must be > 0. "
                    "From the core datasheet (e.g. ETD49 → 114 mm)."
                ),
            },
            "B_sat_mT": {
                "type": "number",
                "description": (
                    "Saturation flux density at 25°C [mT]. Must be > 0. "
                    "Typical: ferrite_3C95 ≈ 500 mT, ferrite_3F36 ≈ 380 mT, "
                    "powdered_iron_-26 ≈ 1400 mT, sendust ≈ 1000 mT, NiFe50 ≈ 1600 mT."
                ),
            },
            "mu_r": {
                "type": "number",
                "description": (
                    "Initial relative permeability of the core (small-signal). "
                    "Must be > 0. "
                    "Typical: ferrite_3C95 ≈ 2000, ferrite_3F36 ≈ 1500, "
                    "powdered_iron_-26 ≈ 75, sendust ≈ 125, NiFe50 ≈ 3000. "
                    "NOTE: real ferrite μ_r rolls off significantly before B_sat — "
                    "this model uses a constant μ_r (conservative/over-estimates B_pk)."
                ),
            },
            "turns_N": {
                "type": "integer",
                "description": "Number of turns. Must be >= 1.",
            },
            "I_dc_A": {
                "type": "number",
                "description": "DC bias (average) current [A]. Must be >= 0.",
            },
            "I_ripple_peak_to_peak_A": {
                "type": "number",
                "description": (
                    "Peak-to-peak AC ripple current [A]. Must be >= 0. "
                    "Peak current = I_dc + I_ripple_pp / 2."
                ),
            },
            "temperature_C": {
                "type": "number",
                "description": (
                    "Core operating temperature [°C]. Default 25.0. "
                    "Used for B_sat derating (ferrite materials only). "
                    "Elevated temperature reduces B_sat significantly for ferrites."
                ),
            },
        },
        "required": [
            "A_e_mm2",
            "l_e_mm",
            "B_sat_mT",
            "mu_r",
            "turns_N",
            "I_dc_A",
            "I_ripple_peak_to_peak_A",
        ],
    },
)


@register(_INDUCTOR_SAT_SPEC, write=False)
async def electronics_check_inductor_saturation(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = check_inductor_saturation_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ────────────────────────

TOOLS = [
    (
        _INDUCTOR_SAT_SPEC.name,
        _INDUCTOR_SAT_SPEC,
        electronics_check_inductor_saturation,
    ),
]
