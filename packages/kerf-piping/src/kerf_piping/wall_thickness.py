"""
kerf_piping.wall_thickness — ASME B31.1 pipe wall thickness sizing.

DISCLAIMER: These calculations implement ASME B31.1 methods from publicly available
engineering references.  They are NOT ASME stamp certified and must NOT be used as
the sole basis for any physical installation without review by a licensed engineer.

References
----------
ASME B31.1-2022 Power Piping, §104.1.2 Eq. (7) — straight pipe minimum thickness.
ASME B31.1-2022 Table 104.1.2-1 — y coefficient vs. material and temperature.
ASME B31.1-2022 Table A-1 — basic allowable stresses for carbon and stainless steel.
ASME B36.10M-2018 — nominal pipe sizes and wall thicknesses (schedules).
Crane TP-410 §7 — pipe wall thickness design.

Key functions
-------------
min_wall_thickness_b31_1        Minimum wall per ASME B31.1 Eq. 7.
recommend_schedule              Map (OD, min_thickness) to nearest ASME schedule.
material_allowable_stress       Allowable stress lookup from ASME B31.1 Table A-1.
compute_thermal_stress          Thermal stress σ_th = E·α·ΔT.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# ASME B31.1 Table A-1 — Basic allowable stress (psi) vs. temperature (°F)
#
# Key:  (material_key, temperature_bin_F)
# Bins: ambient = 70 (room temp), then 400, 500, 600, 650, 700, 750, 800 °F
# Source: ASME B31.1-2022 Table A-1 (selected grades, simplified breakpoints).
#
# NOTE: Real Table A-1 has many more temperature points; the values below
# match the published table at the listed breakpoints.
# ---------------------------------------------------------------------------

# fmt: off
_ALLOWABLE_STRESS_B31_1: Dict[Tuple[str, int], float] = {
    # --- A106 Grade B (carbon steel seamless, SA/ASTM A 106 Gr. B) ---
    # psi values from ASME B31.1-2022 Table A-1 rows for A 106 Gr. B
    ("A106-B",   70): 17_500,
    ("A106-B",  400): 17_500,
    ("A106-B",  500): 17_500,
    ("A106-B",  600): 15_000,
    ("A106-B",  650): 13_800,
    ("A106-B",  700): 12_000,
    ("A106-B",  750): 10_200,
    ("A106-B",  800):  8_000,
    ("A106-B",  850):  6_500,
    ("A106-B",  900):  5_200,

    # --- A53 Grade B (ERW/seamless, lower grade) ---
    ("A53-B",    70): 15_000,
    ("A53-B",   400): 15_000,
    ("A53-B",   500): 14_400,
    ("A53-B",   600): 12_500,
    ("A53-B",   700): 10_000,
    ("A53-B",   750):  8_200,

    # --- A312 TP304 (austenitic stainless, seamless) ---
    # B31.1 Table A-1; austenitic y=0.4 to 900°F then re-check for 304
    ("A312-304",  70): 20_000,
    ("A312-304", 400): 17_300,
    ("A312-304", 500): 16_200,
    ("A312-304", 600): 15_200,
    ("A312-304", 700): 14_500,
    ("A312-304", 750): 14_100,
    ("A312-304", 800): 13_700,
    ("A312-304", 850): 13_300,
    ("A312-304", 900): 12_300,
    ("A312-304", 950): 10_800,

    # --- A312 TP316 (austenitic stainless, seamless) ---
    ("A312-316",  70): 20_000,
    ("A312-316", 400): 18_700,
    ("A312-316", 500): 17_500,
    ("A312-316", 600): 16_500,
    ("A312-316", 700): 15_800,
    ("A312-316", 750): 15_500,
    ("A312-316", 800): 15_000,
    ("A312-316", 850): 14_500,
    ("A312-316", 900): 13_700,
    ("A312-316", 950): 12_200,
}
# fmt: on

# Sorted temperature bins per material key (pre-computed for interpolation)
_TEMP_BINS: Dict[str, list] = {}
for (_mat, _temp), _stress in _ALLOWABLE_STRESS_B31_1.items():
    _TEMP_BINS.setdefault(_mat, [])
    if _temp not in _TEMP_BINS[_mat]:
        _TEMP_BINS[_mat].append(_temp)
for _k in _TEMP_BINS:
    _TEMP_BINS[_k].sort()


# ---------------------------------------------------------------------------
# ASME B31.1 Table 104.1.2-1 — y coefficient
#
# y is a temperature-dependent coefficient used in Eq. 7 to account for
# creep at elevated temperatures.  Values per Table 104.1.2-1.
# ---------------------------------------------------------------------------

def _y_coefficient(material_key: str, temp_F: float) -> float:
    """
    Return the y coefficient from ASME B31.1 Table 104.1.2-1.

    For ferritic steels (A106, A53): y = 0.4 below 900 °F, 0.5 at 900 °F,
    0.7 at 950 °F+.
    For austenitic steels (A312): y = 0.4 below 800 °F, 0.5 at 850 °F+.
    """
    if material_key.startswith("A312"):
        # Austenitic
        if temp_F < 800.0:
            return 0.4
        elif temp_F < 850.0:
            return 0.5
        else:
            return 0.7
    else:
        # Ferritic (A106, A53)
        if temp_F < 900.0:
            return 0.4
        elif temp_F < 950.0:
            return 0.5
        else:
            return 0.7


# ---------------------------------------------------------------------------
# ASME B36.10M wall thickness table (inches) for NPS / schedule lookup
#
# Key: (nps_in, schedule_code)
# NPS in inches (nominal pipe size); schedule codes per ASME B36.10M.
# Values are nominal wall thickness in inches.
# Source: ASME B36.10M-2018 Table 1.
# ---------------------------------------------------------------------------

# fmt: off
_WALL_THICKNESS_IN: Dict[Tuple[float, str], float] = {
    # NPS 0.5 (1/2")
    (0.5,  "40"): 0.109,  (0.5,  "STD"): 0.109,
    (0.5,  "80"): 0.147,  (0.5,  "XS"):  0.147,
    (0.5, "160"): 0.188,  (0.5, "XXS"):  0.294,
    # NPS 0.75 (3/4")
    (0.75,  "40"): 0.113, (0.75,  "STD"): 0.113,
    (0.75,  "80"): 0.154, (0.75,  "XS"):  0.154,
    (0.75, "160"): 0.219, (0.75, "XXS"):  0.308,
    # NPS 1"
    (1.0,  "40"): 0.133,  (1.0,  "STD"): 0.133,
    (1.0,  "80"): 0.179,  (1.0,  "XS"):  0.179,
    (1.0, "160"): 0.250,  (1.0, "XXS"):  0.358,
    # NPS 1.25"
    (1.25,  "40"): 0.140, (1.25,  "STD"): 0.140,
    (1.25,  "80"): 0.191, (1.25,  "XS"):  0.191,
    (1.25, "160"): 0.318, (1.25, "XXS"):  0.382,
    # NPS 1.5"
    (1.5,  "40"): 0.145,  (1.5,  "STD"): 0.145,
    (1.5,  "80"): 0.200,  (1.5,  "XS"):  0.200,
    (1.5, "160"): 0.281,  (1.5, "XXS"):  0.400,
    # NPS 2"
    (2.0,  "40"): 0.154,  (2.0,  "STD"): 0.154,
    (2.0,  "80"): 0.218,  (2.0,  "XS"):  0.218,
    (2.0, "160"): 0.344,  (2.0, "XXS"):  0.436,
    # NPS 2.5"
    (2.5,  "40"): 0.203,  (2.5,  "STD"): 0.203,
    (2.5,  "80"): 0.276,  (2.5,  "XS"):  0.276,
    (2.5, "160"): 0.375,  (2.5, "XXS"):  0.552,
    # NPS 3"
    (3.0,  "40"): 0.216,  (3.0,  "STD"): 0.216,
    (3.0,  "80"): 0.300,  (3.0,  "XS"):  0.300,
    (3.0, "160"): 0.438,  (3.0, "XXS"):  0.600,
    # NPS 4"
    (4.0,  "40"): 0.237,  (4.0,  "STD"): 0.237,
    (4.0,  "80"): 0.337,  (4.0,  "XS"):  0.337,
    (4.0, "120"): 0.438,
    (4.0, "160"): 0.531,  (4.0, "XXS"):  0.674,
    # NPS 6"
    (6.0,  "40"): 0.280,  (6.0,  "STD"): 0.280,
    (6.0,  "80"): 0.432,  (6.0,  "XS"):  0.432,
    (6.0, "120"): 0.562,
    (6.0, "160"): 0.719,  (6.0, "XXS"):  0.864,
    # NPS 8"
    (8.0,  "20"): 0.250,
    (8.0,  "30"): 0.277,
    (8.0,  "40"): 0.322,  (8.0,  "STD"): 0.375,
    (8.0,  "60"): 0.406,
    (8.0,  "80"): 0.500,  (8.0,  "XS"):  0.500,
    (8.0, "100"): 0.594,
    (8.0, "120"): 0.719,
    (8.0, "140"): 0.812,
    (8.0, "160"): 0.906,  (8.0, "XXS"):  0.875,
    # NPS 10"
    (10.0,  "20"): 0.250,
    (10.0,  "30"): 0.307,
    (10.0,  "40"): 0.365, (10.0,  "STD"): 0.365,
    (10.0,  "60"): 0.500,
    (10.0,  "80"): 0.594, (10.0,  "XS"):  0.500,
    (10.0, "100"): 0.719,
    (10.0, "120"): 0.844,
    (10.0, "140"): 1.000,
    (10.0, "160"): 1.125, (10.0, "XXS"):  1.000,
    # NPS 12"
    (12.0,  "20"): 0.250,
    (12.0,  "30"): 0.330,
    (12.0,  "40"): 0.406,
    (12.0, "STD"): 0.375,
    (12.0,  "60"): 0.562,
    (12.0,  "80"): 0.688, (12.0,  "XS"):  0.500,
    (12.0, "100"): 0.844,
    (12.0, "120"): 1.000,
    (12.0, "140"): 1.125,
    (12.0, "160"): 1.312, (12.0, "XXS"):  1.000,
}
# fmt: on

# ASME B36.10M nominal OD (inches) for each NPS size
_NOMINAL_OD_IN: Dict[float, float] = {
    0.5: 0.840,
    0.75: 1.050,
    1.0: 1.315,
    1.25: 1.660,
    1.5: 1.900,
    2.0: 2.375,
    2.5: 2.875,
    3.0: 3.500,
    4.0: 4.500,
    6.0: 6.625,
    8.0: 8.625,
    10.0: 10.75,
    12.0: 12.75,
}

# Schedule preference order (ascending wall thickness, roughly)
_SCHEDULE_ORDER = ["5S", "10S", "20", "30", "40", "STD", "60", "80", "XS",
                   "100", "120", "140", "160", "XXS"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _od_to_nps(diameter_in: float) -> float:
    """
    Map a pipe outside diameter (inches) to the nearest ASME B36.10M NPS size.

    If the input already matches an NPS size exactly (e.g. 6.0) it is returned
    unchanged.  Otherwise the nearest NPS from the OD table is used.

    Parameters
    ----------
    diameter_in  Pipe OD or NPS value (inches).

    Returns
    -------
    NPS size as a float (e.g. 6.0 for a 6" NPS pipe).
    """
    # Build a combined set: NPS values in the wall table + OD→NPS map
    nps_set = set(nps for (nps, _) in _WALL_THICKNESS_IN)

    # If it directly matches an NPS, use it
    for nps in nps_set:
        if math.isclose(diameter_in, nps, rel_tol=1e-3):
            return nps

    # Otherwise find the NPS whose nominal OD is closest to diameter_in
    best_nps = None
    best_diff = float("inf")
    for nps, od in _NOMINAL_OD_IN.items():
        diff = abs(od - diameter_in)
        if diff < best_diff:
            best_diff = diff
            best_nps = nps
    return best_nps if best_nps is not None else diameter_in


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def material_allowable_stress(material: str, temp_F: float) -> float:
    """
    Return the ASME B31.1 Table A-1 basic allowable stress (psi) for the
    given material and temperature.

    Parameters
    ----------
    material  Material key string.  Recognised values:
                'A106-B'    SA/ASTM A 106 Grade B carbon steel (most common)
                'A53-B'     SA/ASTM A 53 Grade B
                'A312-304'  SA/ASTM A 312 TP304 stainless
                'A312-316'  SA/ASTM A 312 TP316 stainless
    temp_F    Design temperature in degrees Fahrenheit.

    Returns
    -------
    Allowable stress in psi (linearly interpolated between table breakpoints).

    Raises
    ------
    KeyError  if material is not in the table.
    ValueError if temp_F exceeds the maximum tabled temperature.

    Notes
    -----
    Values are from ASME B31.1-2022 Table A-1 (selected grades).
    This is NOT ASME stamp certified — for preliminary engineering use only.
    """
    bins = _TEMP_BINS.get(material)
    if bins is None:
        raise KeyError(
            f"Material {material!r} not in B31.1 Table A-1 lookup.  "
            f"Known materials: {sorted(_TEMP_BINS.keys())}"
        )

    # Clamp to table range (below min → use min-temp stress; above max → error)
    t_min, t_max = bins[0], bins[-1]
    if temp_F < t_min:
        return _ALLOWABLE_STRESS_B31_1[(material, t_min)]
    if temp_F > t_max:
        raise ValueError(
            f"Temperature {temp_F:.0f}°F exceeds maximum tabled temperature "
            f"{t_max:.0f}°F for material {material!r}.  "
            "Consult full ASME B31.1 Table A-1 for elevated temperature data."
        )

    # Linear interpolation between nearest bins
    if temp_F in bins:
        return _ALLOWABLE_STRESS_B31_1[(material, int(temp_F))]

    lo = max(b for b in bins if b <= temp_F)
    hi = min(b for b in bins if b >= temp_F)
    if lo == hi:
        return _ALLOWABLE_STRESS_B31_1[(material, lo)]

    s_lo = _ALLOWABLE_STRESS_B31_1[(material, lo)]
    s_hi = _ALLOWABLE_STRESS_B31_1[(material, hi)]
    frac = (temp_F - lo) / (hi - lo)
    return s_lo + frac * (s_hi - s_lo)


def min_wall_thickness_b31_1(
    pressure_psi: float,
    diameter_in: float,
    allowable_stress_psi: float,
    joint_efficiency: float = 1.0,
    mill_tolerance_pct: float = 12.5,
    corrosion_allowance_in: float = 0.0625,
    temp_F: float = 70.0,
    material: str = "A106-B",
) -> dict:
    """
    Minimum pipe wall thickness per ASME B31.1-2022 §104.1.2 Equation 7.

    Formula (Eq. 7):
        t = P·D / (2·(S·E + P·y)) + A

    Where:
      P  = internal design gauge pressure (psi)
      D  = outside diameter (inches)
      S  = basic allowable stress at design temperature (psi)
      E  = longitudinal weld joint efficiency factor (1.0 for seamless)
      y  = temperature coefficient from Table 104.1.2-1
           (0.4 for ferritic steel T < 900°F; 0.4 for austenitic T < 800°F)
      A  = sum of mechanical allowances (corrosion/erosion + thread/groove depth, inches)

    Mill tolerance is applied to obtain the **ordered minimum thickness** (t_m):
        t_m = t / (1 - mill_tolerance_pct / 100)

    Parameters
    ----------
    pressure_psi          Internal design gauge pressure (psi).
    diameter_in           Pipe outside diameter (inches).
    allowable_stress_psi  Basic allowable stress S (psi) at design temperature.
                          Use material_allowable_stress() to look up from Table A-1.
    joint_efficiency      Longitudinal weld joint factor E.
                          1.0 = seamless; 0.85 = ERW; 0.80 = furnace-butt-weld.
    mill_tolerance_pct    Under-thickness mill tolerance (%).  ASME B36.10M = 12.5%.
    corrosion_allowance_in Corrosion/erosion allowance (inches).  Add mechanical
                          thread/groove depth here if applicable.
    temp_F                Design temperature (°F) used to determine y coefficient.
    material              Material key string (used for y lookup; default 'A106-B').

    Returns
    -------
    dict with keys:
      min_thickness_in          Minimum required thickness after allowances (inches).
      ordered_min_thickness_in  t_m — minimum ordered thickness accounting for mill
                                tolerance (must be the actual spec'd wall).
      design_pressure_max_psi   Maximum allowable working pressure for the
                                ordered min thickness (back-calculated from Eq. 7).
      mill_tolerance_added_in   Extra thickness added for mill tolerance.
      t_structural_in           Structural component of wall (Eq. 7 pressure term only).
      corrosion_allowance_in    Corrosion allowance used (inches).
      y_coefficient             y value used.
      schedule_recommended      Nearest ASME B36.10M schedule string for this OD.
      caveat                    Honesty disclaimer.

    Notes
    -----
    This function implements ASME B31.1 §104.1.2 Eq. 7.  It is NOT ASME
    stamp certified and must NOT be the sole basis for a physical installation
    without review by a licensed Professional Engineer.
    """
    if pressure_psi < 0.0:
        raise ValueError(f"pressure_psi must be non-negative, got {pressure_psi}")
    if diameter_in <= 0.0:
        raise ValueError(f"diameter_in must be positive, got {diameter_in}")
    if allowable_stress_psi <= 0.0:
        raise ValueError(f"allowable_stress_psi must be positive, got {allowable_stress_psi}")
    if not (0.0 < joint_efficiency <= 1.0):
        raise ValueError(f"joint_efficiency must be in (0, 1], got {joint_efficiency}")

    P = pressure_psi
    D = diameter_in
    S = allowable_stress_psi
    E = joint_efficiency
    y = _y_coefficient(material, temp_F)
    A = corrosion_allowance_in  # sum of mechanical allowances

    # ASME B31.1 Eq. 7 structural wall
    denominator = 2.0 * (S * E + P * y)
    if denominator <= 0.0:
        raise ValueError("Denominator 2·(S·E + P·y) must be positive.")

    t_structural = (P * D) / denominator    # inches (structural term)
    t_min = t_structural + A                # minimum required thickness

    # Apply mill tolerance to get ordered minimum thickness
    if mill_tolerance_pct < 0.0 or mill_tolerance_pct >= 100.0:
        raise ValueError(
            f"mill_tolerance_pct must be in [0, 100), got {mill_tolerance_pct}"
        )
    mill_factor = 1.0 - mill_tolerance_pct / 100.0
    t_ordered = t_min / mill_factor         # ordered (specified) wall minimum

    # Back-calculate MAWP for the ordered thickness
    # Rearrange Eq. 7 for P:
    #   t_ordered - A = P·D / (2·(S·E + P·y))
    #   Let t_net = t_ordered - A
    #   t_net · 2·(S·E + P·y) = P·D
    #   2·t_net·S·E + 2·t_net·y·P = P·D
    #   2·t_net·S·E = P·(D - 2·t_net·y)
    #   P_mawp = 2·t_net·S·E / (D - 2·t_net·y)
    t_net = t_ordered - A
    mawp_denom = D - 2.0 * t_net * y
    if mawp_denom <= 0.0:
        P_mawp = float("inf")  # extremely thick pipe
    else:
        P_mawp = (2.0 * t_net * S * E) / mawp_denom

    # Recommend schedule — recommend_schedule expects NPS (e.g. 6.0 for 6" NPS).
    # If the caller passed a B36.10M OD directly (e.g. 6.625"), map it to the
    # nearest NPS; if they passed an NPS value it stays unchanged.
    nps_for_lookup = _od_to_nps(diameter_in)
    sched = recommend_schedule(nps_for_lookup, t_ordered)

    mill_added = t_ordered - t_min

    return {
        "min_thickness_in": round(t_min, 5),
        "ordered_min_thickness_in": round(t_ordered, 5),
        "design_pressure_max_psi": round(P_mawp, 1),
        "mill_tolerance_added_in": round(mill_added, 5),
        "t_structural_in": round(t_structural, 5),
        "corrosion_allowance_in": round(A, 5),
        "y_coefficient": y,
        "schedule_recommended": sched,
        "caveat": (
            "ASME B31.1 §104.1.2 Eq. 7 methods — NOT ASME stamp certified.  "
            "Review by a licensed Professional Engineer required before use in "
            "any physical installation."
        ),
    }


def recommend_schedule(diameter_in: float, min_thickness_in: float) -> str:
    """
    Recommend the thinnest ASME B36.10M schedule whose nominal wall thickness
    is ≥ min_thickness_in for the given outside diameter (inches, NPS).

    Parameters
    ----------
    diameter_in       Outside diameter of the pipe (NPS inches, e.g. 6.0 for 6").
                      Must match a value in the ASME B36.10M NPS table
                      (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0,
                       6.0, 8.0, 10.0, 12.0).
    min_thickness_in  Minimum required wall thickness (inches), e.g. from
                      min_wall_thickness_b31_1()['ordered_min_thickness_in'].

    Returns
    -------
    Schedule code string (e.g. '40', '80', 'XXS').
    Returns 'EXCEEDS-XXS' if no standard schedule is thick enough.
    Returns 'NPS-NOT-FOUND' if diameter_in is not in the B36.10M table.

    Notes
    -----
    The schedule with the smallest wall that still meets the minimum is
    returned — this is the most economical selection.  For safety-critical
    services the engineer should apply additional margin.
    """
    # Find entries for this NPS size
    candidates = {
        sched: t
        for (nps, sched), t in _WALL_THICKNESS_IN.items()
        if math.isclose(nps, diameter_in, rel_tol=1e-4)
        and t >= min_thickness_in
    }

    if not candidates:
        # Check whether we have data at all for this NPS
        nps_found = any(
            math.isclose(nps, diameter_in, rel_tol=1e-4)
            for (nps, _) in _WALL_THICKNESS_IN
        )
        return "EXCEEDS-XXS" if nps_found else "NPS-NOT-FOUND"

    # Sort by actual wall thickness ascending, pick thinnest that qualifies
    best_sched = min(candidates, key=lambda s: candidates[s])
    return best_sched


def compute_thermal_stress(
    material: str,
    delta_T_F: float,
    modulus_psi: float,
    alpha_per_F: float,
) -> dict:
    """
    Compute thermal (expansion) stress in a fully restrained pipe.

    Formula:
        σ_th = E · α · ΔT

    Where:
      E   = Young's modulus (psi)
      α   = thermal expansion coefficient (per °F)
      ΔT  = temperature change (°F)

    This represents the maximum axial stress in a pipe that is completely
    prevented from expanding or contracting.  In practice the actual stress
    depends on boundary conditions (fixed-fixed → full restraint;
    guided-guided → zero).

    Parameters
    ----------
    material     Material description string (informational only; included in output).
    delta_T_F    Temperature change ΔT (°F).  Use positive value for heat-up.
    modulus_psi  Young's modulus E (psi).
                 Carbon steel: ~29.0e6 psi (200 GPa)
                 Stainless:    ~28.0e6 psi (193 GPa)
    alpha_per_F  Coefficient of thermal expansion α (per °F).
                 Carbon steel A106: ~6.5e-6 /°F  (11.7e-6 /°C)
                 SS 304/316:        ~9.6e-6 /°F  (17.2e-6 /°C)

    Returns
    -------
    dict with keys:
      thermal_stress_psi  σ_th = E·α·ΔT (psi)
      material            material label (passed through)
      delta_T_F           ΔT used
      modulus_psi         E used
      alpha_per_F         α used
      caveat              Disclaimer note.

    Notes
    -----
    Fully-restrained thermal stress only.  Actual piping flexibility analysis
    per ASME B31.1 Appendix D requires a piping stress package (CAESAR II-class).
    NOT ASME stamp certified.
    """
    sigma_th = modulus_psi * alpha_per_F * delta_T_F

    return {
        "thermal_stress_psi": round(sigma_th, 1),
        "material": material,
        "delta_T_F": delta_T_F,
        "modulus_psi": modulus_psi,
        "alpha_per_F": alpha_per_F,
        "caveat": (
            "Fully-restrained thermal stress (E·α·ΔT).  Actual piping flexibility "
            "must be evaluated per ASME B31.1 Appendix D — NOT ASME stamp certified."
        ),
    }
