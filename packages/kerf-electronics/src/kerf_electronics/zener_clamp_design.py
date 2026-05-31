"""
Zener-diode voltage clamp + series resistor design.

Designs a simple Zener shunt regulator / voltage clamp for a DC supply rail
given input voltage range and load current extremes.  Computes the series
resistor value, series resistor power rating, peak Zener current, peak Zener
power, and recommends a Zener package power rating and nearest E12 series
resistor.

Topology (H&H §2.2.4)
-----------------------

        R_series
 V_in ─┤ ══════ ├─── V_out (≈ V_zener)
                 │
                 ├── I_load
                 │
                [Dz]  (Zener, cathode toward V_out)
                 │
                GND

The Zener clamps V_out ≈ V_zener by shunting the excess current from R_series
that is not consumed by the load.

Design equations (Horowitz & Hill "Art of Electronics" §2.2.4,
Vishay Application Note AN-2014-3)
----------------------------------------------------------------------

  Worst-case for R_series sizing: maximum V_in, minimum I_load
  (gives maximum Zener current — ensures Zener stays in regulation
  at the given minimum load current I_zener_min_A used as the
  knee-current guard):

    R_series = (V_in_max − V_Z) / (I_load_min + I_zener_knee)

  For a practical design we use I_zener_knee = I_zener_min_A (default 1 mA),
  the minimum current to keep the Zener in hard regulation.

  Peak Zener current (worst case: max V_in, min I_load):
    I_zener_max = (V_in_max − V_Z_max) / R_series − I_load_min

  where V_Z_max = V_zener × (1 + V_zener_tolerance_pct/100) accounts for
  the Zener voltage upper tolerance, which gives the most pessimistic
  (highest) I_zener current.

  Peak Zener power (with 25 % derating margin per AN-2014-3 §3):
    P_zener_design = V_zener × I_zener_max × 1.25

  Series resistor power (worst case: max V_in, min I_load):
    V_R = V_in_max − V_zener
    I_R  = I_load_min + I_zener_max
    P_R   = V_R × I_R

  Regulation:
    V_out_min = V_Z_min = V_zener × (1 − V_zener_tolerance_pct/100)
    V_out_max = V_Z_max = V_zener × (1 + V_zener_tolerance_pct/100)
    regulation_pct = 100 × (V_out_max − V_out_min) / V_zener
                   = 2 × V_zener_tolerance_pct   (symmetric about nominal)

  NOTE: this only captures the static tolerance regulation; the dynamic
  (load / line) regulation from Zener incremental resistance rZ is NOT
  modelled here — see honest_caveat.

Zener package selection (Vishay AN-2014-3 §3 + industry standards)
--------------------------------------------------------------------
Standard through-hole / SMD Zener power packages:
  DO-35 / SOD-80 → 0.4 W (BZX55 series, Vishay 1N47xx 400 mW)
  DO-41 / SOD-81 → 0.5 W (1N47xx 500 mW; BZX79 series)
  DO-41 (1W)     → 1 W   (1N4728–1N4764; BZX85 series)
  DO-201 / P600  → 3 W   (BZX3C, 1N5985–1N6004 series)
  SOT-89 / TO-252→ 5 W   (1N5333–1N5388B; BZX8C5V6 series)

Package thresholds applied to P_zener_design (with 25 % margin already in):
  ≤ 0.40 W → 0.4 W
  ≤ 0.50 W → 0.5 W
  ≤ 1.00 W → 1 W
  ≤ 3.00 W → 3 W
  ≤ 5.00 W → 5 W
  > 5.00 W → flag error (discrete Zener shunt not appropriate; use LDO/buck)

HONEST CAVEATS (always reported)
---------------------------------
1. LINEAR SHUNT REGULATOR — a Zener shunt regulator is inherently lossy.
   P_wasted = (V_in − V_Z) × I_R_total regardless of load draw.  At zero
   load the full supply current flows through the Zener.  For I_load > 100 mA
   or where efficiency matters, use an LDO linear regulator or a switching
   buck converter instead.

2. Zener incremental resistance (rZ) is NOT modelled.  A real Zener's output
   voltage rises with current: ΔV_out = rZ × ΔI_Z.  For precision references
   use a TL431 or a shunt reference IC.  Typical rZ for 5 V / 400 mW Zeners:
   ~7–20 Ω (BZX55C5V1 datasheet; Vishay AN-2014-3 §2.2).

3. Temperature coefficient of V_Z is NOT modelled.  Below ~5 V Zeners have
   negative TC; above ~5.6 V they have positive TC.  At ≈ 5.1 V TC ≈ 0
   (Horowitz & Hill §2.2.4 Table 2.1).  For temperature-stable references,
   select a 5.1 V Zener or use a bandgap reference.

4. The 25 % power derating margin follows Vishay AN-2014-3 §3 "derate to
   75 % of P_D max".  This is a steady-state recommendation; pulse-power
   handling requires transient thermal impedance analysis (JEDEC JESD51-2).

5. Zener voltage tolerance sets V_out accuracy.  Standard Zeners are ±5 %
   (C-suffix), ±2 % (B-suffix), ±1 % (A-suffix).  Use spec.V_zener_tolerance_pct
   to model the appropriate grade.

6. I_load must not exceed I_load_max_A or V_out will collapse below V_zener
   because the Zener goes below its knee current.  This tool does NOT model
   sub-knee behaviour (soft regulation region).

References
----------
P. Horowitz & W. Hill, "The Art of Electronics", 3rd ed. §2.2.4,
    Cambridge University Press, 2015.
Vishay Application Note AN-2014-3, "Zener Diode Voltage Regulator Design",
    Rev. 1.0, 2014.
Vishay BZX55 series datasheet (DO-35, 400 mW); 1N4728–1N4764 datasheet
    (DO-41, 1 W); BZX85 series datasheet (DO-41, 1.3 W / 1 W rated).

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ── E12 resistor series ───────────────────────────────────────────────────────
# IEC 60063 E12: 10 values per decade (12 preferred numbers).
_E12_BASE: list[float] = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]


def _e12_nearest(value_ohm: float) -> float:
    """Return the nearest E12 resistor value (any decade) >= value_ohm.

    If *value_ohm* <= 0 return 1.0 Ω.
    Searches ±2 decades around the estimated decade then returns the smallest
    E12 value that is >= value_ohm (round-up, for conservative power/current).
    """
    if value_ohm <= 0:
        return 1.0
    # Decade exponent
    decade = math.floor(math.log10(value_ohm))
    best: Optional[float] = None
    # Search from (decade-1) to (decade+2) to catch boundary cases
    for d in range(decade - 1, decade + 3):
        multiplier = 10.0 ** d
        for base in _E12_BASE:
            candidate = round(base * multiplier, 12)
            if candidate >= value_ohm * 0.9999:  # allow floating-point fuzz
                if best is None or candidate < best:
                    best = candidate
    return best if best is not None else value_ohm


# ── Zener package thresholds ─────────────────────────────────────────────────
# (P_max_W, label) in ascending order.
_ZENER_PACKAGES: list[tuple[float, str]] = [
    (0.40, "0.4W"),
    (0.50, "0.5W"),
    (1.00, "1W"),
    (3.00, "3W"),
    (5.00, "5W"),
]


def _select_package(p_design_w: float) -> str:
    """Return the smallest Zener package string that handles *p_design_w*."""
    for p_max, label in _ZENER_PACKAGES:
        if p_design_w <= p_max:
            return label
    return "EXCEEDS_5W"


# ── Default knee current ──────────────────────────────────────────────────────
_I_ZENER_KNEE_DEFAULT_A: float = 1e-3   # 1 mA minimum knee current


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class ZenerClampSpec:
    """Input specification for a Zener shunt voltage clamp design.

    Attributes
    ----------
    V_in_min_V : float
        Minimum supply input voltage [V].  Must be > V_zener_V.
    V_in_max_V : float
        Maximum supply input voltage [V].  Must be >= V_in_min_V.
    V_zener_V : float
        Nominal Zener breakdown voltage [V].  Typical values: 2.4–47 V.
    I_load_min_A : float
        Minimum DC load current drawn from V_out [A].  May be 0.
    I_load_max_A : float
        Maximum DC load current drawn from V_out [A].  Must be >= I_load_min_A.
    V_zener_tolerance_pct : float
        Zener voltage tolerance [%], one-sided.  Default 5.0 (±5 %, C-suffix).
        Use 2.0 for B-suffix, 1.0 for A-suffix.
    I_zener_knee_A : float
        Minimum Zener current to ensure hard regulation [A].
        Default 1 mA.  Vishay AN-2014-3 §2 recommends 1–5 % of I_Z_max.
    """
    V_in_min_V: float
    V_in_max_V: float
    V_zener_V: float
    I_load_min_A: float
    I_load_max_A: float
    V_zener_tolerance_pct: float = 5.0
    I_zener_knee_A: float = field(default=_I_ZENER_KNEE_DEFAULT_A)


@dataclass
class ZenerClampReport:
    """Result of a Zener shunt voltage clamp design calculation.

    Attributes
    ----------
    R_series_ohm : float
        Computed series resistor value [Ω] (exact; see recommended_R_E12_ohm
        for the nearest standard value).
    R_series_power_W : float
        Required series resistor power rating [W] (worst-case, steady-state).
    I_zener_max_A : float
        Peak Zener current [A] (worst case: V_in_max, I_load_min).
    P_zener_max_W : float
        Peak Zener power WITH 25 % derating margin [W]
        (= V_zener × I_zener_max × 1.25; Vishay AN-2014-3 §3).
    recommended_zener_package : str
        Smallest standard Zener package that handles P_zener_max_W.
        One of: "0.4W", "0.5W", "1W", "3W", "5W", "EXCEEDS_5W".
    recommended_R_E12_ohm : float
        Nearest E12 series resistor value >= R_series_ohm [Ω].
    regulation_pct : float
        Static V_out variation due to Zener tolerance [%].
        = 2 × V_zener_tolerance_pct (symmetric ±tolerance).
        Does NOT include dynamic regulation from Zener rZ.
    honest_caveat : str
        Engineering caveats the caller must acknowledge.
    """
    R_series_ohm: float
    R_series_power_W: float
    I_zener_max_A: float
    P_zener_max_W: float
    recommended_zener_package: str
    recommended_R_E12_ohm: float
    regulation_pct: float
    honest_caveat: str


# ── Input validation ──────────────────────────────────────────────────────────


def _validate_spec(spec: ZenerClampSpec) -> Optional[str]:
    """Return an error string or None if inputs are valid."""
    if not isinstance(spec, ZenerClampSpec):
        return "spec must be a ZenerClampSpec instance"
    if spec.V_zener_V <= 0:
        return f"V_zener_V must be > 0, got {spec.V_zener_V}"
    if spec.V_in_min_V <= spec.V_zener_V:
        return (
            f"V_in_min_V ({spec.V_in_min_V} V) must be > V_zener_V "
            f"({spec.V_zener_V} V) to forward-bias the regulator"
        )
    if spec.V_in_max_V < spec.V_in_min_V:
        return (
            f"V_in_max_V ({spec.V_in_max_V} V) must be >= "
            f"V_in_min_V ({spec.V_in_min_V} V)"
        )
    if spec.I_load_min_A < 0:
        return f"I_load_min_A must be >= 0, got {spec.I_load_min_A}"
    if spec.I_load_max_A < spec.I_load_min_A:
        return (
            f"I_load_max_A ({spec.I_load_max_A} A) must be >= "
            f"I_load_min_A ({spec.I_load_min_A} A)"
        )
    if not (0 < spec.V_zener_tolerance_pct < 50):
        return (
            f"V_zener_tolerance_pct must be in (0, 50), "
            f"got {spec.V_zener_tolerance_pct}"
        )
    if spec.I_zener_knee_A < 0:
        return f"I_zener_knee_A must be >= 0, got {spec.I_zener_knee_A}"
    return None


# ── Core design function ───────────────────────────────────────────────────────


def design_zener_clamp(spec: ZenerClampSpec) -> ZenerClampReport:
    """Design a Zener diode voltage clamp + series resistor.

    Algorithm (Horowitz & Hill §2.2.4 + Vishay AN-2014-3)
    -------------------------------------------------------

    1. Series resistor (sized for worst-case: max V_in, min I_load):
       R = (V_in_max − V_Z) / (I_load_min + I_zener_knee)

    2. Peak Zener current (max V_in, min I_load, worst-case V_Z_max):
       V_Z_max = V_zener × (1 + tol/100)
       I_Z_max = (V_in_max − V_Z_max) / R − I_load_min

    3. Series resistor worst-case power (max V_in, any load):
       V_R = V_in_max − V_zener
       I_R  = I_load_min + I_Z_max      [same worst case as I_Z_max calc]
       P_R  = V_R × I_R

    4. Zener peak power with 25 % margin (Vishay AN-2014-3 §3):
       P_Z_design = V_zener × I_Z_max × 1.25

    5. Package selection from P_Z_design vs standard ratings.

    6. E12 nearest series resistor (round up for conservative power).

    7. Static regulation = 2 × V_zener_tolerance_pct [%].

    Parameters
    ----------
    spec : ZenerClampSpec

    Returns
    -------
    ZenerClampReport

    Raises
    ------
    ValueError
        On invalid or physically inconsistent inputs.
    """
    err = _validate_spec(spec)
    if err:
        raise ValueError(err)

    vz = spec.V_zener_V
    vin_max = spec.V_in_max_V
    vin_min = spec.V_in_min_V
    il_min = spec.I_load_min_A
    il_max = spec.I_load_max_A
    tol = spec.V_zener_tolerance_pct
    i_knee = spec.I_zener_knee_A

    # ── 1. Series resistor ────────────────────────────────────────────────────
    # Denominator: current through R at worst case (max Vin, min Iload).
    # Total current = I_load_min + I_zener_knee (keeps Zener in regulation).
    i_r_design = il_min + i_knee
    if i_r_design <= 0:
        # Edge case: zero load, zero knee — use a minimum of 1 mA
        i_r_design = 1e-3

    R = (vin_max - vz) / i_r_design

    if R <= 0:
        raise ValueError(
            f"Computed R_series <= 0 ({R:.4f} Ω): "
            f"V_in_max ({vin_max} V) must be > V_zener ({vz} V)"
        )

    # ── 2. Peak Zener current ────────────────────────────────────────────────
    # Use V_Z_max (upper tolerance) to give most current through Zener.
    vz_max = vz * (1.0 + tol / 100.0)
    i_z_max = (vin_max - vz_max) / R - il_min
    # Guard: if tolerance pushes Vz_max very close to Vin_max, clamp to >= 0
    if i_z_max < 0.0:
        i_z_max = 0.0

    # ── 3. Series resistor worst-case power ──────────────────────────────────
    # V across R = V_in_max − V_zener (use nominal; worst-case current below)
    v_r = vin_max - vz
    i_r_peak = i_z_max + il_min
    p_r = v_r * i_r_peak

    # ── 4. Zener peak power with 25 % design margin ──────────────────────────
    p_z_design = vz * i_z_max * 1.25

    # ── 5. Package selection ─────────────────────────────────────────────────
    pkg = _select_package(p_z_design)

    # ── 6. E12 nearest standard resistor ─────────────────────────────────────
    r_e12 = _e12_nearest(R)

    # ── 7. Static regulation ─────────────────────────────────────────────────
    regulation_pct = 2.0 * tol   # ±tol% → total band = 2×tol%

    # ── 8. Honest caveat ─────────────────────────────────────────────────────
    load_flag = ""
    if il_max > 0.1:
        load_flag = (
            f" WARNING: I_load_max = {il_max*1000:.0f} mA > 100 mA — "
            "a Zener shunt regulator is highly inefficient at this load "
            "(wasted power = (V_in_max−V_Z)×I_R_total regardless of load). "
            "STRONGLY recommend an LDO linear regulator (e.g. LM1117, "
            "MCP1700) or a buck DC-DC converter instead."
        )
    exceeds_flag = ""
    if pkg == "EXCEEDS_5W":
        exceeds_flag = (
            " CRITICAL: P_zener_max > 5 W — no standard discrete Zener shunt "
            "regulator is appropriate. Use an LDO or switching regulator."
        )

    caveat = (
        f"Zener shunt regulator: V_in=[{vin_min}..{vin_max}] V, "
        f"V_Z={vz} V ±{tol}%, "
        f"R_series={R:.2f} Ω (E12={r_e12} Ω), "
        f"I_Z_max={i_z_max*1000:.1f} mA, "
        f"P_Z_design={p_z_design*1000:.0f} mW (with 25% margin) → {pkg}."
        " HONEST: "
        "(1) LINEAR SHUNT only — wasted power P=(V_in_max−V_Z)×I_R_total is "
        "independent of load; at zero load ALL current flows through Zener. "
        "For I_load > 100 mA or efficiency-sensitive rails use LDO/buck. "
        "(2) Zener incremental resistance rZ NOT modelled — V_out rises "
        "with I_Z (typical rZ 7–20 Ω for 5 V / 400 mW parts); use TL431 "
        "or a shunt reference IC for tight regulation (H&H §2.2.4; "
        "Vishay AN-2014-3 §2.2). "
        "(3) Temperature coefficient of V_Z NOT modelled — below ~5 V "
        "TC is negative, above ~5.6 V positive; ≈ 5.1 V Zeners have ~0 TC. "
        "(4) 25% power derating per Vishay AN-2014-3 §3 (steady-state); "
        "pulse/transient peak power requires JEDEC JESD51-2 transient "
        "thermal impedance analysis. "
        f"(5) Static regulation = {regulation_pct:.1f}% from Zener tolerance only; "
        "dynamic (load/line) regulation from rZ NOT included. "
        "(6) Sub-knee behaviour (I_Z < I_Z_knee) not modelled — load must "
        f"not exceed I_load_max = {il_max*1000:.0f} mA or clamping collapses. "
        "Refs: H&H §2.2.4; Vishay AN-2014-3."
        + load_flag
        + exceeds_flag
    )

    return ZenerClampReport(
        R_series_ohm=round(R, 6),
        R_series_power_W=round(p_r, 6),
        I_zener_max_A=round(i_z_max, 6),
        P_zener_max_W=round(p_z_design, 6),
        recommended_zener_package=pkg,
        recommended_R_E12_ohm=r_e12,
        regulation_pct=round(regulation_pct, 3),
        honest_caveat=caveat,
    )


# ── Dict-in / dict-out wrapper ────────────────────────────────────────────────


def design_zener_clamp_from_dict(d: dict) -> dict:
    """Dict-in / dict-out wrapper for LLM / HTTP callers.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    Never raises.
    """
    try:
        spec = ZenerClampSpec(
            V_in_min_V=float(d["V_in_min_V"]),
            V_in_max_V=float(d["V_in_max_V"]),
            V_zener_V=float(d["V_zener_V"]),
            I_load_min_A=float(d["I_load_min_A"]),
            I_load_max_A=float(d["I_load_max_A"]),
            V_zener_tolerance_pct=float(d.get("V_zener_tolerance_pct", 5.0)),
            I_zener_knee_A=float(d.get("I_zener_knee_A", _I_ZENER_KNEE_DEFAULT_A)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid spec: {exc}"}

    try:
        report = design_zener_clamp(spec)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "R_series_ohm": report.R_series_ohm,
        "R_series_power_W": report.R_series_power_W,
        "I_zener_max_A": report.I_zener_max_A,
        "P_zener_max_W": report.P_zener_max_W,
        "recommended_zener_package": report.recommended_zener_package,
        "recommended_R_E12_ohm": report.recommended_R_E12_ohm,
        "regulation_pct": report.regulation_pct,
        "honest_caveat": report.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────

_ZENER_CLAMP_SPEC = ToolSpec(
    name="electronics_design_zener_clamp",
    description=(
        "Design a Zener-diode voltage clamp (shunt regulator) + series resistor "
        "for a DC supply rail.\n\n"
        "Computes R_series, peak Zener current, peak Zener power, and recommends "
        "a Zener package power rating and nearest E12 series resistor.\n\n"
        "Topology: V_in → R_series → V_out ≈ V_zener, Zener shunts excess current.\n\n"
        "Design equations (Horowitz & Hill §2.2.4 + Vishay AN-2014-3):\n"
        "  R = (V_in_max − V_Z) / (I_load_min + I_zener_knee)\n"
        "  I_Z_max = (V_in_max − V_Z_max) / R − I_load_min\n"
        "  P_Z_design = V_Z × I_Z_max × 1.25  (25% derating margin)\n"
        "  regulation_pct = 2 × V_zener_tolerance_pct\n\n"
        "Zener packages: 0.4W (DO-35/SOD-80), 0.5W (DO-41), 1W (DO-41/BZX85), "
        "3W (DO-201), 5W (SOT-89/TO-252).\n\n"
        "HONEST: simple linear shunt regulator only — wasted power is constant "
        "regardless of load draw; Zener incremental resistance rZ NOT modelled; "
        "temperature coefficient of V_Z NOT modelled; for I_load > 100 mA "
        "prefer LDO or buck converter.\n\n"
        "Input: { V_in_min_V, V_in_max_V, V_zener_V, I_load_min_A, I_load_max_A, "
        "[V_zener_tolerance_pct=5.0], [I_zener_knee_A=0.001] }\n\n"
        "Returns: { ok, R_series_ohm, R_series_power_W, I_zener_max_A, "
        "P_zener_max_W, recommended_zener_package, recommended_R_E12_ohm, "
        "regulation_pct, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V_in_min_V": {
                "type": "number",
                "description": "Minimum supply input voltage [V]. Must be > V_zener_V.",
            },
            "V_in_max_V": {
                "type": "number",
                "description": "Maximum supply input voltage [V].",
            },
            "V_zener_V": {
                "type": "number",
                "description": "Nominal Zener breakdown voltage [V].",
            },
            "I_load_min_A": {
                "type": "number",
                "description": "Minimum DC load current [A]. May be 0.",
            },
            "I_load_max_A": {
                "type": "number",
                "description": "Maximum DC load current [A].",
            },
            "V_zener_tolerance_pct": {
                "type": "number",
                "description": (
                    "Zener voltage tolerance [%], one-sided. Default 5.0 (±5%, C-suffix). "
                    "Use 2.0 for B-suffix, 1.0 for A-suffix."
                ),
            },
            "I_zener_knee_A": {
                "type": "number",
                "description": (
                    "Minimum Zener current to maintain hard regulation [A]. "
                    "Default 0.001 A (1 mA). "
                    "Vishay AN-2014-3 §2 recommends 1–5% of I_Z_max."
                ),
            },
        },
        "required": [
            "V_in_min_V",
            "V_in_max_V",
            "V_zener_V",
            "I_load_min_A",
            "I_load_max_A",
        ],
    },
)


@register(_ZENER_CLAMP_SPEC, write=False)
async def electronics_design_zener_clamp(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = design_zener_clamp_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ────────────────────────

TOOLS = [
    (
        _ZENER_CLAMP_SPEC.name,
        _ZENER_CLAMP_SPEC,
        electronics_design_zener_clamp,
    ),
]
