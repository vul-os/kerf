"""
kerf_mold.gate_vestige_check
============================
Estimate gate vestige (gate-mark protrusion) height on a molded part and
check compliance against cosmetic class requirements.

Theory
------
After degating, the gate land leaves a protruding or depressed mark on the
part surface — the *vestige*.  The size depends strongly on gate geometry,
resin ductility, degating method, and mold temperature.  Beaumont (2007)
§7.6 provides empirical guidance per gate type; Menges (2001) §6.6 covers
gate-type characteristics.

Empirical vestige model (Beaumont 2007 Table 7.4)
--------------------------------------------------
Each gate type has a characteristic vestige range due to its breakaway
geometry:

  Gate type   | Vestige estimate        | Mechanism
  ----------- | ----------------------- | ---------------------------------
  edge        | ≈ gate_thickness × 1.0  | Knife-shear leaves full thickness
  fan         | ≈ gate_thickness × 1.0  | Same as edge (wide edge gate)
  tunnel      | ≈ 0.05–0.15 mm          | Sub-surface breakaway; clean shear
  submarine   | ≈ 0.05 mm               | Angled sub-surface breakaway
  hot_tip     | ≈ 0.10–0.30 mm          | Thermal pip from gate tip freeze
  pin_point   | ≈ 0.10 mm               | Small circular gate; controlled pip
  film        | ≈ 0.50 mm               | Trimmed tab; variable scar

Cosmetic class definitions (SPI/Beaumont practice; Beaumont 2007 §7.6)
-----------------------------------------------------------------------
  A1 — no visible vestige allowed (flush surface)
  A2 — vestige ≤ 0.1 mm
  A3 — vestige ≤ 0.3 mm
  B  — vestige ≤ 1.0 mm
  C  — any visible vestige acceptable

Honest caveat
-------------
These are *empirical estimates* from Beaumont 2007.  Actual vestige depends
on:
  • Degating tool sharpness and operator technique
  • Melt temperature and resin grade ductility (e.g. ABS vs PC vs POM)
  • Mold temperature (cold mold → brittle snap; hot mold → stretched pip)
  • Gate land length (shorter = cleaner break)
  • Part wall thickness and local rigidity

For A1/A2 cosmetic surfaces confirm vestige by molding trials.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §7.6 — Gate vestige and removal, Table 7.4.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.6 — Gate types (edge, tunnel, hot-tip, fan, submarine).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Cosmetic class constants
# ---------------------------------------------------------------------------

#: Maximum vestige height (mm) per cosmetic class.
#: None means "no vestige allowed" (flush surface, e.g. Class A1).
COSMETIC_CLASS_LIMITS_MM: Dict[str, Optional[float]] = {
    "A1": 0.0,       # flush — zero protrusion
    "A2": 0.1,       # ≤ 0.1 mm
    "A3": 0.3,       # ≤ 0.3 mm
    "B":  1.0,       # ≤ 1.0 mm
    "C":  None,      # any visible vestige OK (no numeric limit)
}

_CLASS_ORDER: list[str] = ["A1", "A2", "A3", "B", "C"]


# ---------------------------------------------------------------------------
# Removal method lookup
# ---------------------------------------------------------------------------

_REMOVAL_METHODS: Dict[str, str] = {
    "edge":      "Knife trim or side-gate cutter; flash trim fixture recommended for A3/B class.",
    "tunnel":    "Automatic degating on ejection — no secondary operation for B/A3 class.",
    "submarine": "Automatic degating on ejection — no secondary operation for B/A3 class.",
    "hot_tip":   "Flush-trim or light sanding; gate pip geometry controlled by tip design.",
    "pin_point": "Hand-trim nippers or gate-pip grinder; small circular scar.",
    "fan":       "Knife trim across fan width; trimming jig recommended for A3/B class.",
    "film":      "Band-saw or blanking die trim; secondary sanding for A2/A3 class.",
}


# ---------------------------------------------------------------------------
# Vestige estimator — Beaumont 2007 Table 7.4
# ---------------------------------------------------------------------------

def _estimate_vestige_mm(gate_type: str, gate_thickness_mm: float) -> float:
    """Return estimated vestige protrusion (mm) per Beaumont 2007 Table 7.4.

    For gate types whose vestige is independent of gate_thickness, a fixed
    empirical central value is returned.  For thickness-dependent types
    (edge, fan) the vestige equals gate_thickness × 1.0 (worst-case
    handbook assumption; actual trim quality may reduce this).

    Parameters
    ----------
    gate_type : str
        Must be one of: "edge", "tunnel", "submarine", "hot_tip",
        "pin_point", "fan", "film".
    gate_thickness_mm : float
        Gate land thickness (mm).  Used for edge and fan gates.

    Returns
    -------
    float
        Estimated vestige height (mm).

    Raises
    ------
    ValueError
        If gate_type is not recognised.
    """
    gt = gate_type.lower().strip()
    if gt in ("edge", "fan"):
        # Vestige ≈ gate thickness (Beaumont 2007 Table 7.4)
        return gate_thickness_mm
    elif gt == "tunnel":
        # Sub-surface breakaway: central estimate 0.10 mm (range 0.05–0.15)
        return 0.10
    elif gt == "submarine":
        # Angled sub-surface breakaway: 0.05 mm
        return 0.05
    elif gt == "hot_tip":
        # Thermal pip: central estimate 0.20 mm (range 0.10–0.30)
        return 0.20
    elif gt == "pin_point":
        # Small circular gate: 0.10 mm
        return 0.10
    elif gt == "film":
        # Trimmed film tab: 0.50 mm
        return 0.50
    else:
        raise ValueError(
            f"Unknown gate_type '{gate_type}'. "
            f"Supported types: edge, tunnel, submarine, hot_tip, pin_point, fan, film."
        )


def _class_achieved(vestige_mm: float) -> str:
    """Return the best cosmetic class achieved for the given vestige height."""
    if vestige_mm <= 0.0:
        return "A1"
    if vestige_mm <= 0.1:
        return "A2"
    if vestige_mm <= 0.3:
        return "A3"
    if vestige_mm <= 1.0:
        return "B"
    return "C"


def _class_compliant(achieved: str, required: str) -> bool:
    """Return True if *achieved* class meets or exceeds *required* class."""
    if required not in _CLASS_ORDER:
        raise ValueError(
            f"Unknown required cosmetic class '{required}'. "
            f"Valid classes: {_CLASS_ORDER}."
        )
    if achieved not in _CLASS_ORDER:
        return False
    # Lower index in _CLASS_ORDER = stricter (A1 is index 0, C is index 4)
    return _CLASS_ORDER.index(achieved) <= _CLASS_ORDER.index(required)


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class GateSpec:
    """Specification of a gate for vestige estimation.

    Attributes
    ----------
    gate_type : str
        Gate geometry type.  Must be one of:
        "edge", "tunnel", "submarine", "hot_tip", "pin_point", "fan", "film".
    gate_thickness_mm : float
        Gate land thickness (mm).  Typically 0.5–3.0 mm.  Must be > 0.
    gate_width_mm : float
        Gate width (mm).  Primarily used for fan/film gates.  Must be > 0.
    polymer_grade : str
        Informational — e.g. "ABS", "PC", "PP".  Does not change the
        numeric estimate (ductility adjustments require trial data), but
        is recorded in the caveat.
    """

    gate_type: str
    gate_thickness_mm: float
    gate_width_mm: float
    polymer_grade: str

    def __post_init__(self) -> None:
        if self.gate_thickness_mm <= 0.0:
            raise ValueError(
                f"gate_thickness_mm must be > 0, got {self.gate_thickness_mm}"
            )
        if self.gate_width_mm <= 0.0:
            raise ValueError(
                f"gate_width_mm must be > 0, got {self.gate_width_mm}"
            )
        # Validate gate type immediately so bad input errors early
        _estimate_vestige_mm(self.gate_type, self.gate_thickness_mm)


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class GateVestigeReport:
    """Report produced by check_gate_vestige.

    Attributes
    ----------
    estimated_vestige_mm : float
        Estimated vestige protrusion height (mm) per Beaumont 2007 Table 7.4.
    cosmetic_class_required : str
        The cosmetic class requirement passed in.
    cosmetic_class_achieved : str
        Best cosmetic class achieved at the estimated vestige.
    compliant : bool
        True if estimated vestige meets the required cosmetic class.
    removal_method : str
        Recommended gate-removal / degating operation for this gate type.
    honest_caveat : str
        Plain-language statement of model limitations and key sensitivities.
    """

    estimated_vestige_mm: float
    cosmetic_class_required: str
    cosmetic_class_achieved: str
    compliant: bool
    removal_method: str
    honest_caveat: str = field(default="")


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

_HONEST_CAVEAT_TMPL = (
    "Empirical estimate from Beaumont 2007 Table 7.4 for '{gate_type}' gate "
    "(polymer: {polymer_grade}). "
    "Actual vestige depends on degating tool sharpness, melt temperature, "
    "mold temperature, gate land length, and resin grade ductility "
    "(e.g. brittle POM snaps cleaner than tough PC). "
    "For A1/A2 cosmetic class, confirm by molding trial — trim and measure "
    "vestige with a calibrated optical comparator. "
    "Reference: Beaumont J.P. Runner and Gating Design Handbook, "
    "2nd ed., Hanser 2007, §7.6 + Table 7.4; "
    "Menges et al. How to Make Injection Molds, 3rd ed., Hanser 2001, §6.6."
)


def check_gate_vestige(
    gate: GateSpec,
    required_class: str = "A2",
) -> GateVestigeReport:
    """Estimate gate vestige and check against cosmetic class requirements.

    Applies empirical vestige rules from Beaumont 2007 Table 7.4 for the
    given gate type and checks the estimate against the required SPI
    cosmetic class threshold.

    Parameters
    ----------
    gate : GateSpec
        Gate geometry and material specification.
    required_class : str, optional
        Required cosmetic class for the part surface at the gate location.
        One of "A1", "A2", "A3", "B", "C".  Default: "A2".

    Returns
    -------
    GateVestigeReport

    Raises
    ------
    ValueError
        If gate_type is unrecognised or required_class is invalid.
    """
    if required_class not in _CLASS_ORDER:
        raise ValueError(
            f"Unknown required_class '{required_class}'. "
            f"Valid classes: {_CLASS_ORDER}."
        )

    vestige_mm = _estimate_vestige_mm(gate.gate_type, gate.gate_thickness_mm)
    vestige_mm = round(vestige_mm, 6)

    achieved = _class_achieved(vestige_mm)
    compliant = _class_compliant(achieved, required_class)

    removal = _REMOVAL_METHODS.get(
        gate.gate_type.lower().strip(),
        "No removal method data — consult gate tooling manufacturer.",
    )

    caveat = _HONEST_CAVEAT_TMPL.format(
        gate_type=gate.gate_type,
        polymer_grade=gate.polymer_grade,
    )

    return GateVestigeReport(
        estimated_vestige_mm=vestige_mm,
        cosmetic_class_required=required_class,
        cosmetic_class_achieved=achieved,
        compliant=compliant,
        removal_method=removal,
        honest_caveat=caveat,
    )
