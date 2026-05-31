"""
kerf_mold.surface_finish_check
===============================
Validates that a molded part's resin + mold-steel + processing combination can
achieve the requested SPI Mold Finish Standard, and recommends mold steel
hardness and polishing method.

SPI Mold Finish Standards (2017)
----------------------------------
The Society of Plastics Industry (SPI) / Plastics Industry Association (PLASTICS)
defines four finish categories for injection molds, each subdivided into three
sub-grades:

    Grade A — Mirror / High-Polish (optical-quality)
    ─────────────────────────────────────────────────
    SPI-A1  Ra ≤ 0.012 µm   #3 diamond buff on grade S136 or equivalent (52+ HRC)
    SPI-A2  Ra ≤ 0.025 µm   #6 diamond buff on S136 / H13 (48+ HRC)
    SPI-A3  Ra ≤ 0.050 µm   #15 diamond buff on S136 / H13 (44+ HRC)

    Grade B — Semi-Gloss (fine stone / paper finish)
    ──────────────────────────────────────────────────
    SPI-B1  Ra ≤ 0.10 µm    600-grit stone on H13 / P20 (≥ 38 HRC)
    SPI-B2  Ra ≤ 0.20 µm    400-grit stone on H13 / P20 (≥ 32 HRC)
    SPI-B3  Ra ≤ 0.40 µm    320-grit stone on P20 (≥ 28 HRC)

    Grade C — Matte (paper/emery cloth polish)
    ────────────────────────────────────────────
    SPI-C1  Ra ≤ 0.80 µm    400-grit emery on P20 (≥ 28 HRC)
    SPI-C2  Ra ≤ 1.60 µm    320-grit emery on P20 (≥ 28 HRC)
    SPI-C3  Ra ≤ 3.20 µm    220-grit emery on P20 (≥ 20 HRC)

    Grade D — Textured / Industrial (blasted)
    ────────────────────────────────────────────
    SPI-D1  Ra  ~ 3.2 µm    dry blast #11 glass bead on P20 (any HRC ≥ 20)
    SPI-D2  Ra  ~ 6.4 µm    dry blast #240 oxide on P20 (any HRC ≥ 20)
    SPI-D3  Ra  ~ 14.0 µm   dry blast #24 oxide on P20 (any HRC ≥ 20)

Resin Compatibility Rules (Menges §11)
-----------------------------------------
A-grade polishes transfer a mirror surface to the molded part only when:
  1. The mold cavity has NO free glass-fiber reinforcement at the surface.
     Glass-reinforced resins (≥ 10 wt % GF) present fiber pull-out and
     fiber-print-through at ejection, permanently imprinting sub-micron
     scratch patterns that prevent Ra < 0.10 µm on the *part* regardless of
     mold finish.  (Menges §11.4.2 — "fiber print-through below the resin
     skin layer"; observable above 30 % GF at all process conditions.)
  2. The resin is amorphous or very fine semi-crystalline and has optical
     clarity potential: PMMA, PC, ABS, TPU (amorphous) → fully capable at A.
     PA66 (semi-crystalline) — achievable to A3; A1/A2 are marginal without
     specialised post-mold polishing due to crystalline-skin haze.
     PP (semi-crystalline, high crystallinity) — limited to B-grade in standard
     IM; A3 only with very precise mold temperature control and clarified grade.

Steel and Hardness Requirements
---------------------------------
The Rockwell hardness (HRC) of the mold steel determines:
  • Achievable surface finish: soft steels polish unevenly; hard steels accept
    finer abrasives without smearing (Menges §11.3.1).
  • Polishing longevity: steel below the recommended HRC wears out during
    polishing, causing "orange-peel" micro-texture.

  Steel    Typical HRC range    Application
  ───────  ───────────────────  ──────────────────────────────────────────
  P20      28–36                High-volume B/C/D grade, pre-hardened,
                                low-cost; insufficient for A-grade
  H13      40–52                A3/B/C; hot-work tool steel; good for
                                glass-filled (harder than P20)
  S136     48–58                A1/A2/A3; corrosion-resistant stainless
                                tool steel; best polishability; required
                                for optical-grade mirror finish
  420SS    26–52                Corrosion-resistant; polishable to A2/A3;
                                poor edge retention at low HRC

Honest Caveats
---------------
This module is a CATALOG-based compliance checker using published SPI finish
grades, Menges §11 resin-compatibility rules, and steel hardness lookup tables.
It does NOT model:
  • Texture chemistry (chemical etching achievability vs. resin grade)
  • Etcher capability (actual achievable depth depends on etch bath,
    concentration, temperature, and cycle count — not modelled)
  • Polishing wear-life (how many shots before the mold re-polish is needed;
    wear rate depends on abrasive resin filler content, shot count, injection
    speed, and cavity temperature — not modelled)
  • Part geometry effects (weld lines, sharp edges, and deep ribs are harder
    to polish and may not achieve the specified Ra even with correct steel)
  • Process variables (mold temperature, hold pressure, cooling time all
    affect surface replication fidelity — not modelled here)

References
-----------
SPI (now PLASTICS — Plastics Industry Association) "Mold Finish Standards"
  2017 edition — defines A1–D3 finish categories, Ra ranges, and recommended
  polishing methods.
Menges G., Mohren P. "How to Make Injection Molds", 3rd ed., Hanser 2001,
  §11 (Surface Finish of Injection Molds) — resin-steel compatibility,
  polishing practice, glass-fiber print-through.
Bryce D. M. "Plastic Injection Molding: Mold Design and Construction
  Fundamentals", Society of Manufacturing Engineers, 1998, Ch. 8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# SPI finish catalogue
# ---------------------------------------------------------------------------

# (Ra_max_um, min_HRC, recommended_steel, polishing_method)
_SPI_CATALOG: dict[str, tuple[float, float, str, str]] = {
    #              Ra_max  minHRC   rec_steel   polishing_method
    "SPI-A1": (0.012,  50.0,  "S136",  "Diamond paste / diamond buff #3 on hardened S136 ≥50 HRC; final lap with 1 µm diamond slurry"),
    "SPI-A2": (0.025,  48.0,  "S136",  "Diamond buff #6 on S136 or H13 ≥48 HRC; final lap with 3 µm diamond paste"),
    "SPI-A3": (0.050,  44.0,  "S136",  "Diamond buff #15 on S136 or H13 ≥44 HRC; final lap with 6 µm diamond paste"),
    "SPI-B1": (0.100,  38.0,  "H13",   "600-grit stone followed by 1200-grit paper on H13 or P20 ≥38 HRC"),
    "SPI-B2": (0.200,  32.0,  "H13",   "400-grit stone on H13 or P20 ≥32 HRC"),
    "SPI-B3": (0.400,  28.0,  "P20",   "320-grit stone on P20 ≥28 HRC"),
    "SPI-C1": (0.800,  28.0,  "P20",   "400-grit emery cloth on P20 ≥28 HRC"),
    "SPI-C2": (1.600,  28.0,  "P20",   "320-grit emery cloth on P20 ≥28 HRC"),
    "SPI-C3": (3.200,  20.0,  "P20",   "220-grit emery cloth on P20 ≥20 HRC"),
    "SPI-D1": (3.200,  20.0,  "P20",   "Dry blast #11 glass bead on P20; no polishing required"),
    "SPI-D2": (6.400,  20.0,  "P20",   "Dry blast #240 aluminium oxide on P20"),
    "SPI-D3": (14.00,  20.0,  "P20",   "Dry blast #24 aluminium oxide on P20; coarsest SPI texture"),
}

# Glass-fiber-filled designators that trigger A-grade incompatibility
_GLASS_FILLED_KEYWORDS = ("glass-filled", "gf", "glass_filled", "glassfilled")

# Resins with known limitations for A1/A2 (semi-crystalline, surface haze risk)
# Maps resin_lower -> max_achievable_grade (None = no limit)
_RESIN_LIMITS: dict[str, Optional[str]] = {
    "abs":            None,       # fully achievable through A1
    "pc":             None,       # optical grade, excellent polishability
    "pmma":           None,       # optical grade; highest polishability
    "tpu":            None,       # amorphous; achievable to A1 with care
    "pa66":           "SPI-A3",   # semi-crystalline skin haze limits to A3
    "pa":             "SPI-A3",   # generic nylon alias
    "pp":             "SPI-B1",   # high crystallinity limits to B-grade
    "pe":             "SPI-B3",   # polyethylene — low polish potential
    "pom":            "SPI-B2",   # acetal — moderate polish limit
    "pbt":            "SPI-B2",   # semi-crystalline polyester
    "pet":            "SPI-B1",   # semi-crystalline polyester (lower haze than PBT)
    "ldpe":           "SPI-C1",   # soft; very limited
    "hdpe":           "SPI-B3",   # similar to PP
}

# Ordered SPI grades (finest → coarsest) for limit comparison
_SPI_ORDER = [
    "SPI-A1", "SPI-A2", "SPI-A3",
    "SPI-B1", "SPI-B2", "SPI-B3",
    "SPI-C1", "SPI-C2", "SPI-C3",
    "SPI-D1", "SPI-D2", "SPI-D3",
]

# Steel-to-max-achievable grade mapping
_STEEL_LIMITS: dict[str, str] = {
    "S136":  "SPI-A1",   # best polishability
    "420SS": "SPI-A2",   # corrosion-resistant; A2 max reliable
    "H13":   "SPI-A3",   # hot-work steel; A3 max
    "P20":   "SPI-B3",   # pre-hardened; max B3
}


def _grade_index(grade: str) -> int:
    """Return position in _SPI_ORDER (0 = finest A1, 11 = coarsest D3)."""
    try:
        return _SPI_ORDER.index(grade)
    except ValueError:
        raise ValueError(f"Unknown SPI grade: {grade!r}. Valid grades: {_SPI_ORDER}")


def _is_glass_filled(resin: str) -> bool:
    """Return True if the resin name indicates glass reinforcement."""
    r = resin.lower()
    return any(kw in r for kw in _GLASS_FILLED_KEYWORDS)


def _resin_key(resin: str) -> str:
    """Normalise resin name for lookup in _RESIN_LIMITS."""
    r = resin.lower().strip()
    # Strip common suffixes: "pa66" -> "pa66" (already in dict)
    # "glass-filled-pa" -> handled by _is_glass_filled first
    return r


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SurfaceFinishSpec:
    """Required cosmetic surface finish specification.

    Attributes
    ----------
    required_finish : str
        Target SPI finish grade, e.g. "SPI-A2", "SPI-B1", "SPI-C2", "SPI-D3".
        Must be one of the 12 standard SPI 2017 grades.
    resin : str
        Resin or polymer grade, e.g. "ABS", "PC", "PA66", "PP", "PMMA",
        "TPU", "glass-filled-PA".  Case-insensitive.
    """

    required_finish: str
    resin: str

    def __post_init__(self) -> None:
        if self.required_finish not in _SPI_CATALOG:
            raise ValueError(
                f"required_finish {self.required_finish!r} is not a recognised SPI grade. "
                f"Valid values: {sorted(_SPI_CATALOG)}"
            )
        if not self.resin or not isinstance(self.resin, str):
            raise ValueError("resin must be a non-empty string")


@dataclass
class MoldSpec:
    """Mold configuration for finish validation.

    Attributes
    ----------
    mold_steel : str
        Steel grade: "P20", "H13", "S136", "420SS".
    hardness_HRC : float
        Actual Rockwell C hardness of the mold cavity steel. Must be > 0.
    mold_finish_achieved : str, optional
        The SPI finish grade already achieved on the mold (blank = not yet
        polished / unknown).  If provided, used to cross-check against
        the required finish.  Default: "".
    """

    mold_steel: str
    hardness_HRC: float
    mold_finish_achieved: str = ""

    def __post_init__(self) -> None:
        if self.mold_steel not in _STEEL_LIMITS:
            raise ValueError(
                f"mold_steel {self.mold_steel!r} not recognised. "
                f"Valid values: {sorted(_STEEL_LIMITS)}"
            )
        if self.hardness_HRC <= 0:
            raise ValueError(
                f"hardness_HRC must be > 0, got {self.hardness_HRC}"
            )


@dataclass
class SurfaceFinishReport:
    """Result of check_surface_finish.

    Attributes
    ----------
    achievable : bool
        True if the resin + mold configuration can achieve the required finish.
    recommended_steel : str
        Recommended mold steel grade for the required finish (from SPI catalog).
    recommended_hardness_HRC_min : float
        Minimum mold steel hardness (HRC) recommended for the required finish.
    recommended_polishing_method : str
        Polishing method description (abrasive type, grit, technique).
    Ra_target_um : float
        Maximum Ra (µm) allowed by the required SPI finish grade.
    Ra_achievable_um : float
        Estimated Ra (µm) achievable given the actual mold steel and hardness.
        If the configuration meets requirements, equals Ra_target_um.
        If steel is under-grade, equals the Ra limit of the mold steel's max
        achievable grade.
    glass_filled_warning : str or None
        Warning message if the resin contains glass fibers that prevent A-grade
        finishes.  None if no glass-fill concern.
    honest_caveat : str
        Plain-language statement of model limitations.
    """

    achievable: bool
    recommended_steel: str
    recommended_hardness_HRC_min: float
    recommended_polishing_method: str
    Ra_target_um: float
    Ra_achievable_um: float
    glass_filled_warning: Optional[str]
    honest_caveat: str


# ---------------------------------------------------------------------------
# Honest caveat string
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Catalog-based compliance check using SPI Mold Finish Standards 2017 Ra bands "
    "and Menges §11 resin-compatibility rules. Does NOT model: (1) texture chemistry "
    "— chemical etching achievability depends on etch bath composition, resin "
    "crystallinity, and pigment type (not modelled); (2) etcher capability — actual "
    "achievable etch depth depends on bath concentration, temperature, and cycle count "
    "(not modelled); (3) polishing wear-life — how many shots before re-polish depends "
    "on abrasive filler content, shot count, injection speed, and cavity temperature "
    "(not modelled); (4) part geometry — weld lines, sharp internal corners, and deep "
    "ribs are locally harder to polish and may not achieve the specified Ra even with "
    "correct steel selection; (5) process variables — mold temperature, hold pressure, "
    "and cooling time all affect surface replication fidelity; low mold temperature can "
    "leave a frosted skin on otherwise mirror-polished cavities. "
    "References: SPI/PLASTICS Mold Finish Standards 2017; "
    "Menges G., Mohren P. How to Make Injection Molds 3rd ed. Hanser 2001 §11; "
    "Bryce D. M. Plastic Injection Molding: Mold Design and Construction Fundamentals, "
    "SME 1998 Ch. 8."
)


# ---------------------------------------------------------------------------
# Core check function
# ---------------------------------------------------------------------------

def check_surface_finish(
    part: SurfaceFinishSpec,
    mold: MoldSpec,
) -> SurfaceFinishReport:
    """Validate that the mold configuration can achieve the required SPI finish.

    Parameters
    ----------
    part : SurfaceFinishSpec
        Required surface finish grade and resin.
    mold : MoldSpec
        Mold steel, hardness, and (optionally) the already-achieved finish.

    Returns
    -------
    SurfaceFinishReport
        Achievability flag, recommendations, Ra values, glass-fill warning,
        and honest caveat.

    Raises
    ------
    ValueError
        If any input field has an invalid value (delegated to dataclass
        ``__post_init__`` validators).
    """
    req_grade = part.required_finish
    req_ra_max, req_hrc_min, rec_steel, polishing_method = _SPI_CATALOG[req_grade]

    # ------------------------------------------------------------------
    # 1. Glass-fiber check (Menges §11.4.2)
    # ------------------------------------------------------------------
    glass_filled_warning: Optional[str] = None
    glass_fill_fail = False

    if _is_glass_filled(part.resin):
        # Glass-reinforced resins cannot achieve A-grade finishes
        req_idx = _grade_index(req_grade)
        a3_idx = _grade_index("SPI-A3")
        if req_idx <= a3_idx:  # requesting A1, A2, or A3
            glass_filled_warning = (
                f"Glass-fiber-reinforced resin '{part.resin}' cannot achieve "
                f"{req_grade} (Ra ≤ {req_ra_max} µm) finish on the molded part. "
                "Glass-fiber pull-out and fiber print-through at ejection imprint "
                "sub-micron scratch patterns into the part surface regardless of "
                "mold polish quality (Menges §11.4.2). Maximum achievable part "
                "finish with glass-filled resins is approximately SPI-B1 "
                "(Ra ≤ 0.10 µm) — and only if the mold cavity is polished to "
                "SPI-A2 or better to ensure surface resin-rich skin layer. "
                "Consider switching to an unfilled or mineral-filled grade if "
                "A-grade finish is required."
            )
            glass_fill_fail = True
        else:
            # B/C/D grades with glass fill — advisable warning only
            glass_filled_warning = (
                f"Glass-fiber-reinforced resin '{part.resin}': finish replication "
                "is degraded by fiber print-through at the part surface. "
                f"{req_grade} is achievable on the mold cavity but the molded "
                "part surface quality may be slightly coarser than the mold. "
                "Use adequate mold temperature (≥ Tg-20°C) and moderate injection "
                "speed to maximise resin-rich skin thickness (Menges §11.4.2)."
            )

    # ------------------------------------------------------------------
    # 2. Resin limit check (semi-crystalline / optical)
    # ------------------------------------------------------------------
    resin_fail = False
    resin_limit_grade: Optional[str] = None

    resin_key = _resin_key(part.resin)
    if resin_key in _RESIN_LIMITS and _RESIN_LIMITS[resin_key] is not None:
        limit = _RESIN_LIMITS[resin_key]
        assert limit is not None
        req_idx = _grade_index(req_grade)
        lim_idx = _grade_index(limit)
        if req_idx < lim_idx:  # requesting finer than the resin can achieve
            resin_fail = True
            resin_limit_grade = limit

    # ------------------------------------------------------------------
    # 3. Steel grade check
    # ------------------------------------------------------------------
    steel_max_grade = _STEEL_LIMITS.get(mold.mold_steel, "SPI-D3")
    steel_max_idx = _grade_index(steel_max_grade)
    req_idx = _grade_index(req_grade)
    steel_grade_fail = steel_max_idx > req_idx  # steel can't reach this grade

    # ------------------------------------------------------------------
    # 4. Hardness check
    # ------------------------------------------------------------------
    hardness_fail = mold.hardness_HRC < req_hrc_min

    # ------------------------------------------------------------------
    # 5. Already-achieved mold finish cross-check
    # ------------------------------------------------------------------
    achieved_grade_fail = False
    if mold.mold_finish_achieved:
        try:
            ach_idx = _grade_index(mold.mold_finish_achieved)
            if ach_idx > req_idx:  # achieved is coarser than required
                achieved_grade_fail = True
        except ValueError:
            pass  # unknown achieved grade string — ignore

    # ------------------------------------------------------------------
    # 6. Compute Ra_achievable
    # ------------------------------------------------------------------
    # Ra achievable = the worst (coarsest) limit imposed by the current mold
    # hardware (steel grade max + hardness max) — independent of resin.
    # If steel is under-spec, achievable Ra is the max for the steel's limit.
    if steel_grade_fail:
        steel_achievable_ra = _SPI_CATALOG[steel_max_grade][0]
    else:
        steel_achievable_ra = req_ra_max

    if hardness_fail:
        # Find the finest grade the actual HRC supports
        hrc_achievable_ra = req_ra_max  # start optimistic
        for grade in _SPI_ORDER:
            _, min_hrc, _, _ = _SPI_CATALOG[grade]
            if mold.hardness_HRC >= min_hrc:
                hrc_achievable_ra = _SPI_CATALOG[grade][0]
                break
        else:
            hrc_achievable_ra = _SPI_CATALOG["SPI-D3"][0]
        ra_achievable = max(steel_achievable_ra, hrc_achievable_ra)
    else:
        ra_achievable = steel_achievable_ra

    # ------------------------------------------------------------------
    # 7. Aggregate achievability
    # ------------------------------------------------------------------
    achievable = not (
        glass_fill_fail
        or resin_fail
        or steel_grade_fail
        or hardness_fail
        or achieved_grade_fail
    )

    # ------------------------------------------------------------------
    # 8. Build report
    # ------------------------------------------------------------------
    # If not achievable due to resin limit, report the resin's actual limit Ra
    if resin_fail and resin_limit_grade:
        ra_achievable = max(ra_achievable, _SPI_CATALOG[resin_limit_grade][0])

    if achievable:
        ra_achievable = req_ra_max  # best-case: exactly meets spec

    return SurfaceFinishReport(
        achievable=achievable,
        recommended_steel=rec_steel,
        recommended_hardness_HRC_min=req_hrc_min,
        recommended_polishing_method=polishing_method,
        Ra_target_um=req_ra_max,
        Ra_achievable_um=ra_achievable,
        glass_filled_warning=glass_filled_warning,
        honest_caveat=_HONEST_CAVEAT,
    )
