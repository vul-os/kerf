"""Swiss-lever escapement geometry validator.

Implements the 16-check validation suite described in George Daniels,
"Watchmaking" (1981) §6.2, cross-referenced against Schmid-Hammond-Roberts
"The Theory of Horology" (2002) §10.

Public API
----------
validate_swiss_lever(geometry: dict) -> ValidationResult
    Run all 16 geometry checks.  Returns a structured result with
    violations, warnings, and Daniels section references.

compute_lift_angle(geometry: dict) -> float
    Compute derived total pallet swing angle from pallet geometry.
    Standard: 52° for 28 800 bph, 49° for high-beat.

compute_drop_uniformity(geometry: dict) -> float
    Difference between entry and exit angular drop.  Acceptable: < 0.2°.

recommend_corrections(geometry: dict, violations: list[Violation]) -> list[str]
    Human-readable correction text per violation.

Geometry dict keys
------------------
Required
~~~~~~~~
escape_wheel_teeth : int
    Number of teeth on the escape wheel.  Swiss standard: 15, 18, or 21.
escape_wheel_pitch_radius_mm : float
    Pitch-circle radius of the escape wheel (mm).
escape_wheel_addendum_mm : float
    Tooth addendum (tip overhang above pitch circle, mm).
escape_wheel_dedendum_mm : float
    Tooth dedendum (root below pitch circle, mm).
locking_face_angle_deg : float
    Angle of the pallet locking (draw) face (degrees).  Standard ≈ 10°.
impulse_face_angle_deg : float
    Angle of the pallet impulse face (degrees).  Standard 4–6°.
pallet_jewel_separation_teeth : float
    Spacing between entry and exit pallet jewels, expressed as a fraction
    of tooth pitches.  Must equal exactly 5.5 (5 teeth + ½).
impulse_pin_diameter_mm : float
    Diameter of the roller impulse pin (mm).
slot_width_mm : float
    Width of the lever notch / impulse slot (mm).
safety_roller_diameter_mm : float
    Diameter of the safety (guard) roller (mm).
roller_diameter_mm : float
    Diameter of the main roller (mm).
horn_gap_mm : float
    Clearance between the lever horn and the safety roller (mm).
entry_drop_deg : float
    Angular drop on the entry pallet side (degrees).  Typical ≈ 1.5°.
exit_drop_deg : float
    Angular drop on the exit pallet side (degrees).  Typical ≈ 1.5°.
lock_depth_ratio : float
    Lock depth as a fraction of the impulse face depth.  Standard = 1/3.
slide_entry_deg : float
    Draw (slide) angle on the entry pallet locking face (degrees).
slide_exit_deg : float
    Draw (slide) angle on the exit pallet locking face (degrees).
    Standard: slide_entry ≈ slide_exit + 1°.
beat_rate_bph : int, optional
    Beat rate in beats per hour (default 28 800).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    """A single geometry rule violation.

    Attributes
    ----------
    rule_id : str
        Short identifier, e.g. "D6.2-01".
    description : str
        Human-readable rule description.
    measured : float | str
        The value that was measured / computed.
    limit : str
        The requirement that was not met.
    daniels_ref : str
        Reference: "Daniels §6.2" or "SHR §10.x".
    severity : str
        "error" (will not function) or "warning" (sub-optimal).
    """
    rule_id: str
    description: str
    measured: Any
    limit: str
    daniels_ref: str
    severity: str = "error"


@dataclass
class ValidationResult:
    """Result of validate_swiss_lever().

    Attributes
    ----------
    valid : bool
        True when zero error-severity violations exist.
    violations : list[Violation]
        All violations (errors and warnings).
    warnings : list[str]
        Warning messages (severity="warning") as plain strings.
    daniels_section_refs : list[str]
        All Daniels / SHR section references cited.
    lift_angle_deg : float
        Computed pallet swing angle (see compute_lift_angle).
    drop_uniformity_deg : float
        |entry_drop − exit_drop| in degrees.
    """
    valid: bool
    violations: list[Violation]
    warnings: list[str]
    daniels_section_refs: list[str]
    lift_angle_deg: float
    drop_uniformity_deg: float


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Standard Swiss-lever escape-wheel tooth counts (Daniels §6.2)
_STANDARD_TOOTH_COUNTS = {15, 18, 21}

# Addendum ratio bounds: addendum / pitch_radius in [0.03, 0.12]
# Corresponds to addendum ≈ 0.9–1.1 × module; Daniels §6.2 tab.
_ADDENDUM_RATIO_MIN = 0.03
_ADDENDUM_RATIO_MAX = 0.12

# Dedendum ratio: dedendum must be > addendum (clearance)
_DEDENDUM_OVER_ADDENDUM_MIN = 1.05

# Locking face draw angle range, degrees (Daniels §6.2)
_LOCKING_FACE_MIN_DEG = 8.0
_LOCKING_FACE_MAX_DEG = 14.0
_LOCKING_FACE_NOMINAL_DEG = 10.0

# Impulse face angle range, degrees (Daniels §6.2)
_IMPULSE_FACE_MIN_DEG = 4.0
_IMPULSE_FACE_MAX_DEG = 6.0

# Pallet jewel separation: must be (N + 0.5) teeth where N is integer
# Swiss standard: 5.5 (Daniels §6.2; SHR §10.3)
_PALLET_SEP_NOMINAL = 5.5
_PALLET_SEP_TOLERANCE = 0.02  # ±0.02 tooth pitches

# Impulse pin / slot ratio (60% rule, Daniels §6.2)
# pin_diameter >= 0.60 × slot_width
_PIN_SLOT_RATIO_MIN = 0.60
_PIN_SLOT_RATIO_MAX = 0.90  # too large → fouling

# Safety roller diameter: 50–70% of main roller (empirical; SHR §10.5)
_SAFETY_ROLLER_RATIO_MIN = 0.50
_SAFETY_ROLLER_RATIO_MAX = 0.70

# Horn–jewel gap: must be ≥ 1.5 × impulse pin diameter (Daniels §6.2)
_HORN_GAP_MIN_MULTIPLIER = 1.5

# Lock depth ratio: 1/3 of impulse face (Daniels §6.2)
_LOCK_DEPTH_RATIO_NOMINAL = 1.0 / 3.0
_LOCK_DEPTH_RATIO_TOLERANCE = 0.05  # ±5%

# Drop range per side, degrees (Daniels §6.2; SHR §10.4)
_DROP_MIN_DEG = 0.5
_DROP_MAX_DEG = 2.5

# Entry slide angle should exceed exit by ~1° (Daniels §6.2)
_SLIDE_ASYMMETRY_NOMINAL_DEG = 1.0
_SLIDE_ASYMMETRY_TOLERANCE_DEG = 0.5

# Acceptable drop non-uniformity (|entry − exit|), degrees
_DROP_UNIFORMITY_LIMIT_DEG = 0.2

# Lift angle vs beat rate (Daniels §6.2; SHR §10.6)
# 28 800 bph → 52°; 36 000 bph → 49°
_LIFT_ANGLE_TABLE: dict[int, tuple[float, float]] = {
    18_000: (53.0, 57.0),
    21_600: (52.0, 56.0),
    28_800: (50.0, 54.0),  # nominal 52°
    36_000: (47.0, 51.0),  # nominal 49°
}
_LIFT_ANGLE_DEFAULT_RANGE = (48.0, 56.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _g(geometry: dict, key: str, default=None):
    """Retrieve a key from geometry with an optional default."""
    return geometry.get(key, default)


def _compute_lift_angle_from_geometry(geometry: dict) -> float:
    """Total pallet swing angle from pallet geometry.

    The pallet swings from the entry locking position through the full
    impulse arc.  The total lift is approximated as:

        lift = 2 × half_lift

    where:

        half_lift = arctan( lever_arm × sin(impulse_face_angle) / R_esc )

    For the simplified Swiss lever model (symmetric pallets, pallet pivot
    equidistant from entry and exit stones):

        lift_deg = 2 × impulse_face_angle_deg  (first-order)

    Daniels §6.2 gives the direct relationship used here.

    Returns the total pallet swing angle in degrees.
    """
    iface = float(_g(geometry, "impulse_face_angle_deg", 5.0))
    # Each pallet stone delivers iface° of lift; total = 2 × iface (Daniels)
    # Add lock + drop contribution via the pallet span geometry
    sep = float(_g(geometry, "pallet_jewel_separation_teeth", 5.5))
    teeth = int(_g(geometry, "escape_wheel_teeth", 15))
    pitch_deg = 360.0 / teeth
    # Arc subtended by the pallet span (Daniels §6.2 eq. 6-4)
    span_deg = sep * pitch_deg
    # Total pallet lift ≈ span_deg - (drop_entry + drop_exit) per Daniels
    entry_drop = float(_g(geometry, "entry_drop_deg", 1.5))
    exit_drop = float(_g(geometry, "exit_drop_deg", 1.5))
    lift = span_deg - (entry_drop + exit_drop)
    # Clamp to physically plausible range
    return max(0.0, lift)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def compute_lift_angle(geometry: dict) -> float:
    """Compute total pallet swing angle from escapement geometry.

    Standard values (Daniels §6.2):
      - 52° for 28 800 bph low-beat
      - 49° for 36 000 bph high-beat

    Parameters
    ----------
    geometry : dict
        Escapement geometry dict (see module docstring for keys).

    Returns
    -------
    float
        Total pallet lift angle in degrees.
    """
    return _compute_lift_angle_from_geometry(geometry)


def compute_drop_uniformity(geometry: dict) -> float:
    """Compute |entry_drop − exit_drop| in degrees.

    Acceptable drop non-uniformity per Daniels §6.2: < 0.2°.
    Larger values indicate unequal tooth spacing or pallet stone
    misalignment.

    Parameters
    ----------
    geometry : dict
        Escapement geometry dict.

    Returns
    -------
    float
        Absolute difference between entry and exit drop angles (degrees).
    """
    entry = float(_g(geometry, "entry_drop_deg", 0.0))
    exit_ = float(_g(geometry, "exit_drop_deg", 0.0))
    return abs(entry - exit_)


def validate_swiss_lever(geometry: dict) -> ValidationResult:
    """Run 16 geometry checks against Daniels (1981) §6.2.

    Parameters
    ----------
    geometry : dict
        Escapement geometry dict.  Required keys are listed in the module
        docstring.

    Returns
    -------
    ValidationResult
        .valid = True when no error-severity violations are present.
        .violations contains all errors and warnings.
        .warnings is a plain-string list of warning texts.
        .daniels_section_refs is the union of all §-references cited.
        .lift_angle_deg and .drop_uniformity_deg are derived scalars.
    """
    violations: list[Violation] = []

    # ------------------------------------------------------------------
    # CHECK 1 — Escape wheel tooth count: 15 / 18 / 21 (Daniels §6.2)
    # ------------------------------------------------------------------
    teeth = int(_g(geometry, "escape_wheel_teeth", 15))
    if teeth not in _STANDARD_TOOTH_COUNTS:
        violations.append(Violation(
            rule_id="D6.2-01",
            description="Escape wheel tooth count is non-standard",
            measured=teeth,
            limit=f"Must be one of {sorted(_STANDARD_TOOTH_COUNTS)}",
            daniels_ref="Daniels §6.2; SHR §10.1",
            severity="warning",
        ))

    pitch_deg = 360.0 / teeth

    # ------------------------------------------------------------------
    # CHECK 2 — Pitch circle radius positive and plausible (SHR §10.1)
    # ------------------------------------------------------------------
    r_pitch = float(_g(geometry, "escape_wheel_pitch_radius_mm", 1.925))
    if r_pitch <= 0:
        violations.append(Violation(
            rule_id="D6.2-02",
            description="Escape wheel pitch radius must be positive",
            measured=r_pitch,
            limit="> 0 mm",
            daniels_ref="SHR §10.1",
            severity="error",
        ))

    # ------------------------------------------------------------------
    # CHECK 3 — Addendum / pitch ratio (Daniels §6.2)
    # ------------------------------------------------------------------
    addendum = float(_g(geometry, "escape_wheel_addendum_mm", 0.15))
    if r_pitch > 0:
        add_ratio = addendum / r_pitch
        if not (_ADDENDUM_RATIO_MIN <= add_ratio <= _ADDENDUM_RATIO_MAX):
            violations.append(Violation(
                rule_id="D6.2-03",
                description="Escape wheel addendum/pitch-radius ratio out of range",
                measured=round(add_ratio, 4),
                limit=f"{_ADDENDUM_RATIO_MIN}–{_ADDENDUM_RATIO_MAX}",
                daniels_ref="Daniels §6.2 table",
                severity="error",
            ))

    # ------------------------------------------------------------------
    # CHECK 4 — Dedendum > addendum (clearance, Daniels §6.2)
    # ------------------------------------------------------------------
    dedendum = float(_g(geometry, "escape_wheel_dedendum_mm", 0.19))
    if dedendum <= addendum * _DEDENDUM_OVER_ADDENDUM_MIN:
        violations.append(Violation(
            rule_id="D6.2-04",
            description="Escape wheel dedendum must exceed addendum by clearance factor",
            measured=round(dedendum, 4),
            limit=f"> {_DEDENDUM_OVER_ADDENDUM_MIN} × addendum = "
                  f"{_DEDENDUM_OVER_ADDENDUM_MIN * addendum:.4f} mm",
            daniels_ref="Daniels §6.2",
            severity="error",
        ))

    # ------------------------------------------------------------------
    # CHECK 5 — Locking face draw angle (Daniels §6.2)
    # ------------------------------------------------------------------
    lock_angle = float(_g(geometry, "locking_face_angle_deg", 10.0))
    if not (_LOCKING_FACE_MIN_DEG <= lock_angle <= _LOCKING_FACE_MAX_DEG):
        violations.append(Violation(
            rule_id="D6.2-05",
            description="Pallet locking face draw angle out of range",
            measured=round(lock_angle, 2),
            limit=f"{_LOCKING_FACE_MIN_DEG}°–{_LOCKING_FACE_MAX_DEG}°",
            daniels_ref="Daniels §6.2; SHR §10.2",
            severity="error",
        ))

    # ------------------------------------------------------------------
    # CHECK 6 — Impulse face angle (Daniels §6.2: 4–6° lift per stone)
    # ------------------------------------------------------------------
    impulse_angle = float(_g(geometry, "impulse_face_angle_deg", 5.0))
    if not (_IMPULSE_FACE_MIN_DEG <= impulse_angle <= _IMPULSE_FACE_MAX_DEG):
        violations.append(Violation(
            rule_id="D6.2-06",
            description="Pallet impulse face angle out of standard range",
            measured=round(impulse_angle, 2),
            limit=f"{_IMPULSE_FACE_MIN_DEG}°–{_IMPULSE_FACE_MAX_DEG}°",
            daniels_ref="Daniels §6.2",
            severity="error",
        ))

    # ------------------------------------------------------------------
    # CHECK 7 — Pallet jewel separation = 5 teeth + ½ (Daniels §6.2)
    # ------------------------------------------------------------------
    pallet_sep = float(_g(geometry, "pallet_jewel_separation_teeth", 5.5))
    if abs(pallet_sep - _PALLET_SEP_NOMINAL) > _PALLET_SEP_TOLERANCE:
        violations.append(Violation(
            rule_id="D6.2-07",
            description="Pallet jewel separation deviates from 5½-tooth rule",
            measured=round(pallet_sep, 4),
            limit=f"{_PALLET_SEP_NOMINAL} ± {_PALLET_SEP_TOLERANCE} tooth pitches",
            daniels_ref="Daniels §6.2; SHR §10.3",
            severity="error",
        ))

    # ------------------------------------------------------------------
    # CHECK 8 — Impulse pin / slot width ratio (60% rule, Daniels §6.2)
    # ------------------------------------------------------------------
    pin_diam = float(_g(geometry, "impulse_pin_diameter_mm", 0.18))
    slot_width = float(_g(geometry, "slot_width_mm", 0.25))
    if slot_width > 0:
        pin_ratio = pin_diam / slot_width
        if pin_ratio < _PIN_SLOT_RATIO_MIN:
            violations.append(Violation(
                rule_id="D6.2-08a",
                description="Impulse pin diameter too small relative to slot width "
                            "(< 60% rule)",
                measured=round(pin_ratio, 4),
                limit=f">= {_PIN_SLOT_RATIO_MIN}  (pin/slot)",
                daniels_ref="Daniels §6.2",
                severity="error",
            ))
        elif pin_ratio > _PIN_SLOT_RATIO_MAX:
            violations.append(Violation(
                rule_id="D6.2-08b",
                description="Impulse pin diameter too large relative to slot width "
                            "(risk of fouling)",
                measured=round(pin_ratio, 4),
                limit=f"<= {_PIN_SLOT_RATIO_MAX}  (pin/slot)",
                daniels_ref="Daniels §6.2",
                severity="warning",
            ))

    # ------------------------------------------------------------------
    # CHECK 9 — Safety roller diameter (50–70% of main roller, SHR §10.5)
    # ------------------------------------------------------------------
    safety_r = float(_g(geometry, "safety_roller_diameter_mm", 0.9))
    roller_r = float(_g(geometry, "roller_diameter_mm", 1.6))
    if roller_r > 0:
        safety_ratio = safety_r / roller_r
        if not (_SAFETY_ROLLER_RATIO_MIN <= safety_ratio <= _SAFETY_ROLLER_RATIO_MAX):
            violations.append(Violation(
                rule_id="D6.2-09",
                description="Safety roller diameter outside standard range vs main roller",
                measured=round(safety_ratio, 4),
                limit=f"{_SAFETY_ROLLER_RATIO_MIN}–{_SAFETY_ROLLER_RATIO_MAX} × main roller",
                daniels_ref="SHR §10.5",
                severity="warning",
            ))

    # ------------------------------------------------------------------
    # CHECK 10 — Horn–jewel gap >= 1.5 × impulse pin diameter (Daniels §6.2)
    # ------------------------------------------------------------------
    horn_gap = float(_g(geometry, "horn_gap_mm", 0.30))
    min_horn_gap = _HORN_GAP_MIN_MULTIPLIER * pin_diam
    if horn_gap < min_horn_gap:
        violations.append(Violation(
            rule_id="D6.2-10",
            description="Horn–jewel gap below minimum safety clearance",
            measured=round(horn_gap, 4),
            limit=f">= {_HORN_GAP_MIN_MULTIPLIER} × pin_diam = {min_horn_gap:.4f} mm",
            daniels_ref="Daniels §6.2",
            severity="error",
        ))

    # ------------------------------------------------------------------
    # CHECK 11 — Lock depth ratio = 1/3 of impulse face (Daniels §6.2)
    # ------------------------------------------------------------------
    lock_depth_ratio = float(_g(geometry, "lock_depth_ratio", 1.0 / 3.0))
    if abs(lock_depth_ratio - _LOCK_DEPTH_RATIO_NOMINAL) > _LOCK_DEPTH_RATIO_TOLERANCE:
        violations.append(Violation(
            rule_id="D6.2-11",
            description="Lock depth ratio deviates from 1/3 rule",
            measured=round(lock_depth_ratio, 4),
            limit=f"{_LOCK_DEPTH_RATIO_NOMINAL:.4f} ± {_LOCK_DEPTH_RATIO_TOLERANCE}",
            daniels_ref="Daniels §6.2",
            severity="error",
        ))

    # ------------------------------------------------------------------
    # CHECK 12 — Entry drop within 0.5°–2.5° (Daniels §6.2; SHR §10.4)
    # ------------------------------------------------------------------
    entry_drop = float(_g(geometry, "entry_drop_deg", 1.5))
    if not (_DROP_MIN_DEG <= entry_drop <= _DROP_MAX_DEG):
        violations.append(Violation(
            rule_id="D6.2-12",
            description="Entry pallet angular drop outside acceptable range",
            measured=round(entry_drop, 3),
            limit=f"{_DROP_MIN_DEG}°–{_DROP_MAX_DEG}°",
            daniels_ref="Daniels §6.2; SHR §10.4",
            severity="error",
        ))

    # ------------------------------------------------------------------
    # CHECK 13 — Exit drop within 0.5°–2.5° (Daniels §6.2; SHR §10.4)
    # ------------------------------------------------------------------
    exit_drop = float(_g(geometry, "exit_drop_deg", 1.5))
    if not (_DROP_MIN_DEG <= exit_drop <= _DROP_MAX_DEG):
        violations.append(Violation(
            rule_id="D6.2-13",
            description="Exit pallet angular drop outside acceptable range",
            measured=round(exit_drop, 3),
            limit=f"{_DROP_MIN_DEG}°–{_DROP_MAX_DEG}°",
            daniels_ref="Daniels §6.2; SHR §10.4",
            severity="error",
        ))

    # ------------------------------------------------------------------
    # CHECK 14 — Drop uniformity |entry − exit| < 0.2° (Daniels §6.2)
    # ------------------------------------------------------------------
    drop_unif = abs(entry_drop - exit_drop)
    if drop_unif > _DROP_UNIFORMITY_LIMIT_DEG:
        violations.append(Violation(
            rule_id="D6.2-14",
            description="Entry/exit drop non-uniformity exceeds limit",
            measured=round(drop_unif, 4),
            limit=f"< {_DROP_UNIFORMITY_LIMIT_DEG}°",
            daniels_ref="Daniels §6.2",
            severity="error",
        ))

    # ------------------------------------------------------------------
    # CHECK 15 — Slide (draw) angles: entry ≈ exit + 1° (Daniels §6.2)
    # ------------------------------------------------------------------
    slide_entry = float(_g(geometry, "slide_entry_deg", 11.0))
    slide_exit = float(_g(geometry, "slide_exit_deg", 10.0))
    slide_asym = slide_entry - slide_exit
    if abs(slide_asym - _SLIDE_ASYMMETRY_NOMINAL_DEG) > _SLIDE_ASYMMETRY_TOLERANCE_DEG:
        violations.append(Violation(
            rule_id="D6.2-15",
            description="Entry–exit slide asymmetry deviates from 1° standard",
            measured=round(slide_asym, 3),
            limit=f"{_SLIDE_ASYMMETRY_NOMINAL_DEG}° ± "
                  f"{_SLIDE_ASYMMETRY_TOLERANCE_DEG}°  (entry − exit)",
            daniels_ref="Daniels §6.2",
            severity="warning",
        ))

    # ------------------------------------------------------------------
    # CHECK 16 — Total lift angle vs beat rate (Daniels §6.2; SHR §10.6)
    # ------------------------------------------------------------------
    lift_angle = _compute_lift_angle_from_geometry(geometry)
    bph = int(_g(geometry, "beat_rate_bph", 28_800))
    lift_range = _LIFT_ANGLE_TABLE.get(bph, _LIFT_ANGLE_DEFAULT_RANGE)
    if not (lift_range[0] <= lift_angle <= lift_range[1]):
        violations.append(Violation(
            rule_id="D6.2-16",
            description=f"Total lift angle outside standard range for {bph} bph",
            measured=round(lift_angle, 2),
            limit=f"{lift_range[0]}°–{lift_range[1]}° for {bph} bph",
            daniels_ref="Daniels §6.2; SHR §10.6",
            severity="warning",
        ))

    # ------------------------------------------------------------------
    # Assemble result
    # ------------------------------------------------------------------
    errors = [v for v in violations if v.severity == "error"]
    warnings_text = [
        f"[{v.rule_id}] {v.description} (measured={v.measured}, limit={v.limit})"
        for v in violations if v.severity == "warning"
    ]
    refs = sorted({v.daniels_ref for v in violations})

    return ValidationResult(
        valid=len(errors) == 0,
        violations=violations,
        warnings=warnings_text,
        daniels_section_refs=refs,
        lift_angle_deg=round(lift_angle, 4),
        drop_uniformity_deg=round(drop_unif, 4),
    )


# ---------------------------------------------------------------------------
# Correction recommendations
# ---------------------------------------------------------------------------

_CORRECTIONS: dict[str, str] = {
    "D6.2-01": (
        "Use a standard tooth count (15, 18, or 21).  15-tooth is most common "
        "for Swiss wristwatches (Daniels §6.2)."
    ),
    "D6.2-02": (
        "Verify the escape wheel pitch-circle radius is positive and consistent "
        "with the module and tooth count."
    ),
    "D6.2-03": (
        "Rescale the escape wheel addendum.  For Swiss lever: "
        "addendum ≈ 0.9–1.1 × module; module = pitch_diameter / tooth_count.  "
        "Larger addendum → stronger impulse but increased tooth interference risk "
        "(Daniels §6.2)."
    ),
    "D6.2-04": (
        "Increase the dedendum to provide root clearance.  "
        "Dedendum must exceed addendum by at least 5% (clearance factor).  "
        "Insufficient dedendum causes tooth tip fouling (Daniels §6.2)."
    ),
    "D6.2-05": (
        "Adjust the pallet locking face draw angle to 10° (nominal).  "
        "Below 8°: insufficient draw → pallet can rebound.  "
        "Above 14°: excessive friction → energy waste (Daniels §6.2)."
    ),
    "D6.2-06": (
        "Adjust the impulse face angle to 4–6°.  The nominal 5° per stone delivers "
        "balanced impulse.  Smaller → insufficient impulse; larger → excessive "
        "slide and wear (Daniels §6.2)."
    ),
    "D6.2-07": (
        "Reposition the pallet jewels to achieve a separation of exactly 5½ tooth "
        "pitches (Daniels §6.2 eq. 6-1).  Deviation causes unequal lock angles on "
        "entry and exit, leading to unequal drop and beat error."
    ),
    "D6.2-08a": (
        "Use a larger impulse pin (roller jewel).  The pin diameter must be at "
        "least 60% of the lever slot width to ensure positive engagement throughout "
        "the full impulse arc (Daniels §6.2)."
    ),
    "D6.2-08b": (
        "Reduce the impulse pin diameter or widen the lever slot to prevent fouling.  "
        "Pin/slot ratio > 0.90 risks jamming on entry/exit of the lever notch "
        "(Daniels §6.2)."
    ),
    "D6.2-09": (
        "Resize the safety (guard) roller to 50–70% of the main roller diameter.  "
        "Too small → guard pin misses the safety roller; too large → contacts the "
        "lever prematurely (SHR §10.5)."
    ),
    "D6.2-10": (
        "Increase the horn–jewel clearance to ≥ 1.5 × impulse pin diameter.  "
        "Insufficient clearance allows the roller jewel to contact the lever horn "
        "during non-impulse phases, causing tripping (Daniels §6.2)."
    ),
    "D6.2-11": (
        "Correct the lock depth so that it equals 1/3 of the impulse face depth.  "
        "Too shallow → safety risk (unlocking under vibration); too deep → "
        "excessive supplementary arc loss (Daniels §6.2)."
    ),
    "D6.2-12": (
        "Adjust escape-wheel tooth spacing or pallet stone angles to bring entry "
        "drop into 1.5° ± 1.0°.  Zero drop → gear locks; excessive drop → "
        "energy waste (Daniels §6.2; SHR §10.4)."
    ),
    "D6.2-13": (
        "Adjust escape-wheel tooth spacing or pallet stone angles to bring exit "
        "drop into 1.5° ± 1.0°.  Zero drop → gear locks; excessive drop → "
        "energy waste (Daniels §6.2; SHR §10.4)."
    ),
    "D6.2-14": (
        "Equalise entry and exit drop to within 0.2°.  Unequal drop indicates "
        "the escape-wheel teeth are unevenly spaced, or entry/exit pallet stones "
        "are at unequal angles from the pallet pivot (Daniels §6.2).  "
        "Re-poise the escape wheel and re-set the stones."
    ),
    "D6.2-15": (
        "Set the entry draw angle to 1° greater than the exit draw angle "
        "(e.g. entry 11°, exit 10°).  This compensates for the geometric "
        "asymmetry inherent in the Swiss lever layout (Daniels §6.2)."
    ),
    "D6.2-16": (
        "Adjust pallet geometry so that the total lift angle (pallet swing) "
        "matches the beat-rate specification.  At 28 800 bph the nominal is 52°; "
        "at 36 000 bph it is 49°.  Check pallet-jewel separation and drop "
        "symmetry (Daniels §6.2; SHR §10.6)."
    ),
}


def recommend_corrections(
    geometry: dict,
    violations: list[Violation],
) -> list[str]:
    """Return human-readable correction text for each violation.

    Parameters
    ----------
    geometry : dict
        Escapement geometry dict (used for context in messages).
    violations : list[Violation]
        Violations returned by validate_swiss_lever().

    Returns
    -------
    list[str]
        One string per violation, ordered identically to *violations*.
        Includes the rule_id prefix and the Daniels reference.
    """
    out: list[str] = []
    for v in violations:
        base = _CORRECTIONS.get(v.rule_id, "Consult Daniels §6.2 for this rule.")
        out.append(
            f"[{v.rule_id}] ({v.daniels_ref}) — {base}"
        )
    return out
