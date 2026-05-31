"""
kerf_mold.sprue_bushing_match
==============================
Verify that a cold-runner sprue bushing nozzle-seat radius and orifice diameter
match the injection-moulding machine nozzle tip, following the Beaumont 2007
§6.4 (Sprue Bushing Design) guidelines and DME standard sprue bushing catalogue
tolerances.

Background
----------
The sprue bushing is the interface between the injection-moulding machine nozzle
and the mold runner system.  The nozzle presses against a spherical concave seat
in the sprue bushing at every shot.  If the bushing radius R is too small (equal
to or less than the machine nozzle tip radius r) the two radii interfere at the
orifice entry, creating a flash ring and making sprue break-off difficult.  If R
is too large (more than ~1 mm bigger than r) the contact ring moves outward and
may cause polymer leakage or a cold-slug pocket at the parting line.

Beaumont 2007 §6.4 rules (applied here)
----------------------------------------
  sprue_R  = nozzle_r + 0.5 mm  …  nozzle_r + 1.0 mm   (compliance band)
  sprue_O  = nozzle_O + 0.5 mm  …  nozzle_O + 1.0 mm   (orifice diameter)
  taper    = 1.5° … 3.0° per side                       (DME standard §3.2)

  Where:
    sprue_R  = sprue bushing nozzle seat radius [mm]
    nozzle_r = machine nozzle tip radius [mm]
    sprue_O  = sprue orifice diameter at the entry face [mm]
    nozzle_O = machine nozzle orifice diameter [mm]

DME standard sprue bushings
----------------------------
DME catalogue part series SB/SBA/SBT: taper 1.5°–3° per side (full-included
angle 3°–6°); seat radii offered at R = machine_r + 0.5 mm increments (e.g.
R13.5 seat for 13 mm nozzle tip; R14 seat for 13.5 mm tip, etc.).  Orifice
diameters: Ø3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0 mm standard series.

Honest caveats
--------------
1. This check applies to STANDARD COLD-RUNNER sprue bushings only.
   Hot-runner nozzle seats (DME hot-tip, edge-gate, valve-gate) follow
   completely different design rules (thermal expansion allowance, nozzle heater
   mass, gate tip diameter) — do NOT use this tool for hot-runner systems.
2. The R + 0.5–1.0 mm rule is a well-established industry heuristic cited in
   Beaumont 2007 §6.4 and consistent with DME/HASCO/Mold-Masters catalogue
   practice.  It is NOT derived from a stress-analysis model of the nozzle-seat
   contact stress.
3. Wear patterns on older machine nozzles and repeated nozzle purging can alter
   the effective tip radius.  Measure the nozzle radius directly with a radius
   gauge before ordering a sprue bushing.
4. Taper compliance (1.5°–3°/side) is a DME standard; higher-viscosity resins
   (e.g. UHMWPE, rigid PVC) may benefit from the upper end of the taper range to
   aid sprue removal; some specialty bushings go to 4°/side for foamed materials.
5. Gate orifice diameter sizing also depends on shot weight and desired sprue
   pull-off force.  The +0.5–+1.0 mm over-machine-orifice rule here is a minimum
   clearance check; consult Beaumont 2007 Table 6.2 for shot-weight sizing.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §6.4 Sprue Bushing Design (pp. 127–138).
DME Company LLC. "Mold Components Catalogue 2023", Series SB/SBA/SBT Sprue
  Bushings, §3.2 Seat Radius and Taper Specifications.
Rosato D.V. & Rosato M.G. "Injection Molding Handbook", 3rd ed., Springer 2000,
  §11.3 Sprue Bushing Selection.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Constants — Beaumont 2007 §6.4 + DME catalogue §3.2
# ---------------------------------------------------------------------------

#: Minimum R excess: sprue_R must be at least this much larger than nozzle_r [mm]
R_EXCESS_MIN_MM: float = 0.5

#: Maximum R excess: sprue_R should not exceed nozzle_r by more than this [mm]
R_EXCESS_MAX_MM: float = 1.0

#: Minimum O excess: sprue orifice must be at least this larger than nozzle orifice [mm]
O_EXCESS_MIN_MM: float = 0.5

#: Maximum O excess: sprue orifice should not exceed nozzle orifice by more than this [mm]
O_EXCESS_MAX_MM: float = 1.0

#: Minimum taper (per side) in degrees — DME standard §3.2
TAPER_MIN_DEG: float = 1.5

#: Maximum taper (per side) in degrees — DME standard §3.2
TAPER_MAX_DEG: float = 3.0

#: Honest caveat appended to every report.
_HONEST_CAVEAT = (
    "STANDARD COLD-RUNNER sprue bushings only (Beaumont 2007 §6.4 + DME "
    "catalogue §3.2). "
    "Rules: sprue_R = nozzle_r + 0.5–1.0 mm; sprue_O = nozzle_O + 0.5–1.0 mm; "
    "taper 1.5–3.0°/side. "
    "Hot-runner bushings (DME hot-tip, valve-gate, edge-gate nozzles) follow "
    "different design rules accounting for thermal expansion, heater mass, and "
    "gate-tip diameter — this tool does NOT apply to hot-runner systems. "
    "Taper values above 3°/side appear in specialty foamed-material bushings; "
    "UHMWPE/rigid PVC may warrant the upper 3° limit. "
    "Measure nozzle tip radius directly with a radius gauge; worn nozzles "
    "may deviate from nominal. "
    "Shot-weight sizing of the orifice requires Beaumont 2007 Table 6.2 — "
    "this check is a minimum-clearance verification only."
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SprueBushingSpec:
    """Specification for the sprue bushing to be checked.

    Attributes
    ----------
    nozzle_radius_R_mm : float
        Spherical concave seat radius of the sprue bushing [mm].
        Must be > 0.
    sprue_orifice_diameter_O_mm : float
        Orifice diameter at the nozzle-contact face of the sprue bushing [mm].
        Must be > 0.
    total_length_mm : float
        Overall length of the sprue bushing from nozzle face to parting plane
        [mm].  Informational; used for a minimum-practical-length sanity check
        (must be > 0).
    taper_per_side_deg : float
        Half-included angle (taper per side) of the sprue bore [degrees].
        DME standard range: 1.5°–3.0°.
        Must be > 0.
    """

    nozzle_radius_R_mm: float
    sprue_orifice_diameter_O_mm: float
    total_length_mm: float
    taper_per_side_deg: float

    def __post_init__(self) -> None:
        if self.nozzle_radius_R_mm <= 0.0:
            raise ValueError(
                f"nozzle_radius_R_mm must be > 0, got {self.nozzle_radius_R_mm!r}"
            )
        if self.sprue_orifice_diameter_O_mm <= 0.0:
            raise ValueError(
                f"sprue_orifice_diameter_O_mm must be > 0, "
                f"got {self.sprue_orifice_diameter_O_mm!r}"
            )
        if self.total_length_mm <= 0.0:
            raise ValueError(
                f"total_length_mm must be > 0, got {self.total_length_mm!r}"
            )
        if self.taper_per_side_deg <= 0.0:
            raise ValueError(
                f"taper_per_side_deg must be > 0, got {self.taper_per_side_deg!r}"
            )


@dataclass
class MachineNozzleSpec:
    """Specification for the injection-moulding machine nozzle tip.

    Attributes
    ----------
    nozzle_tip_radius_mm : float
        Convex spherical radius of the machine nozzle tip [mm].
        Must be > 0.
    nozzle_tip_orifice_diameter_mm : float
        Orifice bore diameter of the machine nozzle tip [mm].
        Must be > 0.
    """

    nozzle_tip_radius_mm: float
    nozzle_tip_orifice_diameter_mm: float

    def __post_init__(self) -> None:
        if self.nozzle_tip_radius_mm <= 0.0:
            raise ValueError(
                f"nozzle_tip_radius_mm must be > 0, got {self.nozzle_tip_radius_mm!r}"
            )
        if self.nozzle_tip_orifice_diameter_mm <= 0.0:
            raise ValueError(
                f"nozzle_tip_orifice_diameter_mm must be > 0, "
                f"got {self.nozzle_tip_orifice_diameter_mm!r}"
            )


@dataclass
class SprueMatchReport:
    """Report produced by check_sprue_bushing_match.

    Attributes
    ----------
    R_mismatch_mm : float
        Actual excess of sprue bushing seat radius over nozzle tip radius
        (sprue_R − nozzle_r).  Positive means sprue is larger (desirable).
        Negative means sprue is smaller or equal (interference risk).
    R_compliant : bool
        True if R_mismatch_mm is within [0.5, 1.0] mm (Beaumont §6.4).
    O_mismatch_mm : float
        Actual excess of sprue orifice diameter over nozzle orifice diameter
        (sprue_O − nozzle_O).  Positive means sprue orifice is larger
        (desirable).  Negative means undersized (risk of melt back-pressure
        into seat).
    O_compliant : bool
        True if O_mismatch_mm is within [0.5, 1.0] mm (Beaumont §6.4).
    taper_compliant : bool
        True if taper_per_side_deg is within [1.5, 3.0]° (DME standard §3.2).
    recommendation : str
        Plain-language summary of compliance status and corrective action.
    honest_caveat : str
        Plain-language statement of model scope and limitations.
    """

    R_mismatch_mm: float
    R_compliant: bool
    O_mismatch_mm: float
    O_compliant: bool
    taper_compliant: bool
    recommendation: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def check_sprue_bushing_match(
    sprue: SprueBushingSpec,
    nozzle: MachineNozzleSpec,
) -> SprueMatchReport:
    """Verify sprue bushing geometry against machine nozzle (Beaumont 2007 §6.4).

    Beaumont rules applied
    ----------------------
    R compliance:  nozzle_r + 0.5 mm ≤ sprue_R ≤ nozzle_r + 1.0 mm
    O compliance:  nozzle_O + 0.5 mm ≤ sprue_O ≤ nozzle_O + 1.0 mm
    Taper compliance: 1.5°/side ≤ taper ≤ 3.0°/side  (DME standard §3.2)

    Parameters
    ----------
    sprue : SprueBushingSpec
        Geometry of the sprue bushing.
    nozzle : MachineNozzleSpec
        Geometry of the machine nozzle tip.

    Returns
    -------
    SprueMatchReport

    Raises
    ------
    ValueError
        If any dimension in ``sprue`` or ``nozzle`` is non-positive
        (raised during dataclass ``__post_init__``).
    """
    # --- Radius check ---
    R_mismatch = sprue.nozzle_radius_R_mm - nozzle.nozzle_tip_radius_mm
    R_compliant = R_EXCESS_MIN_MM <= R_mismatch <= R_EXCESS_MAX_MM

    # --- Orifice check ---
    O_mismatch = sprue.sprue_orifice_diameter_O_mm - nozzle.nozzle_tip_orifice_diameter_mm
    O_compliant = O_EXCESS_MIN_MM <= O_mismatch <= O_EXCESS_MAX_MM

    # --- Taper check ---
    taper_compliant = TAPER_MIN_DEG <= sprue.taper_per_side_deg <= TAPER_MAX_DEG

    # --- Build recommendation ---
    issues = []
    actions = []

    if R_compliant:
        issues.append(
            f"Seat radius excess {R_mismatch:+.3f} mm is within the "
            f"[+{R_EXCESS_MIN_MM}, +{R_EXCESS_MAX_MM}] mm Beaumont §6.4 band "
            f"(sprue R={sprue.nozzle_radius_R_mm:.2f} mm vs nozzle r="
            f"{nozzle.nozzle_tip_radius_mm:.2f} mm)."
        )
    else:
        if R_mismatch < R_EXCESS_MIN_MM:
            if R_mismatch <= 0.0:
                issues.append(
                    f"FAIL — sprue seat radius ({sprue.nozzle_radius_R_mm:.2f} mm) "
                    f"is not larger than the nozzle tip radius "
                    f"({nozzle.nozzle_tip_radius_mm:.2f} mm); "
                    f"mismatch={R_mismatch:+.3f} mm. "
                    f"Radius interference will lock the nozzle in the bushing seat "
                    f"and cause flash at the nozzle contact ring."
                )
                actions.append(
                    f"Increase sprue seat radius to at least "
                    f"{nozzle.nozzle_tip_radius_mm + R_EXCESS_MIN_MM:.2f} mm "
                    f"(nozzle r + 0.5 mm)."
                )
            else:
                issues.append(
                    f"FAIL — seat radius excess {R_mismatch:+.3f} mm is below the "
                    f"+{R_EXCESS_MIN_MM} mm minimum (Beaumont §6.4); "
                    f"contact ring forms too close to the orifice bore, "
                    f"risking a cold-polymer lip and difficult sprue break-off."
                )
                actions.append(
                    f"Increase sprue seat radius to "
                    f"{nozzle.nozzle_tip_radius_mm + R_EXCESS_MIN_MM:.2f}–"
                    f"{nozzle.nozzle_tip_radius_mm + R_EXCESS_MAX_MM:.2f} mm."
                )
        else:
            issues.append(
                f"FAIL — seat radius excess {R_mismatch:+.3f} mm exceeds the "
                f"+{R_EXCESS_MAX_MM} mm maximum (Beaumont §6.4); contact ring "
                f"shifts too far outward — risk of polymer leakage around the "
                f"nozzle seat and cold-slug pocket formation."
            )
            actions.append(
                f"Reduce sprue seat radius to "
                f"{nozzle.nozzle_tip_radius_mm + R_EXCESS_MIN_MM:.2f}–"
                f"{nozzle.nozzle_tip_radius_mm + R_EXCESS_MAX_MM:.2f} mm."
            )

    if O_compliant:
        issues.append(
            f"Orifice excess {O_mismatch:+.3f} mm is within the "
            f"[+{O_EXCESS_MIN_MM}, +{O_EXCESS_MAX_MM}] mm Beaumont §6.4 band "
            f"(sprue O={sprue.sprue_orifice_diameter_O_mm:.2f} mm vs nozzle O="
            f"{nozzle.nozzle_tip_orifice_diameter_mm:.2f} mm)."
        )
    else:
        if O_mismatch < O_EXCESS_MIN_MM:
            if O_mismatch <= 0.0:
                issues.append(
                    f"FAIL — sprue orifice ({sprue.sprue_orifice_diameter_O_mm:.2f} mm) "
                    f"is not larger than the nozzle orifice "
                    f"({nozzle.nozzle_tip_orifice_diameter_mm:.2f} mm); "
                    f"mismatch={O_mismatch:+.3f} mm. "
                    f"Back-pressure will push melt into the nozzle-seat gap."
                )
            else:
                issues.append(
                    f"FAIL — orifice excess {O_mismatch:+.3f} mm is below the "
                    f"+{O_EXCESS_MIN_MM} mm minimum; runner entry may cold-seal "
                    f"or create excessive sprue-pull resistance."
                )
            actions.append(
                f"Increase sprue orifice diameter to "
                f"{nozzle.nozzle_tip_orifice_diameter_mm + O_EXCESS_MIN_MM:.2f}–"
                f"{nozzle.nozzle_tip_orifice_diameter_mm + O_EXCESS_MAX_MM:.2f} mm."
            )
        else:
            issues.append(
                f"FAIL — orifice excess {O_mismatch:+.3f} mm exceeds "
                f"+{O_EXCESS_MAX_MM} mm; oversized orifice increases sprue weight "
                f"(waste) and may weaken sprue break-off."
            )
            actions.append(
                f"Reduce sprue orifice diameter to "
                f"{nozzle.nozzle_tip_orifice_diameter_mm + O_EXCESS_MIN_MM:.2f}–"
                f"{nozzle.nozzle_tip_orifice_diameter_mm + O_EXCESS_MAX_MM:.2f} mm."
            )

    if taper_compliant:
        issues.append(
            f"Taper {sprue.taper_per_side_deg:.2f}°/side is within the "
            f"{TAPER_MIN_DEG}°–{TAPER_MAX_DEG}° DME standard band."
        )
    else:
        if sprue.taper_per_side_deg < TAPER_MIN_DEG:
            issues.append(
                f"FAIL — taper {sprue.taper_per_side_deg:.2f}°/side is below "
                f"the {TAPER_MIN_DEG}° DME minimum; sprue will be difficult "
                f"to demold (sticking in the bore)."
            )
            actions.append(
                f"Increase taper to at least {TAPER_MIN_DEG}°/side "
                f"(DME standard §3.2)."
            )
        else:
            issues.append(
                f"FAIL — taper {sprue.taper_per_side_deg:.2f}°/side exceeds "
                f"the {TAPER_MAX_DEG}° DME maximum; sprue mass and cycle waste "
                f"will be excessive; also weakens gate area."
            )
            actions.append(
                f"Reduce taper to {TAPER_MIN_DEG}°–{TAPER_MAX_DEG}°/side."
            )

    fully_compliant = R_compliant and O_compliant and taper_compliant
    if fully_compliant:
        summary = "COMPLIANT — sprue bushing matches machine nozzle geometry."
    else:
        summary = (
            "NON-COMPLIANT — " + "; ".join(actions)
        )

    recommendation = " | ".join(issues) + " — " + summary

    return SprueMatchReport(
        R_mismatch_mm=R_mismatch,
        R_compliant=R_compliant,
        O_mismatch_mm=O_mismatch,
        O_compliant=O_compliant,
        taper_compliant=taper_compliant,
        recommendation=recommendation,
        honest_caveat=_HONEST_CAVEAT,
    )
