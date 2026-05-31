"""
kerf_cad_core.arch.bolt_shear_aisc — AISC 360-22 §J3.6 bolt-group shear strength.

Checks bolted connection shear capacity per AISC 360-22 Chapter J, including:

  • Bolt shear strength §J3.6:  φ·Rn_bolt = φ·Fnv·Ab  (per shear plane)
  • Bearing at bolt holes §J3.10a:  φ·Rn_brg = φ·2.4·d·t·Fu
  • Tearout (short end distance) §J3.10b:  φ·Rn_to = φ·1.2·Lc·t·Fu
  • Slip-critical design strength §J3.8:
      Rn = μ · Du · hf · Tb · ns  (per bolt, LRFD)
      φ_sc = 1.00 (standard holes, Class A) or 0.85 (oversize/short-slot)

Table J3.2 nominal shear stress Fnv (ksi):
  A325-N  54 ksi  (threads in shear plane)
  A325-X  68 ksi  (threads excluded)
  A490-N  68 ksi  (threads in shear plane)
  A490-X  84 ksi  (threads excluded)
  A307    27 ksi  (Grade A, threads in shear plane only)

Table J3.1 minimum pretension Tb (kip) — bolt diameter in inches:
  1/2"→12, 5/8"→19, 3/4"→28, 7/8"→39, 1"→51, 1-1/8"→56, 1-1/4"→71,
  1-3/8"→85, 1-1/2"→103

LRFD only.  φ_v = 0.75 (bolt shear), φ = 0.75 (bearing/tearout).
Slip-critical: φ_sc = 1.00 standard holes / 0.85 oversized/short-slot (AISC §J3.8).

Scope caveats:
  - Shear-lag (§J4.3) not modelled
  - Combined tension + shear (§J3.7) not modelled
  - Prying action (§J3.6 tension) not modelled
  - Weld + bolt combined groups (§J8) not modelled
  - Eccentrically loaded bolt groups (instantaneous centre method) not modelled
  - Block shear (§J4.3) not checked — separate check needed
  - Fatigue and fillet-weld combinations not checked
  - AISC ASD (Ω-factor) not provided — LRFD only

References:
  AISC 360-22 §J3.6 (bolt shear), §J3.8 (slip-critical), §J3.10 (bearing/tearout)
  AISC Steel Construction Manual 16e Part 9 (Table 7-1 through 7-4)
  AISC Design Guide 9 (Seating connections)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "BoltSpec",
    "ConnectionSpec",
    "BoltShearReport",
    "check_bolt_shear",
]

# ---------------------------------------------------------------------------
# AISC Table J3.2 — Nominal shear stress Fnv (ksi)
# ---------------------------------------------------------------------------

_FNV_KSI: dict[str, float] = {
    "A325-N": 54.0,   # threads in shear plane
    "A325-X": 68.0,   # threads excluded from shear plane
    "A490-N": 68.0,   # threads in shear plane
    "A490-X": 84.0,   # threads excluded from shear plane
    "A307":   27.0,   # Grade A, threads in shear plane (no X variant)
}

# ---------------------------------------------------------------------------
# AISC Table J3.1 — Minimum pretension Tb (kip) for bolt snug-tight/SC design
# These are for Class A325 and A490 structural bolts.
# ---------------------------------------------------------------------------

_TB_KIP: dict[float, float] = {
    0.500: 12.0,   # 1/2"
    0.625: 19.0,   # 5/8"
    0.750: 28.0,   # 3/4"
    0.875: 39.0,   # 7/8"
    1.000: 51.0,   # 1"
    1.125: 56.0,   # 1-1/8"
    1.250: 71.0,   # 1-1/4"
    1.375: 85.0,   # 1-3/8"
    1.500: 103.0,  # 1-1/2"
}

# Slip coefficient per faying surface class (AISC Table J3.2 footnotes)
_MU: dict[str, float] = {
    "A": 0.35,   # Class A: unpainted clean mill scale; hot-dip galvanized + roughened
    "B": 0.50,   # Class B: unpainted blast-cleaned + Class B coating; hot-dip galvanized + roughened + Class B coating
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BoltSpec:
    """
    AISC bolt specification for shear-dominant connections.

    Parameters
    ----------
    grade : str
        Bolt grade and thread condition.  One of:
        ``"A325-N"``, ``"A325-X"``, ``"A490-N"``, ``"A490-X"``, ``"A307"``.
        -N = threads IN the shear plane; -X = threads EXCLUDED (higher Fnv).
    diameter_in : float
        Nominal bolt diameter (inches).  Common sizes: 0.5, 0.625, 0.75, 0.875, 1.0.
        Must be > 0.
    threads_in_shear_plane : bool
        If True, uses the -N (threads-in-shear) Fnv from Table J3.2.
        For grade A307, this field is ignored (only N condition exists).
        NOTE: this field is informational when grade already encodes N/X.
    num_shear_planes : int
        Number of shear planes.  1 = single-shear, 2 = double-shear.
        Default 1.  Must be ≥ 1.
    """
    grade: str
    diameter_in: float
    threads_in_shear_plane: bool = True
    num_shear_planes: int = 1


@dataclass
class ConnectionSpec:
    """
    Connected-plate geometry for bearing/tearout and slip-critical checks.

    Parameters
    ----------
    num_bolts : int
        Total number of bolts in the group.  Must be ≥ 1.
    plate_thickness_in : float
        Thickness of the bearing/tearout plate (thinnest element at bolt hole),
        in inches.  Must be > 0.
    plate_Fu_ksi : float
        Ultimate tensile strength of the bearing plate (ksi).
        Default 58.0 ksi (A36 Fy=36 → Fu=58 ksi per AISC Table 2-4).
    end_distance_in : float
        Clear distance from the centre of the bolt hole nearest the end of the
        member to the edge (end) of the connected part, measured along the
        direction of the applied shear load (inches).  Used in tearout Lc.
        Must be > 0.
    spacing_in : float
        Centre-to-centre bolt spacing along the load direction (inches).
        AISC §J3.3 minimum = 2⅔d; preferred = 3d.  Must be > 0.
    slip_critical : bool
        If True, compute slip-critical (serviceability) design strength in
        addition to bearing-type strength.  Default False.
    faying_class : str
        Faying surface class for slip-critical strength.
        ``"A"`` (μ=0.35) or ``"B"`` (μ=0.50).  Default ``"A"``.
    num_slip_planes : int
        Number of slip planes (= number of faying surfaces).
        Same as bolt.num_shear_planes for most connections.  Default 1.
    """
    num_bolts: int
    plate_thickness_in: float
    plate_Fu_ksi: float = 58.0
    end_distance_in: float = 1.5
    spacing_in: float = 3.0
    slip_critical: bool = False
    faying_class: str = "A"
    num_slip_planes: int = 1


@dataclass
class BoltShearReport:
    """
    Output of AISC 360-22 §J3.6 bolt-group shear strength check.

    Parameters
    ----------
    phi_Rn_per_bolt_kip : float
        φ·Rn per bolt for bolt shear (kip).
        = φ_v · Fnv · Ab · num_shear_planes   (φ_v = 0.75)
    phi_Rn_group_kip : float
        Total bolt shear strength of the group (kip).
        = phi_Rn_per_bolt_kip × num_bolts
    bearing_phi_Rn_kip : float
        φ·Rn bearing for the critical bolt (kip) per §J3.10a.
        = φ · 2.4 · d · t · Fu
    tearout_phi_Rn_kip : float
        φ·Rn tearout for the end bolt (kip) per §J3.10b.
        = φ · 1.2 · Lc · t · Fu
        where Lc = clear distance = end_distance − dh/2  (dh = d + 1/16" standard)
    governing_mode : str
        Which limit state governs per bolt: ``"bolt_shear"``, ``"bearing"``,
        or ``"tearout"``.  This is the mode for the single-bolt comparison;
        full group design must also check total group capacity.
    slip_critical_phi_Rn_kip : float | None
        φ·Rn_slip for the group (kip) if slip_critical=True, else None.
        = φ_sc · μ · Du · hf · Tb · ns · nb   (AISC 360-22 §J3.8 Eq J3-4)
    honest_caveat : str
        Scope limitations and honest caveats for this check.
    """
    phi_Rn_per_bolt_kip: float
    phi_Rn_group_kip: float
    bearing_phi_Rn_kip: float
    tearout_phi_Rn_kip: float
    governing_mode: str
    slip_critical_phi_Rn_kip: float | None
    honest_caveat: str


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_GRADES = frozenset(_FNV_KSI)
_VALID_FAYING = frozenset(_MU)


def _validate(bolt: BoltSpec, conn: ConnectionSpec) -> None:
    """Raise ValueError on invalid inputs."""
    if bolt.grade not in _VALID_GRADES:
        raise ValueError(
            f"bolt.grade must be one of {sorted(_VALID_GRADES)}, got '{bolt.grade}'"
        )
    if bolt.diameter_in <= 0:
        raise ValueError(f"bolt.diameter_in must be > 0, got {bolt.diameter_in}")
    if bolt.num_shear_planes < 1:
        raise ValueError(f"bolt.num_shear_planes must be >= 1, got {bolt.num_shear_planes}")
    if conn.num_bolts < 1:
        raise ValueError(f"conn.num_bolts must be >= 1, got {conn.num_bolts}")
    if conn.plate_thickness_in <= 0:
        raise ValueError(f"conn.plate_thickness_in must be > 0, got {conn.plate_thickness_in}")
    if conn.plate_Fu_ksi <= 0:
        raise ValueError(f"conn.plate_Fu_ksi must be > 0, got {conn.plate_Fu_ksi}")
    if conn.end_distance_in <= 0:
        raise ValueError(f"conn.end_distance_in must be > 0, got {conn.end_distance_in}")
    if conn.spacing_in <= 0:
        raise ValueError(f"conn.spacing_in must be > 0, got {conn.spacing_in}")
    if conn.faying_class not in _VALID_FAYING:
        raise ValueError(
            f"conn.faying_class must be one of {sorted(_VALID_FAYING)}, "
            f"got '{conn.faying_class}'"
        )
    if conn.num_slip_planes < 1:
        raise ValueError(f"conn.num_slip_planes must be >= 1, got {conn.num_slip_planes}")
    if conn.slip_critical and bolt.grade == "A307":
        raise ValueError(
            "A307 bolts are not permitted in slip-critical connections "
            "(AISC 360-22 Commentary §J3.8; A307 does not have a pretension value)."
        )


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def _bolt_area_in2(diameter_in: float) -> float:
    """Nominal (unthreaded) bolt cross-section area Ab = π·d²/4 (in²)."""
    return math.pi * diameter_in ** 2 / 4.0


def _hole_diameter_in(diameter_in: float) -> float:
    """
    Standard punch hole diameter = bolt diameter + 1/16"
    (AISC Table J3.3; also accounts for 1/16" damage deduction for net area).
    """
    return diameter_in + 1.0 / 16.0


def _lookup_Tb(diameter_in: float) -> float:
    """
    Look up Table J3.1 bolt pretension Tb (kip).

    Finds the closest standard bolt size (within 1/64" tolerance).
    Raises ValueError if diameter is not a recognised standard size.
    """
    tol = 1.0 / 64.0  # 1/64" tolerance for float comparison
    for d_std, tb in _TB_KIP.items():
        if abs(diameter_in - d_std) <= tol:
            return tb
    raise ValueError(
        f"bolt diameter {diameter_in:.4f} in is not a standard AISC Table J3.1 "
        f"size for pretension lookup ({sorted(_TB_KIP)}). "
        "Supply a standard bolt diameter for slip-critical connections."
    )


def check_bolt_shear(
    bolt: BoltSpec,
    conn: ConnectionSpec,
    phi_v: float = 0.75,
    phi_br: float = 0.75,
) -> BoltShearReport:
    """
    AISC 360-22 §J3.6 bolt-group shear strength check (LRFD).

    Computes three limit states per bolt:
      1. Bolt shear (§J3.6):  φ·Rn_shear = φ_v · Fnv · Ab · n_planes
      2. Bearing (§J3.10a):   φ·Rn_brg   = φ · 2.4 · d · t · Fu
      3. Tearout (§J3.10b):   φ·Rn_to    = φ · 1.2 · Lc · t · Fu
         where Lc = end_distance − dh/2   (end bolt)

    For slip-critical connections (conn.slip_critical=True) adds:
      4. Slip (§J3.8 Eq J3-4): Rn_slip = μ · Du · hf · Tb · ns  per bolt
         φ_sc = 1.00 (standard holes)
         Total group: φ_sc · Rn_slip · nb

    The function returns per-bolt strengths plus the total group bolt-shear
    strength.  Governing mode is based on single-bolt comparison.

    Parameters
    ----------
    bolt : BoltSpec
        Bolt grade, diameter, thread condition, shear planes.
    conn : ConnectionSpec
        Connection geometry: bolts, plate thickness, Fu, end distance, spacing.
    phi_v : float
        LRFD resistance factor for bolt shear.  Default 0.75 per AISC §J3.6.
    phi_br : float
        LRFD resistance factor for bearing and tearout.  Default 0.75 per §J3.10.

    Returns
    -------
    BoltShearReport

    Raises
    ------
    ValueError
        On invalid inputs or A307 slip-critical request.
    """
    _validate(bolt, conn)

    d = bolt.diameter_in        # bolt diameter (in)
    n_planes = bolt.num_shear_planes
    nb = conn.num_bolts

    # ── 1. Bolt shear §J3.6 ─────────────────────────────────────────────────
    Fnv = _FNV_KSI[bolt.grade]  # ksi
    Ab = _bolt_area_in2(d)       # in²
    # Rn per bolt = Fnv · Ab · num_shear_planes (Eq J3-1 generalised)
    Rn_shear = Fnv * Ab * n_planes
    phi_Rn_per_bolt = phi_v * Rn_shear  # kip

    # ── 2. Bearing §J3.10a ──────────────────────────────────────────────────
    # φ·Rn = φ · 2.4 · d · t · Fu   (Eq J3-6a, deformation of bolt hole ≤ 1/4")
    t = conn.plate_thickness_in
    Fu = conn.plate_Fu_ksi
    Rn_brg = 2.4 * d * t * Fu     # kip
    phi_Rn_brg = phi_br * Rn_brg  # kip

    # ── 3. Tearout §J3.10b ──────────────────────────────────────────────────
    # Lc = clear distance from end of connected part to edge of bolt hole
    # For the end bolt: Lc = Le - dh/2  (AISC Eq J3-6b)
    # Le = end_distance (centre of bolt to end of part)
    # dh = nominal hole diameter = d + 1/16"
    dh = _hole_diameter_in(d)
    Le = conn.end_distance_in
    Lc = Le - dh / 2.0            # clear distance (in)
    # Lc must be positive; very short end distance → Lc may be ≤ 0
    if Lc <= 0.0:
        raise ValueError(
            f"end_distance_in ({Le:.4f}\") is too small: Lc = {Lc:.4f}\" ≤ 0. "
            f"Minimum end distance = dh/2 = {dh/2:.4f}\". "
            "Check AISC §J3.4 minimum end distances."
        )
    # φ·Rn = φ · 1.2 · Lc · t · Fu   (Eq J3-6b)
    Rn_tearout = 1.2 * Lc * t * Fu  # kip
    phi_Rn_tearout = phi_br * Rn_tearout  # kip

    # ── 4. Governing mode per bolt ──────────────────────────────────────────
    strengths = {
        "bolt_shear": phi_Rn_per_bolt,
        "bearing":    phi_Rn_brg,
        "tearout":    phi_Rn_tearout,
    }
    governing_mode = min(strengths, key=lambda k: strengths[k])

    # Total group shear strength (bolt shear governs per-plane, but bearing/tearout
    # may govern for individual bolts; group capacity uses bolt shear × nb):
    phi_Rn_group = phi_Rn_per_bolt * nb

    # ── 5. Slip-critical §J3.8 ──────────────────────────────────────────────
    slip_phi_Rn: float | None = None
    if conn.slip_critical:
        mu = _MU[conn.faying_class]
        Du = 1.13    # ratio of mean installed bolt pretension to Tb (AISC §J3.8)
        hf = 1.0     # factor for fillers — 1.0 (no fillers, AISC §J3.8)
        Tb = _lookup_Tb(d)   # kip
        ns = conn.num_slip_planes
        phi_sc = 1.00   # standard holes, LRFD (AISC §J3.8)
        # Rn_slip per bolt = μ · Du · hf · Tb · ns  (Eq J3-4)
        Rn_slip_per_bolt = mu * Du * hf * Tb * ns  # kip
        slip_phi_Rn = phi_sc * Rn_slip_per_bolt * nb  # group (kip)

    # ── 6. Honest caveat ─────────────────────────────────────────────────────
    caveat = (
        f"AISC 360-22 §J3.6 bolt-group shear strength — LRFD ONLY. "
        f"Grade: {bolt.grade} (Fnv={Fnv} ksi, Table J3.2); "
        f"d={d:.4f} in; Ab={Ab:.5f} in²; n_shear_planes={n_planes}; "
        f"nb={nb} bolts. "
        f"(1) Bolt shear §J3.6: φ·Rn_per_bolt = {phi_Rn_per_bolt:.3f} kip "
        f"[φ={phi_v}·{Fnv}·{Ab:.5f}·{n_planes}]; "
        f"group = {phi_Rn_group:.3f} kip. "
        f"(2) Bearing §J3.10a: φ·Rn = {phi_Rn_brg:.3f} kip "
        f"[φ·2.4·{d:.4f}·{t:.4f}·{Fu:.1f}]; "
        f"(3) Tearout §J3.10b: Le={Le:.4f} in, dh={dh:.4f} in, Lc={Lc:.4f} in; "
        f"φ·Rn = {phi_Rn_tearout:.3f} kip "
        f"[φ·1.2·{Lc:.4f}·{t:.4f}·{Fu:.1f}]. "
        f"Governing mode: {governing_mode}. "
    )
    if conn.slip_critical:
        mu = _MU[conn.faying_class]
        Tb = _lookup_Tb(d)
        caveat += (
            f"(4) Slip-critical §J3.8 Class {conn.faying_class}: "
            f"μ={mu}, Du=1.13, hf=1.0, Tb={Tb:.0f} kip, ns={conn.num_slip_planes}; "
            f"φ_sc·Rn_slip_group = {slip_phi_Rn:.3f} kip. "
        )
    caveat += (
        "SCOPE LIMITATIONS: "
        "(1) LRFD only — ASD (Ω-factors) NOT provided. "
        "(2) Shear-lag reduction (§J4.3) NOT applied. "
        "(3) Combined shear + tension (§J3.7) NOT checked. "
        "(4) Block shear (§J4.3) NOT checked — perform separately. "
        "(5) Prying action (tension bolts) NOT modelled. "
        "(6) Eccentrically loaded bolt groups (ICR method) NOT modelled. "
        "(7) Weld + bolt combined groups (§J8) NOT modelled. "
        "(8) Fatigue and fillet-weld combination checks NOT included. "
        "(9) Bearing check uses deformation-at-bolt-hole limit (2.4·d·Fu); "
        "deformation-not-concern limit (3.0·d·Fu, Eq J3-6c) NOT used. "
        "(10) Tearout uses end bolt Lc; interior bolts (Lc=s−dh) may govern "
        "for close spacing — check separately if s < 3d. "
        "(11) A307 bolts: no slip-critical provisions. "
        "(12) Hole type assumed standard punched (dh=d+1/16\"); short-slot, "
        "long-slot, oversize holes require different φ_sc per Table J3.1 footnotes. "
        "Always verify with a licensed structural engineer."
    )

    return BoltShearReport(
        phi_Rn_per_bolt_kip=phi_Rn_per_bolt,
        phi_Rn_group_kip=phi_Rn_group,
        bearing_phi_Rn_kip=phi_Rn_brg,
        tearout_phi_Rn_kip=phi_Rn_tearout,
        governing_mode=governing_mode,
        slip_critical_phi_Rn_kip=slip_phi_Rn,
        honest_caveat=caveat,
    )
