"""
NEC 2023 circuit protection check — NEC Article 240 + Table 310.16 + Article 215.

Given a conductor (AWG/material/insulation) and a circuit load (continuous /
non-continuous current), verifies that:

  1. The OCPD is sized correctly per NEC 215.3 / 210.20(A):
       required_ocpd_min = 1.25 × I_continuous + I_non_continuous

  2. The conductor ampacity (NEC Table 310.16, 75 °C column) is not exceeded
     after applying the OCPD per NEC 240.4:
       OCPD rating ≤ conductor ampacity  (240.4(B))

  3. Small-conductor tap rule (NEC 240.4(D)):
       14 AWG copper → maximum 15 A breaker
       12 AWG copper → maximum 20 A breaker
       10 AWG copper → maximum 30 A breaker

References:
  - NEC 2023 Table 310.16: 60/75/90 °C ampacity table (Cu + Al)
  - NEC 2023 Article 240.4: Protection of conductors
  - NEC 2023 Article 240.4(D): Small conductors — tap protection limits
  - NEC 2023 Article 215.3 / 210.20(A): Continuous + non-continuous load sizing

HONEST CAVEATS (always included in report):
  1. Ampacity baseline is 75 °C THWN/THHN/XHHW/RHW column from NEC Table 310.16
     for up to three current-carrying conductors in conduit at 30 °C ambient.
  2. No ambient-temperature derating is applied (NEC 310.15(B)(2)(a) correction
     factors for temperatures other than 30 °C are NOT included here).
  3. No conductor-bundling derating is applied (NEC Table 310.15(B)(3)(a)
     adjustment factors for more than three current-carrying conductors are NOT
     included here).
  4. Aluminum values use NEC Table 310.16 aluminium column (≈ 78 % of copper
     ampacity; ratio varies by size — values hard-coded from Table 310.16).
  5. This check covers only the ampacity and OCPD rating rules; it does not
     check short-circuit withstand, arc-flash, or grounding requirements.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# NEC 2023 Table 310.16 — conductor ampacity at 75 °C (THWN/THHN/XHHW/RHW)
# for not more than three current-carrying conductors in conduit, 30 °C ambient.
#
# Keys: AWG/kcmil string.
# Values: (copper_A, aluminum_A)
# Sources:
#   Copper column: NEC 2023 Table 310.16 (75 °C column)
#   Aluminum column: NEC 2023 Table 310.16 (75 °C, Al/CU-clad Al column)
# ---------------------------------------------------------------------------
_TABLE_310_16_75C: dict[str, tuple[float, float]] = {
    "14":        (20.0,   None),   # Al not listed for 14 AWG in NEC; not rated ≥ 14 AWG Al
    "12":        (25.0,   20.0),
    "10":        (35.0,   30.0),
    "8":         (50.0,   40.0),
    "6":         (65.0,   50.0),
    "4":         (85.0,   65.0),
    "3":         (100.0,  75.0),
    "2":         (115.0,  90.0),
    "1":         (130.0,  100.0),
    "1/0":       (150.0,  120.0),
    "2/0":       (175.0,  135.0),
    "3/0":       (200.0,  155.0),
    "4/0":       (230.0,  180.0),
    "250kcmil":  (255.0,  205.0),
    "300kcmil":  (285.0,  230.0),
    "500kcmil":  (380.0,  310.0),
}

# NEC 240.4(D) — small-conductor maximum OCPD limits (copper only).
# These are absolute maximums regardless of Table 310.16 ampacity.
_SMALL_CONDUCTOR_MAX_OCPD_CU: dict[str, float] = {
    "14": 15.0,
    "12": 20.0,
    "10": 30.0,
}

_VALID_AWG = frozenset(_TABLE_310_16_75C.keys())
_VALID_MATERIAL = frozenset({"copper", "aluminum"})
_VALID_INSULATION = frozenset({"THWN", "THHN", "XHHW", "RHW"})
_VALID_PHASE = frozenset({"single_phase", "three_phase"})
_VALID_BREAKER_TYPE = frozenset({"standard", "hacr", "slow_blow"})


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ConductorSpec:
    """Physical conductor specification for NEC Table 310.16 ampacity lookup.

    Attributes:
        awg_size: AWG / kcmil string.  Supported: "14","12","10","8","6","4",
            "3","2","1","1/0","2/0","3/0","4/0","250kcmil","300kcmil","500kcmil".
        material: "copper" or "aluminum".
        insulation_class: "THWN", "THHN", "XHHW", or "RHW".  All four carry a
            75 °C wet/dry rating — the 75 °C column of Table 310.16 applies to
            all of them.
    """
    awg_size: str
    material: str
    insulation_class: str


@dataclass
class LoadSpec:
    """Electrical load specification.

    Attributes:
        continuous_current_A: Portion of load current flowing for 3 or more
            hours continuously [A].  NEC 100 definition of "continuous load."
        non_continuous_current_A: Portion of load current that is not
            continuous [A].
        voltage_V: System voltage [V] (informational; not used in NEC 240.4 calc).
        phase: "single_phase" or "three_phase" (informational).
    """
    continuous_current_A: float
    non_continuous_current_A: float
    voltage_V: float
    phase: str


@dataclass
class OcpdSpec:
    """Overcurrent protective device specification.

    Attributes:
        breaker_rating_A: Nominal breaker trip/fuse rating [A].
        breaker_type: "standard", "hacr" (heating/air-conditioning/refrigeration),
            or "slow_blow".
    """
    breaker_rating_A: float
    breaker_type: str


@dataclass
class CircuitProtectionReport:
    """Result of NEC 240.4 + 215.3 circuit-protection compliance check.

    Attributes:
        ampacity_A: Conductor ampacity from NEC Table 310.16 at 75 °C [A].
        required_ocpd_min_A: Minimum required OCPD rating per NEC 215.3 /
            210.20(A) = 1.25 × continuous + non_continuous [A].
        derated_ampacity_A: Ampacity after 240.4(D) small-conductor cap (if
            applicable); equals ampacity_A for sizes > 10 AWG.
        ocpd_compliant: True if the OCPD satisfies NEC 215.3 sizing AND NEC
            240.4 conductor protection.
        conductor_adequate: True if conductor ampacity ≥ required OCPD rating
            (NEC 240.4(B)).
        code_section_cited: List of NEC code sections relevant to the check.
        honest_caveat: Engineering notes and model limitations.
    """
    ampacity_A: float
    required_ocpd_min_A: float
    derated_ampacity_A: float
    ocpd_compliant: bool
    conductor_adequate: bool
    code_section_cited: list[str]
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def check_circuit_protection(
    conductor: ConductorSpec,
    load: LoadSpec,
    ocpd: OcpdSpec,
) -> CircuitProtectionReport:
    """Verify conductor ampacity and OCPD sizing per NEC 2023 Articles 240 and 215.

    Implements:
      1. NEC Table 310.16 (75 °C column) ampacity lookup — copper and aluminum.
      2. NEC 215.3 / 210.20(A): required OCPD ≥ 1.25 × I_continuous + I_non_continuous.
      3. NEC 240.4(B): OCPD rating ≤ conductor ampacity.
      4. NEC 240.4(D): Small-conductor maximum OCPD (14 AWG → 15 A, 12 → 20 A, 10 → 30 A,
         copper only).

    Args:
        conductor: ConductorSpec — AWG, material, insulation class.
        load: LoadSpec — continuous and non-continuous current, voltage, phase.
        ocpd: OcpdSpec — breaker rating and type.

    Returns:
        CircuitProtectionReport with ampacity, required OCPD, compliance flags,
        NEC code sections cited, and honest engineering caveats.

    Raises:
        ValueError: If any input is outside accepted ranges.
    """
    # ---- input validation ----
    awg = conductor.awg_size
    material = conductor.material.lower()
    insulation = conductor.insulation_class.upper()

    if awg not in _VALID_AWG:
        raise ValueError(
            f"Unsupported AWG size {awg!r}.  Valid: {sorted(_VALID_AWG)}"
        )
    if material not in _VALID_MATERIAL:
        raise ValueError(
            f"material must be 'copper' or 'aluminum', got {material!r}"
        )
    if insulation not in _VALID_INSULATION:
        raise ValueError(
            f"insulation_class must be one of {sorted(_VALID_INSULATION)}, got {insulation!r}"
        )
    if load.phase not in _VALID_PHASE:
        raise ValueError(
            f"phase must be 'single_phase' or 'three_phase', got {load.phase!r}"
        )
    if load.continuous_current_A < 0:
        raise ValueError("continuous_current_A must be non-negative")
    if load.non_continuous_current_A < 0:
        raise ValueError("non_continuous_current_A must be non-negative")
    if load.voltage_V <= 0:
        raise ValueError("voltage_V must be positive")
    if ocpd.breaker_rating_A <= 0:
        raise ValueError("breaker_rating_A must be positive")
    if ocpd.breaker_type not in _VALID_BREAKER_TYPE:
        raise ValueError(
            f"breaker_type must be one of {sorted(_VALID_BREAKER_TYPE)}, got {ocpd.breaker_type!r}"
        )

    # ---- Table 310.16 ampacity lookup ----
    row = _TABLE_310_16_75C[awg]
    cu_amp, al_amp = row

    if material == "copper":
        ampacity = cu_amp
    else:
        if al_amp is None:
            raise ValueError(
                f"NEC Table 310.16 does not list an ampacity for {awg} AWG aluminum "
                f"(aluminum conductors are not rated at this size in the NEC)."
            )
        ampacity = al_amp

    # ---- 240.4(D) small-conductor cap ----
    small_cond_cap: float | None = None
    if material == "copper" and awg in _SMALL_CONDUCTOR_MAX_OCPD_CU:
        small_cond_cap = _SMALL_CONDUCTOR_MAX_OCPD_CU[awg]

    derated_ampacity = min(ampacity, small_cond_cap) if small_cond_cap is not None else ampacity

    # ---- NEC 215.3 / 210.20(A): required OCPD minimum ----
    # OCPD must be rated ≥ 125 % of continuous load + 100 % of non-continuous load.
    required_ocpd_min = 1.25 * load.continuous_current_A + load.non_continuous_current_A

    # ---- Compliance checks ----
    # (a) OCPD is large enough for the load (NEC 215.3 / 210.20(A))
    ocpd_large_enough = ocpd.breaker_rating_A >= required_ocpd_min

    # (b) OCPD does not exceed conductor derated ampacity (NEC 240.4(B) + 240.4(D))
    ocpd_not_too_large = ocpd.breaker_rating_A <= derated_ampacity

    ocpd_compliant = ocpd_large_enough and ocpd_not_too_large

    # (c) Conductor ampacity ≥ required OCPD size (240.4(B): the conductor must
    #     be protected at no more than its ampacity; for our check this means the
    #     conductor must be able to carry at least required_ocpd_min amps without
    #     exceeding its ampacity).
    conductor_adequate = derated_ampacity >= required_ocpd_min

    # ---- Code sections cited ----
    sections: list[str] = [
        "NEC 2023 Table 310.16 (75°C column)",
        "NEC 2023 Article 240.4(B) — conductor protection",
        "NEC 2023 Article 215.3 / 210.20(A) — 125% continuous load sizing",
    ]
    if small_cond_cap is not None:
        sections.append(
            f"NEC 2023 Article 240.4(D) — small conductor rule "
            f"({awg} AWG Cu ≤ {small_cond_cap:.0f} A OCPD)"
        )

    # ---- Honest caveat ----
    caveat_parts = [
        "Ampacity baseline: NEC Table 310.16 75°C column (THWN/THHN/XHHW/RHW), "
        "≤3 current-carrying conductors in conduit, 30°C ambient.",
        "No ambient-temperature derating applied (NEC 310.15(B)(2)(a) correction "
        "factors are NOT included — apply correction if ambient ≠ 30°C).",
        "No conductor-bundling derating applied (NEC Table 310.15(B)(3)(a) "
        "adjustment factors for >3 conductors NOT included).",
    ]
    if material == "aluminum":
        caveat_parts.append(
            "Aluminum ampacity: NEC Table 310.16 Al column (≈ 78% of copper; "
            "verify alloy and termination temperature rating)."
        )
    caveat_parts.append(
        "This check covers ampacity + OCPD rating rules only; "
        "short-circuit withstand, arc-flash, and grounding are out of scope."
    )

    return CircuitProtectionReport(
        ampacity_A=ampacity,
        required_ocpd_min_A=round(required_ocpd_min, 4),
        derated_ampacity_A=derated_ampacity,
        ocpd_compliant=ocpd_compliant,
        conductor_adequate=conductor_adequate,
        code_section_cited=sections,
        honest_caveat=" | ".join(caveat_parts),
    )
