"""
NEC 2023 wire ampacity derating — Article 310, Tables 310.15(B)(2)(a) and
310.15(B)(3)(a), base ampacity from Table 310.16.

Given a base wire ampacity (NEC Table 310.16, 75 °C column), this module
applies:

  1. Ambient temperature correction (NEC Table 310.15(B)(2)(a)):
     The base ampacity in Table 310.16 is tabulated at 30 °C (86 °F) ambient.
     When the actual ambient temperature differs from 30 °C, a correction
     factor C_T is applied.  For the 75 °C insulation column:
       ≤ 30 °C → 1.00
       31–35   → 0.94
       36–40   → 0.88
       41–45   → 0.82
       46–50   → 0.75
       51–55   → 0.67
       56–60   → 0.58
     (Ambient > 60 °C is outside this table's range and raises ValueError.)

  2. Conductor bundling (adjustment) factor (NEC Table 310.15(B)(3)(a)):
     When more than three current-carrying conductors are in a conduit,
     cable, or raceway, the base ampacity is reduced by an adjustment factor:
       1–3   → 1.00  (no derating; the Table 310.16 base already covers ≤ 3)
       4–6   → 0.80
       7–9   → 0.70
       10–20 → 0.50
       21–30 → 0.45
       31–40 → 0.40
       41+   → 0.35

  Effective (derated) ampacity:
    I_eff = base_ampacity_A × C_T × C_bundle

References:
  - NEC 2023 Table 310.16: base ampacity, 75 °C insulation column (THWN /
    THHN / XHHW / RHW), ≤ 3 current-carrying conductors in conduit, 30 °C ambient.
  - NEC 2023 Article 310.15(B)(2)(a) + Table 310.15(B)(2)(a): ambient
    temperature correction factors.
  - NEC 2023 Article 310.15(B)(3)(a) + Table 310.15(B)(3)(a): adjustment
    factors for more than three current-carrying conductors.

HONEST CAVEATS (always included in report):
  1. Ampacity column: 75 °C (THWN/THHN/XHHW/RHW only).  90 °C column (THHN
     at 90 °C) is NOT used here; NEC 110.14(C) terminal rating limits the
     circuit to 75 °C in practice for most ≤ 100 A installations.
  2. Ambient correction: 75 °C insulation column of Table 310.15(B)(2)(a)
     only.  This module does not implement the 60 °C or 90 °C sub-columns.
  3. Bundling factor: applies only when conductors share a raceway / conduit
     or are bundled (in_conduit=True).  Free-air installations (NEC Table
     310.17) are NOT covered — user must supply Table 310.17 base ampacity
     separately and set in_conduit=False for an honest result.
  4. Ambient > 60 °C: outside Table 310.15(B)(2)(a) range — not supported.
  5. Rooftop adder (NEC 310.15(B)(3)(c)), underground / direct-buried
     (Table 310.15(B)(7)), and Type NM cable derating are NOT modelled.
  6. The caller supplies base_ampacity_A directly; this module does NOT embed
     Table 310.16 — use kerf_electronics.circuit_protection_check._TABLE_310_16_75C
     or kerf-wiring ampacity.py for a full table lookup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# NEC Table 310.15(B)(2)(a) — ambient temperature correction factors
# for 75 °C insulation column.
#
# Each entry is (max_ambient_C_inclusive, correction_factor).
# The table is applied by walking the brackets in ascending order.
# ---------------------------------------------------------------------------
_AMBIENT_CORRECTION_75C: list[tuple[float, float]] = [
    (30.0, 1.00),
    (35.0, 0.94),
    (40.0, 0.88),
    (45.0, 0.82),
    (50.0, 0.75),
    (55.0, 0.67),
    (60.0, 0.58),
]

# ---------------------------------------------------------------------------
# NEC Table 310.15(B)(3)(a) — adjustment factors for more than 3
# current-carrying conductors in a raceway or cable.
#
# Each entry is (max_conductors_inclusive, adjustment_factor).
# Note: the table says "41 and above" for the last bracket — represented here
# as (None, 0.35) so any count ≥ 41 matches.
# ---------------------------------------------------------------------------
_BUNDLING_FACTORS: list[tuple[Optional[int], float]] = [
    (3,  1.00),   # 1–3 conductors: no adjustment (already in Table 310.16)
    (6,  0.80),   # 4–6 conductors
    (9,  0.70),   # 7–9 conductors
    (20, 0.50),   # 10–20 conductors
    (30, 0.45),   # 21–30 conductors
    (40, 0.40),   # 31–40 conductors
    (None, 0.35), # 41+ conductors
]

_VALID_MATERIAL = frozenset({"copper", "aluminum"})
_VALID_INSULATION = frozenset({"TW", "THWN", "THHN", "XHHW", "RHW"})


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WireSpec:
    """Physical wire specification.

    Attributes:
        awg_size: AWG gauge string (e.g. "14", "12", "10", "8", "6", "4",
            "2", "1", "1/0", "2/0", "3/0", "4/0", "250kcmil").
        material: Conductor material — "copper" or "aluminum".
        insulation_class: Insulation type — "TW", "THWN", "THHN", "XHHW",
            or "RHW".  THWN / THHN / XHHW / RHW are all 75 °C rated and use
            the 75 °C correction column.  TW is 60 °C but is included as a
            recognised class; callers using TW should note that this module
            applies 75 °C correction factors — use with care (conservative for
            TW; not NEC-exact).
        base_ampacity_A: Conductor base ampacity from NEC Table 310.16 at
            30 °C ambient, 75 °C insulation column [A].  The caller is
            responsible for supplying the correct Table 310.16 value.
    """
    awg_size: str
    material: str
    insulation_class: str
    base_ampacity_A: float


@dataclass
class InstallationConditions:
    """Electrical installation conditions.

    Attributes:
        ambient_temp_C: Actual ambient temperature at the installation site [°C].
            Correction factor from NEC Table 310.15(B)(2)(a) is applied.
            Supported range: ≤ 60 °C.  Values ≤ 30 °C map to factor 1.00.
        num_current_carrying_conductors: Total number of current-carrying
            conductors sharing the raceway or cable bundle.  Default 1.
            NEC Table 310.16 base ampacity already assumes ≤ 3; values 1–3
            yield a bundling factor of 1.00.
        in_conduit: If True (default), the bundling adjustment factor from
            NEC Table 310.15(B)(3)(a) is applied when
            num_current_carrying_conductors > 3.  If False, no bundling
            derating is applied (free-air installation — caller must supply
            a Table 310.17 base ampacity via WireSpec.base_ampacity_A).
    """
    ambient_temp_C: float
    num_current_carrying_conductors: int = 1
    in_conduit: bool = True


@dataclass
class DeratedAmpacityReport:
    """Result of the NEC ampacity derating calculation.

    Attributes:
        base_ampacity_A: Base ampacity supplied by the caller [A].
        ambient_correction_factor: NEC Table 310.15(B)(2)(a) factor for the
            given ambient temperature (75 °C insulation column).
        bundling_factor: NEC Table 310.15(B)(3)(a) adjustment factor for the
            given number of current-carrying conductors.  1.00 if in_conduit
            is False or num_current_carrying_conductors ≤ 3.
        effective_ampacity_A: Derated ampacity =
            base_ampacity_A × ambient_correction_factor × bundling_factor [A].
        conditions_summary: Human-readable summary of the installation
            conditions applied.
        code_section_cited: List of NEC code sections used in the calculation.
        honest_caveat: Engineering notes and model limitations.
    """
    base_ampacity_A: float
    ambient_correction_factor: float
    bundling_factor: float
    effective_ampacity_A: float
    conditions_summary: str
    code_section_cited: list[str]
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ambient_correction_factor_75c(ambient_C: float) -> float:
    """Return NEC Table 310.15(B)(2)(a) correction factor for 75 °C column.

    Args:
        ambient_C: Ambient temperature [°C].

    Returns:
        Correction factor (dimensionless, ≤ 1.00).

    Raises:
        ValueError: If ambient_C > 60 °C (outside table range).
    """
    if ambient_C > 60.0:
        raise ValueError(
            f"Ambient temperature {ambient_C:.1f} °C exceeds the maximum "
            "supported by NEC Table 310.15(B)(2)(a) for 75 °C insulation (60 °C). "
            "Consult NEC 310.15(B)(2)(a) extended table or derate conductor to "
            "a higher temperature insulation class."
        )
    for max_temp, factor in _AMBIENT_CORRECTION_75C:
        if ambient_C <= max_temp:
            return factor
    # Should not be reached after the > 60 guard above, but be defensive.
    raise ValueError(f"Ambient temperature {ambient_C:.1f} °C out of table range.")


def _bundling_factor(num_conductors: int) -> float:
    """Return NEC Table 310.15(B)(3)(a) bundling adjustment factor.

    Args:
        num_conductors: Number of current-carrying conductors in the raceway.

    Returns:
        Adjustment factor (dimensionless, ≤ 1.00).

    Raises:
        ValueError: If num_conductors < 1.
    """
    if num_conductors < 1:
        raise ValueError("num_current_carrying_conductors must be ≥ 1")
    for max_count, factor in _BUNDLING_FACTORS:
        if max_count is None or num_conductors <= max_count:
            return factor
    # Fallback (logically unreachable — last bracket has max_count=None).
    return 0.35


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_derated_ampacity(
    wire: WireSpec,
    conditions: InstallationConditions,
) -> DeratedAmpacityReport:
    """Compute effective installation ampacity after ambient and bundling derating.

    Applies NEC 2023 Article 310 derating in sequence:
      1. Ambient temperature correction — NEC Table 310.15(B)(2)(a), 75 °C column.
      2. Conductor bundling adjustment — NEC Table 310.15(B)(3)(a).

    Effective ampacity = base_ampacity_A × C_ambient × C_bundling.

    Args:
        wire: WireSpec — AWG, material, insulation class, and base ampacity.
        conditions: InstallationConditions — ambient temperature, conductor
            count, and whether conductors are in conduit/bundled.

    Returns:
        DeratedAmpacityReport with individual factors, effective ampacity,
        NEC code sections cited, and honest engineering caveats.

    Raises:
        ValueError: If any input is invalid or out of supported range.
    """
    # ---- input validation ----
    material = wire.material.lower()
    insulation = wire.insulation_class.upper()

    if material not in _VALID_MATERIAL:
        raise ValueError(
            f"material must be 'copper' or 'aluminum', got {wire.material!r}"
        )
    if insulation not in _VALID_INSULATION:
        raise ValueError(
            f"insulation_class must be one of {sorted(_VALID_INSULATION)}, "
            f"got {wire.insulation_class!r}"
        )
    if wire.base_ampacity_A <= 0:
        raise ValueError("base_ampacity_A must be positive")
    if conditions.num_current_carrying_conductors < 1:
        raise ValueError("num_current_carrying_conductors must be ≥ 1")

    # ---- Ambient temperature correction ----
    c_ambient = _ambient_correction_factor_75c(conditions.ambient_temp_C)

    # ---- Bundling adjustment ----
    if conditions.in_conduit:
        c_bundle = _bundling_factor(conditions.num_current_carrying_conductors)
    else:
        c_bundle = 1.00

    # ---- Effective ampacity ----
    effective = wire.base_ampacity_A * c_ambient * c_bundle

    # ---- Conditions summary ----
    bundle_desc = (
        f"{conditions.num_current_carrying_conductors} current-carrying conductors "
        f"({'in conduit/bundled' if conditions.in_conduit else 'free-air, no bundling derating'})"
    )
    summary = (
        f"{wire.awg_size} AWG {material} {insulation} | "
        f"base={wire.base_ampacity_A:.1f} A | "
        f"ambient={conditions.ambient_temp_C:.1f} °C (C_T={c_ambient:.2f}) | "
        f"{bundle_desc} (C_bundle={c_bundle:.2f}) | "
        f"effective={effective:.2f} A"
    )

    # ---- Code sections cited ----
    sections: list[str] = [
        "NEC 2023 Table 310.16 (75°C column — base ampacity, ≤3 conductors, 30°C ambient)",
        "NEC 2023 Article 310.15(B)(2)(a) + Table 310.15(B)(2)(a) — ambient temperature correction",
    ]
    if conditions.in_conduit and conditions.num_current_carrying_conductors > 3:
        sections.append(
            f"NEC 2023 Article 310.15(B)(3)(a) + Table 310.15(B)(3)(a) — "
            f"bundling adjustment for {conditions.num_current_carrying_conductors} "
            f"current-carrying conductors (factor {c_bundle:.2f})"
        )
    else:
        sections.append(
            "NEC 2023 Article 310.15(B)(3)(a) — bundling factor = 1.00 "
            f"(≤3 conductors or free-air; no adjustment applied)"
        )

    # ---- Honest caveat ----
    caveat_parts = [
        "Ampacity column: 75°C (THWN/THHN/XHHW/RHW). "
        "This module does NOT apply the 60°C or 90°C sub-columns. "
        "NEC 110.14(C) limits most ≤100 A circuits to 75°C terminal rating.",
        "Ambient correction: 75°C insulation column of Table 310.15(B)(2)(a) only. "
        "Supported range: ≤60°C ambient. "
        "TW (60°C) insulation with 75°C correction factors is conservative but not NEC-exact.",
        "Bundling factor: applies to conductors in a common raceway/conduit (in_conduit=True). "
        "Free-air installations (Table 310.17) not covered — supply Table 310.17 base ampacity "
        "and set in_conduit=False.",
        "NOT modelled: rooftop adder (NEC 310.15(B)(3)(c)), underground/direct-buried "
        "(Table 310.15(B)(7)), Type NM cable derating, neutral-conductor treatment (NEC 310.15(B)(5)).",
        "Base ampacity is caller-supplied; this module does not embed Table 310.16 — verify the "
        "correct table value for the conductor AWG, material, and insulation class.",
    ]
    if insulation == "TW":
        caveat_parts.append(
            "TW insulation is 60°C rated. Applying 75°C correction factors overstates "
            "the correction — use 60°C column of Table 310.15(B)(2)(a) for TW conductors."
        )

    return DeratedAmpacityReport(
        base_ampacity_A=wire.base_ampacity_A,
        ambient_correction_factor=c_ambient,
        bundling_factor=c_bundle,
        effective_ampacity_A=round(effective, 6),
        conditions_summary=summary,
        code_section_cited=sections,
        honest_caveat=" | ".join(caveat_parts),
    )
