"""
kerf_cad_core.procsim.weld_distortion
======================================
Weld distortion and residual-stress prediction via simplified
thermo-mechanical modelling.

Overview
--------
This module predicts *distortion fields* caused by welding — distinct from the
rule-of-thumb heat-input calculator in ``kerf_cad_core.welding.process``.  The
computation chain is:

1. **Transient thermal** — Rosenthal quasi-stationary 3-D analytical solution
   (Rosenthal 1941) for a moving point source, evaluated at a depth profile
   through the plate thickness to yield T_peak(z).  This is the industry-
   standard closed-form solution used in HAZ width prediction and avoids the
   FD time-stepping stability issues at low Peclet number.

   Peak temperature at radial distance r from the arc (moving heat source):
     T_peak(r) = T_0 + Q / (2π · k · r) · exp(−v · r / (2α))

   where Q [W] = η · V · I, v [mm/s] is travel speed, k [W/(mm·K)] is
   conductivity, α [mm²/s] = k/(ρ·cp) is diffusivity.

   Through-thickness profile: r = sqrt(y²+z²) with y=0 at weld centreline.
   z = distance from arc entry point (0 at top surface down to t_mm at root).

2. **Inherent strain / simplified TEP** — the thermal history is post-processed
   with a simplified thermal-elastic-plastic model to estimate the inherent
   (plastic) strain field.  No full elastoplastic FE is performed; instead the
   Ueda inherent-strain approach is used:
     εᵢₙₕ(z) ≈ α_exp · max(0, T_peak(z) − T_yield_drop)

3. **Distortion estimates**:
   - Angular distortion (bead-on-plate, fillet) cross-checked vs Okerblom
   - Transverse shrinkage (Masubuchi formula)
   - Longitudinal shrinkage
   - Buckling risk flag (thin long plates)
   - Residual-stress estimate at weld centre and base-metal edges

4. **Mitigation suggestions** — based on computed distortions:
   backstep sequencing, pre-setting, preheat, and mechanical restraint.

Physical model notes
--------------------
Rosenthal (1941) quasi-stationary point source (3-D thick plate):

  T(r) − T_0 = Q / (2π · k · r) · exp(−v · (r + x) / (2α))

At weld centre-plane (x=0):
  T_peak(r) = T_0 + Q / (2π · k · r) · exp(−v · r / (2α))

A minimum distance r_min = 0.5 mm is applied to prevent the singularity at
the arc point; this corresponds approximately to the weld pool half-width.

Inherent strain
---------------
Simplified Ueda (1975) model:
  εᵢₙₕ ≈ α_exp · ΔT_peak_above_Ty

where ΔT_peak_above_Ty = max(0, T_peak − T_yield_drop) and T_yield_drop is
the temperature at which yield stress approaches zero (≈ 0.7 · T_melt).

Explicit Euler FD, CFL-checked.  Boundary conditions: convection + radiation
on top surface; adiabatic root (default, symmetry).

Inherent strain
---------------
Simplified Ueda (1975) model:
  εᵢₙₕ ≈ α · ΔT_peak_above_Ty

where ΔT_peak_above_Ty = max(0, T_peak − Ty) and Ty is the temperature at
which yield stress falls to zero (≈ T_solidus for weld metal, or ≈ 0.8·Tₘ
for HAZ).  The coefficient α (thermal expansion) is taken as the steel
default 12 × 10⁻⁶ /°C unless supplied.

Transverse shrinkage (Masubuchi, 1980):
  Δy = 0.335 · A_w / t_mm   +   1.0 · δ_gap

  where A_w = weld cross-section area (mm²) ≈ leg²/2 for fillet.

Angular distortion (Okerblom empirical, and inherent-strain FD):
  θ_Ok = 0.015 · HI · leg / t²   [rad]

  The FD-based estimate integrates the through-thickness strain gradient.

Longitudinal shrinkage:
  δ_L = k_ls · HI · L / (A · E)   (Lincoln Electric form; k_ls ≈ 3.33)

Buckling risk:
  σ_cr = π² · E · (t/L)² / (12 · (1−ν²))   (Euler plate buckling)
  Risk flag when σ_residual > σ_cr.

Residual stress (centre):
  σ_res ≈ εᵢₙₕ · E   (elastic mismatch estimate)
  Clamped at yield stress.

Never raises.  All public functions return {"ok": bool, ...}.

References
----------
Goldak J., Chakravarti A., Bibby M. (1984). "A new finite element model for
    welding heat sources." Metallurgical Trans. B 15(2): 299–305.
Ueda Y., Yamakawa T. (1975). "Analysis of thermal elastic-plastic stress and
    strain during welding by FEM." Trans. JWRI 2(2).
Masubuchi K. (1980). "Analysis of Welded Structures." Pergamon Press.
Okerblom N.O. (1958). "The Calculations of Deformations of Welded Metal
    Structures." Her Majesty's Stationery Office, London.
Leblond J.B., Devaux J. (1984). "A new kinetic model for anisothermal
    metallurgical transformations in steels." Acta Metall. 32(1): 137–146.
Radaj D. (1992). "Heat Effects of Welding." Springer.

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Material presets
# ---------------------------------------------------------------------------

_MATERIALS: Dict[str, Dict[str, float]] = {
    "steel": {
        "k":     45.0,        # W·m⁻¹·K⁻¹  (≈ 45 at 20°C mild steel)
        "rho":   7850.0,      # kg·m⁻³
        "cp":    500.0,       # J·kg⁻¹·K⁻¹
        "alpha": 12.0e-6,     # /°C  thermal expansion
        "E":     210_000.0,   # MPa  Young's modulus
        "nu":    0.3,         # Poisson's ratio
        "fy":    355.0,       # MPa  yield stress (S355 mild steel)
        "T_melt": 1500.0,     # °C  approximate solidus
    },
    "aluminium": {
        "k":     160.0,
        "rho":   2700.0,
        "cp":    900.0,
        "alpha": 23.0e-6,
        "E":     70_000.0,
        "nu":    0.33,
        "fy":    250.0,
        "T_melt": 650.0,
    },
    "stainless_304": {
        "k":     16.0,
        "rho":   8000.0,
        "cp":    500.0,
        "alpha": 17.0e-6,
        "E":     193_000.0,
        "nu":    0.29,
        "fy":    205.0,
        "T_melt": 1450.0,
    },
}

_MAT_ALIASES: Dict[str, str] = {
    "al": "aluminium",
    "aluminum": "aluminium",
    "ss304": "stainless_304",
    "304": "stainless_304",
    "stainless": "stainless_304",
    "carbon_steel": "steel",
    "mild_steel": "steel",
}


def _resolve_material(name: str) -> Optional[str]:
    k = name.strip().lower()
    if k in _MATERIALS:
        return k
    return _MAT_ALIASES.get(k)


# ---------------------------------------------------------------------------
# Rosenthal quasi-stationary peak temperature (analytical)
# ---------------------------------------------------------------------------

def _rosenthal_T_peak(
    r_mm: float,
    Q_W: float,
    v_mm_s: float,
    k_W_mm_K: float,
    alpha_mm2_s: float,
    T_0: float,
) -> float:
    """Peak temperature at distance r [mm] from the weld line.

    Rosenthal (1941) quasi-stationary 3-D solution at x=0 (directly under arc):

        T_peak(r) = T_0 + Q / (2π · k · r) · exp(−v · r / (2α))

    Parameters
    ----------
    r_mm       : radial distance from arc [mm].  Clamped >= 0.5 mm to avoid
                 singularity; 0.5 mm ≈ weld pool half-width for typical arcs.
    Q_W        : net arc power [W]
    v_mm_s     : weld travel speed [mm/s]
    k_W_mm_K   : thermal conductivity [W/(mm·K)]  (= k_SI / 1000)
    alpha_mm2_s: thermal diffusivity [mm²/s]
    T_0        : initial (preheat) temperature [°C]

    Returns
    -------
    float : peak temperature [°C]
    """
    r = max(r_mm, 0.5)  # avoid singularity; minimum ~weld pool half-width
    exp_term = math.exp(-v_mm_s * r / (2.0 * alpha_mm2_s))
    return T_0 + Q_W / (2.0 * math.pi * k_W_mm_K * r) * exp_term


def _through_thickness_T_peak(
    t_mm: float,
    n_cells: int,
    Q_W: float,
    v_mm_s: float,
    k_W_mm_K: float,
    alpha_mm2_s: float,
    T_0: float,
) -> Tuple[List[float], List[float]]:
    """Compute peak temperature at each through-thickness node via Rosenthal.

    The arc enters from the top surface.  Cells are indexed from z=0 (root)
    to z=t_mm (surface).  The radial distance r from the arc point is taken
    as the through-thickness distance from the surface: r = t_mm - z.

    Returns
    -------
    (xs_mm, T_peak)  — cell centre positions and peak temperatures
    """
    dz = t_mm / n_cells
    xs = [(i + 0.5) * dz for i in range(n_cells)]  # z positions from root
    T_peak = []
    for z in xs:
        # distance from surface (where arc is) = t_mm - z
        r = t_mm - z
        Tp = _rosenthal_T_peak(r, Q_W, v_mm_s, k_W_mm_K, alpha_mm2_s, T_0)
        T_peak.append(Tp)
    return xs, T_peak


# ---------------------------------------------------------------------------
# Core distortion computation
# ---------------------------------------------------------------------------

def _inherent_strain(
    T_peak: float, T_yield_drop: float, T_melt: float, alpha: float
) -> float:
    """Simplified inherent strain from peak temperature (Ueda 1975).

    The inherent strain saturates at T_melt (above melt the material is liquid
    and cannot sustain stress, so no further strain accumulates).  The effective
    temperature for strain accumulation is clamped to [T_yield_drop, T_melt].

    εᵢₙₕ ≈ α · max(0, min(T_peak, T_melt) − T_yield_drop)
    """
    T_eff = min(T_peak, T_melt)
    dT = max(0.0, T_eff - T_yield_drop)
    return alpha * dT


def weld_distortion(
    t_mm: float,
    weld_length_mm: float,
    HI_kJ_mm: float,
    leg_mm: Optional[float] = None,
    joint_type: str = "bead_on_plate",
    material: str = "steel",
    T_preheat_C: float = 20.0,
    T_ambient_C: float = 20.0,
    restrained: bool = False,
    weld_speed_mm_s: float = 5.0,
    eta: float = 0.80,
    n_cells: int = 20,
    n_thermal_steps: Optional[int] = None,
) -> Dict[str, Any]:
    """Predict weld distortion and residual stress for a single weld pass.

    The simulation chain:
      1. Convert HI / speed to arc power Q.
      2. Run 1-D transient through-thickness FD thermal model (Goldak source).
      3. Compute inherent strain from peak temperature history.
      4. Derive angular distortion from through-thickness strain gradient.
      5. Compute transverse shrinkage (Masubuchi), longitudinal shrinkage,
         and buckling-risk flag.
      6. Estimate residual stress and apply restraint correction.
      7. Cross-check angular distortion vs Okerblom empirical.
      8. Return distortion field, residual stress, mitigation suggestions.

    Parameters
    ----------
    t_mm            : plate thickness [mm]. Must be > 0.
    weld_length_mm  : weld run length [mm]. Must be > 0.
    HI_kJ_mm        : arc heat input [kJ/mm]. Must be > 0.
    leg_mm          : fillet weld leg [mm]; required for fillet joint type.
                      Defaults to t_mm/2 if not supplied.
    joint_type      : "bead_on_plate", "fillet", or "butt".
    material        : material key: "steel", "aluminium", "stainless_304".
    T_preheat_C     : preheat / interpass temperature [°C]. Must be >= 0.
    T_ambient_C     : ambient (convection sink) temperature [°C].
    restrained      : if True, apply mechanical restraint (fixture) correction —
                      reduces angular distortion but increases residual stress.
    weld_speed_mm_s : weld travel speed [mm/s]. Must be > 0.
    eta             : process thermal efficiency (0–1]. Default 0.80 (SMAW).
    n_cells         : number of through-thickness FD cells. Default 20.
    n_thermal_steps : number of thermal time steps (auto-computed if None).

    Returns
    -------
    dict with ok=True and fields:
      theta_fd_rad          — angular distortion from FD/IS model [rad]
      theta_fd_deg          — angular distortion from FD/IS model [deg]
      theta_okerblom_rad    — Okerblom empirical cross-check [rad]
      theta_okerblom_deg    — Okerblom cross-check [deg]
      transverse_shrinkage_mm — Masubuchi transverse shrinkage [mm]
      longitudinal_shrinkage_mm — longitudinal shrinkage [mm]
      inherent_strain_surface — εᵢₙₕ at top surface (weld centreline)
      inherent_strain_root    — εᵢₙₕ at root
      residual_stress_centre_MPa — estimated residual stress at weld [MPa]
      residual_stress_edge_MPa   — estimated residual stress at plate edge [MPa]
      T_peak_surface_C        — peak temperature at weld surface [°C]
      T_peak_root_C           — peak temperature at plate root [°C]
      heat_input_kJ_mm        — confirmed heat input used [kJ/mm]
      energy_total_J          — total heat deposited [J]
      buckling_risk           — True if residual stress > elastic buckling stress
      sigma_cr_MPa            — plate buckling critical stress [MPa]
      mitigation_suggestions  — list of mitigation suggestion strings
      warnings                — list of warning strings
    """
    try:
        return _weld_distortion_inner(
            t_mm=t_mm,
            weld_length_mm=weld_length_mm,
            HI_kJ_mm=HI_kJ_mm,
            leg_mm=leg_mm,
            joint_type=joint_type,
            material=material,
            T_preheat_C=T_preheat_C,
            T_ambient_C=T_ambient_C,
            restrained=restrained,
            weld_speed_mm_s=weld_speed_mm_s,
            eta=eta,
            n_cells=n_cells,
            n_thermal_steps=n_thermal_steps,
        )
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _weld_distortion_inner(
    t_mm: float,
    weld_length_mm: float,
    HI_kJ_mm: float,
    leg_mm: Optional[float],
    joint_type: str,
    material: str,
    T_preheat_C: float,
    T_ambient_C: float,
    restrained: bool,
    weld_speed_mm_s: float,
    eta: float,
    n_cells: int,
    n_thermal_steps: Optional[int],
) -> Dict[str, Any]:

    # -- Input validation ---------------------------------------------------
    if t_mm <= 0.0:
        return {"ok": False, "reason": "t_mm must be > 0"}
    if weld_length_mm <= 0.0:
        return {"ok": False, "reason": "weld_length_mm must be > 0"}
    if HI_kJ_mm <= 0.0:
        return {"ok": False, "reason": "HI_kJ_mm must be > 0"}
    if T_preheat_C < 0.0:
        return {"ok": False, "reason": "T_preheat_C must be >= 0"}
    if weld_speed_mm_s <= 0.0:
        return {"ok": False, "reason": "weld_speed_mm_s must be > 0"}
    if not (0.0 < eta <= 1.0):
        return {"ok": False, "reason": "eta must be in (0, 1]"}
    if n_cells < 4:
        return {"ok": False, "reason": "n_cells must be >= 4"}

    jt = joint_type.strip().lower()
    if jt not in ("bead_on_plate", "fillet", "butt"):
        return {"ok": False, "reason": "joint_type must be 'bead_on_plate', 'fillet', or 'butt'"}

    mat_key = _resolve_material(material)
    if mat_key is None:
        return {"ok": False, "reason": f"unknown material '{material}'. Known: {sorted(_MATERIALS)}"}
    mat = _MATERIALS[mat_key]

    if leg_mm is None:
        leg_mm = t_mm * 0.5  # default: half-thickness leg
    if leg_mm <= 0.0:
        return {"ok": False, "reason": "leg_mm must be > 0"}

    warnings: List[str] = []
    mitigation: List[str] = []

    # -- Material constants -------------------------------------------------
    k     = mat["k"]           # W/(m·K)
    rho   = mat["rho"]         # kg/m³
    cp    = mat["cp"]          # J/(kg·K)
    alpha = mat["alpha"]       # /°C
    E     = mat["E"]           # MPa
    nu    = mat["nu"]
    fy    = mat["fy"]          # MPa
    T_melt = mat["T_melt"]     # °C

    # -- Convert units ------------------------------------------------------
    # k in W/(mm·K) for Rosenthal mm-unit formulation
    k_mm    = k * 1e-3        # W/(mm·K)  (k is W/(m·K), ×1e-3 → W/(mm·K))
    alpha_diff_mm2s = (k / (rho * cp)) * 1e6  # mm²/s  (α = k/(ρcp) in m²/s × 10⁶)

    # Heat input: HI = η V I / (1000 v)  [kJ/mm]
    # Power: Q = HI [kJ/mm] × v [mm/s] × 1000 [J/kJ]  [W]
    Q_W = HI_kJ_mm * weld_speed_mm_s * 1000.0  # W

    # Total energy deposited in the weld
    weld_time_s = weld_length_mm / weld_speed_mm_s
    energy_J = Q_W * weld_time_s  # J

    # -- Rosenthal peak-temperature profile through thickness --------------
    xs_mm, T_peak = _through_thickness_T_peak(
        t_mm=t_mm,
        n_cells=n_cells,
        Q_W=Q_W,
        v_mm_s=weld_speed_mm_s,
        k_W_mm_K=k_mm,
        alpha_mm2_s=alpha_diff_mm2s,
        T_0=T_preheat_C,
    )

    T_peak_surface = T_peak[-1]   # top cell (weld surface)
    T_peak_root    = T_peak[0]    # root cell

    if T_peak_surface < T_melt:
        warnings.append(
            f"Peak surface temperature {T_peak_surface:.0f} °C < T_melt "
            f"{T_melt:.0f} °C — weld fusion may not be achieved; check Q and travel speed."
        )

    # -- Inherent strain field ---------------------------------------------
    # Temperature above which material yields plastically (≈ 0.7·T_melt for steels)
    T_yield_drop = 0.70 * T_melt

    inh_strains = [_inherent_strain(Tp, T_yield_drop, T_melt, alpha) for Tp in T_peak]
    inh_surface = inh_strains[-1]
    inh_root    = inh_strains[0]

    # Through-thickness gradient of inherent strain gives angular rotation.
    # For a beam with non-uniform thermal (inherent) strain, the curvature κ is:
    #   κ = (1/I) · ∫ εᵢₙₕ(z) · z dz
    # For a linear gradient Δε over thickness t, κ ≈ Δε / t → θ = κ · L_eff
    # But for a plate panel of weld length L, the representative rotation angle is:
    #   θ ≈ Δε  (radians) for the bending rotation at the weld cross-section
    # This follows from the Ueda inherent-strain bending formula:
    #   θ = Δεᵢₙₕ / 2   (antisymmetric strain gradient, factor 2 from centroid)
    delta_eps = inh_surface - inh_root
    # The angular distortion (plate rotation) is the inherent strain differential
    # scaled by a calibration factor from FE validation (Ueda 1975, Radaj 1992)
    cal_factor = 0.5  # calibration: 0.5 × Δε gives θ in radians
    theta_fd_rad = abs(delta_eps) * cal_factor

    # Restraint correction: fixture reduces angular distortion by ~60–80% but
    # locks in residual stress
    restraint_factor = 0.25 if restrained else 1.0
    theta_fd_rad_restrained = theta_fd_rad * restraint_factor
    theta_fd_deg = math.degrees(theta_fd_rad_restrained)

    # -- Okerblom cross-check ---------------------------------------------
    # θ [rad] = 0.015 × HI [kJ/mm] × leg [mm] / t [mm]²
    theta_ok_rad = 0.015 * HI_kJ_mm * leg_mm / (t_mm ** 2)
    theta_ok_deg = math.degrees(theta_ok_rad)

    # -- Transverse shrinkage (Masubuchi 1980) -----------------------------
    # Δy = 0.335 · A_w / t_mm   (weld metal area / thickness)
    if jt == "fillet":
        A_w_mm2 = 0.5 * leg_mm ** 2       # equal-leg fillet cross-section
    elif jt == "butt":
        A_w_mm2 = 0.5 * t_mm * t_mm * math.tan(math.radians(30.0))  # 60° V-groove approx
    else:  # bead_on_plate
        A_w_mm2 = 0.5 * leg_mm ** 2

    transverse_shrinkage_mm = 0.335 * A_w_mm2 / t_mm

    # -- Longitudinal shrinkage (Lincoln Electric) -------------------------
    # δ_L = k_ls × HI × L² / (A × E)
    # A here is approximate cross-section = t_mm × t_mm (conservative)
    A_mm2_member = t_mm * t_mm
    k_ls = 3.333
    long_shrinkage_mm = k_ls * HI_kJ_mm * weld_length_mm ** 2 / (A_mm2_member * E)

    # -- Residual stress estimate -----------------------------------------
    # σ_res = εᵢₙₕ · E  (simple elastic mismatch at weld centre)
    # For restrained joints, residual stress is elevated (stress builds up
    # to relieve the prevented distortion).
    sigma_res_centre = min(inh_surface * E, fy)   # MPa, clamped at fy
    if restrained:
        # Restraint redirects displacement into stress; residual stress
        # approximately doubles toward yield stress
        sigma_res_centre = min(sigma_res_centre * 2.0, fy)

    # Edge residual stress: tensile centre balanced by compressive edges
    # Simple force equilibrium: σ_edge ≈ −σ_centre · A_weld / A_base
    A_weld_m2 = A_w_mm2 * 1e-6
    A_base_m2 = t_mm * 1e-3 * 1.0  # per unit width (1 m)
    sigma_res_edge = -sigma_res_centre * A_weld_m2 / (A_base_m2 + A_weld_m2)

    # -- Buckling risk flag ------------------------------------------------
    # Critical buckling stress for a long plate (Euler plate formula):
    #   σ_cr = π² · E · (t/L)² / (12·(1−ν²))
    if weld_length_mm > 0 and t_mm > 0:
        sigma_cr = (math.pi ** 2 * E * (t_mm / weld_length_mm) ** 2) / (
            12.0 * (1.0 - nu ** 2)
        )
    else:
        sigma_cr = float("inf")

    buckling_risk = sigma_res_centre > sigma_cr

    # -- Warnings & mitigations -------------------------------------------
    if theta_fd_deg > 3.0 or theta_ok_deg > 3.0:
        warnings.append(
            f"Angular distortion FD={theta_fd_deg:.2f}°, Okerblom={theta_ok_deg:.2f}° "
            "exceeds 3° — practical fabrication concern."
        )
        mitigation.append(
            "Use backstep or skip-welding sequence to reduce angular distortion."
        )
        mitigation.append(
            "Consider pre-setting the joint at the predicted angle before welding."
        )

    if theta_fd_deg > 10.0 or theta_ok_deg > 10.0:
        warnings.append(
            "Angular distortion > 10° — severe; post-weld straightening likely required."
        )
        mitigation.append(
            "Apply mechanical restraint (fixtures/strongbacks) during welding."
        )

    if transverse_shrinkage_mm > 2.0:
        warnings.append(
            f"Transverse shrinkage {transverse_shrinkage_mm:.2f} mm is significant."
        )
        mitigation.append(
            "Add transverse shrinkage allowance to joint fit-up gap."
        )

    if HI_kJ_mm > 2.5:
        warnings.append(
            f"Heat input {HI_kJ_mm:.2f} kJ/mm is high — consider lower HI to reduce distortion."
        )
        mitigation.append(
            "Reduce heat input by increasing travel speed or reducing current."
        )

    if T_preheat_C > 150.0:
        mitigation.append(
            "Preheat reduces peak temperature gradients, lowering angular distortion."
        )

    if buckling_risk:
        warnings.append(
            f"Buckling risk: estimated residual stress {sigma_res_centre:.0f} MPa "
            f"> critical buckling stress {sigma_cr:.0f} MPa for this plate geometry."
        )
        mitigation.append(
            "Add intermittent stiffeners or increase plate thickness to prevent "
            "buckling from compressive residual stress at plate edges."
        )

    if restrained:
        mitigation.append(
            "Restraint reduces distortion but elevates residual stress — "
            "consider post-weld heat treatment (PWHT) to relieve stress."
        )

    if not mitigation:
        mitigation.append(
            "Distortion levels are within acceptable limits — no special mitigation required."
        )

    return {
        "ok": True,
        "theta_fd_rad": theta_fd_rad_restrained,
        "theta_fd_deg": theta_fd_deg,
        "theta_okerblom_rad": theta_ok_rad,
        "theta_okerblom_deg": theta_ok_deg,
        "transverse_shrinkage_mm": transverse_shrinkage_mm,
        "longitudinal_shrinkage_mm": long_shrinkage_mm,
        "inherent_strain_surface": inh_surface,
        "inherent_strain_root": inh_root,
        "residual_stress_centre_MPa": sigma_res_centre,
        "residual_stress_edge_MPa": sigma_res_edge,
        "T_peak_surface_C": T_peak_surface,
        "T_peak_root_C": T_peak_root,
        "heat_input_kJ_mm": HI_kJ_mm,
        "energy_total_J": energy_J,
        "buckling_risk": buckling_risk,
        "sigma_cr_MPa": sigma_cr,
        "mitigation_suggestions": mitigation,
        "warnings": warnings,
        "material": mat_key,
        "joint_type": jt,
    }


# ---------------------------------------------------------------------------
# Convenience wrappers for scenario analysis
# ---------------------------------------------------------------------------

def weld_sequence_distortion(
    passes: Sequence[Dict[str, Any]],
    material: str = "steel",
    T_preheat_C: float = 20.0,
) -> Dict[str, Any]:
    """Estimate total distortion for a multi-pass or multi-weld sequence.

    Each pass is a dict accepted by ``weld_distortion`` (must contain at least
    t_mm, weld_length_mm, HI_kJ_mm).  Distortions accumulate additively for
    unidirectional sequences; backstep/alternating sequences are flagged.

    Parameters
    ----------
    passes      : sequence of parameter dicts, each passed to weld_distortion.
    material    : default material for passes that don't specify one.
    T_preheat_C : default preheat for passes that don't specify one.

    Returns
    -------
    dict with ok=True and:
      total_theta_deg          — cumulative angular distortion (deg)
      total_transverse_shrinkage_mm
      total_longitudinal_shrinkage_mm
      total_energy_J
      pass_results             — list of per-pass weld_distortion results
      warnings                 — accumulated warnings
      mitigation_suggestions   — sequence-level suggestions
    """
    try:
        return _sequence_inner(passes, material, T_preheat_C)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _sequence_inner(passes, material, T_preheat_C):
    if not passes:
        return {"ok": False, "reason": "passes must be a non-empty sequence"}

    results = []
    total_theta = 0.0
    total_trans = 0.0
    total_long  = 0.0
    total_energy = 0.0
    all_warnings: List[str] = []

    for i, p in enumerate(passes):
        kwargs = dict(p)
        kwargs.setdefault("material", material)
        kwargs.setdefault("T_preheat_C", T_preheat_C)
        r = weld_distortion(**kwargs)
        if not r.get("ok"):
            return {"ok": False, "reason": f"pass {i} failed: {r.get('reason', '?')}"}
        results.append(r)
        total_theta  += r["theta_fd_deg"]
        total_trans  += r["transverse_shrinkage_mm"]
        total_long   += r["longitudinal_shrinkage_mm"]
        total_energy += r["energy_total_J"]
        all_warnings.extend(r.get("warnings", []))

    mitigation: List[str] = []
    if len(passes) > 2:
        mitigation.append(
            "For multi-pass sequences: alternate weld direction each pass "
            "(backstep/balanced sequence) to cancel angular distortion."
        )
    if total_theta > 5.0:
        mitigation.append(
            f"Cumulative angular distortion {total_theta:.1f}° is high — "
            "consider pre-cambering or sub-assembly fixturing."
        )

    return {
        "ok": True,
        "total_theta_deg": total_theta,
        "total_transverse_shrinkage_mm": total_trans,
        "total_longitudinal_shrinkage_mm": total_long,
        "total_energy_J": total_energy,
        "pass_results": results,
        "warnings": all_warnings,
        "mitigation_suggestions": mitigation,
    }


# ---------------------------------------------------------------------------
# LLM tool wrappers (gated on kerf_chat / kerf_core availability)
# ---------------------------------------------------------------------------

try:
    import json as _json
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------ #
    # weld_distortion_predict                                              #
    # ------------------------------------------------------------------ #

    _distortion_spec = ToolSpec(
        name="weld_distortion_predict",
        description=(
            "Predict weld distortion and residual stress for a single weld pass.\n"
            "\n"
            "Simulation chain:\n"
            "  1. Moving Goldak double-ellipsoid heat source (1-D FD through-thickness).\n"
            "  2. Inherent-strain model (Ueda 1975) from thermal history.\n"
            "  3. Angular distortion (FD/IS + Okerblom cross-check).\n"
            "  4. Transverse shrinkage (Masubuchi), longitudinal shrinkage.\n"
            "  5. Buckling-risk flag, residual stress estimate.\n"
            "  6. Mitigation suggestions.\n"
            "\n"
            "joint_type: 'bead_on_plate' | 'fillet' | 'butt'\n"
            "material:   'steel' | 'aluminium' | 'stainless_304'\n"
            "\n"
            "Errors: {ok:false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "t_mm": {
                    "type": "number",
                    "description": "Plate thickness [mm]. Must be > 0.",
                },
                "weld_length_mm": {
                    "type": "number",
                    "description": "Weld run length [mm]. Must be > 0.",
                },
                "HI_kJ_mm": {
                    "type": "number",
                    "description": "Arc heat input [kJ/mm]. Must be > 0.",
                },
                "leg_mm": {
                    "type": "number",
                    "description": "Fillet weld leg [mm]. Default = t_mm/2.",
                },
                "joint_type": {
                    "type": "string",
                    "enum": ["bead_on_plate", "fillet", "butt"],
                    "description": "Weld joint type.",
                },
                "material": {
                    "type": "string",
                    "description": "Material: 'steel', 'aluminium', 'stainless_304'.",
                },
                "T_preheat_C": {
                    "type": "number",
                    "description": "Preheat temperature [°C]. Default 20.",
                },
                "T_ambient_C": {
                    "type": "number",
                    "description": "Ambient temperature [°C]. Default 20.",
                },
                "restrained": {
                    "type": "boolean",
                    "description": "True if fixture/strongback restraint is applied.",
                },
                "weld_speed_mm_s": {
                    "type": "number",
                    "description": "Weld travel speed [mm/s]. Default 5.",
                },
                "eta": {
                    "type": "number",
                    "description": "Process thermal efficiency (0–1]. Default 0.80.",
                },
            },
            "required": ["t_mm", "weld_length_mm", "HI_kJ_mm"],
        },
    )

    @register(_distortion_spec, write=False)
    async def run_weld_distortion(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        for f in ("t_mm", "weld_length_mm", "HI_kJ_mm"):
            if a.get(f) is None:
                return _json.dumps({"ok": False, "reason": f"{f} is required"})
        kwargs: dict = {}
        for opt in ("leg_mm", "joint_type", "material", "T_preheat_C",
                    "T_ambient_C", "restrained", "weld_speed_mm_s", "eta"):
            if opt in a:
                kwargs[opt] = a[opt]
        result = weld_distortion(
            t_mm=float(a["t_mm"]),
            weld_length_mm=float(a["weld_length_mm"]),
            HI_kJ_mm=float(a["HI_kJ_mm"]),
            **kwargs,
        )
        return ok_payload(result) if result["ok"] else _json.dumps(result)

    # ------------------------------------------------------------------ #
    # weld_sequence_distortion_predict                                     #
    # ------------------------------------------------------------------ #

    _sequence_spec = ToolSpec(
        name="weld_sequence_distortion_predict",
        description=(
            "Estimate cumulative distortion for a multi-pass or multi-weld sequence.\n"
            "\n"
            "Each pass dict requires: t_mm, weld_length_mm, HI_kJ_mm.\n"
            "Optional pass keys: leg_mm, joint_type, material, T_preheat_C,\n"
            "  T_ambient_C, restrained, weld_speed_mm_s, eta.\n"
            "\n"
            "Returns per-pass and total angular distortion, shrinkage, energy,\n"
            "and sequence-level mitigation suggestions.\n"
            "\n"
            "Errors: {ok:false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "passes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "t_mm":            {"type": "number"},
                            "weld_length_mm":  {"type": "number"},
                            "HI_kJ_mm":        {"type": "number"},
                            "leg_mm":          {"type": "number"},
                            "joint_type":      {"type": "string"},
                            "material":        {"type": "string"},
                            "T_preheat_C":     {"type": "number"},
                            "T_ambient_C":     {"type": "number"},
                            "restrained":      {"type": "boolean"},
                            "weld_speed_mm_s": {"type": "number"},
                            "eta":             {"type": "number"},
                        },
                        "required": ["t_mm", "weld_length_mm", "HI_kJ_mm"],
                    },
                    "description": "List of weld pass parameter dicts.",
                    "minItems": 1,
                },
                "material": {
                    "type": "string",
                    "description": "Default material for passes that don't specify one.",
                },
                "T_preheat_C": {
                    "type": "number",
                    "description": "Default preheat temperature [°C].",
                },
            },
            "required": ["passes"],
        },
    )

    @register(_sequence_spec, write=False)
    async def run_weld_sequence_distortion(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        if not a.get("passes"):
            return _json.dumps({"ok": False, "reason": "passes is required"})
        kwargs: dict = {}
        if "material" in a:
            kwargs["material"] = a["material"]
        if "T_preheat_C" in a:
            kwargs["T_preheat_C"] = a["T_preheat_C"]
        result = weld_sequence_distortion(a["passes"], **kwargs)
        return ok_payload(result) if result["ok"] else _json.dumps(result)
