"""
kerf_mold.ejector_stroke_verify
================================
Ejector stroke sufficiency verifier for injection-mold tooling.

Verifies that the machine ejector stroke is adequate to release the part from
the mold cavity, that the ejector pins collectively produce enough force, and
that individual pins remain within allowable deflection limits under load.

Checks performed
----------------
1. **Stroke adequacy** (Beaumont 2007 §9):
       required_stroke = part_depth_mm + safety_margin_mm
       PASS iff required_stroke ≤ machine_stroke_mm.

2. **Force adequacy** (Menges 2001 §7.4):
       force_per_pin = ejection_force_N / n_pins
       PASS iff force_per_pin × n_pins ≥ ejection_force_N  (tautological but
       explicit; also checks no single pin is overloaded > force_per_pin_max_N).

3. **Pin deflection** (Euler–Bernoulli cantilever, Beaumont 2007 §9.3):
       For each pin of diameter d (mm) and free length L (mm):
           I = π·d⁴/64           [mm⁴]  — second moment of area (solid round)
           δ = F·L³/(3·E·I)      [mm]   — tip deflection under tip load F
       PASS iff δ ≤ allowable_deflection_mm (default 0.05 mm per Beaumont §9.3).
       Modulus E defaults to 200 000 N/mm² (steel, P20 tool steel class).

4. **Knockout bar contact** (Beaumont 2007 §9.5):
       The knockout bar must contact the ejector plate squarely — this is
       verified by checking that the ejector plate thickness ≥ knockout_bar_diameter_mm.
       If knockout_bar_diameter_mm is not supplied the check is skipped.

Honest-flag
-----------
This module implements **static load analysis only**.  It does NOT model:
  - Dynamic ejection forces due to cycle time or ejection velocity.
  - Plastic material shrinkage effects on grip pressure during cooling.
  - Thermal expansion of pins or mold steel at operating temperature.
  - Fatigue life of ejector pins over millions of cycles.
  - Friction variation with surface finish, lubrication, or polymer type.
For dynamic or fatigue analysis use dedicated mold-simulation software.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007.
  §9    — Ejector system design and stroke requirements.
  §9.3  — Pin deflection limits.
  §9.5  — Knockout bar and ejector plate design.

Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001.
  §7.4  — Ejector design: force, stroke, and pin selection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Allowable pin tip deflection (mm) — Beaumont 2007 §9.3
DEFAULT_ALLOWABLE_DEFLECTION_MM: float = 0.05

# Young's modulus for P20 / H13 tool steel (N/mm² = MPa)
STEEL_E_N_MM2: float = 200_000.0


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class EjectorPinSpec:
    """Specification for a single ejector pin.

    Parameters
    ----------
    diameter_mm : Pin body diameter (mm).  SPI standard: 2.38 / 3.18 / 4.76 /
                  6.35 / 7.94 / 9.53 / 12.70 mm.
    free_length_mm : Unsupported (cantilevered) length from ejector plate face
                     to pin tip contact with the part (mm).
    count : Number of identical pins in the layout.  Default 1.
    """
    diameter_mm: float
    free_length_mm: float
    count: int = 1

    def __post_init__(self) -> None:
        if self.diameter_mm <= 0.0:
            raise ValueError(f"diameter_mm must be > 0, got {self.diameter_mm}")
        if self.free_length_mm <= 0.0:
            raise ValueError(f"free_length_mm must be > 0, got {self.free_length_mm}")
        if self.count < 1:
            raise ValueError(f"count must be >= 1, got {self.count}")

    @property
    def second_moment_of_area_mm4(self) -> float:
        """I = π·d⁴/64  [mm⁴] — solid circular cross-section.

        Beaumont 2007 §9.3; standard mechanics of materials.
        """
        d = self.diameter_mm
        return math.pi * d ** 4 / 64.0


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PinDeflectionResult:
    """Per-pin deflection result.

    Attributes
    ----------
    diameter_mm       : Pin diameter (mm).
    free_length_mm    : Unsupported pin length (mm).
    force_per_pin_N   : Ejection force applied to this pin (N).
    deflection_mm     : Computed tip deflection δ = F·L³/(3·E·I) (mm).
    allowable_mm      : Allowable deflection limit (mm).
    passes            : True iff deflection_mm ≤ allowable_mm.
    """
    diameter_mm: float
    free_length_mm: float
    force_per_pin_N: float
    deflection_mm: float
    allowable_mm: float
    passes: bool


@dataclass
class EjectorStrokeReport:
    """Complete ejector stroke verification report.

    Attributes
    ----------
    stroke_adequate       : PASS — required_stroke_mm ≤ machine_stroke_mm.
    required_stroke_mm    : part_depth_mm + safety_margin_mm (mm).
    machine_stroke_mm     : Rated machine ejector stroke (mm).
    stroke_clearance_mm   : machine_stroke_mm − required_stroke_mm (mm).
                            Positive = surplus; negative = shortfall.

    force_adequate        : PASS — total force capacity ≥ ejection_force_N.
    total_pin_count       : Sum of all pin counts.
    force_per_pin_N       : ejection_force_N / total_pin_count (N).
    force_capacity_N      : force_per_pin_max_N × total_pin_count (N).

    deflection_ok         : True iff every pin group passes deflection check.
    pin_deflections       : Per pin-group deflection results.
    max_deflection_mm     : Worst-case tip deflection across all pin groups (mm).

    knockout_bar_ok       : True iff knockout bar check passes (or was skipped).
    knockout_bar_checked  : Whether the knockout bar check was performed.

    violations            : List of human-readable violation strings.
    warnings              : Non-fatal advisory notes.
    ok                    : True iff ALL checks pass (and no hard violations).

    honest_flag           : Reminder that this is static-load-only analysis.
    """
    # Stroke
    stroke_adequate: bool
    required_stroke_mm: float
    machine_stroke_mm: float
    stroke_clearance_mm: float

    # Force
    force_adequate: bool
    total_pin_count: int
    force_per_pin_N: float
    force_capacity_N: float

    # Deflection
    deflection_ok: bool
    pin_deflections: List[PinDeflectionResult]
    max_deflection_mm: float

    # Knockout bar
    knockout_bar_ok: bool
    knockout_bar_checked: bool

    # Summary
    violations: List[str]
    warnings: List[str]
    ok: bool

    honest_flag: str = (
        "Static load analysis only. Does not model dynamic ejection forces, "
        "plastic shrinkage grip, thermal expansion, pin fatigue, or lubrication "
        "effects. See Beaumont 2007 §9 / Menges 2001 §7.4 for full treatment."
    )


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def verify_ejector_stroke(
    part_depth_mm: float,
    machine_stroke_mm: float,
    pins: List[EjectorPinSpec],
    ejection_force_N: float,
    safety_margin_mm: float = 5.0,
    force_per_pin_max_N: float = 500.0,
    allowable_deflection_mm: float = DEFAULT_ALLOWABLE_DEFLECTION_MM,
    steel_E_N_mm2: float = STEEL_E_N_MM2,
    ejector_plate_thickness_mm: Optional[float] = None,
    knockout_bar_diameter_mm: Optional[float] = None,
) -> EjectorStrokeReport:
    """Verify the ejector stroke and pin system for an injection mold.

    Implements four checks from Beaumont 2007 §9 and Menges 2001 §7.4:

    1. **Stroke** — required_stroke = part_depth + safety_margin ≤ machine_stroke.
    2. **Force capacity** — pin_count × force_per_pin_max ≥ ejection_force.
    3. **Pin deflection** — δ = F·L³/(3·E·I) ≤ allowable for every pin group.
    4. **Knockout bar** — ejector_plate_thickness ≥ knockout_bar_diameter (if given).

    HONEST FLAG: static load only — does not model dynamic ejection, shrinkage
    grip, thermal expansion, fatigue, or lubrication.  See Beaumont 2007 §9 and
    Menges 2001 §7.4 for full treatment.

    Parameters
    ----------
    part_depth_mm : Depth of the part in the mold cavity (mm).
    machine_stroke_mm : Machine-rated maximum ejector stroke (mm).
    pins : List of EjectorPinSpec objects describing each pin group.
    ejection_force_N : Total required ejection force (N).  Obtain from
                       ejector_pin_planner._ejection_force_total() or from
                       a rheology calculation (Menges §7.4 Eq. 7-9).
    safety_margin_mm : Additional stroke margin above part depth.  Default 5 mm
                       (Beaumont 2007 §9.1 recommends 3–8 mm).
    force_per_pin_max_N : Maximum allowable force per pin (N).  Default 500 N.
    allowable_deflection_mm : Maximum allowable tip deflection (mm).  Default
                               0.05 mm (Beaumont 2007 §9.3 Table 9.1).
    steel_E_N_mm2 : Young's modulus of pin material (N/mm²).  Default 200 000
                    (P20 / H13 tool steel; Beaumont §9.3).
    ejector_plate_thickness_mm : Thickness of the ejector plate (mm). Optional;
                                 used only for knockout bar check.
    knockout_bar_diameter_mm : Knockout bar body diameter (mm). If supplied,
                               checks ejector_plate_thickness ≥ this value
                               (Beaumont 2007 §9.5).

    Returns
    -------
    EjectorStrokeReport — dataclass with all check results and violation list.

    References
    ----------
    Beaumont J.P. "Runner and Gating Design Handbook", Hanser 2007, §9.
    Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", Hanser 2001,
    §7.4 Ejector design.
    """
    if part_depth_mm <= 0.0:
        raise ValueError(f"part_depth_mm must be > 0, got {part_depth_mm}")
    if machine_stroke_mm <= 0.0:
        raise ValueError(f"machine_stroke_mm must be > 0, got {machine_stroke_mm}")
    if ejection_force_N < 0.0:
        raise ValueError(f"ejection_force_N must be >= 0, got {ejection_force_N}")
    if not pins:
        raise ValueError("pins must be a non-empty list of EjectorPinSpec")

    violations: List[str] = []
    warnings: List[str] = []

    # ── Check 1: Stroke adequacy (Beaumont 2007 §9.1) ──────────────────────
    required_stroke_mm = part_depth_mm + safety_margin_mm
    stroke_clearance_mm = machine_stroke_mm - required_stroke_mm
    stroke_adequate = stroke_clearance_mm >= 0.0

    if not stroke_adequate:
        violations.append(
            f"STROKE INSUFFICIENT: required {required_stroke_mm:.2f} mm "
            f"(part {part_depth_mm:.2f} mm + margin {safety_margin_mm:.2f} mm) "
            f"> machine stroke {machine_stroke_mm:.2f} mm "
            f"(shortfall {-stroke_clearance_mm:.2f} mm). "
            f"Ref: Beaumont 2007 §9.1."
        )
    elif stroke_clearance_mm < 10.0:
        warnings.append(
            f"Stroke clearance {stroke_clearance_mm:.2f} mm is marginal "
            f"(< 10 mm); verify machine stroke is not reduced by tooling "
            f"at operating temperature (Beaumont §9.1)."
        )

    # ── Check 2: Force adequacy (Menges 2001 §7.4) ──────────────────────────
    total_pin_count = sum(p.count for p in pins)
    force_per_pin_N = ejection_force_N / total_pin_count if total_pin_count > 0 else 0.0
    force_capacity_N = force_per_pin_max_N * total_pin_count
    force_adequate = force_capacity_N >= ejection_force_N

    if not force_adequate:
        violations.append(
            f"FORCE INSUFFICIENT: pin capacity {force_capacity_N:.2f} N "
            f"({total_pin_count} pins × {force_per_pin_max_N:.1f} N/pin) "
            f"< required ejection force {ejection_force_N:.2f} N "
            f"(shortfall {ejection_force_N - force_capacity_N:.2f} N). "
            f"Ref: Menges 2001 §7.4."
        )

    if force_per_pin_N > force_per_pin_max_N:
        warnings.append(
            f"Average force per pin {force_per_pin_N:.2f} N exceeds "
            f"force_per_pin_max_N {force_per_pin_max_N:.1f} N. "
            f"Add more pins or increase diameter."
        )

    # ── Check 3: Pin deflection (Beaumont 2007 §9.3; Euler-Bernoulli cantilever)
    # δ = F·L³ / (3·E·I)
    # F  = ejection force borne by this pin group ÷ count (N)
    # L  = free_length_mm (mm)
    # E  = steel_E_N_mm2 (N/mm²)
    # I  = π·d⁴/64 (mm⁴)
    # Result δ in mm.
    pin_deflections: List[PinDeflectionResult] = []
    deflection_ok = True

    for pin in pins:
        f_pin = force_per_pin_N  # Force per individual pin (N)
        L = pin.free_length_mm
        E = steel_E_N_mm2
        I = pin.second_moment_of_area_mm4

        delta_mm = (f_pin * L ** 3) / (3.0 * E * I)
        passes = delta_mm <= allowable_deflection_mm

        pin_deflections.append(PinDeflectionResult(
            diameter_mm=pin.diameter_mm,
            free_length_mm=L,
            force_per_pin_N=round(f_pin, 6),
            deflection_mm=round(delta_mm, 8),
            allowable_mm=allowable_deflection_mm,
            passes=passes,
        ))

        if not passes:
            deflection_ok = False
            violations.append(
                f"PIN DEFLECTION EXCEEDED: Ø{pin.diameter_mm:.2f}mm pin "
                f"L={L:.1f}mm deflects {delta_mm:.4f}mm "
                f"> allowable {allowable_deflection_mm:.4f}mm "
                f"under {f_pin:.2f}N load "
                f"(I={I:.4f}mm⁴, E={E:.0f}N/mm²). "
                f"Ref: Beaumont 2007 §9.3."
            )
        elif delta_mm > allowable_deflection_mm * 0.8:
            warnings.append(
                f"Ø{pin.diameter_mm:.2f}mm pin (L={L:.1f}mm) deflection "
                f"{delta_mm:.4f}mm is >80% of allowable {allowable_deflection_mm:.4f}mm."
            )

    max_deflection_mm = max((r.deflection_mm for r in pin_deflections), default=0.0)

    # ── Check 4: Knockout bar contact (Beaumont 2007 §9.5) ──────────────────
    knockout_bar_checked = False
    knockout_bar_ok = True

    if knockout_bar_diameter_mm is not None and ejector_plate_thickness_mm is not None:
        knockout_bar_checked = True
        knockout_bar_ok = ejector_plate_thickness_mm >= knockout_bar_diameter_mm
        if not knockout_bar_ok:
            violations.append(
                f"KNOCKOUT BAR CONTACT FAIL: ejector plate thickness "
                f"{ejector_plate_thickness_mm:.2f}mm < knockout bar diameter "
                f"{knockout_bar_diameter_mm:.2f}mm. "
                f"Plate must be at least as thick as the bar for full contact. "
                f"Ref: Beaumont 2007 §9.5."
            )
    elif knockout_bar_diameter_mm is not None and ejector_plate_thickness_mm is None:
        warnings.append(
            "knockout_bar_diameter_mm supplied but ejector_plate_thickness_mm "
            "is missing; knockout bar contact check skipped."
        )

    ok = stroke_adequate and force_adequate and deflection_ok and knockout_bar_ok

    return EjectorStrokeReport(
        stroke_adequate=stroke_adequate,
        required_stroke_mm=round(required_stroke_mm, 4),
        machine_stroke_mm=round(machine_stroke_mm, 4),
        stroke_clearance_mm=round(stroke_clearance_mm, 4),
        force_adequate=force_adequate,
        total_pin_count=total_pin_count,
        force_per_pin_N=round(force_per_pin_N, 6),
        force_capacity_N=round(force_capacity_N, 4),
        deflection_ok=deflection_ok,
        pin_deflections=pin_deflections,
        max_deflection_mm=round(max_deflection_mm, 8),
        knockout_bar_ok=knockout_bar_ok,
        knockout_bar_checked=knockout_bar_checked,
        violations=violations,
        warnings=warnings,
        ok=ok,
    )
