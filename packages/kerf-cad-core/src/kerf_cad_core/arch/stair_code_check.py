"""
kerf_cad_core.arch.stair_code_check
=====================================

Automated stair code-compliance checker per:
  - IBC 2024 §1011  (International Building Code — egress stairs)
  - ADA §504.2       (Americans with Disabilities Act)
  - ICC A117.1 §504  (Accessible and Usable Buildings and Facilities)
  - Ontario OBC Part 9 (Ontario Building Code — residential)

All input dimensions are in **inches** (imperial) to match the code references
directly (IBC and ADA publish requirements in inches).

Public API
----------
  StairCodeSpec    — input descriptor
  StairCodeReport  — output report with per-category booleans + violations list
  check_stair_codes(spec) -> StairCodeReport
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Jurisdiction constants
# ---------------------------------------------------------------------------

_VALID_JURISDICTIONS = frozenset(
    ["ibc_2024", "ada_504", "icc_a117_1", "ontario_obc"]
)

# IBC 2024 §1011.5.2
_IBC_RISER_MIN_IN = 4.0
_IBC_RISER_MAX_IN = 7.0
_IBC_TREAD_MIN_IN = 11.0
_IBC_WIDTH_MIN_IN = 44.0        # occupant-load ≥ 50; §1011.2 allows 36" for < 50
_IBC_WIDTH_MIN_SMALL_IN = 36.0  # < 50 occupants
_IBC_HEADROOM_MIN_IN = 80.0     # §1011.3 — 6 ft 8 in
_IBC_LANDING_MIN_IN = 36.0      # §1011.7 — landing depth ≥ stair width, min 36"

# ADA §504 / ICC A117.1 §504
_ADA_RISER_MIN_IN = 4.0
_ADA_RISER_MAX_IN = 7.0
_ADA_TREAD_MIN_IN = 11.0
_ADA_TREAD_MAX_IN = 12.0        # consistent uniform nosing projection
_ADA_HANDRAIL_MIN_IN = 34.0     # §505.4 — above stair nosing
_ADA_HANDRAIL_MAX_IN = 38.0
_ADA_HEADROOM_MIN_IN = 80.0

# Blondel formula: 24" ≤ 2R + T ≤ 25"
# (Note: IBC comfort range is sometimes quoted as 24–25"; ergonomic optimum)
_BLONDEL_MIN_IN = 24.0
_BLONDEL_MAX_IN = 25.0

# Ontario OBC Part 9 §9.8.4 (residential)
_OBC_RISER_MIN_IN = 4.0          # 100 mm converted
_OBC_RISER_MAX_IN = 8.27         # 210 mm
_OBC_TREAD_MIN_IN = 8.27         # 210 mm (nosing-to-nosing)
_OBC_WIDTH_MIN_IN = 35.43        # 900 mm
_OBC_HANDRAIL_MIN_IN = 34.0
_OBC_HANDRAIL_MAX_IN = 38.0
_OBC_HEADROOM_MIN_IN = 78.74     # 2000 mm

# Max riser count between landings (IBC §1011.8 — 147 in vertical rise)
_IBC_MAX_VERT_BETWEEN_LANDINGS_IN = 147.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StairCodeSpec:
    """Input specification for a stair flight to be code-checked.

    All linear dimensions are in **inches** (to match IBC/ADA source units).

    Parameters
    ----------
    tread_depth_in : float
        Horizontal tread depth, measured nose-to-nose (IBC §1011.5.3).
    riser_height_in : float
        Vertical riser height (IBC §1011.5.2).
    stair_width_in : float
        Clear width between handrails (or between wall faces where no handrail
        is present).
    handrail_height_in : float
        Height of the handrail gripping surface above the stair tread nosing
        (ADA §505.4).
    headroom_clearance_in : float
        Minimum vertical headroom measured from the tread nosing line
        (IBC §1011.3).
    num_risers : int
        Number of risers in the flight.
    has_landing : bool
        Whether an intermediate landing is provided between the top and bottom.
    landing_depth_in : float
        Depth of the landing in the direction of travel (IBC §1011.7).
        Only checked when *has_landing* is True.
    jurisdiction : str
        Code edition to enforce: ``"ibc_2024"`` | ``"ada_504"`` |
        ``"icc_a117_1"`` | ``"ontario_obc"``.
    """

    tread_depth_in: float
    riser_height_in: float
    stair_width_in: float
    handrail_height_in: float
    headroom_clearance_in: float
    num_risers: int
    has_landing: bool
    landing_depth_in: float
    jurisdiction: str


@dataclass
class StairCodeReport:
    """Result of ``check_stair_codes()``.

    Each boolean field is ``True`` when that dimension is **within the
    code-required range** for the chosen jurisdiction.

    Attributes
    ----------
    riser_compliant : bool
    tread_compliant : bool
    width_compliant : bool
    handrail_compliant : bool
    headroom_compliant : bool
    landing_compliant : bool
        Always ``True`` when *has_landing* is ``False`` (not required by the
        spec; a separate accessibility judgement is outside scope here).
    ratio_2r_plus_t_compliant : bool
        Blondel formula: ``24 ≤ 2R + T ≤ 25`` inches.
    turning_compliant : bool
        Vertical rise between landings ≤ IBC 147 in (12 ft 3 in). Only
        evaluated for ``ibc_2024``/``icc_a117_1``; always ``True`` for
        ``ada_504``/``ontario_obc`` (handled via landing depth check instead).
    violations : list[tuple[str, str, str]]
        Each violation is ``(code_ref, requirement, actual)`` — all strings,
        suitable for rendering in a table.
    honest_caveat : str
        Plain-English disclaimer to include in any code-review package.
    """

    riser_compliant: bool = True
    tread_compliant: bool = True
    width_compliant: bool = True
    handrail_compliant: bool = True
    headroom_compliant: bool = True
    landing_compliant: bool = True
    ratio_2r_plus_t_compliant: bool = True
    turning_compliant: bool = True
    violations: List[Tuple[str, str, str]] = field(default_factory=list)
    honest_caveat: str = ""

    # Convenience property.
    @property
    def all_compliant(self) -> bool:
        return not self.violations


# ---------------------------------------------------------------------------
# Core checker
# ---------------------------------------------------------------------------

def check_stair_codes(spec: StairCodeSpec) -> StairCodeReport:
    """Apply jurisdiction-specific building-code rules to *spec*.

    Returns a :class:`StairCodeReport` that describes pass/fail for every
    category and a structured violations list.

    Does **not** raise on invalid input — missing or nonsensical values produce
    violations rather than exceptions, so the LLM can always show a result.

    Parameters
    ----------
    spec : StairCodeSpec
        Input stair specification.

    Returns
    -------
    StairCodeReport
    """
    if spec.jurisdiction not in _VALID_JURISDICTIONS:
        report = StairCodeReport()
        report.violations.append((
            "general",
            f"jurisdiction must be one of {sorted(_VALID_JURISDICTIONS)}",
            repr(spec.jurisdiction),
        ))
        report.honest_caveat = _caveat(spec.jurisdiction)
        return report

    report = StairCodeReport()

    if spec.jurisdiction in ("ibc_2024", "icc_a117_1"):
        _check_ibc(spec, report)
    elif spec.jurisdiction == "ada_504":
        _check_ada(spec, report)
    elif spec.jurisdiction == "ontario_obc":
        _check_obc(spec, report)

    # Blondel formula is checked for ALL jurisdictions (ergonomic standard).
    _check_blondel(spec, report)

    # Turning / vertical-rise-between-landings — IBC / ICC only.
    if spec.jurisdiction in ("ibc_2024", "icc_a117_1"):
        _check_turning_ibc(spec, report)
    else:
        report.turning_compliant = True

    report.honest_caveat = _caveat(spec.jurisdiction)
    return report


# ---------------------------------------------------------------------------
# Jurisdiction-specific checkers
# ---------------------------------------------------------------------------

def _check_ibc(spec: StairCodeSpec, report: StairCodeReport) -> None:
    """IBC 2024 §1011 checks."""
    R = spec.riser_height_in
    T = spec.tread_depth_in
    W = spec.stair_width_in
    HR = spec.handrail_height_in
    HC = spec.headroom_clearance_in

    # §1011.5.2 — riser height 4"–7"
    if not (_IBC_RISER_MIN_IN <= R <= _IBC_RISER_MAX_IN):
        report.riser_compliant = False
        report.violations.append((
            "IBC 2024 §1011.5.2",
            f"riser height {_IBC_RISER_MIN_IN}\"–{_IBC_RISER_MAX_IN}\"",
            f"{R:.3f}\"",
        ))

    # §1011.5.3 — tread depth ≥ 11"
    if T < _IBC_TREAD_MIN_IN:
        report.tread_compliant = False
        report.violations.append((
            "IBC 2024 §1011.5.3",
            f"tread depth ≥ {_IBC_TREAD_MIN_IN}\"",
            f"{T:.3f}\"",
        ))

    # §1011.2 — minimum width 44" (occupant load ≥ 50); 36" for < 50
    # We use 44" as the conservative default.
    if W < _IBC_WIDTH_MIN_IN:
        report.width_compliant = False
        report.violations.append((
            "IBC 2024 §1011.2",
            f"stair width ≥ {_IBC_WIDTH_MIN_IN}\" (occ. load ≥ 50) or ≥ {_IBC_WIDTH_MIN_SMALL_IN}\" (occ. load < 50)",
            f"{W:.3f}\"",
        ))

    # §1011.3 — headroom ≥ 80"
    if HC < _IBC_HEADROOM_MIN_IN:
        report.headroom_compliant = False
        report.violations.append((
            "IBC 2024 §1011.3",
            f"headroom clearance ≥ {_IBC_HEADROOM_MIN_IN}\"",
            f"{HC:.3f}\"",
        ))

    # §1012.2 / §505.4 — handrail height 34"–38" above nosing
    if not (_ADA_HANDRAIL_MIN_IN <= HR <= _ADA_HANDRAIL_MAX_IN):
        report.handrail_compliant = False
        report.violations.append((
            "IBC 2024 §1012.2",
            f"handrail height {_ADA_HANDRAIL_MIN_IN}\"–{_ADA_HANDRAIL_MAX_IN}\" above nosing",
            f"{HR:.3f}\"",
        ))

    # §1011.7 — landing depth ≥ 36" or stair width, whichever is smaller
    if spec.has_landing:
        LD = spec.landing_depth_in
        required = max(_IBC_LANDING_MIN_IN, min(W, 36.0))
        if LD < required:
            report.landing_compliant = False
            report.violations.append((
                "IBC 2024 §1011.7",
                f"landing depth ≥ {required:.1f}\"",
                f"{LD:.3f}\"",
            ))


def _check_ada(spec: StairCodeSpec, report: StairCodeReport) -> None:
    """ADA §504 checks (mirrors ICC A117.1 §504)."""
    R = spec.riser_height_in
    T = spec.tread_depth_in
    W = spec.stair_width_in
    HR = spec.handrail_height_in
    HC = spec.headroom_clearance_in

    # §504.2 — riser 4"–7"
    if not (_ADA_RISER_MIN_IN <= R <= _ADA_RISER_MAX_IN):
        report.riser_compliant = False
        report.violations.append((
            "ADA §504.2",
            f"riser height {_ADA_RISER_MIN_IN}\"–{_ADA_RISER_MAX_IN}\"",
            f"{R:.3f}\"",
        ))

    # §504.2 — tread depth ≥ 11"
    if T < _ADA_TREAD_MIN_IN:
        report.tread_compliant = False
        report.violations.append((
            "ADA §504.2",
            f"tread depth ≥ {_ADA_TREAD_MIN_IN}\"",
            f"{T:.3f}\"",
        ))

    # §504.2 — tread uniformity (max 0.375" variation — tread max implicit 12")
    if T > _ADA_TREAD_MAX_IN:
        # Not strictly a fail but flag as advisory per §504.2 note
        report.tread_compliant = False
        report.violations.append((
            "ADA §504.2",
            f"tread depth ≤ {_ADA_TREAD_MAX_IN}\" (uniform nosing projection)",
            f"{T:.3f}\"",
        ))

    # §505.4 — handrail height 34"–38"
    if not (_ADA_HANDRAIL_MIN_IN <= HR <= _ADA_HANDRAIL_MAX_IN):
        report.handrail_compliant = False
        report.violations.append((
            "ADA §505.4",
            f"handrail height {_ADA_HANDRAIL_MIN_IN}\"–{_ADA_HANDRAIL_MAX_IN}\" above nosing",
            f"{HR:.3f}\"",
        ))

    # Headroom — ADA defers to IBC §1011.3 (80")
    if HC < _ADA_HEADROOM_MIN_IN:
        report.headroom_compliant = False
        report.violations.append((
            "ADA §504 / IBC §1011.3",
            f"headroom clearance ≥ {_ADA_HEADROOM_MIN_IN}\"",
            f"{HC:.3f}\"",
        ))

    # Width — ADA does not mandate a specific egress width; flag if < 36"
    if W < _IBC_WIDTH_MIN_SMALL_IN:
        report.width_compliant = False
        report.violations.append((
            "ADA §504 (advisory)",
            f"accessible stair width ≥ {_IBC_WIDTH_MIN_SMALL_IN}\"",
            f"{W:.3f}\"",
        ))

    # Landing
    if spec.has_landing:
        LD = spec.landing_depth_in
        if LD < _IBC_LANDING_MIN_IN:
            report.landing_compliant = False
            report.violations.append((
                "ADA §504 / IBC §1011.7",
                f"landing depth ≥ {_IBC_LANDING_MIN_IN}\"",
                f"{LD:.3f}\"",
            ))


def _check_obc(spec: StairCodeSpec, report: StairCodeReport) -> None:
    """Ontario OBC Part 9 §9.8.4 residential stair checks."""
    R = spec.riser_height_in
    T = spec.tread_depth_in
    W = spec.stair_width_in
    HR = spec.handrail_height_in
    HC = spec.headroom_clearance_in

    # OBC §9.8.4.1 — riser 100–210 mm (≈ 3.94"–8.27")
    if not (_OBC_RISER_MIN_IN <= R <= _OBC_RISER_MAX_IN):
        report.riser_compliant = False
        report.violations.append((
            "OBC §9.8.4.1",
            f"riser height {_OBC_RISER_MIN_IN:.2f}\"–{_OBC_RISER_MAX_IN:.2f}\" (100–210 mm)",
            f"{R:.3f}\"",
        ))

    # OBC §9.8.4.2 — tread ≥ 210 mm nose-to-nose (≈ 8.27")
    if T < _OBC_TREAD_MIN_IN:
        report.tread_compliant = False
        report.violations.append((
            "OBC §9.8.4.2",
            f"tread depth ≥ {_OBC_TREAD_MIN_IN:.2f}\" (210 mm nose-to-nose)",
            f"{T:.3f}\"",
        ))

    # OBC §9.8.2.1 — width ≥ 900 mm (≈ 35.43")
    if W < _OBC_WIDTH_MIN_IN:
        report.width_compliant = False
        report.violations.append((
            "OBC §9.8.2.1",
            f"stair width ≥ {_OBC_WIDTH_MIN_IN:.2f}\" (900 mm)",
            f"{W:.3f}\"",
        ))

    # OBC §9.8.7 — handrail height 865–965 mm (≈ 34.1"–38.0")
    if not (_OBC_HANDRAIL_MIN_IN <= HR <= _OBC_HANDRAIL_MAX_IN):
        report.handrail_compliant = False
        report.violations.append((
            "OBC §9.8.7",
            f"handrail height {_OBC_HANDRAIL_MIN_IN:.1f}\"–{_OBC_HANDRAIL_MAX_IN:.1f}\" (865–965 mm)",
            f"{HR:.3f}\"",
        ))

    # OBC §9.8.3.1 — headroom ≥ 2000 mm (≈ 78.74")
    if HC < _OBC_HEADROOM_MIN_IN:
        report.headroom_compliant = False
        report.violations.append((
            "OBC §9.8.3.1",
            f"headroom ≥ {_OBC_HEADROOM_MIN_IN:.2f}\" (2000 mm)",
            f"{HC:.3f}\"",
        ))

    # Landing — OBC §9.8.6.1: landing ≥ stair width
    if spec.has_landing:
        LD = spec.landing_depth_in
        if LD < W:
            report.landing_compliant = False
            report.violations.append((
                "OBC §9.8.6.1",
                f"landing depth ≥ stair width ({W:.2f}\")",
                f"{LD:.3f}\"",
            ))


# ---------------------------------------------------------------------------
# Blondel formula + turning
# ---------------------------------------------------------------------------

def _check_blondel(spec: StairCodeSpec, report: StairCodeReport) -> None:
    """Blondel ergonomic formula: 24 ≤ 2R + T ≤ 25 inches."""
    val = 2.0 * spec.riser_height_in + spec.tread_depth_in
    if not (_BLONDEL_MIN_IN <= val <= _BLONDEL_MAX_IN):
        report.ratio_2r_plus_t_compliant = False
        report.violations.append((
            "Blondel formula",
            f"24\" ≤ 2R + T ≤ 25\" (ergonomic comfort range)",
            f"2×{spec.riser_height_in:.3f}\" + {spec.tread_depth_in:.3f}\" = {val:.3f}\"",
        ))


def _check_turning_ibc(spec: StairCodeSpec, report: StairCodeReport) -> None:
    """IBC §1011.8 — max 147\" vertical rise between landings."""
    vert_rise = spec.riser_height_in * spec.num_risers
    if vert_rise > _IBC_MAX_VERT_BETWEEN_LANDINGS_IN:
        report.turning_compliant = False
        report.violations.append((
            "IBC 2024 §1011.8",
            f"max vertical rise between landings: {_IBC_MAX_VERT_BETWEEN_LANDINGS_IN}\"",
            f"{vert_rise:.3f}\" ({spec.num_risers} risers × {spec.riser_height_in:.3f}\")",
        ))


# ---------------------------------------------------------------------------
# Honest caveat text
# ---------------------------------------------------------------------------

_CAVEAT_BODY = (
    "This automated check covers the dimensional limits stated in the cited code "
    "edition. It does not substitute for a licensed architect's or building "
    "official's plan review. Occupancy classification, egress path analysis, "
    "special-use exceptions, local amendments, and accessibility overlays (e.g. "
    "California CBC, Florida FBC) are outside the scope of this tool. Always have "
    "your drawings reviewed by the authority having jurisdiction (AHJ) before "
    "construction."
)

_JURISDICTION_NOTE = {
    "ibc_2024":    "IBC 2024 §1011 (egress stairs) + §1012 (handrails).",
    "ada_504":     "ADA Standards for Accessible Design §504 + §505 (2010 edition).",
    "icc_a117_1":  "ICC A117.1-2017 §504 + §505.",
    "ontario_obc": "Ontario Building Code 2012 (as amended) Part 9 §9.8.",
}


def _caveat(jurisdiction: str) -> str:
    note = _JURISDICTION_NOTE.get(jurisdiction, "Unknown jurisdiction.")
    return f"Checked against: {note} {_CAVEAT_BODY}"
