"""
AISC 360-22 W-shape moment capacity with lateral-torsional buckling (LTB).

Implements Chapter F of AISC 360-22 for compact doubly-symmetric I-sections
bent about the strong axis.

Zone selection
--------------
Lb <= Lp  → plastic moment Mp  (no LTB)
Lp < Lb <= Lr  → inelastic LTB  (linear interpolation)
Lb > Lr  → elastic LTB

All units: US customary (kips, inches, ksi) unless noted.

References
----------
AISC 360-22 Chapter F (F2 for doubly-symmetric compact sections)
AISC Steel Construction Manual, 16th ed. — Table 3-2 for W-shapes
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# W-shape section properties
# ---------------------------------------------------------------------------

@dataclass
class WSection:
    """
    Minimal strong-axis flexure properties for a W-shape.

    Parameters
    ----------
    designation : str
        AISC designation, e.g. 'W18X50'.
    d : float
        Total depth (in).
    bf : float
        Flange width (in).
    tf : float
        Flange thickness (in).
    tw : float
        Web thickness (in).
    Ix : float
        Moment of inertia about strong axis (in⁴).
    Sx : float
        Elastic section modulus  Ix / (d/2)  (in³).
    Zx : float
        Plastic section modulus (in³).
    Iy : float
        Moment of inertia about weak axis (in⁴).
    ry : float
        Radius of gyration about weak axis (in).
    J : float
        Torsional constant (in⁴).
    Cw : float
        Warping constant (in⁶).
    rts : float
        Effective radius of gyration per AISC F2-7 (in).
        If omitted (0.0) it is estimated as ry * sqrt(sqrt(Iy * Cw) / Sx).
    ho : float
        Distance between flange centroids ≈ d − tf (in). 0 → computed.
    """
    designation: str = ""
    d: float = 0.0
    bf: float = 0.0
    tf: float = 0.0
    tw: float = 0.0
    Ix: float = 0.0
    Sx: float = 0.0
    Zx: float = 0.0
    Iy: float = 0.0
    ry: float = 0.0
    J: float = 0.0
    Cw: float = 0.0
    rts: float = 0.0
    ho: float = 0.0

    def __post_init__(self):
        if self.ho == 0.0 and self.d > 0 and self.tf > 0:
            self.ho = self.d - self.tf
        if self.rts == 0.0 and self.Iy > 0 and self.Cw > 0 and self.Sx > 0:
            self.rts = math.sqrt(math.sqrt(self.Iy * self.Cw) / self.Sx)


# A small lookup table of common W-shapes (d, bf, tf, tw, Ix, Sx, Zx, Iy, ry, J, Cw)
# Values from AISC 16th ed. Part 1 tables.
_W_TABLE: dict[str, tuple] = {
    # (d, bf, tf, tw, Ix, Sx, Zx, Iy, ry, J, Cw)
    "W8X31":   (8.00,  7.995, 0.435, 0.285,  110,  27.5,  30.4,  37.1, 2.02, 0.536,  530),
    "W10X33":  (9.73,  7.960, 0.435, 0.290,  170,  35.0,  38.8,  36.6, 1.94, 0.583,  791),
    "W12X40":  (11.94, 8.005, 0.515, 0.295,  307,  51.5,  57.5,  44.1, 1.93, 0.810, 1480),
    "W12X50":  (12.19, 8.077, 0.641, 0.371,  394,  64.7,  72.4,  56.3, 1.96, 1.71,  1880),
    "W14X48":  (13.79, 8.031, 0.595, 0.340,  485,  70.3,  78.4,  51.4, 1.91, 1.45,  2240),
    "W16X36":  (15.86, 6.985, 0.428, 0.295,  448,  56.5,  64.0,  24.5, 1.52, 0.545, 1460),
    "W16X50":  (16.26, 7.073, 0.628, 0.380,  659,  81.0,  92.0,  37.2, 1.59, 1.52,  2170),
    "W18X35":  (17.70, 6.000, 0.425, 0.300,  510,  57.6,  66.5,  15.3, 1.22, 0.506, 1140),
    "W18X50":  (17.99, 7.495, 0.570, 0.355,  800,  88.9, 101.0,  40.1, 1.65, 1.24,  3050),
    "W21X50":  (20.83, 6.530, 0.535, 0.380,  984,  94.5, 110.0,  24.9, 1.30, 1.14,  2110),
    "W21X68":  (21.13, 8.270, 0.685, 0.430, 1480, 140.0, 160.0,  70.6, 1.80, 2.45,  6060),
    "W24X55":  (23.57, 7.005, 0.505, 0.395, 1350, 114.0, 131.0,  29.1, 1.34, 1.18,  3160),
    "W24X68":  (23.73, 8.965, 0.585, 0.415, 1830, 154.0, 177.0,  70.0, 1.87, 1.87,  9430),
    "W27X84":  (26.71, 9.960, 0.640, 0.460, 2850, 213.0, 244.0, 106.0, 2.07, 2.81, 17600),
    "W30X90":  (29.53, 10.40, 0.610, 0.470, 3610, 245.0, 283.0, 115.0, 2.08, 2.84, 22700),
    "W33X130": (33.09, 11.51, 0.855, 0.580, 6710, 406.0, 467.0, 218.0, 2.28, 9.24, 59500),
    "W36X135": (35.55, 11.95, 0.790, 0.600, 7800, 439.0, 509.0, 225.0, 2.38, 7.79, 65100),
}


def w_section(designation: str) -> WSection:
    """
    Look up a W-shape from the built-in table.

    Parameters
    ----------
    designation : str
        AISC designation in upper-case, e.g. 'W18X50'.

    Raises
    ------
    KeyError
        If the section is not in the built-in table.
    """
    key = designation.upper().replace(" ", "").replace("X", "X")
    if key not in _W_TABLE:
        raise KeyError(
            f"W-shape '{designation}' not in built-in table. "
            f"Supply a WSection dataclass directly."
        )
    d, bf, tf, tw, Ix, Sx, Zx, Iy, ry, J, Cw = _W_TABLE[key]
    return WSection(
        designation=key, d=d, bf=bf, tf=tf, tw=tw,
        Ix=Ix, Sx=Sx, Zx=Zx, Iy=Iy, ry=ry, J=J, Cw=Cw,
    )


# ---------------------------------------------------------------------------
# LTB limits and capacity
# ---------------------------------------------------------------------------

@dataclass
class SteelBeamResult:
    """Output from :func:`design_steel_beam`."""
    ok: bool
    reason: str = ""

    designation: str = ""
    Lb: float = 0.0       # unbraced length (in)
    Lp: float = 0.0       # plastic limit (in)
    Lr: float = 0.0       # elastic LTB limit (in)
    ltb_zone: str = ""    # 'plastic', 'inelastic', 'elastic'
    Mp: float = 0.0       # plastic moment capacity (kip-in)
    Mn: float = 0.0       # nominal moment capacity (kip-in)
    phi_Mn: float = 0.0   # design moment (kip-in)
    phi_Mn_kip_ft: float = 0.0  # design moment (kip-ft)


def design_steel_beam(
    section: "str | WSection",
    Lb_ft: float,
    *,
    Fy: float = 50.0,
    E: float = 29_000.0,
    G: float = 11_200.0,
    Cb: float = 1.0,
    phi: float = 0.9,
) -> SteelBeamResult:
    """
    AISC 360-22 F2 — nominal and design moment capacity for a compact
    doubly-symmetric W-shape bent about the strong axis.

    Parameters
    ----------
    section : str or WSection
        AISC designation string or a populated :class:`WSection`.
    Lb_ft : float
        Laterally unbraced length (ft).
    Fy : float
        Steel yield strength (ksi). Default 50 ksi (A992).
    E : float
        Elastic modulus (ksi). Default 29 000 ksi.
    G : float
        Shear modulus (ksi). Default 11 200 ksi.
    Cb : float
        Lateral-torsional buckling modification factor. Default 1.0 (conservative).
    phi : float
        Resistance factor. Default 0.90.

    Returns
    -------
    SteelBeamResult
    """
    res = SteelBeamResult(ok=False)

    if isinstance(section, str):
        try:
            sec = w_section(section)
        except KeyError as exc:
            res.reason = str(exc)
            return res
    else:
        sec = section

    res.designation = sec.designation or "custom"

    Lb = Lb_ft * 12.0   # convert to inches
    res.Lb = Lb

    # Ensure rts is set
    if sec.rts == 0.0:
        res.reason = "rts is zero — populate WSection.rts or provide Iy, Cw, Sx"
        return res

    # Plastic moment  Mp = Fy × Zx  (kip-in)
    Mp = Fy * sec.Zx
    res.Mp = Mp

    # Lp  AISC F2-5
    Lp = 1.76 * sec.ry * math.sqrt(E / Fy)
    res.Lp = Lp

    # Lr  AISC F2-6
    c = 1.0  # doubly-symmetric I-shape
    X = (sec.rts ** 2) * math.sqrt(
        0.0078 * sec.J * c / (sec.Sx * sec.ho)
    )
    Lr = 1.95 * sec.rts * (E / (0.7 * Fy)) * math.sqrt(
        sec.J * c / (sec.Sx * sec.ho) + math.sqrt(
            (sec.J * c / (sec.Sx * sec.ho)) ** 2 + 6.76 * (0.7 * Fy / E) ** 2
        )
    )
    res.Lr = Lr

    # Determine LTB zone and Mn
    if Lb <= Lp:
        res.ltb_zone = "plastic"
        Mn = Mp

    elif Lb <= Lr:
        res.ltb_zone = "inelastic"
        # AISC F2-2  Mn = Cb[Mp − (Mp − 0.7 Fy Sx)(Lb−Lp)/(Lr−Lp)] ≤ Mp
        Mn = Cb * (Mp - (Mp - 0.7 * Fy * sec.Sx) * (Lb - Lp) / (Lr - Lp))
        Mn = min(Mn, Mp)

    else:
        res.ltb_zone = "elastic"
        # AISC F2-3  Fcr = Cb π² E / (Lb/rts)² × √(1 + 0.078 J c/(Sx ho)(Lb/rts)²)
        Lb_rts = Lb / sec.rts
        Fcr = (Cb * math.pi ** 2 * E / Lb_rts ** 2) * math.sqrt(
            1.0 + 0.078 * sec.J * c / (sec.Sx * sec.ho) * Lb_rts ** 2
        )
        Mn = min(Fcr * sec.Sx, Mp)

    res.Mn = Mn
    res.phi_Mn = phi * Mn
    res.phi_Mn_kip_ft = phi * Mn / 12.0
    res.ok = True
    return res


def moment_capacity(
    designation: str,
    Lb_ft: float,
    *,
    Fy: float = 50.0,
    Cb: float = 1.0,
) -> float:
    """
    Convenience wrapper — returns φMn in kip-ft.

    Raises
    ------
    ValueError
        On any design failure.
    """
    res = design_steel_beam(designation, Lb_ft, Fy=Fy, Cb=Cb)
    if not res.ok:
        raise ValueError(res.reason)
    return res.phi_Mn_kip_ft
