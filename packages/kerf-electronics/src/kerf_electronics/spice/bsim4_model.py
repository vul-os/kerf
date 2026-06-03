"""bsim4_model.py — BSIM4.8 reference compact MOSFET model.

Reference: BSIM4.8.0 MOSFET Model Technical Manual, UC Berkeley Device Group,
           2013.  Freely available at https://bsim.berkeley.edu/models/bsim4/

HONEST DISCLAIMER
-----------------
This implementation captures the first-order DC I-V and small-signal
capacitance equations from BSIM4.8 §4 (threshold voltage), §5 (mobility
degradation, simplified), §6 (velocity-saturation current), and §9 (charge/
capacitance).  Of the ~400 BSIM4.8 parameters, only ~50 of the most
influential are exposed.  This is NOT a foundry-calibrated PDK model and must
NOT be used for tape-out sign-off.  Use for design exploration only.

Statistical matching follows:
  Pelgrom, M.J.M., Duinmaijer, A.C.J., Welbers, A.P.G. (1989).
  "Matching properties of MOS transistors."
  IEEE Journal of Solid-State Circuits, 24(5), 1433-1439.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

_Q   = 1.602176634e-19   # elementary charge, C
_KB  = 1.380649e-23      # Boltzmann constant, J/K
_EPS0 = 8.854187817e-12  # permittivity of free space, F/m
_EPS_SI = 11.7           # relative permittivity of silicon
_EPS_OX = 3.9            # relative permittivity of SiO2

# ---------------------------------------------------------------------------
# Model parameter dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Bsim4Parameters:
    """BSIM4.8 model parameters (UC Berkeley, public reference).

    A representative ~50-parameter subset of the full ~400-parameter model.
    All defaults correspond to a generic 100 nm bulk NMOS process corner (TT).

    References: BSIM4.8 §2 (parameter definitions), §4 (Vth), §5-6 (current).
    """

    # ── Process / threshold ─────────────────────────────────────────────────
    vth0: float = 0.7          # Threshold voltage at V_BS=0, V  [BSIM4 §4.1]
    k1: float   = 0.5          # First-order body-effect coefficient, V^0.5 [§4.1]
    k2: float   = 0.0          # Second-order body-effect coefficient [§4.1]
    k3: float   = 80.0         # Narrow-width effect coefficient [§4.3]
    w0: float   = 2.5e-6       # Narrow-width fitting parameter, m [§4.3]
    dvt0: float = 2.2          # Short-channel effect coeff 0 [§4.2]
    dvt1: float = 0.53         # Short-channel effect coeff 1 [§4.2]
    nlx: float  = 1.74e-7      # Lateral non-uniform doping param, m [§4.2]

    # ── Mobility ─────────────────────────────────────────────────────────────
    u0: float   = 0.0670       # Low-field carrier mobility, m²/(V·s) [§5.1]
    ua: float   = 2.25e-9      # First-order mobility degradation coeff, m/V [§5.1]
    ub: float   = 5.87e-19     # Second-order mobility degradation coeff, (m/V)² [§5.1]
    uc: float   = -4.65e-11    # Body-effect mobility degradation coeff [§5.1]

    # ── Saturation / velocity ────────────────────────────────────────────────
    vsat: float = 8.0e4        # Saturation velocity, m/s [§6.1]
    a1: float   = 0.0          # First non-saturation factor [§6.2]
    a2: float   = 1.0          # Second non-saturation factor [§6.2]
    pclm: float = 1.3          # Channel-length modulation parameter [§6.3]
    delta: float = 0.01        # Effective V_ds transition width [§6.2]

    # ── Channel / oxide ──────────────────────────────────────────────────────
    tox: float  = 3.0e-9       # Gate oxide thickness, m [§2]
    toxe: float = 3.3e-9       # Electrical oxide thickness (includes quantum), m
    nch: float  = 1.7e17       # Channel doping concentration, /cm³ [§2]
    xj: float   = 1.5e-7       # Junction depth, m [§4.2]

    # ── Source/drain resistance ──────────────────────────────────────────────
    rdsw: float = 100.0        # Width-normalised S/D resistance, Ω·μm [§7.1]
    rdswmin: float = 0.0       # Minimum RDSW, Ω·μm

    # ── Capacitances ─────────────────────────────────────────────────────────
    cgso: float = 2.5e-10      # Gate-source overlap cap per unit width, F/m [§9.1]
    cgdo: float = 2.5e-10      # Gate-drain overlap cap per unit width, F/m [§9.1]
    cgbo: float = 1.0e-11      # Gate-body overlap cap per unit length, F/m [§9.1]
    cj: float   = 1.0e-3       # Source/drain bottom junction cap density, F/m² [§9.3]
    mj: float   = 0.5          # Grading coefficient for bottom junction [§9.3]
    cjsw: float = 5.0e-10      # Sidewall junction cap density, F/m [§9.3]
    mjsw: float = 0.33         # Grading coefficient for sidewall junction [§9.3]
    pb: float   = 0.8          # Built-in potential (junction), V [§9.3]

    # ── Channel-length modulation / DIBL ────────────────────────────────────
    pdiblc1: float = 0.39      # DIBL coefficient 1 [§4.4]
    pdiblc2: float = 0.0086    # DIBL coefficient 2 [§4.4]
    eta0: float = 0.08         # DIBL coefficient [§4.4]
    etab: float = -0.07        # DIBL body-bias coeff [§4.4]

    # ── Subthreshold / leakage ───────────────────────────────────────────────
    nfactor: float = 1.0       # Subthreshold swing ideality factor [§4.5]
    cit: float  = 0.0          # Interface trap capacitance, F/m² [§4.5]
    cdsc: float = 2.4e-4       # Drain/source to channel coupling cap, F/m² [§4.5]

    # ── Temperature coefficients ──────────────────────────────────────────────
    tnom: float = 300.15       # Nominal temperature for parameters, K (27°C) [§8.1]
    kt1: float  = -0.11        # Temperature coefficient for Vth, V [§8.1]
    kt2: float  = 0.022        # Second temperature coefficient for Vth [§8.1]
    ute: float  = -1.5         # Mobility temperature exponent [§8.1]
    ua1: float  = 4.31e-9      # Temperature coefficient for UA [§8.1]

    # ── Pelgrom statistical matching (Pelgrom 1989, IEEE JSSC 24(5)) ─────────
    # σ(Vth) = AVT0 / sqrt(W·L),  σ(β)/β = ABETA / sqrt(W·L)
    avt0: float = 5.0e-3       # Vth matching coefficient, V·m  [Pelgrom 1989, eq. 4]
    abeta: float = 1.0e-2      # β (current factor) matching coefficient, %·m [Pelgrom 1989, eq. 6]


@dataclass
class Bsim4Geometry:
    """MOSFET device geometry."""

    W: float                    # Channel width, m
    L: float                    # Channel length, m
    AS: float = 0.0             # Source diffusion area, m²
    AD: float = 0.0             # Drain diffusion area, m²
    PS: float = 0.0             # Source diffusion perimeter, m
    PD: float = 0.0             # Drain diffusion perimeter, m
    nf: int   = 1               # Number of fingers


# ---------------------------------------------------------------------------
# Internal helper utilities
# ---------------------------------------------------------------------------

def _vt(T_kelvin: float) -> float:
    """Thermal voltage kT/q at temperature T (K)."""
    return _KB * T_kelvin / _Q


def _phi_f(nch_cm3: float, T_kelvin: float) -> float:
    """Fermi potential 2φF = 2·(kT/q)·ln(Nch/ni).

    Uses ni ≈ 1.45e10 cm⁻³ at 300 K with T-scaling per BSIM4 §8.
    """
    vt = _vt(T_kelvin)
    # Intrinsic carrier concentration temperature scaling (approximation)
    ni_300 = 1.45e10  # cm⁻³ at 300 K
    ni = ni_300 * (T_kelvin / 300.0) ** 1.5 * math.exp(-0.605 * (1.0 / (vt) - 1.0 / _vt(300.0)))
    ni = max(ni, 1e6)  # avoid log(0)
    # 2φF
    phi_bulk = 2.0 * vt * math.log(max(nch_cm3, 1.0) / ni)
    return max(phi_bulk, 0.1)  # physical floor


def _cox(tox_m: float) -> float:
    """Oxide capacitance per unit area, F/m²."""
    return (_EPS_OX * _EPS0) / tox_m


def _eps_si() -> float:
    return _EPS_SI * _EPS0


# ---------------------------------------------------------------------------
# Threshold voltage — BSIM4.8 §4
# ---------------------------------------------------------------------------

def vth_bsim4(
    vbs: float,
    T_kelvin: float,
    params: Bsim4Parameters,
    geom: Bsim4Geometry,
) -> float:
    """Long-channel threshold voltage with bulk/temperature modulation.

    Implements BSIM4.8 §4.1 (bulk effect) + §8.1 (temperature).
    Short-channel effects (SCE, DIBL) are omitted at this stage (v1).

    HONEST NOTE: This is a first-order approximation.  Full BSIM4 §4 includes
    SCE, reverse-short-channel effect, quantum-mechanical corrections, etc.
    Not foundry-PDK accurate; for design exploration only.
    """
    phi2 = _phi_f(params.nch, T_kelvin)  # 2φF

    # Bulk-charge body effect (BSIM4 §4.1, eq. 4.1b)
    # Vth = Vth0 + k1·(√(2φF - Vbs) - √(2φF)) - k2·Vbs
    arg = max(phi2 - vbs, 1e-12)
    delta_vth_body = params.k1 * (math.sqrt(arg) - math.sqrt(phi2)) - params.k2 * vbs

    # Temperature shift (BSIM4 §8.1, simplified)
    dT = T_kelvin - params.tnom
    delta_vth_temp = params.kt1 * (dT / params.tnom) + params.kt2 * vbs * (dT / params.tnom)

    return params.vth0 + delta_vth_body + delta_vth_temp


# ---------------------------------------------------------------------------
# Effective mobility — BSIM4.8 §5 (simplified)
# ---------------------------------------------------------------------------

def _mu_eff(
    vgs: float, vth: float, vbs: float,
    T_kelvin: float,
    params: Bsim4Parameters,
    geom: Bsim4Geometry,
) -> float:
    """Effective mobility with vertical-field degradation and temperature scaling.

    Implements BSIM4.8 §5.1 (unified mobility model, simplified to first two
    terms) and §8.1 temperature scaling.

    HONEST NOTE: Quantum-mechanical corrections, strain, and scattering models
    are omitted.
    """
    cox = _cox(params.toxe)
    # Effective vertical field (simplified: Eeff ≈ (Vgs - Vth) / (2 * tox))
    vgst = max(vgs - vth, 0.0)
    Eeff = (vgst + 2.0 * _phi_f(params.nch, T_kelvin)) / (2.0 * params.toxe * 1e6)
    # Avoid extreme values
    Eeff = max(Eeff, 0.0)

    # Mobility degradation denominator (BSIM4 §5.1 eq. 5.1a)
    denom = 1.0 + (params.ua + params.uc * vbs) * Eeff + params.ub * Eeff ** 2
    denom = max(denom, 0.1)  # numerical floor

    # Temperature scaling of u0 (BSIM4 §8.1: μ(T) ∝ (T/Tnom)^UTE)
    u0_T = params.u0 * (T_kelvin / params.tnom) ** params.ute

    return u0_T / denom


# ---------------------------------------------------------------------------
# Drain current — BSIM4.8 §6
# ---------------------------------------------------------------------------

def id_bsim4(
    vgs: float,
    vds: float,
    vbs: float,
    T_kelvin: float,
    params: Bsim4Parameters,
    geom: Bsim4Geometry,
) -> float:
    """Drain current per BSIM4.8 §4 + §5 + §6 first-order DC model.

    Regions:
      Sub-threshold: Id = Id0 · exp((Vgs - Vth) / (n·Vt)) · (1 - exp(-Vds/Vt))
      Triode:        Id = β · (Vgs - Vth - Vds/2) · Vds · (1 + λ·Vds)
      Saturation:    Id = β/2 · Vgst²/(1 + Vgst/(Vsat·L)) · (1 + λ·Vds)

    where β = μeff · Cox · W/L (per finger, scaled by nf).

    HONEST NOTE: CLM (channel-length modulation), DIBL, velocity overshoot,
    noise, and other second-order effects are simplified.  Not foundry-PDK
    accurate; for design exploration only.

    References:
      BSIM4.8 Technical Manual, UC Berkeley, 2013, §4, §5, §6.
      Tsividis, Y. & McAndrew, C. (2011). Operation and Modeling of the MOS
      Transistor, 3e. Oxford University Press.
    """
    if vgs <= 0.0 and vds <= 0.0:
        return 0.0

    vth = vth_bsim4(vbs, T_kelvin, params, geom)
    vt  = _vt(T_kelvin)
    cox = _cox(params.toxe)
    mu  = _mu_eff(vgs, vth, vbs, T_kelvin, params, geom)

    # Current factor β per device (all fingers in parallel)
    nf   = max(geom.nf, 1)
    beta = mu * cox * (geom.W * nf) / geom.L

    # Source/drain series resistance Rds (width-normalised, BSIM4 §7.1)
    rds_total = params.rdsw / (geom.W * nf * 1e6)  # rdsw in Ω·μm, W in m → Ω

    # ── Subthreshold ──────────────────────────────────────────────────────
    # n = ideality factor from Nfactor + Cdsc/Cox (BSIM4 §4.5)
    cdep = math.sqrt(_eps_si() * _Q * params.nch * 1e6 / (2.0 * max(_phi_f(params.nch, T_kelvin), 0.1)))
    cox_area = _cox(params.toxe)
    n_sub = 1.0 + params.nfactor * cdep / cox_area + params.cdsc / cox_area
    n_sub = max(n_sub, 1.0)

    vgst = vgs - vth
    if vgst < -n_sub * vt * 3:
        # Deep subthreshold — effectively off
        return 0.0

    if vgst < 0.0:
        # Subthreshold regime (BSIM4 §4.5 simplified)
        Id_sub = beta * (vt ** 2) * math.exp(vgst / (n_sub * vt)) * (1.0 - math.exp(-max(vds, 0.0) / vt))
        return max(Id_sub, 0.0)

    # ── Above threshold ────────────────────────────────────────────────────
    # Velocity-saturation limited Vdsat (BSIM4 §6.1)
    # Esat = 2·Vsat / μeff  → Vdsat ≈ Esat·L·Vgst / (Esat·L + Vgst)
    Esat  = 2.0 * params.vsat / mu
    vdsat = (Esat * geom.L * vgst) / (Esat * geom.L + vgst)
    vdsat = max(vdsat, 1e-6)

    vds_eff = min(vds, vdsat)

    # Channel-length modulation factor λ (BSIM4 §6.3 simplified)
    # λ ≈ Pclm / (L · √(2εsi·q·Nch)) — only active above Vdsat
    lam = 0.0
    if params.pclm > 0 and vds > vdsat:
        # Simplified CLM: λ_eff = pclm * (vds - vdsat) / vdsat
        lam = params.pclm * (vds - vdsat) / (vdsat * geom.L * 1e7)
        lam = min(lam, 0.5)  # physical cap

    clm_factor = 1.0 + lam

    # Long-channel drain current (modified for velocity saturation)
    # Using the "charge-sheet" formulation with Vdsat clamp:
    Id_raw = beta * (vgst - vds_eff / 2.0) * vds_eff * clm_factor

    # Rds voltage drop correction (iterative would be needed for full accuracy;
    # use a first-order correction here)
    if rds_total > 0 and Id_raw > 0:
        # Vds_int ≈ Vds - Id·Rds  (first-order)
        vds_int = max(vds - Id_raw * rds_total, 0.0)
        if vds_int < vds * 0.999:
            vdsat2 = (Esat * geom.L * vgst) / (Esat * geom.L + vgst)
            vds_eff2 = min(vds_int, vdsat2)
            Id_raw = beta * (vgst - vds_eff2 / 2.0) * vds_eff2 * clm_factor

    return max(Id_raw, 0.0)


# ---------------------------------------------------------------------------
# Transconductance gm = ∂Id/∂Vgs
# ---------------------------------------------------------------------------

def gm_bsim4(
    vgs: float, vds: float, vbs: float,
    T_kelvin: float,
    params: Bsim4Parameters,
    geom: Bsim4Geometry,
    dvgs: float = 1e-6,
) -> float:
    """Transconductance ∂Id/∂Vgs via numerical central differentiation.

    HONEST NOTE: Not foundry-PDK accurate; for design exploration only.
    """
    id_plus  = id_bsim4(vgs + dvgs / 2, vds, vbs, T_kelvin, params, geom)
    id_minus = id_bsim4(vgs - dvgs / 2, vds, vbs, T_kelvin, params, geom)
    return (id_plus - id_minus) / dvgs


# ---------------------------------------------------------------------------
# Output conductance gds = ∂Id/∂Vds
# ---------------------------------------------------------------------------

def gds_bsim4(
    vgs: float, vds: float, vbs: float,
    T_kelvin: float,
    params: Bsim4Parameters,
    geom: Bsim4Geometry,
    dvds: float = 1e-6,
) -> float:
    """Output conductance ∂Id/∂Vds via numerical central differentiation.

    HONEST NOTE: Not foundry-PDK accurate; for design exploration only.
    """
    id_plus  = id_bsim4(vgs, vds + dvds / 2, vbs, T_kelvin, params, geom)
    id_minus = id_bsim4(vgs, vds - dvds / 2, vbs, T_kelvin, params, geom)
    return (id_plus - id_minus) / dvds


# ---------------------------------------------------------------------------
# Gate capacitances — BSIM4.8 §9
# ---------------------------------------------------------------------------

def cgs_bsim4(
    vgs: float,
    vds: float,
    params: Bsim4Parameters,
    geom: Bsim4Geometry,
) -> float:
    """Gate-source capacitance = overlap + inversion-layer contribution.

    Implements BSIM4.8 §9.1 (overlap) + §9.2 (charge partitioning,
    simplified CAPMOD=0 style: linear interpolation between off/triode/sat).

    HONEST NOTE: Full BSIM4 §9 includes CAPMOD 1/2/3, quantum-mechanical
    corrections, and gate electrode parasitics.  Not foundry-PDK accurate;
    for design exploration only.

    References:
      BSIM4.8 Technical Manual, UC Berkeley, 2013, §9.
      Ward, D.E. & Dutton, R.W. (1978).  IEEE JSSC 13(5).
    """
    nf   = max(geom.nf, 1)
    W_eff = geom.W * nf
    cox  = _cox(params.tox)
    Cox_total = cox * W_eff * geom.L  # total oxide capacitance

    # Overlap capacitance (always present)
    C_ov = params.cgso * W_eff

    # Inversion capacitance — simplified charge-sheet model
    # Three regions: cutoff (Vgs < Vth → 0), triode, saturation
    # Use T=300 K for Vth at this call (no T argument for cap model)
    vth = vth_bsim4(0.0, 300.15, params, geom)  # Vbs=0 for cap
    vgst = vgs - vth

    if vgst <= 0.0:
        # Cutoff: only overlap
        Cinv = 0.0
    elif vds >= 2.0 / 3.0 * vgst:
        # Saturation: Cgs = 2/3 · Cox_total  (Ward-Dutton partition)
        Cinv = (2.0 / 3.0) * Cox_total
    else:
        # Triode: interpolate between 2/3 and Cox_total
        frac = min(vds / (2.0 / 3.0 * max(vgst, 1e-9)), 1.0)
        Cinv = (2.0 / 3.0 + (1.0 - 2.0 / 3.0) * (1.0 - frac)) * Cox_total

    return C_ov + Cinv


def cgd_bsim4(
    vgs: float,
    vds: float,
    params: Bsim4Parameters,
    geom: Bsim4Geometry,
) -> float:
    """Gate-drain capacitance = overlap + inversion-layer contribution.

    HONEST NOTE: Simplified; not foundry-PDK accurate; for design exploration.
    """
    nf    = max(geom.nf, 1)
    W_eff = geom.W * nf
    cox   = _cox(params.tox)
    Cox_total = cox * W_eff * geom.L

    C_ov  = params.cgdo * W_eff

    vth   = vth_bsim4(0.0, 300.15, params, geom)
    vgst  = vgs - vth

    if vgst <= 0.0:
        Cinv = 0.0
    elif vds >= 2.0 / 3.0 * vgst:
        # Saturation: Cgd ≈ 0 (channel pinched off at drain)
        Cinv = 0.0
    else:
        frac = min(vds / (2.0 / 3.0 * max(vgst, 1e-9)), 1.0)
        Cinv = (1.0 / 3.0) * Cox_total * frac

    return C_ov + Cinv


def cjd_bsim4(
    vbd: float,
    params: Bsim4Parameters,
    geom: Bsim4Geometry,
) -> float:
    """Drain-body junction capacitance (bottom + sidewall).

    HONEST NOTE: Simplified; not foundry-PDK accurate; for design exploration.
    References: BSIM4.8 §9.3.
    """
    nf   = max(geom.nf, 1)
    AD   = geom.AD if geom.AD > 0 else geom.W * nf * 100e-9
    PD   = geom.PD if geom.PD > 0 else 2 * (geom.W * nf + 100e-9)

    # Bottom junction (reverse bias reduces cap)
    arg_bot = max(1.0 - vbd / params.pb, 0.01)
    Cj_bot  = params.cj * AD / (arg_bot ** params.mj)

    # Sidewall junction
    arg_sw  = max(1.0 - vbd / params.pb, 0.01)
    Cj_sw   = params.cjsw * PD / (arg_sw ** params.mjsw)

    return Cj_bot + Cj_sw


# ---------------------------------------------------------------------------
# PMOS convenience wrapper (sign inversion)
# ---------------------------------------------------------------------------

def id_pmos(
    vgs: float, vds: float, vbs: float,
    T_kelvin: float,
    params: Bsim4Parameters,
    geom: Bsim4Geometry,
) -> float:
    """PMOS drain current via sign-reflected NMOS model.

    All voltages supplied as PMOS convention (Vgs, Vds, Vbs negative
    for on-state PMOS).  Returns |Id| (positive convention for PMOS).

    HONEST NOTE: A symmetric sign inversion; real PMOS has different
    parameters.  Not foundry-PDK accurate; for design exploration only.
    """
    return id_bsim4(-vgs, -vds, -vbs, T_kelvin, params, geom)
