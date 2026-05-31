"""
Fuse I²t (melting energy) verification — IEC 60269 + Cooper Bussmann selection guide.

Given a fuse's pre-arcing I²t rating and a fault current waveform (described as a
square pulse: peak current × duration), verifies that:

  1. The applied I²t does NOT exceed the fuse's rated pre-arcing I²t (otherwise the
     fuse will melt prematurely or unpredictably — i.e. it clears on the fault, which
     may or may not be desired depending on perspective; see logic note below).
  2. The available short-circuit current does NOT exceed the fuse's breaking capacity
     (the fuse must be able to interrupt the maximum prospective fault current
     without rupturing).

IEC 60269 definition of I²t:
    Pre-arcing I²t  = energy let-through before the fuse element begins to arc.
    Total (clearing) I²t = pre-arcing I²t + arcing I²t.
    This module checks against the pre-arcing value (worst case for downstream
    equipment because arcing adds more let-through energy).

Applied I²t (square-wave approximation):
    I²t_applied = I_peak² × t_fault   [A²·s]
    where t_fault = duration_ms / 1000

Clearing logic (per IEC 60269-1 §2.5 and Cooper Bussmann §3):
    clears_safely  = I²t_applied ≥ fuse pre-arcing I²t
        • True  → fuse melts during the fault; it provides the intended protection.
        • False → applied energy is below the melt threshold; fuse does NOT clear.
          This is a nuisance no-trip condition: the fault current persists and
          downstream components must withstand it continuously.

Fuse class guidance (IEC 60269-1 Table 1 + Cooper Bussmann §2):
    gG  — general-purpose full-range fuse (cable protection); slow blow.
    aR  — back-up (current-limiting) fuse for semiconductor/motor protection; fast.
    F   — fast blow (US/Canadian 250 V class); melts in < 1 s at 200% rated current.
    FF  — very fast blow; semiconductor protection (300% in milliseconds).
    M   — medium / semi-time-delay.
    T   — slow blow / time-delay; motor, transformer inrush-tolerant.

HONEST CAVEATS (always included in report):
  1. Square-wave fault current assumed — sinusoidal AC fault or exponentially decaying
     DC fault NOT modelled; apply I_rms² × t (with appropriate correction factor from
     IEC 60909 or manufacturer data) for more accurate AC let-through.
  2. Arcing I²t NOT included — total clearing I²t > pre-arcing I²t; downstream
     equipment must also withstand arcing phase energy (add 20–50% per Bussmann §3.6).
  3. Pre-arcing I²t varies with ambient temperature and prior thermal history; values
     at temperatures above 25°C should be derated per the manufacturer temperature
     correction curve (typically −3% to −8% per 10°C for silver-element fuses).
  4. Breaking capacity is the rated maximum prospective symmetrical AC current (rms);
     for asymmetrical or DC faults apply the manufacturer's asymmetry factor (X/R ratio
     correction — IEC 60909-0 §11).
  5. Co-ordination between upstream and downstream fuses (selectivity / discrimination)
     is NOT checked here — use the fuse I²t hierarchy: downstream pre-arc I²t must be
     < upstream pre-arc I²t for full selectivity.

References:
  - IEC 60269-1:2020 — Low-voltage fuses — General requirements
  - IEC 60269-2:2013 — Fuses for industrial applications
  - Cooper Bussmann "Selecting Protective Devices" SPD (2014 ed.) §2–§4
  - IEC 60909-0:2016 §11 — Short-circuit currents in three-phase AC systems
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Valid fuse class strings
# ---------------------------------------------------------------------------

_VALID_FUSE_CLASSES = frozenset({"F", "M", "T", "FF", "gG", "aR"})

# Recommended fuse class for different fault regimes.
# Logic: heavy fast faults → aR or FF; moderate faults → F or gG; slow/inrush → M or T.
# Thresholds are indicative; real selection requires manufacturer time-current curves.
_FUSE_CLASS_RECOMMENDATION: dict[str, str] = {
    # ratio_pct key → (threshold, recommended)
    # Used in a series of if-else comparisons in the function.
}


def _recommend_fuse_class(ratio_pct: float, current_fuse_class: str) -> str:
    """Return a recommended fuse class based on utilisation ratio.

    A ratio near 100% (near the melt threshold) is ideal.  Very high ratios suggest
    a faster class; very low ratios suggest a slower class or a larger nominal.
    """
    if ratio_pct >= 500.0:
        return "aR" if current_fuse_class != "aR" else "aR"
    if ratio_pct >= 200.0:
        return "FF"
    if ratio_pct >= 100.0:
        return "F"
    if ratio_pct >= 50.0:
        return "gG"
    # Very low applied I²t vs fuse rating — consider a much smaller fuse
    return "T"


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FuseSpec:
    """Fuse device specification.

    Attributes:
        nominal_current_A: Fuse nominal (rated) current [A].
        voltage_rating_V: Fuse maximum voltage rating [V].
        I_squared_t_pre_arc_A2_s: Pre-arcing I²t rating of the fuse [A²·s].
            This is the energy the fuse element absorbs before it begins to arc.
            Source: manufacturer datasheet; IEC 60269-1 Table II.
        breaking_capacity_kA: Maximum prospective short-circuit current the fuse
            can safely interrupt [kA rms symmetrical].  Also called 'rated short-
            circuit breaking capacity' (I_cc in IEC 60269-1).
        fuse_class: IEC/ANSI fuse utilisation category.
            "F"  — fast blow (IEC class F, ANSI/UL 248)
            "M"  — medium time-delay
            "T"  — slow blow / time-delay (IEC class T, ANSI/UL 248)
            "FF" — very fast blow (semiconductor protection)
            "gG" — IEC general-purpose full-range (cable protection)
            "aR" — IEC back-up current-limiting (semiconductor / motor protection)
    """
    nominal_current_A: float
    voltage_rating_V: float
    I_squared_t_pre_arc_A2_s: float
    breaking_capacity_kA: float
    fuse_class: str


@dataclass
class FaultSpec:
    """Fault event specification (square-wave pulse approximation).

    Attributes:
        peak_current_A: Peak (or RMS for a rectangular approximation) fault
            current amplitude [A].
        duration_ms: Duration of the fault current pulse [ms].
        available_short_circuit_current_kA: Maximum prospective short-circuit
            current available from the supply at the fuse's installation point
            [kA rms symmetrical].  This is compared against the fuse's breaking
            capacity to verify the fuse can interrupt the fault safely.
    """
    peak_current_A: float
    duration_ms: float
    available_short_circuit_current_kA: float


@dataclass
class FuseI2tReport:
    """Result of a fuse I²t verification.

    Attributes:
        applied_I2t_A2s: Computed applied I²t for the fault [A²·s].
            = peak_current_A² × (duration_ms / 1000).
        fuse_pre_arc_I2t_A2s: Fuse pre-arcing I²t rating [A²·s] (from FuseSpec).
        ratio_pct: Ratio of applied to rated I²t as a percentage.
            ratio_pct = 100 × applied_I2t / fuse_pre_arc_I2t.
        clears_safely: True when applied_I2t ≥ fuse_pre_arc_I2t — the fault
            contains enough energy to melt the fuse element; fuse provides
            protection.  False means the fuse does NOT clear (nuisance no-trip).
        breaking_capacity_adequate: True when available_SCC ≤ fuse breaking
            capacity; fuse can safely interrupt the fault.  False means the
            prospective fault current exceeds the fuse's interrupting rating —
            the fuse may rupture violently.
        recommended_fuse_class: A suggested fuse utilisation class based on the
            ratio_pct (indicative only — confirm with manufacturer time-current
            curves).
        honest_caveat: Engineering notes and model limitations.
    """
    applied_I2t_A2s: float
    fuse_pre_arc_I2t_A2s: float
    ratio_pct: float
    clears_safely: bool
    breaking_capacity_adequate: bool
    recommended_fuse_class: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------


def check_fuse_i2t(fuse: FuseSpec, fault: FaultSpec) -> FuseI2tReport:
    """Verify a fuse's I²t rating against a fault waveform.

    Applied I²t = I_peak² × (duration_ms / 1000)   [A²·s]

    Clears safely when applied_I2t >= fuse pre-arcing I²t (the fuse melts on the
    fault, providing protection).  If applied_I2t < pre-arcing I²t the fuse does
    NOT clear — the fault current continues and downstream equipment must withstand
    it indefinitely.

    Breaking capacity check: available_SCC <= fuse.breaking_capacity_kA.

    Args:
        fuse: FuseSpec — nominal current, voltage rating, I²t pre-arc, breaking
            capacity, and fuse class.
        fault: FaultSpec — peak current, duration, and available SCC.

    Returns:
        FuseI2tReport with applied I²t, ratio, clearing decision, breaking
        capacity flag, recommended class, and honest caveats.

    Raises:
        ValueError: If any input value is outside accepted ranges.
    """
    # ---- input validation ----
    if fuse.nominal_current_A <= 0:
        raise ValueError("nominal_current_A must be positive")
    if fuse.voltage_rating_V <= 0:
        raise ValueError("voltage_rating_V must be positive")
    if fuse.I_squared_t_pre_arc_A2_s <= 0:
        raise ValueError("I_squared_t_pre_arc_A2_s must be positive")
    if fuse.breaking_capacity_kA <= 0:
        raise ValueError("breaking_capacity_kA must be positive")
    if fuse.fuse_class not in _VALID_FUSE_CLASSES:
        raise ValueError(
            f"fuse_class must be one of {sorted(_VALID_FUSE_CLASSES)}, "
            f"got {fuse.fuse_class!r}"
        )
    if fault.peak_current_A < 0:
        raise ValueError("peak_current_A must be non-negative")
    if fault.duration_ms <= 0:
        raise ValueError("duration_ms must be positive")
    if fault.available_short_circuit_current_kA < 0:
        raise ValueError("available_short_circuit_current_kA must be non-negative")

    # ---- applied I²t ----
    duration_s = fault.duration_ms / 1000.0
    applied_I2t = fault.peak_current_A ** 2 * duration_s

    # ---- ratio ----
    ratio_pct = 100.0 * applied_I2t / fuse.I_squared_t_pre_arc_A2_s

    # ---- clearing decision ----
    # clears_safely = True  → fuse melts on this fault (desired protection).
    # clears_safely = False → applied energy below melt threshold; fuse does NOT clear.
    clears_safely = applied_I2t >= fuse.I_squared_t_pre_arc_A2_s

    # ---- breaking capacity check ----
    breaking_capacity_adequate = (
        fault.available_short_circuit_current_kA <= fuse.breaking_capacity_kA
    )

    # ---- recommendation ----
    recommended_class = _recommend_fuse_class(ratio_pct, fuse.fuse_class)

    # ---- honest caveat ----
    caveat_parts = [
        "Square-wave fault current assumed: applied I²t = I_peak² × t; "
        "sinusoidal AC or exponentially decaying DC fault NOT modelled — "
        "for AC use I_rms² × t with IEC 60909 asymmetry correction.",
        "Arcing I²t NOT included: total clearing I²t > pre-arcing I²t; "
        "downstream equipment must also survive the arcing phase "
        "(add 20–50% per Cooper Bussmann §3.6 for equipment let-through rating).",
        "Pre-arcing I²t is the 25°C rated value; derate for ambient > 25°C "
        "per manufacturer temperature correction curve (typically −3% to −8%/10°C).",
        "Breaking capacity is rated rms symmetrical AC; for asymmetrical "
        "or DC faults apply the manufacturer asymmetry factor (IEC 60909-0 §11).",
        "Selectivity / discrimination between upstream and downstream fuses "
        "is NOT checked here.",
    ]
    if not clears_safely:
        caveat_parts.insert(
            0,
            "WARNING: applied I²t is below the fuse pre-arcing threshold — "
            "the fuse does NOT clear on this fault (nuisance no-trip). "
            "Downstream components must withstand the fault current continuously.",
        )
    if not breaking_capacity_adequate:
        caveat_parts.insert(
            0,
            "WARNING: available short-circuit current exceeds fuse breaking "
            "capacity — fuse may rupture violently without safely interrupting "
            "the fault.  Select a fuse with higher breaking capacity immediately.",
        )

    return FuseI2tReport(
        applied_I2t_A2s=round(applied_I2t, 6),
        fuse_pre_arc_I2t_A2s=fuse.I_squared_t_pre_arc_A2_s,
        ratio_pct=round(ratio_pct, 4),
        clears_safely=clears_safely,
        breaking_capacity_adequate=breaking_capacity_adequate,
        recommended_fuse_class=recommended_class,
        honest_caveat=" | ".join(caveat_parts),
    )
