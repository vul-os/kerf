"""
NEC 2023 voltage-drop calculator for wire runs.

References:
  - NEC 2023 Chapter 9 Table 8 — DC resistance of conductors (Cu/Al, solid/stranded)
  - NEC 2023 §215.2(A)(1)(b) — recommended max voltage drop: 3% branch circuits,
    5% total (feeder + branch) system
  - NEC 2023 §310.15(B)(2)(a) — resistance increase with temperature (correction
    factor used in ampacity; same conductor data applies here)

Formula:
  Single-phase (2-wire, round-trip):
    V_drop = 2 × I × L × R_per_foot

  Three-phase (line-to-line):
    V_drop = sqrt(3) × I × L × R_per_foot

where R_per_foot is the conductor DC resistance in ohms/foot, optionally
temperature-corrected using the copper/aluminium resistance-temperature formula.

HONEST-FLAG: This calculator uses DC resistance only.  For AC circuits, inductive
reactance (X_L) adds to impedance, especially in larger conductors (≥1/0 AWG) at
60 Hz.  Ignoring X_L may underestimate drop by 5–15% for large conductors.  For a
full AC impedance model, use NEC Chapter 9 Table 9 which lists effective impedance
Z at 0.85 PF for common raceway types.  This implementation is conservative for
small conductors (AWG 14–6) and increasingly optimistic above AWG 2.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# NEC 2023 Chapter 9 Table 8 — DC resistance (Ω/1000 ft) at 75 °F (≈ 24 °C)
# Cu column: stranded THHN (uncoated copper, compacted)
# Al column:  stranded aluminium (compacted)
# Keys: AWG string or kcmil string.
# Values: (cu_resistance, al_resistance) in Ω/1000 ft at 75 °F
#
# Source: NFPA 70-2023, Chapter 9 Table 8.
# ---------------------------------------------------------------------------
_TABLE_8: dict[str, tuple[float, float]] = {
    "14":     (3.07,  None),   # type: ignore[assignment]  # Al <14 not rated
    "12":     (1.93,  3.18),
    "10":     (1.21,  2.00),
    "8":      (0.764, 1.26),
    "6":      (0.491, 0.808),
    "4":      (0.308, 0.508),
    "3":      (0.245, 0.403),
    "2":      (0.194, 0.319),
    "1":      (0.154, 0.253),
    "1/0":    (0.122, 0.201),
    "2/0":    (0.0967, 0.159),
    "3/0":    (0.0766, 0.126),
    "4/0":    (0.0608, 0.100),
    "250":    (0.0515, 0.0847),
    "300":    (0.0429, 0.0707),
    "350":    (0.0367, 0.0605),
    "400":    (0.0321, 0.0529),
    "500":    (0.0258, 0.0424),
    "600":    (0.0214, 0.0353),
    "700":    (0.0184, 0.0303),
    "750":    (0.0171, 0.0282),
}

# Temperature coefficients (per °C above 20 °C) from NEC Chapter 9 Table 8 notes
# α_Cu = 0.00323, α_Al = 0.00330 (per NEC 2023, same as IEC 60228)
_ALPHA_CU = 0.00323   # /°C
_ALPHA_AL = 0.00330   # /°C

# Reference temperature for Table 8 data
_T_REF_C = 24.0   # 75 °F ≈ 24.4 °C (NEC Table 8 header)


@dataclass
class VoltageDropResult:
    """Result of a NEC 2023 voltage-drop calculation."""

    # --- inputs (normalised) ---
    awg: str
    material: Literal["Cu", "Al"]
    run_length_ft: float
    current_amps: float
    voltage: float
    phase: Literal["single", "three"]
    conductor_temp_c: float

    # --- table resistance ---
    r_per_1000ft_at_ref: float
    "Resistance from NEC Ch9 Table 8 at 75 °F, Ω/1000 ft"
    r_per_1000ft_corrected: float
    "Temperature-corrected resistance at conductor_temp_c, Ω/1000 ft"

    # --- results ---
    v_drop_volts: float
    v_drop_percent: float
    within_3_percent: bool
    "NEC §215.2 branch-circuit recommendation: ≤ 3% drop"
    within_5_percent: bool
    "NEC §215.2 total-system recommendation: ≤ 5% drop"

    notes: list[str] = field(default_factory=list)


def _get_resistance(awg: str, material: Literal["Cu", "Al"]) -> float:
    """Return base DC resistance (Ω/1000 ft) from NEC Ch9 Table 8."""
    awg = awg.strip()
    if awg not in _TABLE_8:
        raise ValueError(
            f"Conductor size '{awg}' not in NEC 2023 Chapter 9 Table 8.  "
            f"Supported: {', '.join(_TABLE_8.keys())}"
        )
    cu_r, al_r = _TABLE_8[awg]
    if material == "Cu":
        return cu_r
    # Aluminium
    if al_r is None:
        raise ValueError(
            f"Aluminium conductors are not rated below AWG 12 per NEC; "
            f"got '{awg}'."
        )
    return al_r


def _temperature_correct(r_ref: float, material: Literal["Cu", "Al"], temp_c: float) -> float:
    """
    Correct DC resistance from Table 8 reference temperature to temp_c.

    Formula (NEC Ch9 Table 8 note + Neher-McGrath / IEEE Std 835):
        R(T) = R_ref × [1 + α × (T − T_ref)]

    where T_ref = 75 °F (≈ 24 °C), α = 0.00323/°C (Cu) or 0.00330/°C (Al).
    """
    alpha = _ALPHA_CU if material == "Cu" else _ALPHA_AL
    return r_ref * (1.0 + alpha * (temp_c - _T_REF_C))


def compute_voltage_drop(
    awg: str,
    material: Literal["Cu", "Al"],
    run_length_ft: float,
    current_amps: float,
    voltage: float,
    phase: Literal["single", "three"] = "single",
    conductor_temp_c: float = 75.0,
) -> VoltageDropResult:
    """
    Compute voltage drop for a wire run per NEC 2023.

    Parameters
    ----------
    awg:
        Conductor size — AWG string ('14', '12', ..., '4/0') or kcmil string
        ('250', '300', ..., '750').
    material:
        'Cu' (copper) or 'Al' (aluminium).
    run_length_ft:
        One-way run length in feet.  For single-phase 2-wire the current
        travels this distance twice (out and back), so the formula uses 2 × L.
    current_amps:
        Load current in amperes.
    voltage:
        System voltage (line-to-neutral for single-phase, line-to-line for
        three-phase) used to compute V_drop_percent.  Typical: 120, 208, 240,
        277, 480.
    phase:
        'single' — single-phase 2-wire, V_drop = 2 × I × L × R_per_foot
        'three'  — 3-phase line-to-line, V_drop = √3 × I × L × R_per_foot
    conductor_temp_c:
        Estimated conductor operating temperature in °C.  NEC Table 8 data is
        at 75 °F (≈ 24 °C); this applies the linear resistance-temperature
        correction.  75 °C (the NEC 310.16 column temperature) is the default
        and is conservative for most THHN wiring.

    Returns
    -------
    VoltageDropResult
        Dataclass with V_drop_volts, V_drop_percent, within_3_percent,
        within_5_percent, and advisory notes.

    Notes
    -----
    HONEST-FLAG — AC reactance ignored:
        This calculation uses DC resistance only (NEC Ch9 Table 8).  For AC
        circuits at 60 Hz, inductive reactance X_L can add 5–15% to total
        impedance on conductors ≥ 1/0 AWG.  Use NEC Chapter 9 Table 9
        (effective AC impedance Z at 0.85 PF) for a rigorous AC calculation.
        Small conductors (AWG 14 through 6) are dominated by resistance; the
        DC-only model is adequate for those sizes.

    References
    ----------
    NEC 2023 Chapter 9 Table 8  — DC resistance of conductors.
    NEC 2023 §215.2(A)(1)(b)    — 3% branch-circuit and 5% total system
                                   voltage-drop recommendations.
    """
    if material not in ("Cu", "Al"):
        raise ValueError(f"material must be 'Cu' or 'Al'; got '{material}'")
    if phase not in ("single", "three"):
        raise ValueError(f"phase must be 'single' or 'three'; got '{phase}'")
    if run_length_ft <= 0:
        raise ValueError(f"run_length_ft must be > 0; got {run_length_ft}")
    if current_amps <= 0:
        raise ValueError(f"current_amps must be > 0; got {current_amps}")
    if voltage <= 0:
        raise ValueError(f"voltage must be > 0; got {voltage}")

    r_ref = _get_resistance(awg, material)
    r_corrected = _temperature_correct(r_ref, material, conductor_temp_c)

    # R per foot (Ω/ft)
    r_per_ft = r_corrected / 1000.0

    # Voltage drop
    if phase == "single":
        v_drop = 2.0 * current_amps * run_length_ft * r_per_ft
    else:
        v_drop = math.sqrt(3.0) * current_amps * run_length_ft * r_per_ft

    v_drop_pct = (v_drop / voltage) * 100.0

    within_3 = v_drop_pct <= 3.0
    within_5 = v_drop_pct <= 5.0

    notes: list[str] = [
        "DC resistance only — NEC 2023 Chapter 9 Table 8.  AC reactance (X_L) "
        "ignored; for conductors ≥ 1/0 AWG at 60 Hz X_L can add 5–15% to "
        "impedance.  Use NEC Ch9 Table 9 for full AC impedance.",
        f"NEC §215.2: branch-circuit limit 3%, total-system limit 5%.  "
        f"Drop is {v_drop_pct:.2f}% — "
        f"{'within' if within_3 else 'EXCEEDS'} 3% branch limit, "
        f"{'within' if within_5 else 'EXCEEDS'} 5% system limit.",
    ]

    if conductor_temp_c != _T_REF_C:
        notes.append(
            f"Resistance temperature-corrected from 75 °F ({_T_REF_C} °C) to "
            f"{conductor_temp_c} °C using NEC Ch9 Table 8 α coefficient."
        )

    if not within_3:
        notes.append(
            "EXCEEDS NEC §215.2 3% branch-circuit recommendation.  Consider "
            "a larger conductor or shorter run."
        )
    if not within_5:
        notes.append(
            "EXCEEDS NEC §215.2 5% total-system recommendation.  Conductor "
            "upsizing strongly recommended."
        )

    # Flag large conductors where X_L matters most
    _large_awg = {"1/0", "2/0", "3/0", "4/0", "250", "300", "350", "400",
                  "500", "600", "700", "750"}
    if awg.strip() in _large_awg:
        notes.append(
            f"AWG/kcmil {awg}: inductive reactance is non-negligible at 60 Hz.  "
            "DC-only result may underestimate total impedance drop."
        )

    return VoltageDropResult(
        awg=awg,
        material=material,
        run_length_ft=run_length_ft,
        current_amps=current_amps,
        voltage=voltage,
        phase=phase,
        conductor_temp_c=conductor_temp_c,
        r_per_1000ft_at_ref=r_ref,
        r_per_1000ft_corrected=r_corrected,
        v_drop_volts=v_drop,
        v_drop_percent=v_drop_pct,
        within_3_percent=within_3,
        within_5_percent=within_5,
        notes=notes,
    )
