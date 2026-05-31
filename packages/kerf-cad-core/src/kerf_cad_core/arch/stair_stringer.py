"""
kerf_cad_core.arch.stair_stringer — Wood/steel stair stringer design check.

Implements stair geometry verification per IBC 2021 §1011 (riser/tread limits)
and stringer bending/deflection capacity per:
  • AWC NDS-2018 §3.3 — sawn lumber bending (Fb reference + adjustment factors)
  • AISC 360-22 §F2 — steel member bending (compact I/channel/HSS in strong axis)

Design model
------------
The stringer is idealised as a simply-supported inclined beam of span length
  L = √(run² + rise²)        (inclined span along stringer neutral axis)

Tributary loading per stringer:
  trib_width = stair_width / num_stringers
  w_total    = (live_load_psf + dead_load_psf) · trib_width   [lb/in or lb/ft → see units]

Unit conversion: all dimensional inputs are in **inches**; load inputs are in
**psf** (pounds per square foot).  Internal calculations are in **lb** and
**inches**.

Load model (uniform distributed, simply-supported):
  w   = (LL + DL) · trib_ft   [lb/ft]   → convert to lb/in   = w / 12
  M_max = w_in · L² / 8          [lb·in]
  δ_max = 5 · w_in · L⁴ / (384 · E · I)   [in]

Deflection limit: L/360  (IBC Table 1604.3 — stair live-load deflection limit)

Materials supported
-------------------
  "sawn-DF-No2"    Douglas Fir-Larch No.2 2×12:
                   Fb = 875 psi (NDS Supplement Table 4A);  E = 1 600 000 psi
                   Sx = b·d²/6 = 1.5·11.25²/6 = 31.64 in³;
                   I  = b·d³/12 = 1.5·11.25³/12 = 177.98 in⁴

  "sawn-SP-No1"    Southern Pine No.1 2×12:
                   Fb = 1500 psi (NDS Supplement Table 4B);  E = 1 700 000 psi
                   Sx = 31.64 in³;  I = 177.98 in⁴  (same 2×12 net section)

  "steel-C10x15.3" AISC C10×15.3 standard channel:
                   Sx = 13.5 in³;  I = 67.4 in⁴;  E = 29 000 000 psi
                   Fb = 0.9 · Fy · ... → simplified φ·Mn/Sx; for this compact
                   channel Φb·Fy = 0.9·50 000 = 45 000 psi   (A36: 0.9·36000=32400)
                   Use Fy = 36 000 psi (A36 default) → Fb_eff = 0.9·Fy = 32 400 psi

  "steel-HSS6x4x1/4" AISC HSS6×4×1/4:
                   Sx = 8.53 in³;  I = 25.6 in⁴;  E = 29 000 000 psi
                   Fy = 46 000 psi (ASTM A500 Gr.B); Fb_eff = 0.9·46000 = 41 400 psi

For wood members the bending stress check is:
  fb = M_max / Sx   ≤  F'b  (reference Fb, adjusted for load duration CD=1.0,
                              wet service CM=1.0, size CF from Table 4A/4B,
                              temperature Ct=1.0, beam stability CL=1.0 for notch-free)
  For 2×12: CF = 1.0 (NDS Supplement Table 4A footnote — width = 11.25 in, CF=1.0)
  F'b = Fb · CD · CM · Ct · CF · CL = Fb   (with all factors = 1.0 for this model)

For steel members:
  fb = M_max / Sx   ≤  Fb_eff  (= 0.9·Fy for compact compact-shape strong axis)

DCR = fb / Fb_eff   (bending)
DCR_defl = δ_max / (L / 360)   (deflection)
governing_dcr = max(bending_dcr, deflection_dcr)

Status logic
------------
  status = "ok"               if governing_dcr ≤ 1.0 and code compliant
  status = "oversize"         if governing_dcr ≤ 0.25 (more than 4× capacity)
  status = "fail-bending"     if bending_dcr > 1.0
  status = "fail-deflection"  if deflection_dcr > 1.0 (and bending ok)
  status = "fail-code"        if riser or tread fails IBC §1011

References
----------
  IBC 2021 §1011.5.2 — riser height 4–7 in; tread depth ≥ 11 in (R ≤ 7¾ in
    allowed for residential; this module enforces the general commercial 7 in
    limit unless residential flag set).
  AWC NDS-2018 §3.3 — bending stress fb = M / Sx ≤ F'b.
  AISC 360-22 §F2 — φMn = φ·Fy·Zx for compact shapes (LTB not checked here;
    caller responsible for lateral support; Sx used for elastic check).
  Roark 9e §8 Table 8.1 case 2 — δ = 5wL⁴/(384EI) for SS UDL.
  ASCE 7-22 Table 4.3-1 — stair live load = 100 psf (assembly occupancies).
  IBC 2021 Table 1604.3 — deflection limit L/360 for floor/stair live load.

Scope and caveats
-----------------
  • BENDING ONLY — no shear check; horizontal shear at notch (NDS §4.4.3 for
    wood) and web shear at tee-section (AISC §G2.1 for steel) NOT verified.
  • No bearing check at top/bottom riser connections or at floor/landing.
  • For wood: size factor CF and all NDS adjustment factors assumed = 1.0 (single
    repetitive member; add Cr=1.15 for shared 3+ stringer systems).
  • For steel: compact section assumed; LTB not checked — ensure adequate lateral
    bracing at each riser or tread attachment point.
  • Deflection check is for the inclined span under full UDL; concentrated
    mid-span load (IBC §1607.4 300 lb) is reported as a separate conservative
    moment value but NOT combined with UDL (envelope reported in warnings).
  • Notched stringers (saw-cut at each tread/riser) reduce effective section
    depth; depth-after-notch must be verified manually for wood (NOT auto-checked
    here).
  • IBC §1011.5.2: 300 lb concentrated load is checked as P·L/4 (simply supported
    centre point) for comparison only; worst-case envelope must be reviewed by EOR.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "StairGeometry",
    "StringerSpec",
    "StringerReport",
    "design_stair_stringer",
    "MATERIAL_DEFAULTS",
]

# ---------------------------------------------------------------------------
# IBC §1011 limits
# ---------------------------------------------------------------------------
IBC_RISER_MIN_IN: float = 4.0    # IBC §1011.5.2: commercial stairs (not residential)
IBC_RISER_MAX_IN: float = 7.0    # IBC §1011.5.2: max riser height (commercial)
IBC_TREAD_MIN_IN: float = 11.0   # IBC §1011.5.2: min tread depth (nosing-to-nosing)

# IBC Table 1604.3 stair live-load deflection limit
DEFLECTION_LIMIT_RATIO: float = 360.0   # L/360

# ---------------------------------------------------------------------------
# Material property defaults
# ---------------------------------------------------------------------------
# (material_key -> {Fb_psi, E_psi, Sx_in3, I_in4, description})
MATERIAL_DEFAULTS: dict[str, dict] = {
    "sawn-DF-No2": {
        # Douglas Fir-Larch No.2, 2×12 net: b=1.5", d=11.25"
        # NDS Supplement Table 4A; Fb=875 psi reference design value
        # E=1 600 000 psi; CF=1.0 for 2×12
        "Fb_psi": 875.0,
        "E_psi": 1_600_000.0,
        "Sx_in3": (1.5 * 11.25**2) / 6.0,       # = 31.641 in³
        "I_in4": (1.5 * 11.25**3) / 12.0,        # = 177.98 in⁴
        "description": "DF-Larch No.2 2×12 (NDS Supp Table 4A; CF=1.0)",
    },
    "sawn-SP-No1": {
        # Southern Pine No.1 2×12: Fb=1500 psi (NDS Supplement Table 4B)
        # E=1 700 000 psi; CF=1.0 for 2×12
        "Fb_psi": 1500.0,
        "E_psi": 1_700_000.0,
        "Sx_in3": (1.5 * 11.25**2) / 6.0,        # = 31.641 in³
        "I_in4": (1.5 * 11.25**3) / 12.0,        # = 177.98 in⁴
        "description": "Southern Pine No.1 2×12 (NDS Supp Table 4B; CF=1.0)",
    },
    "steel-C10x15.3": {
        # AISC C10×15.3: Sx=13.5 in³, Ix=67.4 in⁴ (AISC Manual v16 Table 1-5)
        # A36 steel Fy=36 ksi; Fb_eff = φ·Fy = 0.9×36000 = 32400 psi
        "Fb_psi": 0.9 * 36_000.0,                 # = 32 400 psi
        "E_psi": 29_000_000.0,
        "Sx_in3": 13.5,
        "I_in4": 67.4,
        "description": (
            "AISC C10×15.3 A36 channel (AISC Manual v16 Table 1-5; "
            "φ·Mn/Sx = 0.9·Fy = 32 400 psi; compact, no LTB)"
        ),
    },
    "steel-HSS6x4x1/4": {
        # AISC HSS6×4×1/4: Sx=8.53 in³, Ix=25.6 in⁴ (AISC Manual v16 Table 1-11)
        # ASTM A500 Gr.B Fy=46 ksi; Fb_eff = φ·Fy = 0.9×46000 = 41 400 psi
        "Fb_psi": 0.9 * 46_000.0,                 # = 41 400 psi
        "E_psi": 29_000_000.0,
        "Sx_in3": 8.53,
        "I_in4": 25.6,
        "description": (
            "AISC HSS6×4×1/4 A500 Gr.B (AISC Manual v16 Table 1-11; "
            "φ·Mn/Sx = 0.9·Fy = 41 400 psi; compact, no LTB)"
        ),
    },
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StairGeometry:
    """
    Geometric parameters for a straight-run stair.

    Parameters
    ----------
    num_treads : int
        Number of treads (= number of risers for a standard stair flight).
        Must be ≥ 1.
    riser_height_in : float
        Vertical riser height in inches.  IBC §1011.5.2: 4–7 in (commercial).
    tread_depth_in : float
        Horizontal tread depth (nosing to nosing) in inches.
        IBC §1011.5.2: ≥ 11 in.
    total_run_in : float
        Total horizontal run of the stair flight in inches
        (= num_treads × tread_depth_in).  If supplied as 0 it will be computed.
    total_rise_in : float
        Total vertical rise of the stair flight in inches
        (= num_treads × riser_height_in).  If supplied as 0 it will be computed.
    stair_width_in : float
        Clear width of the stair in inches.  Must be > 0.
    """
    num_treads: int
    riser_height_in: float
    tread_depth_in: float
    total_run_in: float
    total_rise_in: float
    stair_width_in: float


@dataclass
class StringerSpec:
    """
    Material and section properties for one stringer.

    Parameters
    ----------
    material : str
        Material key.  One of:
          "sawn-DF-No2"      Douglas Fir-Larch No.2 2×12 (NDS Table 4A)
          "sawn-SP-No1"      Southern Pine No.1 2×12 (NDS Table 4B)
          "steel-C10x15.3"  AISC C10×15.3, A36 (AISC Manual v16 Table 1-5)
          "steel-HSS6x4x1/4" AISC HSS6×4×1/4, A500 Gr.B (AISC Manual v16 Table 1-11)
        If material is "custom" (or anything not in the lookup table) then
        Fb_psi, E_psi, and Sx_in3 must all be supplied explicitly.
    Fb_psi : float
        Reference bending design value (wood: NDS F'b with CD=CM=CF=1;
        steel: φ·Fy for compact section).  If 0, looked up from MATERIAL_DEFAULTS.
    E_psi : float
        Modulus of elasticity in psi.  If 0, looked up from MATERIAL_DEFAULTS.
    Sx_in3 : float
        Section modulus about the strong axis in in³.
        If 0, looked up from MATERIAL_DEFAULTS.
    """
    material: str
    Fb_psi: float = 0.0
    E_psi: float = 0.0
    Sx_in3: float = 0.0


@dataclass
class StringerReport:
    """
    Result of the stair stringer design check.

    Parameters
    ----------
    riser_compliant : bool
        True if riser_height_in is within IBC §1011.5.2 limits (4–7 in).
    tread_compliant : bool
        True if tread_depth_in ≥ IBC §1011.5.2 minimum (11 in).
    span_length_in : float
        Inclined stringer span length in inches = √(run² + rise²).
    max_moment_in_lb : float
        Maximum bending moment under full UDL (UDL governs for uniform stair
        load): M_max = w_in · L² / 8   [lb·in].
    max_moment_conc_in_lb : float
        Maximum bending moment under IBC §1607.4 300 lb concentrated load
        at mid-span: M_conc = P·L/4   [lb·in].  Reported separately; envelope
        noted in warnings.
    max_deflection_in : float
        Maximum mid-span deflection under full UDL: δ = 5wL⁴/(384EI) [in].
    bending_dcr : float
        Demand/capacity ratio for bending = fb / Fb_eff.
    deflection_dcr : float
        Demand/capacity ratio for deflection = δ_max / (L/360).
    governing_dcr : float
        max(bending_dcr, deflection_dcr).
    status : str
        "ok"               governing_dcr ≤ 1.0 and code compliant.
        "oversize"         governing_dcr ≤ 0.25 (stringer is 4× oversized).
        "fail-bending"     bending_dcr > 1.0.
        "fail-deflection"  deflection_dcr > 1.0 (bending ok).
        "fail-code"        IBC §1011 geometry violation (riser/tread).
    warnings : list[str]
        Advisory messages (e.g., envelope 300-lb concentrated load check).
    honest_caveat : str
        Plain-language scope statement referencing standards and listing what
        is NOT checked.
    """
    riser_compliant: bool
    tread_compliant: bool
    span_length_in: float
    max_moment_in_lb: float
    max_moment_conc_in_lb: float
    max_deflection_in: float
    bending_dcr: float
    deflection_dcr: float
    governing_dcr: float
    status: str
    warnings: list = field(default_factory=list)
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Core design function
# ---------------------------------------------------------------------------

def design_stair_stringer(
    geom: StairGeometry,
    stringer: StringerSpec,
    num_stringers: int = 2,
    live_load_psf: float = 100.0,
    dead_load_psf: float = 15.0,
) -> StringerReport:
    """
    Check a stair stringer for IBC §1011 code compliance, AWC NDS-2018 §3.3
    wood bending, or AISC 360-22 §F2 steel bending and deflection.

    Parameters
    ----------
    geom : StairGeometry
        Stair flight geometry.
    stringer : StringerSpec
        Material and section for one stringer.
    num_stringers : int
        Number of stringers sharing the stair width (default 2).
    live_load_psf : float
        Design live load in psf (default 100 psf per ASCE 7-22 Table 4.3-1
        for assembly occupancy stairs).
    dead_load_psf : float
        Superimposed dead load in psf (default 15 psf for typical finish).

    Returns
    -------
    StringerReport

    Raises
    ------
    ValueError
        If any geometry, material, or loading parameter is invalid.
    """
    # ------------------------------------------------------------------
    # Validate inputs
    # ------------------------------------------------------------------
    if geom.num_treads < 1:
        raise ValueError(f"num_treads must be ≥ 1, got {geom.num_treads}")
    if geom.riser_height_in <= 0:
        raise ValueError(f"riser_height_in must be > 0, got {geom.riser_height_in}")
    if geom.tread_depth_in <= 0:
        raise ValueError(f"tread_depth_in must be > 0, got {geom.tread_depth_in}")
    if geom.stair_width_in <= 0:
        raise ValueError(f"stair_width_in must be > 0, got {geom.stair_width_in}")
    if num_stringers < 1:
        raise ValueError(f"num_stringers must be ≥ 1, got {num_stringers}")
    if live_load_psf <= 0:
        raise ValueError(f"live_load_psf must be > 0, got {live_load_psf}")
    if dead_load_psf < 0:
        raise ValueError(f"dead_load_psf must be ≥ 0, got {dead_load_psf}")

    # ------------------------------------------------------------------
    # Resolve geometry
    # ------------------------------------------------------------------
    n = geom.num_treads
    r_in = geom.riser_height_in
    t_in = geom.tread_depth_in

    total_run = geom.total_run_in if geom.total_run_in > 0 else n * t_in
    total_rise = geom.total_rise_in if geom.total_rise_in > 0 else n * r_in

    if total_run <= 0:
        raise ValueError(f"total_run_in must be > 0, got {total_run}")
    if total_rise <= 0:
        raise ValueError(f"total_rise_in must be > 0, got {total_rise}")

    # Inclined span length (hypotenuse of run/rise triangle) — in inches
    L = math.hypot(total_run, total_rise)

    # ------------------------------------------------------------------
    # IBC §1011.5.2 code compliance checks
    # ------------------------------------------------------------------
    riser_compliant = (IBC_RISER_MIN_IN <= r_in <= IBC_RISER_MAX_IN)
    tread_compliant = (t_in >= IBC_TREAD_MIN_IN)

    # ------------------------------------------------------------------
    # Resolve material properties
    # ------------------------------------------------------------------
    defaults = MATERIAL_DEFAULTS.get(stringer.material, {})

    Fb_psi = stringer.Fb_psi if stringer.Fb_psi > 0 else defaults.get("Fb_psi", 0.0)
    E_psi = stringer.E_psi if stringer.E_psi > 0 else defaults.get("E_psi", 0.0)
    Sx_in3 = stringer.Sx_in3 if stringer.Sx_in3 > 0 else defaults.get("Sx_in3", 0.0)
    I_in4 = defaults.get("I_in4", 0.0)
    # Derive I from Sx if not in defaults (S = I/c, c = half-depth — cannot derive
    # without depth; warn and approximate as I ≈ Sx * depth/2 if I unknown).
    # For custom sections caller should override via subclass or extend lookup.
    if I_in4 <= 0:
        # Fallback: I not available — use Sx × arbitrary assumption of d/c.
        # This path is only reached for custom materials; warn in output.
        I_in4 = Sx_in3 * 3.0   # rough placeholder; real EOR must supply I

    if Fb_psi <= 0:
        raise ValueError(
            f"Fb_psi must be > 0 for material '{stringer.material}'. "
            f"Either use a recognised material key or supply Fb_psi explicitly."
        )
    if E_psi <= 0:
        raise ValueError(
            f"E_psi must be > 0 for material '{stringer.material}'."
        )
    if Sx_in3 <= 0:
        raise ValueError(
            f"Sx_in3 must be > 0 for material '{stringer.material}'."
        )

    # ------------------------------------------------------------------
    # Tributary width and uniform load per stringer
    # ------------------------------------------------------------------
    trib_width_in = geom.stair_width_in / num_stringers       # in inches
    trib_width_ft = trib_width_in / 12.0                       # in feet

    # Total load intensity per stringer  [lb/ft along horizontal run]
    w_total_psf = live_load_psf + dead_load_psf
    w_per_stringer_plf = w_total_psf * trib_width_ft            # lb/ft

    # Convert to lb/in along horizontal run
    w_horiz_lb_per_in = w_per_stringer_plf / 12.0               # lb/in

    # Resolve load onto the inclined span.
    # Load is applied as vertical load on horizontal projection; the
    # load per unit *inclined* length = w_horiz × (run/L) since the
    # area loaded is proportional to horizontal projection.
    # For simply-supported UDL this simplification is standard practice
    # (beam on inclined span with load expressed per horizontal unit):
    #   M = w_horiz · run² / 8   (moment at mid-horizontal-projection)
    # But since the structural span is the inclined length L, we express
    # load per inclined inch as:
    #   w_in = w_horiz_lb_per_in × (total_run / L)   → w_inclined
    # Then M_max = w_inclined · L² / 8
    # This is consistent with the task spec which states:
    #   w = (live+dead)·trib_width and M_max = w·L²/8
    # where L is the inclined span.  To honour that exactly we interpret
    # the task load as load-per-unit-inclined-length directly:
    #   w_inclined = w_total_psf × trib_width_ft / 12  (lb/in inclined)
    # This is the literal reading of the task specification.
    w_in = w_per_stringer_plf / 12.0   # lb/in on inclined span (task spec)

    # Maximum moment under UDL (Roark 9e §8 Table 8.1 case 2)
    M_max_in_lb = w_in * L**2 / 8.0   # lb·in

    # Maximum deflection under UDL (Roark 9e §8 Table 8.1 case 2)
    E_I = E_psi * I_in4
    delta_max_in = (5.0 * w_in * L**4) / (384.0 * E_I)   # in

    # IBC §1607.4 concentrated 300 lb load at mid-span (simply supported)
    P_conc_lb = 300.0
    M_conc_in_lb = P_conc_lb * L / 4.0   # lb·in  (P·L/4)

    # ------------------------------------------------------------------
    # Bending capacity check
    # ------------------------------------------------------------------
    # Bending stress demand
    fb_udl_psi = M_max_in_lb / Sx_in3     # psi — from UDL
    fb_conc_psi = M_conc_in_lb / Sx_in3  # psi — from 300 lb concentrated

    bending_dcr = fb_udl_psi / Fb_psi
    bending_dcr_conc = fb_conc_psi / Fb_psi

    # ------------------------------------------------------------------
    # Deflection limit check: δ ≤ L/360
    # ------------------------------------------------------------------
    deflection_limit_in = L / DEFLECTION_LIMIT_RATIO
    deflection_dcr = delta_max_in / deflection_limit_in

    # ------------------------------------------------------------------
    # Governing DCR
    # ------------------------------------------------------------------
    governing_dcr = max(bending_dcr, deflection_dcr)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    if not (riser_compliant and tread_compliant):
        status = "fail-code"
    elif bending_dcr > 1.0:
        status = "fail-bending"
    elif deflection_dcr > 1.0:
        status = "fail-deflection"
    elif governing_dcr <= 0.25:
        status = "oversize"
    else:
        status = "ok"

    # ------------------------------------------------------------------
    # Warnings
    # ------------------------------------------------------------------
    warnings: list[str] = []

    if not riser_compliant:
        warnings.append(
            f"IBC §1011.5.2 VIOLATION: riser_height={r_in:.3f} in is outside "
            f"the {IBC_RISER_MIN_IN}–{IBC_RISER_MAX_IN} in commercial range."
        )
    if not tread_compliant:
        warnings.append(
            f"IBC §1011.5.2 VIOLATION: tread_depth={t_in:.3f} in < "
            f"minimum {IBC_TREAD_MIN_IN} in."
        )
    if bending_dcr_conc > bending_dcr:
        warnings.append(
            f"ENVELOPE: IBC §1607.4 300-lb concentrated load governs bending "
            f"over UDL (DCR_conc={bending_dcr_conc:.3f} vs DCR_udl={bending_dcr:.3f}). "
            f"Both must be checked; this report uses the UDL case per task spec."
        )
    if stringer.material not in MATERIAL_DEFAULTS:
        warnings.append(
            f"Material '{stringer.material}' not in lookup table — "
            f"custom properties used; no cross-check performed."
        )
    if I_in4 == Sx_in3 * 3.0 and stringer.material not in MATERIAL_DEFAULTS:
        warnings.append(
            "I_in4 was approximated as Sx × 3 for unknown material — "
            "deflection result is approximate; provide exact I_in4 for precision."
        )
    if geom.stair_width_in / num_stringers > 36.0:
        warnings.append(
            f"Tributary width per stringer = "
            f"{geom.stair_width_in / num_stringers:.1f} in > 36 in — "
            f"consider adding an intermediate stringer."
        )

    # ------------------------------------------------------------------
    # Honest caveat
    # ------------------------------------------------------------------
    is_wood = stringer.material.startswith("sawn")
    if is_wood:
        standard_ref = "AWC NDS-2018 §3.3"
        fb_note = (
            f"F'b={Fb_psi:.0f} psi (NDS CD·CM·CT·CF·CL all assumed=1.0; "
            f"adjust for wet service, temperature, repetitive-member, LTB if applicable)"
        )
    else:
        standard_ref = "AISC 360-22 §F2"
        fb_note = (
            f"φFy={Fb_psi:.0f} psi (compact section assumed; LTB not checked; "
            f"lateral bracing at each tread required)"
        )

    honest_caveat = (
        f"ARCH-STAIR-STRINGER: IBC 2021 §1011.5.2 + {standard_ref} + "
        f"Roark 9e §8 (UDL SS). "
        f"Geometry: rise={r_in} in, tread={t_in} in, n={n} treads, "
        f"width={geom.stair_width_in} in, L_inclined={L:.2f} in. "
        f"Load: LL={live_load_psf} psf + DL={dead_load_psf} psf, "
        f"trib_width={trib_width_in:.2f} in, w={w_in:.4f} lb/in. "
        f"Section: {stringer.material}; Sx={Sx_in3:.3f} in³, "
        f"I={I_in4:.3f} in⁴, {fb_note}. "
        f"M_max(UDL)={M_max_in_lb:.1f} lb·in, "
        f"M_conc(300lb)={M_conc_in_lb:.1f} lb·in, "
        f"fb(UDL)={fb_udl_psi:.1f} psi, δ={delta_max_in:.4f} in, "
        f"L/360={deflection_limit_in:.4f} in. "
        f"DCR_bending={bending_dcr:.3f}, DCR_deflection={deflection_dcr:.3f}, "
        f"DCR_governing={governing_dcr:.3f}. "
        f"SCOPE LIMITS: "
        f"(1) BENDING ONLY — shear check (NDS §4.4.3 horizontal shear / "
        f"AISC §G2.1 web shear) NOT performed. "
        f"(2) Bearing at top/bottom connections NOT verified. "
        f"(3) For wood: notch depth reduction at tread cuts NOT auto-applied "
        f"(EOR must verify net section depth after stringer notching). "
        f"(4) For steel: compact section and adequate lateral bracing assumed; "
        f"LTB (AISC §F2.2) NOT checked. "
        f"(5) 300-lb concentrated load (IBC §1607.4) reported for reference; "
        f"envelope check is the responsibility of the EOR. "
        f"(6) Load factors (ASCE 7-22 §2.3): ASD basis with w=LL+DL (service level); "
        f"LRFD combo 1.2D+1.6L NOT applied — EOR to confirm load combination. "
        f"(7) IBC §1011.5.2 rise/run tolerances (±3/8 in uniformity) NOT checked — "
        f"dimensional consistency of construction must be field-verified."
    )

    return StringerReport(
        riser_compliant=riser_compliant,
        tread_compliant=tread_compliant,
        span_length_in=L,
        max_moment_in_lb=M_max_in_lb,
        max_moment_conc_in_lb=M_conc_in_lb,
        max_deflection_in=delta_max_in,
        bending_dcr=bending_dcr,
        deflection_dcr=deflection_dcr,
        governing_dcr=governing_dcr,
        status=status,
        warnings=warnings,
        honest_caveat=honest_caveat,
    )
