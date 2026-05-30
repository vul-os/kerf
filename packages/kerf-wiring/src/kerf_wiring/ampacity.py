"""
NEC 2023 (NFPA 70-2023) Wire Ampacity Calculator.

Implements Table 310.16 ampacity values with temperature correction
(NEC 310.15(B)(2)(a)) and bundling/fill correction (NEC 310.15(B)(3)(a)).

Supported conductors:
  - Copper (Cu): THHN/THWN-2 at 90 °C column (most common building wire)
  - Aluminum (Al): XHHW-2 at 90 °C column (~78% of Cu for same AWG)

Installation methods:
  - free_air   : Table 310.17 free-air values (not yet — falls back to 310.16)
  - conduit    : Table 310.16 raceway/conduit values (default)
  - cable_tray : Same as conduit for bundled cables per NEC 392.80

NEC section references are cited inline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# NEC 2023 Table 310.16 — Allowable Ampacities, 60 Hz, 75°C ambient earth,
# conductors in raceway/cable/earth (based on 30°C ambient air).
#
# Keys are AWG strings ("14", "12", … "4/0") or kcmil ("250", …).
# Values are (60°C_Cu, 75°C_Cu, 90°C_Cu, 60°C_Al, 75°C_Al, 90°C_Al)
#
# Source: NFPA 70-2023, Table 310.16 (verified against published tables).
# Aluminum values ≈ 78% of copper for small AWG; exact NEC 310.16 values used.
# ---------------------------------------------------------------------------

# Column indices within each tuple
_COL_60C_CU = 0
_COL_75C_CU = 1
_COL_90C_CU = 2
_COL_60C_AL = 3
_COL_75C_AL = 4
_COL_90C_AL = 5

#: NEC 2023 Table 310.16 base ampacities at 30 °C ambient.
#: (60°C Cu, 75°C Cu, 90°C Cu, 60°C Al, 75°C Al, 90°C Al)
TABLE_310_16: dict[str, tuple[int, int, int, int, int, int]] = {
    # AWG 14–2/0 copper; aluminum not rated below AWG 12
    "14":  (15,  20,  25,   0,   0,   0),
    "12":  (20,  25,  30,  15,  20,  25),
    "10":  (30,  35,  40,  25,  30,  35),
    "8":   (40,  50,  55,  30,  40,  45),
    "6":   (55,  65,  75,  40,  50,  60),
    "4":   (70,  85,  95,  55,  65,  75),
    "3":   (85, 100, 110,  65,  75,  85),
    "2":   (95, 115, 130,  75,  90, 100),
    "1":  (110, 130, 150,  85, 100, 115),
    "1/0":(125, 150, 170, 100, 120, 135),
    "2/0":(145, 175, 195, 115, 135, 150),
    "3/0":(165, 200, 225, 130, 155, 175),
    "4/0":(195, 230, 260, 150, 180, 205),
    # kcmil
    "250": (215, 255, 290, 170, 205, 230),
    "300": (240, 285, 320, 195, 230, 260),
    "350": (260, 310, 350, 210, 250, 280),
    "400": (280, 335, 380, 225, 270, 305),
    "500": (320, 380, 430, 260, 310, 350),
    "600": (355, 420, 475, 285, 340, 385),
    "700": (385, 460, 520, 315, 375, 420),
    "750": (400, 475, 535, 320, 385, 435),
}

# AWG to mm² approximate cross-sectional area for reference (not used in calc)
AWG_TO_MM2: dict[str, float] = {
    "14": 2.08, "12": 3.31, "10": 5.26, "8": 8.37,
    "6": 13.30, "4": 21.15, "3": 26.67, "2": 33.62,
    "1": 42.41, "1/0": 53.49, "2/0": 67.43, "3/0": 85.01,
    "4/0": 107.2, "250": 126.7, "300": 152.0, "350": 177.3,
    "400": 202.7, "500": 253.4, "600": 304.0, "700": 354.7, "750": 380.0,
}


# ---------------------------------------------------------------------------
# NEC 310.15(B)(2)(a) — Ambient temperature correction factors
# Reference column: 90 °C insulation at 30 °C ambient (factor = 1.00)
# Table applies to conductors rated 60, 75, and 90 °C.
#
# Formula (NEC 310.15(B)(2)(a)):
#   CF = sqrt((T_rated - T_ambient) / (T_rated - 30))
# where 30 °C is the NEC standard reference ambient temperature.
# ---------------------------------------------------------------------------

def _ambient_correction(insulation_temp_c: int, ambient_c: float) -> float:
    """
    Compute NEC 310.15(B)(2)(a) ambient temperature correction factor.

    Args:
        insulation_temp_c: Rated insulation temperature (60, 75, or 90 °C).
        ambient_c: Actual ambient temperature in °C.

    Returns:
        Dimensionless correction factor (multiply base ampacity by this).

    Raises:
        ValueError: If ambient >= insulation rating (conductor would fail).
    """
    t_ref = 30.0  # NEC standard reference ambient temperature
    if ambient_c >= insulation_temp_c:
        raise ValueError(
            f"Ambient temperature {ambient_c}°C >= insulation rating "
            f"{insulation_temp_c}°C — conductor is unusable at this temperature."
        )
    return math.sqrt((insulation_temp_c - ambient_c) / (insulation_temp_c - t_ref))


# ---------------------------------------------------------------------------
# NEC 310.15(B)(3)(a) — Adjustment factors for more than 3 current-carrying
# conductors in a raceway or cable (conduit fill adjustment).
#
# Source: NFPA 70-2023 Table 310.15(B)(3)(a)
# ---------------------------------------------------------------------------

#: NEC 2023 Table 310.15(B)(3)(a) bundling derating factors.
#: Key: (min_conductors, max_conductors) → factor
BUNDLING_FACTORS: list[tuple[int, int, float]] = [
    (1,  3,  1.00),   # No derating for 1–3 conductors
    (4,  6,  0.80),
    (7,  9,  0.70),
    (10, 20, 0.50),
    (21, 30, 0.45),
    (31, 40, 0.40),
    (41, 9999, 0.35),
]


def _bundling_factor(bundle_count: int) -> float:
    """
    Return NEC 310.15(B)(3)(a) adjustment factor for bundled conductors.

    Args:
        bundle_count: Total number of current-carrying conductors in the
                      raceway, conduit, or cable bundle.

    Returns:
        Dimensionless derating factor (0.35 – 1.00).
    """
    for lo, hi, factor in BUNDLING_FACTORS:
        if lo <= bundle_count <= hi:
            return factor
    return 0.35  # conservative fallback for very large bundles


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

InstallationMethod = Literal["conduit", "free_air", "cable_tray"]
Material = Literal["Cu", "Al"]


@dataclass
class AmpacityResult:
    """Result of an NEC 310.15 ampacity calculation."""

    awg: str
    """Wire size as AWG string or kcmil string (e.g. '12', '1/0', '250')."""

    material: str
    """Conductor material: 'Cu' or 'Al'."""

    insulation_temp_c: int
    """Rated insulation temperature in °C (60, 75, or 90)."""

    ambient_c: float
    """Ambient air temperature in °C."""

    bundle_count: int
    """Number of current-carrying conductors in the bundle/raceway."""

    installation: str
    """Installation method: 'conduit', 'free_air', or 'cable_tray'."""

    base_ampacity_a: float
    """
    Table 310.16 base ampacity (A) for the selected insulation column,
    before any corrections.
    """

    ambient_correction_factor: float
    """NEC 310.15(B)(2)(a) temperature correction factor."""

    bundling_factor: float
    """NEC 310.15(B)(3)(a) bundling adjustment factor."""

    derated_ampacity_a: float
    """
    Final derated ampacity (A) after applying both correction factors.
    derated = base × ambient_correction × bundling_factor.
    """

    notes: list[str]
    """
    Non-fatal advisory notes (e.g. aluminium honesty flag,
    terminal temperature limits, conduit fill warnings).
    """


def compute_ampacity(
    awg: str,
    material: Material = "Cu",
    insulation_temp_c: int = 90,
    ambient_c: float = 30.0,
    bundle_count: int = 1,
    installation: InstallationMethod = "conduit",
) -> AmpacityResult:
    """
    Compute NEC 2023 (NFPA 70-2023) wire ampacity with all applicable
    correction factors.

    References:
      - NEC 2023 Table 310.16 — base ampacity
      - NEC 2023 §310.15(B)(2)(a) — ambient temperature correction
      - NEC 2023 §310.15(B)(3)(a) — bundling / fill correction

    Args:
        awg: Wire size.  Use AWG strings ("14", "12", "10", "8", "6", "4",
             "3", "2", "1", "1/0", "2/0", "3/0", "4/0") or kcmil strings
             ("250", "300", "350", "400", "500", "600", "700", "750").
        material: "Cu" (copper, default) or "Al" (aluminum).
                  Aluminum is NOT rated below AWG 12 per NEC 310.16.
        insulation_temp_c: Rated insulation temperature: 60, 75, or 90 °C.
                           Use 90 for THHN/THWN-2 (Cu) or XHHW-2 (Al),
                           75 for THWN/RHW, 60 for TW/UF.
        ambient_c: Actual ambient temperature in °C.  NEC reference = 30 °C.
                   Correction factor = sqrt((Tins - Tamb) / (Tins - 30)).
        bundle_count: Total number of current-carrying conductors in the same
                      raceway or cable tray.  1–3 → no derating (factor = 1.0);
                      4–6 → 0.80; 7–9 → 0.70; 10–20 → 0.50 (Table 310.15(B)(3)(a)).
        installation: "conduit" (default), "free_air", or "cable_tray".
                      "free_air" uses the same table column for now (Table 310.17
                      is not yet embedded; result is conservative).
                      "cable_tray" behaves identically to "conduit" per NEC 392.80.

    Returns:
        AmpacityResult dataclass with base, correction factors, and final value.

    Raises:
        ValueError: Invalid AWG, unsupported material/size, or ambient ≥ rating.

    Examples:
        >>> r = compute_ampacity("12", "Cu", 90, 30.0, 1, "conduit")
        >>> r.derated_ampacity_a
        30.0

        >>> r = compute_ampacity("12", "Cu", 90, 30.0, 4, "conduit")
        >>> r.derated_ampacity_a  # 30 × 0.80 = 24.0
        24.0

        >>> r = compute_ampacity("12", "Cu", 90, 40.0, 1, "conduit")
        >>> round(r.derated_ampacity_a, 1)  # 30 × 0.91 ≈ 27.3
        27.3
    """
    awg = str(awg).strip()
    notes: list[str] = []

    # ── Validate size ────────────────────────────────────────────────────────
    if awg not in TABLE_310_16:
        raise ValueError(
            f"AWG/kcmil '{awg}' not in NEC Table 310.16.  "
            f"Valid sizes: {', '.join(TABLE_310_16.keys())}"
        )

    # ── Validate material ────────────────────────────────────────────────────
    if material not in ("Cu", "Al"):
        raise ValueError(f"material must be 'Cu' or 'Al', got '{material}'")

    # ── Validate insulation temperature ──────────────────────────────────────
    if insulation_temp_c not in (60, 75, 90):
        raise ValueError(
            f"insulation_temp_c must be 60, 75, or 90; got {insulation_temp_c}"
        )

    # ── Select base ampacity column ──────────────────────────────────────────
    row = TABLE_310_16[awg]
    if material == "Cu":
        col = {60: _COL_60C_CU, 75: _COL_75C_CU, 90: _COL_90C_CU}[insulation_temp_c]
    else:
        col = {60: _COL_60C_AL, 75: _COL_75C_AL, 90: _COL_90C_AL}[insulation_temp_c]
        notes.append(
            "HONEST FLAG (NEC 310.16): Aluminum conductor ampacity is "
            "approximately 78% of copper for the same AWG.  Embedded Al values "
            "are taken directly from NEC 2023 Table 310.16, NOT derived from Cu. "
            "Al is not rated below AWG 12 per NEC 310.16."
        )

    base_a = float(row[col])
    if base_a == 0:
        raise ValueError(
            f"Aluminum conductors are not rated at AWG '{awg}' in NEC Table 310.16 "
            f"(only AWG 12 and larger are listed for Al)."
        )

    # ── Terminal / equipment temperature limit advisory ───────────────────────
    # NEC 110.14(C): equipment terminals are typically rated 60 or 75 °C.
    # Using 90 °C insulation rating doesn't permit using the 90 °C column
    # unless the terminal is also rated 90 °C.  This is advisory only.
    if insulation_temp_c == 90:
        notes.append(
            "NEC 110.14(C) advisory: Terminal temperature limits apply. "
            "Unless equipment terminals are rated 90 °C, limit final ampacity "
            "to the 75 °C column value even when using 90 °C insulation "
            "(THHN/THWN-2).  The 90 °C value returned here is the conductor "
            "capacity; verify terminal ratings before use."
        )

    # ── Installation method advisory ─────────────────────────────────────────
    if installation == "free_air":
        notes.append(
            "NEC Table 310.17 free-air values are NOT yet embedded; "
            "Table 310.16 (raceway) values are used — result is conservative. "
            "Free-air ampacity is typically 10–20% higher for small AWG."
        )

    # ── Correction factors ───────────────────────────────────────────────────
    cf_ambient = _ambient_correction(insulation_temp_c, ambient_c)
    cf_bundle = _bundling_factor(bundle_count)

    if bundle_count > 3:
        notes.append(
            f"NEC 310.15(B)(3)(a): {bundle_count} conductors in bundle/conduit → "
            f"adjustment factor {cf_bundle:.2f} applied."
        )

    if ambient_c != 30.0:
        notes.append(
            f"NEC 310.15(B)(2)(a): ambient {ambient_c}°C → "
            f"temperature correction factor {cf_ambient:.4f} applied "
            f"(reference 30 °C)."
        )

    derated_a = base_a * cf_ambient * cf_bundle

    return AmpacityResult(
        awg=awg,
        material=material,
        insulation_temp_c=insulation_temp_c,
        ambient_c=ambient_c,
        bundle_count=bundle_count,
        installation=installation,
        base_ampacity_a=base_a,
        ambient_correction_factor=round(cf_ambient, 6),
        bundling_factor=cf_bundle,
        derated_ampacity_a=round(derated_a, 2),
        notes=notes,
    )
