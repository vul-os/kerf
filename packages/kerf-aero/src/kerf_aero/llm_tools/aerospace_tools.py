"""
kerf_aero.llm_tools.aerospace_tools — LLM registry for aerospace simulation.

Each tool is a plain Python function that:
  - Accepts typed arguments (scalars, lists, strings)
  - Returns a JSON-serializable dict
  - Raises ValueError with a descriptive message on invalid input
  - Never raises on computation errors (wraps in ok/error dict)

Tools
-----
aero_airfoil_coords(name)
aero_airfoil_polar(name, alpha_min, alpha_max, step)
aero_vlm_wing(span, root_chord, tip_chord, sweep_deg, alpha_deg)
aero_orbital_elements_to_state(a, e, i, raan, argp, true_anomaly)
aero_hohmann_transfer(r1, r2, mu)
aero_lambert_solve(r1, r2, tof)
aero_rocket_dv(mass_ratio, isp)
aero_cea_lite(propellant, oxidizer, of_ratio, chamber_pressure)
aero_atmosphere(altitude_km)
aero_attitude_propagate(quaternion, omega_body, duration, dt)
aero_thermal_steady_state(nodes_json, links_json)
aero_material_lookup(name)
aero_flutter_typical_section(b, a, x_alpha, r_alpha, omega_h, omega_alpha, mu, rho, v_min, v_max, n_v, zeta_h, zeta_alpha)
aero_reentry_heat_flux(velocity_m_s, altitude_km, nose_radius_m, include_radiative)
aero_sixdof_simulate(mass_kg, ixx, iyy, izz, ixz, state0, force_model_const, duration, dt)
aero_staging(stages, total_delta_v, n_stages, isp_per_stage, payload_mass, structural_fraction)

References
----------
Katz & Plotkin, "Low-Speed Aerodynamics", 2nd ed.
Bate, Mueller & White, "Fundamentals of Astrodynamics", Dover 1971.
Sutton & Biblarz, "Rocket Propulsion Elements", 9th ed.
NOAA/NASA/USAF, "U.S. Standard Atmosphere 1976".
Gilmore, "Spacecraft Thermal Control Handbook", 2nd ed., Aerospace Press 2002.
Bisplinghoff, Ashley & Halfman, "Aeroelasticity", Dover 1955.
Sutton & Graves, "A general stagnation-point convective heating equation", NASA TR R-376, 1971.
Stevens & Lewis, "Aircraft Simulation and Systems", 3rd ed.
"""

from __future__ import annotations

import math
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Lazy subpackage imports (try/except per brief requirement)
# ---------------------------------------------------------------------------

try:
    from kerf_aero.airfoils import naca4, naca5, selig_load, SELIG_SLUGS
    _AIRFOILS_OK = True
except ImportError:
    _AIRFOILS_OK = False

try:
    from kerf_aero.panel_2d import panel_solve
    _PANEL_OK = True
except ImportError:
    _PANEL_OK = False

try:
    from kerf_aero.panel_2d_viscous import panel_solve_viscous
    _VISCOUS_OK = True
except ImportError:
    _VISCOUS_OK = False

try:
    from kerf_aero.vlm import vlm_wing as _vlm_wing
    _VLM_OK = True
except ImportError:
    _VLM_OK = False

try:
    from kerf_aero.orbital.kepler import (
        KeplerianElements,
        elements_to_state,
        MU_EARTH,
    )
    _KEPLER_OK = True
except ImportError:
    _KEPLER_OK = False

try:
    from kerf_aero.orbital.transfers import hohmann_delta_v
    _TRANSFERS_OK = True
except ImportError:
    _TRANSFERS_OK = False

try:
    from kerf_aero.orbital.lambert import lambert_izzo
    _LAMBERT_OK = True
except ImportError:
    _LAMBERT_OK = False

try:
    from kerf_aero.propulsion.rocket_eq import delta_v as _tsiolkovsky, G0
    _ROCKET_OK = True
except ImportError:
    _ROCKET_OK = False
    G0 = 9.80665

try:
    from kerf_aero.propulsion.cea_lite import cea_lite as _cea_lite
    _CEA_OK = True
except ImportError:
    _CEA_OK = False

try:
    from kerf_aero.flight_dynamics.atmosphere import atmosphere as _atmosphere
    _ATMO_OK = True
except ImportError:
    _ATMO_OK = False

try:
    from kerf_aero.adcs.attitude import propagate as _propagate_attitude
    _ADCS_OK = True
except ImportError:
    _ADCS_OK = False

try:
    from kerf_aero.thermal.network import (
        ThermalNetwork,
        Node,
        ConductiveLink,
        RadiativeLink,
    )
    _THERMAL_OK = True
except ImportError:
    _THERMAL_OK = False

try:
    import numpy as np
    _NP_OK = True
except ImportError:
    _NP_OK = False

try:
    from kerf_aero.drag_estimate import (
        Body3D,
        estimate_drag_coefficient as _estimate_drag_coefficient,
    )
    _DRAG_OK = True
except ImportError:
    _DRAG_OK = False

# ---------------------------------------------------------------------------
# Aerospace materials database (self-contained, no external deps)
# ---------------------------------------------------------------------------

_MATERIALS_DB: dict[str, dict[str, Any]] = {
    # Aluminium alloys
    "al2024-t3": {
        "name": "Aluminium 2024-T3",
        "density_kg_m3": 2780.0,
        "youngs_modulus_gpa": 73.1,
        "yield_strength_mpa": 345.0,
        "uts_mpa": 483.0,
        "thermal_conductivity_w_mk": 121.0,
        "specific_heat_j_kgk": 875.0,
        "cte_per_k": 23.2e-6,
        "poisson": 0.33,
        "max_service_temp_c": 175.0,
        "category": "aluminium",
        "uses": "Fuselage skins, wing spars, structural sheet metal",
    },
    "al6061-t6": {
        "name": "Aluminium 6061-T6",
        "density_kg_m3": 2700.0,
        "youngs_modulus_gpa": 68.9,
        "yield_strength_mpa": 276.0,
        "uts_mpa": 310.0,
        "thermal_conductivity_w_mk": 167.0,
        "specific_heat_j_kgk": 896.0,
        "cte_per_k": 23.6e-6,
        "poisson": 0.33,
        "max_service_temp_c": 150.0,
        "category": "aluminium",
        "uses": "General structural, extrusions, machined brackets",
    },
    "al7075-t6": {
        "name": "Aluminium 7075-T6",
        "density_kg_m3": 2810.0,
        "youngs_modulus_gpa": 71.7,
        "yield_strength_mpa": 503.0,
        "uts_mpa": 572.0,
        "thermal_conductivity_w_mk": 130.0,
        "specific_heat_j_kgk": 960.0,
        "cte_per_k": 23.6e-6,
        "poisson": 0.33,
        "max_service_temp_c": 125.0,
        "category": "aluminium",
        "uses": "High-strength airframe: wing spars, ribs, fittings",
    },
    # Titanium alloys
    "ti-6al-4v": {
        "name": "Titanium Ti-6Al-4V",
        "density_kg_m3": 4430.0,
        "youngs_modulus_gpa": 113.8,
        "yield_strength_mpa": 880.0,
        "uts_mpa": 950.0,
        "thermal_conductivity_w_mk": 6.7,
        "specific_heat_j_kgk": 526.0,
        "cte_per_k": 8.6e-6,
        "poisson": 0.342,
        "max_service_temp_c": 315.0,
        "category": "titanium",
        "uses": "Fasteners, fan blades, structural fittings, nacelles",
    },
    # Steels
    "4340-steel": {
        "name": "AISI 4340 Steel (normalized)",
        "density_kg_m3": 7850.0,
        "youngs_modulus_gpa": 205.0,
        "yield_strength_mpa": 710.0,
        "uts_mpa": 1080.0,
        "thermal_conductivity_w_mk": 44.5,
        "specific_heat_j_kgk": 475.0,
        "cte_per_k": 12.3e-6,
        "poisson": 0.29,
        "max_service_temp_c": 400.0,
        "category": "steel",
        "uses": "Landing gear, shafts, high-load fittings",
    },
    # Composites
    "cfrp-ud-t300": {
        "name": "CFRP Unidirectional T300/Epoxy",
        "density_kg_m3": 1600.0,
        "youngs_modulus_gpa": 135.0,
        "yield_strength_mpa": None,
        "uts_mpa": 1500.0,
        "thermal_conductivity_w_mk": 5.0,
        "specific_heat_j_kgk": 900.0,
        "cte_per_k": 0.2e-6,
        "poisson": 0.25,
        "max_service_temp_c": 120.0,
        "category": "composite",
        "uses": "Wing skins, spars, pressure vessels, satellite structures",
        "note": "Longitudinal direction properties; transverse are ~10x weaker",
    },
    "cfrp-woven-t300": {
        "name": "CFRP Woven T300/Epoxy (0/90)",
        "density_kg_m3": 1550.0,
        "youngs_modulus_gpa": 70.0,
        "yield_strength_mpa": None,
        "uts_mpa": 700.0,
        "thermal_conductivity_w_mk": 5.0,
        "specific_heat_j_kgk": 900.0,
        "cte_per_k": 1.0e-6,
        "poisson": 0.05,
        "max_service_temp_c": 120.0,
        "category": "composite",
        "uses": "Panels, fairings, secondary structure",
    },
    "gfrp-e-glass": {
        "name": "GFRP E-Glass/Epoxy (woven)",
        "density_kg_m3": 1900.0,
        "youngs_modulus_gpa": 25.0,
        "yield_strength_mpa": None,
        "uts_mpa": 350.0,
        "thermal_conductivity_w_mk": 0.3,
        "specific_heat_j_kgk": 1200.0,
        "cte_per_k": 14.0e-6,
        "poisson": 0.14,
        "max_service_temp_c": 80.0,
        "category": "composite",
        "uses": "Radomes, fairings, non-structural panels",
    },
    # Superalloys
    "inconel-718": {
        "name": "Inconel 718 (solution + aged)",
        "density_kg_m3": 8190.0,
        "youngs_modulus_gpa": 200.0,
        "yield_strength_mpa": 1100.0,
        "uts_mpa": 1375.0,
        "thermal_conductivity_w_mk": 11.4,
        "specific_heat_j_kgk": 435.0,
        "cte_per_k": 13.0e-6,
        "poisson": 0.29,
        "max_service_temp_c": 650.0,
        "category": "superalloy",
        "uses": "Turbine discs, compressor blades, combustor liners, rocket engine parts",
    },
    "rene-41": {
        "name": "Rene 41 Nickel Superalloy",
        "density_kg_m3": 8250.0,
        "youngs_modulus_gpa": 220.0,
        "yield_strength_mpa": 930.0,
        "uts_mpa": 1420.0,
        "thermal_conductivity_w_mk": 12.2,
        "specific_heat_j_kgk": 450.0,
        "cte_per_k": 12.7e-6,
        "poisson": 0.30,
        "max_service_temp_c": 980.0,
        "category": "superalloy",
        "uses": "High-temperature turbine components, afterburner hardware",
    },
    # Thermal protection / ceramics
    "sic-cmc": {
        "name": "SiC/SiC Ceramic Matrix Composite",
        "density_kg_m3": 2800.0,
        "youngs_modulus_gpa": 200.0,
        "yield_strength_mpa": None,
        "uts_mpa": 350.0,
        "thermal_conductivity_w_mk": 15.0,
        "specific_heat_j_kgk": 750.0,
        "cte_per_k": 4.6e-6,
        "poisson": 0.20,
        "max_service_temp_c": 1200.0,
        "category": "cmc",
        "uses": "Turbine hot section, re-entry vehicle leading edges, combustors",
    },
    "ablator-pica": {
        "name": "PICA (Phenolic Impregnated Carbon Ablator)",
        "density_kg_m3": 270.0,
        "youngs_modulus_gpa": 0.15,
        "yield_strength_mpa": None,
        "uts_mpa": 2.0,
        "thermal_conductivity_w_mk": 0.27,
        "specific_heat_j_kgk": 1260.0,
        "cte_per_k": None,
        "poisson": None,
        "max_service_temp_c": None,
        "category": "tps",
        "uses": "Re-entry heat shields (Dragon, Stardust), hypersonic TPS",
        "note": "Properties degrade under ablation; values are pre-ablation",
    },
    # Specialty spacecraft materials
    "kapton-h": {
        "name": "Kapton H Polyimide Film",
        "density_kg_m3": 1420.0,
        "youngs_modulus_gpa": 2.5,
        "yield_strength_mpa": 69.0,
        "uts_mpa": 165.0,
        "thermal_conductivity_w_mk": 0.12,
        "specific_heat_j_kgk": 1090.0,
        "cte_per_k": 20.0e-6,
        "poisson": 0.35,
        "max_service_temp_c": 400.0,
        "category": "polymer",
        "uses": "Spacecraft MLI blankets, flexible circuits, solar array substrates",
    },
}

# Slug aliases for fuzzy lookup
_MAT_ALIASES: dict[str, str] = {
    "2024": "al2024-t3",
    "al2024": "al2024-t3",
    "2024t3": "al2024-t3",
    "6061": "al6061-t6",
    "al6061": "al6061-t6",
    "7075": "al7075-t6",
    "al7075": "al7075-t6",
    "ti6al4v": "ti-6al-4v",
    "titanium": "ti-6al-4v",
    "ti64": "ti-6al-4v",
    "4340": "4340-steel",
    "cfrp": "cfrp-ud-t300",
    "carbon-fibre": "cfrp-ud-t300",
    "carbon-fiber": "cfrp-ud-t300",
    "gfrp": "gfrp-e-glass",
    "fiberglass": "gfrp-e-glass",
    "fibreglass": "gfrp-e-glass",
    "inconel": "inconel-718",
    "in718": "inconel-718",
    "inconel718": "inconel-718",
    "rene41": "rene-41",
    "sic": "sic-cmc",
    "cmc": "sic-cmc",
    "pica": "ablator-pica",
    "ablator": "ablator-pica",
    "kapton": "kapton-h",
}


# ---------------------------------------------------------------------------
# Tool 1: aero_airfoil_coords
# ---------------------------------------------------------------------------

def aero_airfoil_coords(name: str) -> dict:
    """
    Return (x, y) surface coordinates for a named airfoil.

    Input schema
    ------------
    name : str
        Airfoil identifier. Supports:
        - NACA 4-digit: "naca0012", "naca2412", "0012", "2412"
        - NACA 5-digit: "naca23012", "23012"
        - Selig catalogue slug: "e387", "s1223", "clarky", etc.
          (see kerf_aero.airfoils.SELIG_SLUGS for full list)

    Returns
    -------
    dict:
        name       : str   — normalised airfoil name
        n_points   : int   — number of coordinate points
        coords     : list of [x, y] pairs (chord-normalised, 0..1)
        source     : str   — coordinate origin ("NACA analytic" or "Selig DB")

    Example output
    --------------
    aero_airfoil_coords("naca0012") ->
    {
      "name": "naca0012",
      "n_points": 399,
      "coords": [[1.0, 0.0], [0.997, 0.001], ..., [1.0, 0.0]],
      "source": "NACA analytic"
    }

    Raises
    ------
    ValueError: if the airfoil name is not recognised.
    """
    if not _AIRFOILS_OK or not _NP_OK:
        raise ImportError("kerf_aero.airfoils or numpy not available")

    name_clean = name.strip().lower().replace(" ", "")

    # Try NACA 4-digit: "0012", "2412", "naca0012", "naca2412" etc.
    naca4_name = name_clean.replace("naca", "")
    if len(naca4_name) == 4 and naca4_name.isdigit():
        try:
            coords = naca4(naca4_name)
            return {
                "name": f"naca{naca4_name}",
                "n_points": len(coords),
                "coords": [[float(x), float(y)] for x, y in coords],
                "source": "NACA 4-digit analytic (TR-460)",
            }
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    # Try NACA 5-digit: "23012", "naca23012"
    naca5_name = name_clean.replace("naca", "")
    if len(naca5_name) == 5 and naca5_name.isdigit():
        try:
            coords = naca5(naca5_name)
            return {
                "name": f"naca{naca5_name}",
                "n_points": len(coords),
                "coords": [[float(x), float(y)] for x, y in coords],
                "source": "NACA 5-digit analytic (TR-537)",
            }
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    # Try Selig database slug
    slug = name_clean.replace("naca", "naca")
    try:
        coords = selig_load(slug)
        return {
            "name": slug,
            "n_points": len(coords),
            "coords": [[float(x), float(y)] for x, y in coords],
            "source": "Selig UIUC airfoil database",
        }
    except (KeyError, ValueError):
        pass

    # List available options to help the user
    known_naca = ["naca0006", "naca0009", "naca0012", "naca0015", "naca0018",
                  "naca2412", "naca4412", "naca23012"]
    selig_sample = list(SELIG_SLUGS)[:10] if _AIRFOILS_OK else []
    raise ValueError(
        f"Airfoil {name!r} not recognised. "
        f"Try NACA 4-digit (e.g. 'naca0012'), "
        f"NACA 5-digit (e.g. 'naca23012'), "
        f"or a Selig slug such as {selig_sample!r}. "
        f"Some known slugs: {known_naca}"
    )


# ---------------------------------------------------------------------------
# Tool 2: aero_airfoil_polar
# ---------------------------------------------------------------------------

def aero_airfoil_polar(
    name: str,
    alpha_min: float = -5.0,
    alpha_max: float = 15.0,
    step: float = 1.0,
    Re: float | None = None,
    n_crit: float = 9.0,
) -> dict:
    """
    Compute a CL/CD alpha sweep (polar) for a 2D airfoil.

    When *Re* is supplied the XFOIL-class viscous solver is used (Thwaites
    laminar BL + Head/Green turbulent BL + e^N transition + Squire-Young drag),
    returning physically realistic CL **and** CD as well as transition x/c.

    When *Re* is not supplied (or the viscous solve fails), the inviscid
    linear-vortex panel method is used and CD is set to zero (CD_wave only).

    Input schema
    ------------
    name      : str         — airfoil name (same as aero_airfoil_coords)
    alpha_min : float       — minimum angle of attack [deg] (default -5)
    alpha_max : float       — maximum angle of attack [deg] (default 15)
    step      : float       — alpha increment [deg] (default 1.0, min 0.1)
    Re        : float|None  — chord Reynolds number; enables viscous solve
    n_crit    : float       — e^N critical amplification factor (default 9)

    Returns
    -------
    dict:
        name          : str
        alpha         : list[float]  — angles of attack [deg]
        CL            : list[float]  — lift coefficients
        CD            : list[float]  — profile drag (viscous) or zeros (inviscid)
        CD_wave       : list[float]  — wave/induced drag (always zero for 2D panel)
        x_trans_upper : list[float|None] — upper-surface transition x/c (viscous only)
        x_trans_lower : list[float|None] — lower-surface transition x/c (viscous only)
        alpha_L0      : float        — zero-lift angle [deg] (interpolated)
        CL_alpha      : float        — lift curve slope [1/deg]
        method        : str
        viscous       : bool         — True when viscous solve was used

    Example output (viscous)
    ------------------------
    aero_airfoil_polar("naca0012", -5, 10, 2, Re=1e6) ->
    {
      "name": "naca0012",
      "alpha": [-5.0, -3.0, -1.0, 1.0, 3.0, 5.0, 7.0, 9.0],
      "CL": [-0.548, -0.326, -0.109, 0.109, 0.326, 0.543, 0.757, 0.966],
      "CD": [0.0082, 0.0079, 0.0078, 0.0078, 0.0079, 0.0083, 0.0094, 0.012],
      "CD_wave": [0.0, 0.0, ...],
      "x_trans_upper": [0.72, 0.68, ...],
      "x_trans_lower": [0.80, 0.82, ...],
      "alpha_L0": 0.0,
      "CL_alpha": 0.109,
      "method": "2D viscous panel (Thwaites+Head+e^N, Squire-Young drag)",
      "viscous": true
    }

    Raises
    ------
    ValueError: if name unknown, step < 0.1, or alpha range invalid.
    """
    if not _PANEL_OK:
        raise ImportError("kerf_aero.panel_2d not available")
    if step < 0.1:
        raise ValueError(f"step must be >= 0.1 deg, got {step}")
    if alpha_min >= alpha_max:
        raise ValueError(
            f"alpha_min ({alpha_min}) must be less than alpha_max ({alpha_max})"
        )

    # Get airfoil coordinates first (validates name and raises early)
    coord_result = aero_airfoil_coords(name)
    import numpy as np
    coords = np.array(coord_result["coords"])

    # Build alpha sweep
    alphas = []
    a = alpha_min
    while a <= alpha_max + 1e-9:
        alphas.append(round(a, 6))
        a += step

    use_viscous = Re is not None and _VISCOUS_OK

    cl_list: list[float] = []
    cd_list: list[float] = []
    x_trans_upper_list: list[float | None] = []
    x_trans_lower_list: list[float | None] = []
    viscous_used = False
    fallback_note: str | None = None

    for alpha in alphas:
        if use_viscous:
            try:
                res = panel_solve_viscous(coords, alpha, Re=float(Re), n_crit=n_crit)
                cl_list.append(round(float(res["CL"]), 6))
                cd_list.append(round(float(res["CD"]), 8))
                x_trans_upper_list.append(round(float(res["x_trans_upper"]), 4))
                x_trans_lower_list.append(round(float(res["x_trans_lower"]), 4))
                viscous_used = True
                continue
            except Exception as exc:
                # Viscous solve failed: fall back to inviscid for this alpha
                if fallback_note is None:
                    fallback_note = (
                        f"Viscous solve failed at alpha={alpha} ({exc}); "
                        "falling back to inviscid (CD=0) for this point"
                    )

        # Inviscid fallback
        try:
            res = panel_solve(coords, alpha)
            cl_list.append(round(float(res["CL"]), 6))
        except Exception:
            cl_list.append(float("nan"))
        cd_list.append(0.0)
        x_trans_upper_list.append(None)
        x_trans_lower_list.append(None)

    # Estimate CL_alpha and alpha_L0 by linear regression
    valid = [(a, cl) for a, cl in zip(alphas, cl_list) if math.isfinite(cl)]
    if len(valid) >= 2:
        a_arr = [v[0] for v in valid]
        cl_arr = [v[1] for v in valid]
        n = len(a_arr)
        sum_a = sum(a_arr)
        sum_cl = sum(cl_arr)
        sum_a2 = sum(a * a for a in a_arr)
        sum_acl = sum(a * cl for a, cl in zip(a_arr, cl_arr))
        denom = n * sum_a2 - sum_a ** 2
        if abs(denom) > 1e-12:
            cl_alpha = (n * sum_acl - sum_a * sum_cl) / denom
            intercept = (sum_cl - cl_alpha * sum_a) / n
            alpha_l0 = -intercept / cl_alpha if abs(cl_alpha) > 1e-9 else 0.0
        else:
            cl_alpha = 0.0
            alpha_l0 = 0.0
    else:
        cl_alpha = 0.0
        alpha_l0 = 0.0

    if viscous_used:
        method = "2D viscous panel (Thwaites+Head+e^N, Squire-Young drag)"
    else:
        method = "2D linear-vortex panel (inviscid, XFOIL class)"

    result = {
        "name": coord_result["name"],
        "alpha": alphas,
        "CL": cl_list,
        "CD": cd_list,
        "CD_wave": [0.0] * len(alphas),
        "x_trans_upper": x_trans_upper_list,
        "x_trans_lower": x_trans_lower_list,
        "alpha_L0": round(alpha_l0, 4),
        "CL_alpha": round(cl_alpha, 6),
        "method": method,
        "viscous": viscous_used,
        "Re": Re,
    }
    if fallback_note:
        result["note"] = fallback_note
    return result


# ---------------------------------------------------------------------------
# Tool 3: aero_vlm_wing
# ---------------------------------------------------------------------------

def aero_vlm_wing(
    span: float,
    root_chord: float,
    tip_chord: float | None = None,
    sweep_deg: float = 0.0,
    alpha_deg: float = 5.0,
) -> dict:
    """
    Compute steady aerodynamic coefficients of a finite wing using the
    Vortex Lattice Method (VLM) — Katz & Plotkin §13.

    Input schema
    ------------
    span       : float — full wing span [m] (> 0)
    root_chord : float — root chord length [m] (> 0)
    tip_chord  : float | None — tip chord [m]; None = same as root_chord
    sweep_deg  : float — leading-edge sweep angle [deg] (default 0)
    alpha_deg  : float — angle of attack [deg] (default 5)

    Returns
    -------
    dict:
        CL           : float — lift coefficient
        CDi          : float — induced drag coefficient
        Cm           : float — pitching moment coefficient
        AR           : float — aspect ratio b²/S
        span_efficiency : float — Oswald efficiency e = CL²/(π·AR·CDi)
        S_ref        : float — reference wing area [m²]
        n_panels     : int   — total number of VLM panels

    Example output
    --------------
    aero_vlm_wing(10.0, 1.5, 1.0, 20.0, 5.0) ->
    {
      "CL": 0.389,
      "CDi": 0.0061,
      "Cm": -0.124,
      "AR": 7.62,
      "span_efficiency": 0.913,
      "S_ref": 12.5,
      "n_panels": 80
    }

    Raises
    ------
    ValueError: if span <= 0, root_chord <= 0, or tip_chord < 0.
    """
    if not _VLM_OK:
        raise ImportError("kerf_aero.vlm not available")
    if span <= 0:
        raise ValueError(f"span must be > 0, got {span}")
    if root_chord <= 0:
        raise ValueError(f"root_chord must be > 0, got {root_chord}")
    if tip_chord is not None and tip_chord < 0:
        raise ValueError(f"tip_chord must be >= 0, got {tip_chord}")

    tc = tip_chord if tip_chord is not None else root_chord

    m_chord = 4   # chordwise panels
    n_span = 20   # spanwise panels

    try:
        result = _vlm_wing(
            span=float(span),
            root_chord=float(root_chord),
            tip_chord=float(tc),
            sweep_deg=float(sweep_deg),
            alpha_deg=float(alpha_deg),
            m_chord=m_chord,
            n_span=n_span,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    c_mean = 0.5 * (root_chord + tc)
    S_ref = span * c_mean
    AR = span**2 / S_ref

    CL = result["CL"]
    CDi = result["CDi"]

    # Oswald efficiency: e = CL² / (π * AR * CDi)
    if CDi > 1e-10 and AR > 0:
        e = CL**2 / (math.pi * AR * CDi)
        e = max(0.0, min(1.2, e))  # clamp to physical range
    else:
        e = 1.0

    return {
        "ok": True,
        "CL": round(CL, 6),
        "CDi": round(CDi, 6),
        "Cm": round(result["Cm"], 6),
        "AR": round(AR, 4),
        "span_efficiency": round(e, 4),
        "S_ref": round(S_ref, 4),
        "n_panels": m_chord * n_span,
        "inputs": {
            "span": span,
            "root_chord": root_chord,
            "tip_chord": tc,
            "sweep_deg": sweep_deg,
            "alpha_deg": alpha_deg,
        },
    }


# ---------------------------------------------------------------------------
# Tool 4: aero_orbital_elements_to_state
# ---------------------------------------------------------------------------

def aero_orbital_elements_to_state(
    a: float,
    e: float,
    i: float,
    raan: float,
    argp: float,
    true_anomaly: float,
    mu: float | None = None,
) -> dict:
    """
    Convert classical Keplerian orbital elements to a Cartesian state vector
    in the ECI (Earth-Centered Inertial) frame.

    Input schema
    ------------
    a            : float — semi-major axis [km] (> 0)
    e            : float — eccentricity (0 <= e < 1 for elliptic)
    i            : float — inclination [deg]
    raan         : float — right ascension of ascending node (Ω) [deg]
    argp         : float — argument of periapsis (ω) [deg]
    true_anomaly : float — true anomaly (ν) [deg]
    mu           : float | None — gravitational parameter [km³/s²];
                   default Earth = 398600.4418 km³/s²

    Returns
    -------
    dict:
        position_km    : [x, y, z] in km (ECI frame)
        velocity_km_s  : [vx, vy, vz] in km/s (ECI frame)
        radius_km      : scalar orbit radius at this point [km]
        speed_km_s     : scalar speed [km/s]
        altitude_km    : altitude above Earth surface (assuming R_earth=6371 km)
        orbital_period_s: orbital period [s]

    Example output
    --------------
    aero_orbital_elements_to_state(6778, 0.001, 51.6, 0, 0, 0) ->
    {
      "position_km": [6771.3, 0.0, 0.0],
      "velocity_km_s": [0.0, 7.673, 0.0],
      "radius_km": 6771.3,
      "speed_km_s": 7.673,
      "altitude_km": 400.3,
      "orbital_period_s": 5551.4
    }

    Raises
    ------
    ValueError: if a <= 0, e < 0 or e >= 1, or other invalid parameters.
    """
    if not _KEPLER_OK or not _NP_OK:
        raise ImportError("kerf_aero.orbital.kepler or numpy not available")
    if a <= 0:
        raise ValueError(f"Semi-major axis a must be > 0 km, got {a}")
    if e < 0 or e >= 1.0:
        raise ValueError(f"Eccentricity e must be in [0, 1), got {e}")

    import numpy as np

    _mu = mu if mu is not None else MU_EARTH

    elems = KeplerianElements(
        a=float(a),
        e=float(e),
        i=math.radians(float(i)),
        raan=math.radians(float(raan)),
        argp=math.radians(float(argp)),
        nu=math.radians(float(true_anomaly)),
    )

    try:
        r_vec, v_vec = elements_to_state(elems, mu=_mu)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    r_mag = float(np.linalg.norm(r_vec))
    v_mag = float(np.linalg.norm(v_vec))
    R_EARTH = 6371.0  # km

    period = 2.0 * math.pi * math.sqrt(a**3 / _mu)

    return {
        "ok": True,
        "position_km": [round(float(x), 4) for x in r_vec],
        "velocity_km_s": [round(float(x), 6) for x in v_vec],
        "radius_km": round(r_mag, 4),
        "speed_km_s": round(v_mag, 6),
        "altitude_km": round(r_mag - R_EARTH, 4),
        "orbital_period_s": round(period, 2),
        "inputs": {"a": a, "e": e, "i_deg": i, "raan_deg": raan,
                   "argp_deg": argp, "true_anomaly_deg": true_anomaly},
    }


# ---------------------------------------------------------------------------
# Tool 5: aero_hohmann_transfer
# ---------------------------------------------------------------------------

def aero_hohmann_transfer(
    r1: float,
    r2: float,
    mu: float | None = None,
) -> dict:
    """
    Calculate ΔV for a Hohmann transfer between two circular orbits.

    Input schema
    ------------
    r1  : float — initial circular orbit radius [km] (> 0)
    r2  : float — final circular orbit radius [km] (> 0)
    mu  : float | None — gravitational parameter [km³/s²];
          default Earth = 398600.4418 km³/s²

    Returns
    -------
    dict:
        dv1_km_s      : float — first burn ΔV [km/s]
        dv2_km_s      : float — second burn ΔV [km/s]
        dv_total_km_s : float — total ΔV [km/s]
        tof_s         : float — transfer time [s]
        tof_min       : float — transfer time [min]
        a_transfer_km : float — transfer ellipse semi-major axis [km]
        r_ratio       : float — r2/r1 (> 1 = ascending, < 1 = descending)

    Example output
    --------------
    aero_hohmann_transfer(6778, 42164) ->  # LEO to GEO
    {
      "dv1_km_s": 2.456,
      "dv2_km_s": 1.483,
      "dv_total_km_s": 3.939,
      "tof_s": 19027.3,
      "tof_min": 317.1,
      "a_transfer_km": 24471.0,
      "r_ratio": 6.22
    }

    Raises
    ------
    ValueError: if r1 <= 0 or r2 <= 0.
    """
    if not _TRANSFERS_OK:
        raise ImportError("kerf_aero.orbital.transfers not available")
    if r1 <= 0:
        raise ValueError(f"r1 must be > 0 km, got {r1}")
    if r2 <= 0:
        raise ValueError(f"r2 must be > 0 km, got {r2}")

    _mu = mu if mu is not None else MU_EARTH

    try:
        res = hohmann_delta_v(float(r1), float(r2), mu=_mu)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "dv1_km_s": round(res.dv1, 6),
        "dv2_km_s": round(res.dv2, 6),
        "dv_total_km_s": round(res.dv_total, 6),
        "tof_s": round(res.tof, 2),
        "tof_min": round(res.tof / 60.0, 2),
        "a_transfer_km": round(res.a_transfer, 4),
        "r_ratio": round(r2 / r1, 4),
        "inputs": {"r1_km": r1, "r2_km": r2, "mu_km3_s2": _mu},
    }


# ---------------------------------------------------------------------------
# Tool 6: aero_lambert_solve
# ---------------------------------------------------------------------------

def aero_lambert_solve(
    r1: list,
    r2: list,
    tof: float,
    mu: float | None = None,
    prograde: bool = True,
    revs: int = 0,
    branch: str = "left",
) -> dict:
    """
    Solve Lambert's problem: find the velocity vectors connecting two position
    vectors r1 and r2 in a given time-of-flight.

    Supports both single-revolution (revs=0, default) and multi-revolution
    (revs>=1) transfers.  Multi-revolution uses Izzo's 2010 algorithm.

    Input schema
    ------------
    r1       : [x, y, z] — initial position vector [km]
    r2       : [x, y, z] — final position vector [km]
    tof      : float — time of flight [s] (> 0)
    mu       : float | None — gravitational parameter [km³/s²]; default Earth
    prograde : bool — if True, assume prograde transfer (default True)
    revs     : int — number of complete revolutions (0 = single-rev, default 0)
    branch   : str — multi-rev branch: "left" (lower-energy) or "right"
                     (higher-energy); ignored for revs=0 (default "left")

    Returns
    -------
    dict:
        v1_km_s  : [vx, vy, vz] — departure velocity [km/s]
        v2_km_s  : [vx, vy, vz] — arrival velocity [km/s]
        dv1_km_s : float — |v1| magnitude [km/s]
        dv2_km_s : float — |v2| magnitude [km/s]
        tof_s    : float — time of flight used [s]
        revs     : int   — number of complete revolutions
        branch   : str   — branch selected (multi-rev only)

    Example output
    --------------
    aero_lambert_solve([7000,0,0], [0,7000,7000], 3600) ->
    {
      "v1_km_s": [-0.234, 5.891, 2.445],
      "v2_km_s": [-4.562, 1.234, 3.211],
      "dv1_km_s": 6.489,
      "dv2_km_s": 5.634,
      "tof_s": 3600.0,
      "revs": 0,
      "branch": ""
    }

    Raises
    ------
    ValueError: if r1/r2 are not length-3, tof <= 0, positions are collinear,
                or TOF is below the minimum for multi-rev.
    """
    if not _LAMBERT_OK or not _NP_OK:
        raise ImportError("kerf_aero.orbital.lambert or numpy not available")

    import numpy as np

    if len(r1) != 3:
        raise ValueError(f"r1 must be a length-3 vector, got length {len(r1)}")
    if len(r2) != 3:
        raise ValueError(f"r2 must be a length-3 vector, got length {len(r2)}")
    if tof <= 0:
        raise ValueError(f"tof must be > 0 s, got {tof}")
    if revs < 0:
        raise ValueError(f"revs must be >= 0, got {revs}")
    if branch not in ("left", "right", ""):
        raise ValueError(f"branch must be 'left' or 'right', got {branch!r}")

    _mu = mu if mu is not None else MU_EARTH

    r1_arr = np.array([float(x) for x in r1])
    r2_arr = np.array([float(x) for x in r2])

    _branch = branch if branch else "left"

    try:
        v1, v2 = lambert_izzo(
            r1_arr, r2_arr, float(tof), mu=_mu,
            prograde=prograde, revs=int(revs), branch=_branch,
        )
    except (ValueError, RuntimeError) as exc:
        raise ValueError(str(exc)) from exc
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "v1_km_s": [round(float(x), 6) for x in v1],
        "v2_km_s": [round(float(x), 6) for x in v2],
        "dv1_km_s": round(float(np.linalg.norm(v1)), 6),
        "dv2_km_s": round(float(np.linalg.norm(v2)), 6),
        "tof_s": float(tof),
        "prograde": prograde,
        "revs": int(revs),
        "branch": branch if revs > 0 else "",
    }


# ---------------------------------------------------------------------------
# Tool 7: aero_rocket_dv
# ---------------------------------------------------------------------------

def aero_rocket_dv(
    mass_ratio: float,
    isp: float,
) -> dict:
    """
    Compute delta-V from the Tsiolkovsky rocket equation.

    ΔV = Isp · g₀ · ln(m₀/mf)

    Input schema
    ------------
    mass_ratio : float — initial-to-final mass ratio m₀/mf (> 1 for positive ΔV)
    isp        : float — specific impulse [s] (> 0)

    Returns
    -------
    dict:
        delta_v_m_s   : float — ΔV [m/s]
        delta_v_km_s  : float — ΔV [km/s]
        ve_m_s        : float — effective exhaust velocity [m/s]
        propellant_fraction : float — propellant mass / initial mass
        isp           : float — specific impulse used [s]
        mass_ratio    : float — m0/mf

    Example output
    --------------
    aero_rocket_dv(4.0, 350) ->
    {
      "delta_v_m_s": 4771.0,
      "delta_v_km_s": 4.771,
      "ve_m_s": 3432.3,
      "propellant_fraction": 0.75,
      "isp": 350.0,
      "mass_ratio": 4.0
    }

    Raises
    ------
    ValueError: if mass_ratio <= 0 or isp <= 0.
    """
    if mass_ratio <= 0:
        raise ValueError(f"mass_ratio must be > 0, got {mass_ratio}")
    if isp <= 0:
        raise ValueError(f"isp must be > 0 s, got {isp}")
    if mass_ratio < 1.0:
        raise ValueError(
            f"mass_ratio = m0/mf must be >= 1.0 (final mass <= initial mass), got {mass_ratio}"
        )

    ve = isp * G0
    dv = ve * math.log(float(mass_ratio))
    prop_frac = 1.0 - 1.0 / mass_ratio

    return {
        "ok": True,
        "delta_v_m_s": round(dv, 3),
        "delta_v_km_s": round(dv / 1000.0, 6),
        "ve_m_s": round(ve, 3),
        "propellant_fraction": round(prop_frac, 6),
        "isp": float(isp),
        "mass_ratio": float(mass_ratio),
        "g0_m_s2": G0,
    }


# ---------------------------------------------------------------------------
# Tool 8: aero_cea_lite
# ---------------------------------------------------------------------------

def aero_cea_lite(
    propellant: str,
    oxidizer: str | None = None,
    of_ratio: float = 2.3,
    chamber_pressure: float = 70.0,
) -> dict:
    """
    Simplified chemical equilibrium analysis for canonical bipropellants.

    Supported combinations (case-insensitive):
      LOX/RP-1   — liquid oxygen / kerosene           OF ∈ [1.8, 3.2]
      LOX/LH2    — liquid oxygen / liquid hydrogen    OF ∈ [4.0, 8.0]
      N2O4/MMH   — nitrogen tetroxide / MMH           OF ∈ [1.2, 2.2]
      LOX/CH4    — liquid oxygen / methane            OF ∈ [2.5, 4.5]

    Input schema
    ------------
    propellant       : str   — propellant fuel name or combined "LOX/RP-1" string
    oxidizer         : str | None — oxidizer name; if None, propellant must be "FUEL/OX"
    of_ratio         : float — oxidizer-to-fuel mass ratio (> 0)
    chamber_pressure : float — chamber pressure [bar] (default 70 bar)

    Returns
    -------
    dict:
        propellant  : str   — canonical propellant pair name
        tc_k        : float — adiabatic chamber temperature [K]
        gamma       : float — effective ratio of specific heats
        c_star      : float — characteristic velocity c* [m/s]
        isp_vac     : float — vacuum specific impulse [s]
        isp_sl      : float — sea-level Isp [s]
        within_of_range : bool — whether OF is within the fitted range

    Example output
    --------------
    aero_cea_lite("LOX/RP-1", of_ratio=2.3, chamber_pressure=70) ->
    {
      "propellant": "LOX/RP-1",
      "tc_k": 3571.0,
      "gamma": 1.136,
      "c_star": 1789.0,
      "isp_vac": 350.2,
      "isp_sl": 311.4,
      "within_of_range": true
    }

    Raises
    ------
    ValueError: if propellant combination is unknown, of_ratio <= 0,
                or chamber_pressure <= 0.
    """
    if not _CEA_OK:
        raise ImportError("kerf_aero.propulsion.cea_lite not available")

    if of_ratio <= 0:
        raise ValueError(f"of_ratio must be > 0, got {of_ratio}")
    if chamber_pressure <= 0:
        raise ValueError(f"chamber_pressure must be > 0 bar, got {chamber_pressure}")

    # Build the propellant key
    if oxidizer is not None:
        prop_key = f"{oxidizer.upper()}/{propellant.upper()}"
        # Try both orders
        if prop_key not in ("LOX/RP-1", "LOX/LH2", "N2O4/MMH", "LOX/CH4"):
            prop_key = f"{propellant.upper()}/{oxidizer.upper()}"
    else:
        # propellant contains the slash
        prop_key = propellant

    result = _cea_lite(
        propellant=prop_key,
        of_ratio=float(of_ratio),
        pc_bar=float(chamber_pressure),
    )

    if not result.get("ok", False):
        reason = result.get("reason", "unknown error")
        available = ["LOX/RP-1", "LOX/LH2", "N2O4/MMH", "LOX/CH4"]
        raise ValueError(
            f"CEA-lite failed: {reason}. "
            f"Available propellant pairs: {available}"
        )

    return {
        "ok": True,
        "propellant": result["propellant"],
        "of_ratio": result["of_ratio"],
        "pc_bar": result["pc_bar"],
        "tc_k": round(result["tc_k"], 1),
        "gamma": round(result["gamma"], 4),
        "molar_mass_kg_mol": round(result["molar_mass"], 5),
        "c_star_m_s": round(result["c_star"], 2),
        "isp_vac_s": round(result["isp_vac"], 2),
        "isp_sl_s": round(result["isp_sl"], 2),
        "pe_over_pc": round(result["pe_over_pc"], 6),
        "exit_mach": round(result["exit_mach"], 4),
        "ae_over_at": result["ae_over_at"],
        "within_of_range": result["within_of_range"],
        "of_range": list(result["of_range"]),
    }


# ---------------------------------------------------------------------------
# Tool 9: aero_atmosphere
# ---------------------------------------------------------------------------

def aero_atmosphere(altitude_km: float) -> dict:
    """
    Compute U.S. Standard Atmosphere 1976 properties at a given altitude.

    Input schema
    ------------
    altitude_km : float — geometric altitude [km] (0 to 86 km)

    Returns
    -------
    dict:
        altitude_km        : float — input altitude [km]
        temperature_k      : float — temperature [K]
        pressure_pa        : float — pressure [Pa]
        pressure_hpa       : float — pressure [hPa / mbar]
        density_kg_m3      : float — density [kg/m³]
        speed_of_sound_m_s : float — speed of sound [m/s]
        viscosity_pa_s     : float — dynamic viscosity [Pa·s]
        layer              : str   — atmosphere layer name

    Example output
    --------------
    aero_atmosphere(10.0) ->
    {
      "altitude_km": 10.0,
      "temperature_k": 223.25,
      "pressure_pa": 26500.0,
      "pressure_hpa": 265.0,
      "density_kg_m3": 0.4135,
      "speed_of_sound_m_s": 299.5,
      "viscosity_pa_s": 1.458e-5,
      "layer": "Troposphere"
    }

    Raises
    ------
    ValueError: if altitude_km < 0 or altitude_km > 86.
    """
    if not _ATMO_OK:
        raise ImportError("kerf_aero.flight_dynamics.atmosphere not available")

    if altitude_km < 0:
        raise ValueError(f"altitude_km must be >= 0, got {altitude_km}")
    if altitude_km > 86.0:
        raise ValueError(
            f"altitude_km must be <= 86 km (model limit), got {altitude_km}"
        )

    try:
        state = _atmosphere(altitude_km * 1000.0, geometric=True)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    # Determine layer name
    alt_m = altitude_km * 1000.0
    if alt_m < 11000:
        layer = "Troposphere"
    elif alt_m < 20000:
        layer = "Tropopause"
    elif alt_m < 32000:
        layer = "Stratosphere (lower)"
    elif alt_m < 47000:
        layer = "Stratosphere (upper)"
    elif alt_m < 51000:
        layer = "Stratopause"
    elif alt_m < 71000:
        layer = "Mesosphere (lower)"
    else:
        layer = "Mesosphere (upper)"

    return {
        "ok": True,
        "altitude_km": altitude_km,
        "temperature_k": round(state.temperature_K, 3),
        "pressure_pa": round(state.pressure_Pa, 3),
        "pressure_hpa": round(state.pressure_Pa / 100.0, 4),
        "density_kg_m3": round(state.density_kg_m3, 6),
        "speed_of_sound_m_s": round(state.speed_of_sound_m_s, 3),
        "viscosity_pa_s": round(state.viscosity_Pa_s, 9),
        "layer": layer,
        "standard": "U.S. Standard Atmosphere 1976 (USSA76)",
    }


# ---------------------------------------------------------------------------
# Tool 10: aero_attitude_propagate
# ---------------------------------------------------------------------------

def aero_attitude_propagate(
    quaternion: list,
    omega_body: list,
    duration: float,
    dt: float = 0.1,
    inertia: list | None = None,
    torque: list | None = None,
) -> dict:
    """
    Propagate spacecraft attitude dynamics using Euler's rotation equation and
    quaternion kinematics (RK4 integration).

    Input schema
    ------------
    quaternion : [w, x, y, z] — initial unit quaternion (will be normalised)
    omega_body : [wx, wy, wz] — initial body angular velocity [rad/s]
    duration   : float — simulation duration [s] (> 0)
    dt         : float — integration time step [s] (default 0.1, >= 0.001)
    inertia    : [[Ixx,Ixy,Ixz],[Iyx,Iyy,Iyz],[Izx,Izy,Izz]] — 3×3 inertia
                 tensor [kg·m²]; default: unit sphere I = diag(1,1,1)
    torque     : [Tx, Ty, Tz] — constant body-frame torque [N·m]; default [0,0,0]

    Returns
    -------
    dict:
        q_initial   : [w,x,y,z] — normalised initial quaternion
        q_final     : [w,x,y,z] — final quaternion after propagation
        omega_final : [wx,wy,wz] — final angular velocity [rad/s]
        euler_final_deg: [roll, pitch, yaw] — final ZYX Euler angles [deg]
        n_steps     : int — number of integration steps
        duration_s  : float — actual propagation duration [s]

    Example output
    --------------
    aero_attitude_propagate([1,0,0,0], [0.1,0.05,0.0], 10.0) ->
    {
      "q_initial": [1.0, 0.0, 0.0, 0.0],
      "q_final": [0.878, 0.434, 0.186, 0.0],
      "omega_final": [0.1, 0.05, 0.0],
      "euler_final_deg": [49.8, 21.4, 0.0],
      "n_steps": 100,
      "duration_s": 10.0
    }

    Raises
    ------
    ValueError: if quaternion is not length 4, omega_body not length 3,
                duration <= 0, dt < 0.001, or inertia is not 3×3.
    """
    if not _ADCS_OK or not _NP_OK:
        raise ImportError("kerf_aero.adcs.attitude or numpy not available")

    import numpy as np

    if len(quaternion) != 4:
        raise ValueError(f"quaternion must be length 4 [w,x,y,z], got length {len(quaternion)}")
    if len(omega_body) != 3:
        raise ValueError(f"omega_body must be length 3 [wx,wy,wz], got length {len(omega_body)}")
    if duration <= 0:
        raise ValueError(f"duration must be > 0 s, got {duration}")
    if dt < 0.001:
        raise ValueError(f"dt must be >= 0.001 s, got {dt}")

    # Cap to avoid excessive computation
    max_steps = 10000
    n_steps_requested = int(math.ceil(duration / dt))
    if n_steps_requested > max_steps:
        raise ValueError(
            f"Too many steps: duration/dt = {n_steps_requested} > {max_steps}. "
            f"Increase dt or decrease duration."
        )

    q0 = np.array([float(x) for x in quaternion])
    qnorm = float(np.linalg.norm(q0))
    if qnorm < 1e-10:
        raise ValueError("quaternion must be non-zero")
    q0 = q0 / qnorm

    omega0 = np.array([float(x) for x in omega_body])

    # Inertia tensor
    if inertia is not None:
        I = np.array([[float(x) for x in row] for row in inertia])
        if I.shape != (3, 3):
            raise ValueError("inertia must be a 3×3 matrix")
    else:
        I = np.eye(3)

    # Torque
    torque_vec = np.array([float(x) for x in torque]) if torque else np.zeros(3)

    torque_fn = lambda t, q, omega: torque_vec  # noqa: E731

    try:
        from kerf_aero.adcs.attitude import qto_euler
        t_hist, q_hist, omega_hist = _propagate_attitude(
            q0=q0,
            omega0=omega0,
            I=I,
            torque_fn=torque_fn,
            t_span=float(duration),
            dt=float(dt),
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    q_final = q_hist[-1]
    omega_final = omega_hist[-1]

    from kerf_aero.adcs.attitude import qto_euler
    euler_rad = qto_euler(q_final)
    euler_deg = [math.degrees(float(x)) for x in euler_rad]

    return {
        "ok": True,
        "q_initial": [round(float(x), 6) for x in q0],
        "q_final": [round(float(x), 6) for x in q_final],
        "omega_final": [round(float(x), 6) for x in omega_final],
        "euler_final_deg": [round(x, 4) for x in euler_deg],
        "n_steps": len(t_hist) - 1,
        "duration_s": float(duration),
        "dt_s": float(dt),
    }


# ---------------------------------------------------------------------------
# Tool 11: aero_thermal_steady_state
# ---------------------------------------------------------------------------

def aero_thermal_steady_state(
    nodes_json: list,
    links_json: list,
) -> dict:
    """
    Solve a lumped thermal network for steady-state temperatures.

    The network consists of nodes (thermal masses / boundary conditions) and
    links (conductive or radiative heat paths).

    Input schema
    ------------
    nodes_json : list of node dicts, each with:
        node_id   : str   — unique identifier
        T         : float — initial/boundary temperature [K]
        Q_ext     : float — external heat input [W] (default 0)
        fixed     : bool  — if True, temperature is held fixed (BC) (default False)
        C         : float — thermal capacitance [J/K] (ignored in steady-state)

    links_json : list of link dicts, each with:
        type      : str   — "conductive" or "radiative"
        node_a    : str   — first node ID
        node_b    : str   — second node ID
        For conductive:
            conductance : float — k·A/L [W/K]
        For radiative:
            epsilon_eff : float — effective emissivity (0–1)
            area        : float — reference area [m²]
            view_factor : float — view factor F_{a→b} (0–1)

    Returns
    -------
    dict:
        temperatures : dict[str, float] — {node_id: T_steady [K]}
        heat_flows   : dict[str, float] — {node_id: Q_net [W]}
        converged    : bool

    Example output
    --------------
    nodes = [
      {"node_id": "panel", "T": 300, "Q_ext": 100},
      {"node_id": "space", "T": 3,   "fixed": True}
    ]
    links = [
      {"type": "radiative", "node_a": "panel", "node_b": "space",
       "epsilon_eff": 0.85, "area": 1.0, "view_factor": 1.0}
    ]
    aero_thermal_steady_state(nodes, links) ->
    {
      "temperatures": {"panel": 393.4, "space": 3.0},
      "heat_flows": {"panel": 0.0, "space": 0.0},
      "converged": true
    }

    Raises
    ------
    ValueError: if a link references an unknown node_id, required fields are
                missing, or link type is unrecognised.
    """
    if not _THERMAL_OK:
        raise ImportError("kerf_aero.thermal.network not available")

    net = ThermalNetwork()

    # Parse nodes
    node_ids = set()
    for i, nd in enumerate(nodes_json):
        if not isinstance(nd, dict):
            raise ValueError(f"nodes_json[{i}] must be a dict")
        nid = nd.get("node_id")
        if not nid:
            raise ValueError(f"nodes_json[{i}] missing 'node_id'")
        T = nd.get("T")
        if T is None:
            raise ValueError(f"nodes_json[{i}] ('{nid}') missing 'T' [K]")
        try:
            node = Node(
                node_id=str(nid),
                T=float(T),
                C=float(nd.get("C", 1.0)),
                Q_ext=float(nd.get("Q_ext", 0.0)),
                fixed=bool(nd.get("fixed", False)),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"nodes_json[{i}] invalid: {exc}") from exc
        net.add_node(node)
        node_ids.add(str(nid))

    # Parse links
    for i, lk in enumerate(links_json):
        if not isinstance(lk, dict):
            raise ValueError(f"links_json[{i}] must be a dict")
        ltype = str(lk.get("type", "conductive")).lower()
        node_a = lk.get("node_a")
        node_b = lk.get("node_b")
        if not node_a or not node_b:
            raise ValueError(f"links_json[{i}] must have 'node_a' and 'node_b'")
        if node_a not in node_ids:
            raise ValueError(f"links_json[{i}]: node_a '{node_a}' not in nodes_json")
        if node_b not in node_ids:
            raise ValueError(f"links_json[{i}]: node_b '{node_b}' not in nodes_json")

        if ltype == "conductive":
            cond = lk.get("conductance")
            if cond is None:
                raise ValueError(f"links_json[{i}] conductive link missing 'conductance' [W/K]")
            link = ConductiveLink(
                node_a=str(node_a),
                node_b=str(node_b),
                conductance=float(cond),
            )
        elif ltype == "radiative":
            for field in ("epsilon_eff", "area", "view_factor"):
                if field not in lk:
                    raise ValueError(f"links_json[{i}] radiative link missing '{field}'")
            link = RadiativeLink(
                node_a=str(node_a),
                node_b=str(node_b),
                epsilon_eff=float(lk["epsilon_eff"]),
                area=float(lk["area"]),
                view_factor=float(lk["view_factor"]),
            )
        else:
            raise ValueError(
                f"links_json[{i}]: unknown link type '{ltype}'. Use 'conductive' or 'radiative'."
            )
        net.add_link(link)

    try:
        temps = net.solve_steady_state()
        converged = True
    except RuntimeError:
        # Return current best estimate
        temps = net.temperatures()
        converged = False

    heat_flows = net.heat_flows()

    return {
        "ok": True,
        "converged": converged,
        "temperatures": {k: round(v, 4) for k, v in temps.items()},
        "heat_flows": {k: round(v, 4) for k, v in heat_flows.items()},
    }


# ---------------------------------------------------------------------------
# Tool 12: aero_material_lookup
# ---------------------------------------------------------------------------

def aero_material_lookup(name: str) -> dict:
    """
    Look up aerospace material properties from the built-in database.

    Input schema
    ------------
    name : str — material name or slug (case-insensitive, partial matching).
        Examples: "al2024-t3", "al7075", "titanium", "ti-6al-4v",
                  "cfrp", "inconel", "inconel-718", "pica", "kapton"

    Returns
    -------
    dict:
        name                  : str   — full material name
        category              : str   — material category
        density_kg_m3         : float — density [kg/m³]
        youngs_modulus_gpa    : float | None — Young's modulus [GPa]
        yield_strength_mpa    : float | None — 0.2% proof stress [MPa]
        uts_mpa               : float | None — ultimate tensile strength [MPa]
        thermal_conductivity  : float — k [W/m·K]
        specific_heat_j_kgk   : float — Cp [J/kg·K]
        cte_per_k             : float | None — thermal expansion [1/K]
        poisson               : float | None — Poisson's ratio
        max_service_temp_c    : float | None — maximum service temperature [°C]
        uses                  : str   — typical aerospace applications
        available_materials   : list  — all known slugs (shown on failure)

    Example output
    --------------
    aero_material_lookup("al7075") ->
    {
      "name": "Aluminium 7075-T6",
      "category": "aluminium",
      "density_kg_m3": 2810.0,
      "youngs_modulus_gpa": 71.7,
      "yield_strength_mpa": 503.0,
      "uts_mpa": 572.0,
      ...
    }

    Raises
    ------
    ValueError: if the material is not found. The error message lists available options.
    """
    name_clean = name.strip().lower().replace(" ", "-").replace("_", "-")

    # Direct slug lookup
    if name_clean in _MATERIALS_DB:
        entry = dict(_MATERIALS_DB[name_clean])
        entry["ok"] = True
        entry["slug"] = name_clean
        return entry

    # Alias lookup
    if name_clean in _MAT_ALIASES:
        slug = _MAT_ALIASES[name_clean]
        entry = dict(_MATERIALS_DB[slug])
        entry["ok"] = True
        entry["slug"] = slug
        return entry

    # Fuzzy substring match (first match wins)
    name_noclean = name.strip().lower()
    for slug, entry in _MATERIALS_DB.items():
        if name_noclean in slug or name_noclean in entry["name"].lower():
            result = dict(entry)
            result["ok"] = True
            result["slug"] = slug
            return result

    available = sorted(_MATERIALS_DB.keys())
    raise ValueError(
        f"Material {name!r} not found in aerospace database. "
        f"Available slugs: {available}. "
        f"Also accepts aliases like 'titanium', 'cfrp', 'inconel', '7075', etc."
    )


# ---------------------------------------------------------------------------
# Tool 13: aero_orbit_determination
# ---------------------------------------------------------------------------

def aero_orbit_determination(
    observations: list[dict],
    x0_apriori: list[float],
    include_j2: bool = False,
    max_iter: int = 20,
    tol_pos_km: float = 1e-6,
) -> dict:
    """
    Estimate a spacecraft orbit state from tracking observations via batch
    least-squares (Differential Correction / WLS OD).

    Algorithm: Vallado 2013 §10.6; Tapley, Schutz & Born 2004 §4.3.

    Input schema
    ------------
    observations : list of dicts, each with keys:
        t           float   — time since epoch t_0 [s], must be >= 0
        obs_type    str     — 'range', 'range_rate', or 'both'
        y           list    — observed values [km] or [km/s] or [km, km/s]
        sigma       list    — 1-sigma noise (same shape as y)
        station_eci list[3] — ground station position in ECI [km]
    x0_apriori : list[6] — a priori state [r_x, r_y, r_z (km), v_x, v_y, v_z (km/s)]
    include_j2 : bool   — include J2 oblateness in reference dynamics (default False)
    max_iter   : int    — maximum differential-correction iterations (default 20)
    tol_pos_km : float  — convergence tolerance on position component of δX [km]

    Returns
    -------
    dict:
        ok             : bool
        converged      : bool
        n_iter         : int
        x_estimated    : list[6]  — estimated state [r(3) km, v(3) km/s]
        position_error_km : float — ||δr|| at last iteration
        rms_residual   : float   — RMS post-fit residual
        covariance_trace : float — trace of 6×6 formal covariance matrix
        n_observations  : int
        warnings        : list[str]

    Raises
    ------
    ValueError: if observations are not time-ordered, empty, or x0_apriori is wrong shape.
    """
    try:
        import numpy as np
        from kerf_aero.orbital.orbit_determination import (
            Observation,
            batch_least_squares_od,
        )
    except ImportError as exc:
        raise ValueError(f"orbit determination module unavailable: {exc}") from exc

    if not observations:
        raise ValueError("observations must be a non-empty list")
    if len(x0_apriori) != 6:
        raise ValueError(f"x0_apriori must be length 6, got {len(x0_apriori)}")

    # Parse observations
    obs_list = []
    for i, od in enumerate(observations):
        try:
            t = float(od["t"])
            obs_type = str(od["obs_type"])
            y = np.asarray(od["y"], dtype=float)
            sigma = np.asarray(od["sigma"], dtype=float)
            sta = np.asarray(od["station_eci"], dtype=float)
            obs_list.append(Observation(t=t, obs_type=obs_type, y=y, sigma=sigma, station_eci=sta))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"observations[{i}]: {exc}") from exc

    x0 = np.asarray(x0_apriori, dtype=float)

    try:
        result = batch_least_squares_od(
            obs_list,
            x0,
            include_j2=include_j2,
            max_iter=max_iter,
            tol_pos_km=tol_pos_km,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "n_observations": len(obs_list),
        }

    warnings: list[str] = []
    if not result.converged:
        warnings.append(
            f"OD did not converge within {max_iter} iterations."
        )

    cov_trace = float(np.trace(result.covariance)) if result.covariance is not None else None

    # Position component of the estimated state
    x_est = result.state_epoch
    pos_norm = float(np.linalg.norm(x_est[:3]))

    return {
        "ok": True,
        "converged": result.converged,
        "n_iter": result.iterations,
        "x_estimated": [round(float(v), 6) for v in x_est],
        "position_norm_km": round(pos_norm, 4),
        "rms_residual": round(float(result.rms_residual), 8),
        "sigma_0": round(float(result.sigma_0), 6),
        "covariance_trace": round(cov_trace, 6) if cov_trace is not None else None,
        "n_observations": len(obs_list),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Tool 14: aero_estimate_drag
# ---------------------------------------------------------------------------

def aero_estimate_drag(
    body_type: str,
    dimensions: list,
    flow_direction: list | None = None,
    velocity_m_s: float = 10.0,
    fluid: str = "air_sea_level",
) -> dict:
    """
    Estimate the drag coefficient Cd of a 3D body using Hoerner 1965 empirical
    formulas (skin friction + form factor).

    DISCLAIMER: NOT certified.  Low-fidelity preliminary estimate only.
    Based on Hoerner 1965 "Fluid-Dynamic Drag" — errors of 20-50% are typical.
    Use wind tunnel or CFD for design validation.

    Input schema
    ------------
    body_type  : str  — one of: "sphere", "flat_plate", "ellipsoid"
    dimensions : list — shape-dependent parameters:
        "sphere":     [radius_m]
        "flat_plate": [length_m, width_m, thickness_m]
        "ellipsoid":  [semi_axis_a_m, semi_axis_b_m, semi_axis_c_m]
                      (a = streamwise, b = lateral, c = vertical)
    flow_direction : [dx, dy, dz] — flow direction vector (default [1, 0, 0])
    velocity_m_s   : float — free-stream speed [m/s] (default 10.0)
    fluid          : str   — one of:
                      'air_sea_level' (default), 'air_10km', 'air_20km',
                      'water_fresh_15c', 'water_salt_15c', 'water_fresh_25c'

    Returns
    -------
    dict:
        ok              : bool
        Cd_total        : float — total drag coefficient (frontal-area referenced)
        Cd_friction     : float — skin-friction component
        Cd_form         : float — pressure/form drag component
        Cf              : float — flat-plate skin friction coefficient
        form_factor     : float — Hoerner form factor FF
        Re              : float — Reynolds number (L = √frontal_area)
        frontal_area_m2 : float — projected frontal area [m²]
        wetted_area_m2  : float — total wetted area [m²]
        fineness_ratio  : float — body length / effective diameter
        method          : str
        disclaimer      : str

    Example output
    --------------
    aero_estimate_drag("sphere", [0.5], velocity_m_s=50.0) ->
    {
      "ok": true,
      "Cd_total": 0.139,
      "Cd_friction": 0.017,
      "Cd_form": 0.122,
      "Cf": 0.00432,
      "form_factor": 9.452,
      "Re": 1711175.0,
      "frontal_area_m2": 0.7854,
      "wetted_area_m2": 3.1416,
      "fineness_ratio": 1.0,
      "method": "Hoerner 1965 empirical (Schultz-Grunow skin friction + form factor)",
      "disclaimer": "Hoerner 1965 empirical formulas — NOT certified, ..."
    }

    Raises
    ------
    ValueError: if body_type is unrecognised, dimensions are wrong length/value,
                or fluid is unknown.
    """
    if not _DRAG_OK or not _NP_OK:
        raise ImportError("kerf_aero.drag_estimate or numpy not available")

    SUPPORTED = ("sphere", "flat_plate", "ellipsoid")
    if body_type not in SUPPORTED:
        raise ValueError(
            f"body_type must be one of {SUPPORTED}, got {body_type!r}"
        )

    fd = flow_direction if flow_direction is not None else [1, 0, 0]
    if len(fd) != 3:
        raise ValueError(f"flow_direction must be [dx, dy, dz] (length 3), got {fd}")

    # Build Body3D from simple parameters
    try:
        if body_type == "sphere":
            if len(dimensions) < 1:
                raise ValueError("sphere needs dimensions=[radius_m]")
            body = Body3D.sphere(radius=float(dimensions[0]))

        elif body_type == "flat_plate":
            if len(dimensions) < 3:
                raise ValueError("flat_plate needs dimensions=[length_m, width_m, thickness_m]")
            body = Body3D.flat_plate(
                length=float(dimensions[0]),
                width=float(dimensions[1]),
                thickness=float(dimensions[2]),
            )

        elif body_type == "ellipsoid":
            if len(dimensions) < 3:
                raise ValueError("ellipsoid needs dimensions=[a_m, b_m, c_m] (semi-axes)")
            body = Body3D.ellipsoid(
                a=float(dimensions[0]),
                b=float(dimensions[1]),
                c=float(dimensions[2]),
            )
    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc)) from exc

    try:
        result = _estimate_drag_coefficient(
            body=body,
            flow_direction=fd,
            velocity_m_s=float(velocity_m_s),
            fluid=str(fluid),
        )
    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc)) from exc
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    d = result.to_dict()
    d["body_type"] = body_type
    d["dimensions"] = dimensions
    d["flow_direction"] = [float(x) for x in fd]
    return d


# ---------------------------------------------------------------------------
# Lazy imports for new tools (Tools 15-18)
# ---------------------------------------------------------------------------

try:
    from kerf_aero.aeroelasticity import (
        TypicalSectionParams,
        typical_section_pk,
    )
    _AEROELASTIC_OK = True
except ImportError:
    _AEROELASTIC_OK = False

try:
    from kerf_aero.reentry.heat_flux_trajectory import (
        sutton_graves_heat_flux as _sg_heat_flux,
        total_heat_flux as _total_heat_flux,
    )
    _REENTRY_OK = True
except ImportError:
    _REENTRY_OK = False

try:
    from kerf_aero.flight_dynamics.sixdof import (
        RigidBody,
        Forces,
        integrate as _sixdof_integrate,
        level_flight_state,
        quat_to_euler,
        euler_to_quat,
    )
    _SIXDOF_OK = True
except ImportError:
    _SIXDOF_OK = False

try:
    from kerf_aero.propulsion.staging import (
        multistage_delta_v as _multistage_dv,
        optimal_delta_v_split as _optimal_dv_split,
    )
    _STAGING_OK = True
except ImportError:
    _STAGING_OK = False


# ---------------------------------------------------------------------------
# Tool 15: aero_flutter_typical_section
# ---------------------------------------------------------------------------

def aero_flutter_typical_section(
    b: float = 0.5,
    a: float = -0.2,
    x_alpha: float = 0.1,
    r_alpha: float = 0.5,
    omega_h: float = 10.0,
    omega_alpha: float = 20.0,
    mu: float = 20.0,
    rho: float = 1.225,
    v_min: float | None = None,
    v_max: float | None = None,
    n_v: int = 100,
    zeta_h: float = 0.0,
    zeta_alpha: float = 0.0,
) -> dict:
    """
    Compute V-g / V-f (flutter) curves for a 2-DOF typical-section aeroelastic model
    using the Theodorsen p-k method.

    The typical section has two degrees of freedom: plunge (h, bending) and
    pitch (alpha, torsion).  Theodorsen's unsteady aerodynamic theory (1935)
    with Hassig (1971) p-k iteration is used.

    Input schema
    ------------
    b          : float — wing semi-chord [m] (default 0.5)
    a          : float — elastic-axis position from midchord, non-dim
                         (a=0: midchord, a=-1: LE, a=1: TE; default -0.2)
    x_alpha    : float — CG–EA distance, non-dim (b units, positive aft; default 0.1)
    r_alpha    : float — radius of gyration about EA, non-dim (b units; default 0.5)
    omega_h    : float — plunge natural frequency [rad/s] (default 10.0)
    omega_alpha: float — torsion natural frequency [rad/s] (default 20.0)
    mu         : float — mass ratio m/(π·ρ·b²) (default 20)
    rho        : float — air density [kg/m³] (default 1.225 = sea level)
    v_min      : float | None — min velocity sweep [m/s]; default 1% of b·ω_α
    v_max      : float | None — max velocity sweep [m/s]; default 6× b·ω_α
    n_v        : int   — number of velocity points (default 100)
    zeta_h     : float — structural damping ratio, plunge (default 0)
    zeta_alpha : float — structural damping ratio, pitch (default 0)

    Returns
    -------
    dict:
        ok              : bool
        flutter_speed_m_s   : float — flutter speed U_F [m/s] (NaN if not found)
        flutter_speed_nd    : float — U_F / (b · ω_α) (non-dimensional flutter speed)
        flutter_freq_rad_s  : float — flutter frequency [rad/s]
        flutter_freq_hz     : float — flutter frequency [Hz]
        velocities_m_s      : list[float] — velocity sweep [m/s]
        damping_mode0       : list[float] — g = σ/ω for mode 0 (plunge branch)
        damping_mode1       : list[float] — g = σ/ω for mode 1 (torsion branch)
        freq_mode0_rad_s    : list[float] — modal frequency, mode 0
        freq_mode1_rad_s    : list[float] — modal frequency, mode 1
        method              : str
        reference           : str

    Example output
    --------------
    aero_flutter_typical_section(b=0.5, mu=20, omega_h=10, omega_alpha=20) ->
    {
      "flutter_speed_m_s": 21.3,
      "flutter_speed_nd": 2.13,
      "flutter_freq_rad_s": 14.8,
      "velocities_m_s": [0.1, ...],
      "damping_mode0": [-0.02, ...],
      "damping_mode1": [-0.05, ..., 0.0, ...]
    }

    Raises
    ------
    ValueError: if b <= 0, mu <= 0, omega_h <= 0, omega_alpha <= 0.

    References
    ----------
    Theodorsen (1935) NACA TR 496.
    Hassig (1971) J. Aircraft 8(10), 793-797.
    Bisplinghoff, Ashley & Halfman, "Aeroelasticity", Dover 1955, Ch.5.
    """
    if not _AEROELASTIC_OK or not _NP_OK:
        raise ImportError("kerf_aero.aeroelasticity or numpy not available")

    import numpy as np

    if b <= 0:
        raise ValueError(f"b (semi-chord) must be > 0 m, got {b}")
    if mu <= 0:
        raise ValueError(f"mu (mass ratio) must be > 0, got {mu}")
    if omega_h <= 0:
        raise ValueError(f"omega_h must be > 0 rad/s, got {omega_h}")
    if omega_alpha <= 0:
        raise ValueError(f"omega_alpha must be > 0 rad/s, got {omega_alpha}")
    if n_v < 5 or n_v > 2000:
        raise ValueError(f"n_v must be in [5, 2000], got {n_v}")

    params = TypicalSectionParams(
        b=float(b),
        a=float(a),
        x_alpha=float(x_alpha),
        r_alpha=float(r_alpha),
        omega_h=float(omega_h),
        omega_alpha=float(omega_alpha),
        mu=float(mu),
        rho=float(rho),
        zeta_h=float(zeta_h),
        zeta_alpha=float(zeta_alpha),
    )

    V_ref = b * omega_alpha
    v_lo = float(v_min) if v_min is not None else 0.01 * V_ref
    v_hi = float(v_max) if v_max is not None else 6.0 * V_ref

    if v_lo <= 0:
        v_lo = 0.01 * V_ref
    if v_hi <= v_lo:
        raise ValueError(f"v_max ({v_hi}) must be > v_min ({v_lo})")

    velocities = np.linspace(v_lo, v_hi, int(n_v))

    try:
        vg = typical_section_pk(params, velocities)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    U_F = float(vg["flutter_speed"])
    f_F = float(vg["flutter_freq"])
    U_F_nd = U_F / V_ref if math.isfinite(U_F) else float("nan")
    f_F_hz = f_F / (2.0 * math.pi) if math.isfinite(f_F) else float("nan")

    def _clean(arr: "np.ndarray") -> list:
        return [None if math.isnan(float(x)) else round(float(x), 6) for x in arr]

    return {
        "ok": True,
        "flutter_speed_m_s": round(U_F, 4) if math.isfinite(U_F) else None,
        "flutter_speed_nd": round(U_F_nd, 4) if math.isfinite(U_F_nd) else None,
        "flutter_freq_rad_s": round(f_F, 4) if math.isfinite(f_F) else None,
        "flutter_freq_hz": round(f_F_hz, 4) if math.isfinite(f_F_hz) else None,
        "velocities_m_s": [round(float(v), 4) for v in velocities],
        "damping_mode0": _clean(vg["damping"][:, 0]),
        "damping_mode1": _clean(vg["damping"][:, 1]),
        "freq_mode0_rad_s": _clean(vg["frequency"][:, 0]),
        "freq_mode1_rad_s": _clean(vg["frequency"][:, 1]),
        "inputs": {
            "b_m": b, "a": a, "x_alpha": x_alpha, "r_alpha": r_alpha,
            "omega_h_rad_s": omega_h, "omega_alpha_rad_s": omega_alpha,
            "mu": mu, "rho_kg_m3": rho, "zeta_h": zeta_h, "zeta_alpha": zeta_alpha,
        },
        "method": "Theodorsen p-k (Hassig 1971) with Hankel-function C(k)",
        "reference": "Bisplinghoff, Ashley & Halfman (1955); Theodorsen NACA TR 496 (1935)",
    }


# ---------------------------------------------------------------------------
# Tool 16: aero_reentry_heat_flux
# ---------------------------------------------------------------------------

def aero_reentry_heat_flux(
    velocity_m_s: float,
    altitude_km: float,
    nose_radius_m: float = 0.2,
    include_radiative: bool = True,
    trajectory_table: list | None = None,
) -> dict:
    """
    Compute stagnation-point heat flux for atmospheric re-entry using the
    Sutton-Graves convective correlation and Tauber-Sutton radiative estimate.

    Two modes:
    1. Point evaluation: provide velocity_m_s and altitude_km.
    2. Trajectory sweep: provide trajectory_table as a list of
       [altitude_km, velocity_m_s] pairs to get a heat-flux time history.

    Sutton-Graves correlation (NASA TR R-376, 1971):
        q_conv = k_SG * sqrt(rho / R_n) * V^3
        k_SG = 1.7415e-4 [W·s^0.5·kg^-0.5·m^-0.5]

    Tauber-Sutton radiative estimate (approximation, Earth air, V > 10 km/s):
        q_rad ≈ C * rho^1.22 * V^8.5 * R_n    (C = 4.736e4)

    Input schema
    ------------
    velocity_m_s      : float — free-stream velocity [m/s] (required for point mode)
    altitude_km       : float — altitude [km] (required for point mode)
    nose_radius_m     : float — vehicle nose radius [m] (default 0.2)
    include_radiative : bool  — add Tauber-Sutton radiative flux (default True)
    trajectory_table  : list | None — list of [altitude_km, velocity_m_s] pairs
                        for a trajectory sweep; overrides point-mode inputs

    Returns (point mode)
    --------------------
    dict:
        ok                  : bool
        altitude_km         : float
        velocity_m_s        : float
        density_kg_m3       : float — free-stream density from ISA model
        q_convective_W_m2   : float — Sutton-Graves convective flux [W/m²]
        q_radiative_W_m2    : float — Tauber-Sutton radiative flux [W/m²]
        q_total_W_m2        : float — total stagnation heat flux [W/m²]
        q_total_W_cm2       : float — total flux in W/cm² (=q/1e4)
        nose_radius_m       : float
        method              : str

    Returns (trajectory mode)
    -------------------------
    dict:
        ok           : bool
        n_points     : int
        trajectory   : list of dicts (altitude_km, velocity_m_s, q_total_W_m2, ...)

    Example output (point mode)
    ---------------------------
    aero_reentry_heat_flux(7800, 70) ->
    {
      "q_convective_W_m2": 235000.0,
      "q_total_W_m2": 235000.0,
      "q_total_W_cm2": 23.5
    }

    Raises
    ------
    ValueError: if velocity_m_s <= 0, altitude_km < 0 or > 120 km.

    References
    ----------
    Sutton & Graves, NASA TR R-376 (1971).
    Tauber & Sutton, J. Spacecraft Rockets 28(1), 1991.
    """
    if not _REENTRY_OK or not _ATMO_OK:
        raise ImportError("kerf_aero.reentry or kerf_aero.flight_dynamics.atmosphere not available")

    from kerf_aero.flight_dynamics.atmosphere import atmosphere as _atmosphere
    from kerf_aero.reentry.heat_flux_trajectory import (
        sutton_graves_heat_flux as _sg,
        radiative_heat_flux as _rad,
    )

    if nose_radius_m <= 0:
        raise ValueError(f"nose_radius_m must be > 0, got {nose_radius_m}")

    if trajectory_table is not None:
        # Trajectory sweep mode
        results = []
        for i, row in enumerate(trajectory_table):
            if len(row) < 2:
                raise ValueError(f"trajectory_table[{i}] must be [alt_km, vel_m_s]")
            alt_km = float(row[0])
            vel_ms = float(row[1])
            if alt_km < 0 or alt_km > 120:
                raise ValueError(f"trajectory_table[{i}] altitude {alt_km} km out of range [0, 120]")
            if vel_ms < 0:
                raise ValueError(f"trajectory_table[{i}] velocity {vel_ms} m/s must be >= 0")
            try:
                atm = _atmosphere(alt_km * 1000.0)
                rho = atm.density_kg_m3
            except Exception:
                rho = 1.225 * math.exp(-alt_km / 8.5)
            q_conv = _sg(vel_ms, rho, nose_radius_m)
            q_rad = 0.0
            if include_radiative and vel_ms > 10_000.0:
                q_rad = _rad(vel_ms, rho, nose_radius_m)
            q_tot = q_conv + q_rad
            results.append({
                "altitude_km": round(alt_km, 3),
                "velocity_m_s": round(vel_ms, 2),
                "density_kg_m3": round(rho, 8),
                "q_convective_W_m2": round(q_conv, 2),
                "q_radiative_W_m2": round(q_rad, 2),
                "q_total_W_m2": round(q_tot, 2),
                "q_total_W_cm2": round(q_tot / 1e4, 6),
            })
        return {
            "ok": True,
            "n_points": len(results),
            "nose_radius_m": nose_radius_m,
            "include_radiative": include_radiative,
            "trajectory": results,
        }

    # Point mode
    if velocity_m_s < 0:
        raise ValueError(f"velocity_m_s must be >= 0, got {velocity_m_s}")
    if altitude_km < 0 or altitude_km > 120:
        raise ValueError(f"altitude_km must be in [0, 120], got {altitude_km}")

    try:
        atm = _atmosphere(altitude_km * 1000.0)
        rho = atm.density_kg_m3
    except Exception:
        rho = 1.225 * math.exp(-altitude_km / 8.5)

    q_conv = _sg(velocity_m_s, rho, nose_radius_m)
    q_rad = 0.0
    if include_radiative and velocity_m_s > 10_000.0:
        q_rad = _rad(velocity_m_s, rho, nose_radius_m)
    q_tot = q_conv + q_rad

    return {
        "ok": True,
        "altitude_km": altitude_km,
        "velocity_m_s": velocity_m_s,
        "density_kg_m3": round(rho, 8),
        "q_convective_W_m2": round(q_conv, 2),
        "q_radiative_W_m2": round(q_rad, 2),
        "q_total_W_m2": round(q_tot, 2),
        "q_total_W_cm2": round(q_tot / 1e4, 6),
        "nose_radius_m": nose_radius_m,
        "include_radiative": include_radiative,
        "method": "Sutton-Graves convective (NASA TR R-376) + Tauber-Sutton radiative",
        "note": ("Radiative flux estimate valid above ~10 km/s; "
                 "Sutton-Graves ±15-20% for blunt bodies in Earth air."),
    }


# ---------------------------------------------------------------------------
# Tool 17: aero_sixdof_simulate
# ---------------------------------------------------------------------------

def aero_sixdof_simulate(
    mass_kg: float,
    ixx: float,
    iyy: float,
    izz: float,
    ixz: float = 0.0,
    state0: list | None = None,
    airspeed_m_s: float = 100.0,
    altitude_m: float = 1000.0,
    flight_path_angle_deg: float = 0.0,
    alpha_deg: float = 2.0,
    duration: float = 10.0,
    dt: float = 0.05,
    fx: float = 0.0,
    fy: float = 0.0,
    fz: float = 0.0,
    mx: float = 0.0,
    my: float = 0.0,
    mz: float = 0.0,
) -> dict:
    """
    Simulate 6-DOF rigid-body flight dynamics (NED frame, quaternion attitude).

    State vector: [x_N, y_E, z_D, u, v, w, q0, q1, q2, q3, p, q_ang, r] (13 elements).
    - x, y, z: NED position [m]
    - u, v, w: body-frame velocities [m/s]
    - q0..q3: body-to-Earth quaternion (scalar-first)
    - p, q_ang, r: body roll/pitch/yaw rates [rad/s]

    Gravity is applied internally from the quaternion attitude.
    External aerodynamic + thrust forces must be supplied as constants Fx, Fy, Fz
    (body-frame) and moments Mx, My, Mz (body-frame) — these are constant throughout
    the simulation.  For realistic flight, supply the aerodynamic forces trimmed to the
    given flight condition.

    Input schema
    ------------
    mass_kg  : float — vehicle mass [kg] (> 0)
    ixx      : float — roll inertia [kg·m²]
    iyy      : float — pitch inertia [kg·m²]
    izz      : float — yaw inertia [kg·m²]
    ixz      : float — cross inertia [kg·m²] (default 0)
    state0   : list[13] | None — initial state; if None, built from:
    airspeed_m_s         : float — initial airspeed [m/s] (default 100)
    altitude_m           : float — initial altitude [m] (default 1000)
    flight_path_angle_deg: float — initial FPA [°] (default 0 = level flight)
    alpha_deg            : float — initial angle of attack [°] (default 2)
    duration : float — simulation duration [s] (default 10)
    dt       : float — time step [s] (default 0.05, min 0.001)
    fx/fy/fz : float — body-frame applied force [N] (default 0)
    mx/my/mz : float — body-frame applied moment [N·m] (default 0)

    Returns
    -------
    dict:
        ok            : bool
        n_steps       : int
        duration_s    : float
        final_state   : dict — final 13-element state broken into named fields
        final_altitude_m      : float
        final_airspeed_m_s    : float
        final_euler_deg       : [roll, pitch, yaw] in degrees
        max_altitude_m        : float — max altitude reached
        min_altitude_m        : float — min altitude reached
        trajectory_summary    : list[dict] — sampled trajectory (every 10th step)

    Example output
    --------------
    aero_sixdof_simulate(5000, 10000, 40000, 45000, duration=30) ->
    {
      "n_steps": 600,
      "final_altitude_m": 1000.2,
      "final_airspeed_m_s": 100.1,
      "final_euler_deg": [0.0, 2.0, 0.0]
    }

    Raises
    ------
    ValueError: if mass_kg <= 0, dt < 0.001, or duration <= 0.
    """
    if not _SIXDOF_OK:
        raise ImportError("kerf_aero.flight_dynamics.sixdof not available")

    if mass_kg <= 0:
        raise ValueError(f"mass_kg must be > 0, got {mass_kg}")
    if dt < 0.001:
        raise ValueError(f"dt must be >= 0.001 s, got {dt}")
    if duration <= 0:
        raise ValueError(f"duration must be > 0 s, got {duration}")

    max_steps = 20000
    n_steps = int(math.ceil(duration / dt))
    if n_steps > max_steps:
        raise ValueError(
            f"Too many steps (duration/dt = {n_steps} > {max_steps}). "
            f"Increase dt or reduce duration."
        )

    body = RigidBody(
        mass_kg=float(mass_kg),
        Ixx=float(ixx),
        Iyy=float(iyy),
        Izz=float(izz),
        Ixz=float(ixz),
    )

    forces_const = Forces(
        Fx=float(fx), Fy=float(fy), Fz=float(fz),
        Mx=float(mx), My=float(my), Mz=float(mz),
    )

    def force_model(t, state):
        return forces_const

    # Build initial state
    if state0 is not None:
        if len(state0) != 13:
            raise ValueError(f"state0 must be length 13, got {len(state0)}")
        s0 = [float(x) for x in state0]
    else:
        s0 = level_flight_state(
            airspeed_m_s=float(airspeed_m_s),
            altitude_m=float(altitude_m),
            flight_path_angle_rad=math.radians(float(flight_path_angle_deg)),
            alpha_rad=math.radians(float(alpha_deg)),
        )

    try:
        times, states = _sixdof_integrate(
            t0=0.0,
            state0=s0,
            dt=float(dt),
            n_steps=n_steps,
            force_model=force_model,
            body=body,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    # Extract summary info
    altitudes = [-s[2] for s in states]  # z is Down, altitude = -z
    airspeeds = [math.sqrt(s[3]**2 + s[4]**2 + s[5]**2) for s in states]

    final = states[-1]
    phi, theta, psi = quat_to_euler(final[6], final[7], final[8], final[9])
    euler_deg = [
        round(math.degrees(phi), 4),
        round(math.degrees(theta), 4),
        round(math.degrees(psi), 4),
    ]

    # Sampled trajectory (every 10th step, max 200 points)
    step_stride = max(1, n_steps // 200)
    traj_summary = []
    for i in range(0, len(times), step_stride):
        s = states[i]
        traj_summary.append({
            "t_s": round(times[i], 4),
            "x_n_m": round(s[0], 2),
            "y_e_m": round(s[1], 2),
            "altitude_m": round(-s[2], 2),
            "airspeed_m_s": round(airspeeds[i], 3),
        })

    return {
        "ok": True,
        "n_steps": n_steps,
        "duration_s": float(duration),
        "dt_s": float(dt),
        "final_state": {
            "x_n_m": round(final[0], 3),
            "y_e_m": round(final[1], 3),
            "altitude_m": round(-final[2], 3),
            "u_m_s": round(final[3], 4),
            "v_m_s": round(final[4], 4),
            "w_m_s": round(final[5], 4),
            "quaternion": [round(final[k], 6) for k in range(6, 10)],
            "p_rad_s": round(final[10], 6),
            "q_rad_s": round(final[11], 6),
            "r_rad_s": round(final[12], 6),
        },
        "final_altitude_m": round(altitudes[-1], 3),
        "final_airspeed_m_s": round(airspeeds[-1], 4),
        "final_euler_deg": euler_deg,
        "max_altitude_m": round(max(altitudes), 3),
        "min_altitude_m": round(min(altitudes), 3),
        "trajectory_summary": traj_summary,
        "inputs": {
            "mass_kg": mass_kg,
            "ixx": ixx, "iyy": iyy, "izz": izz, "ixz": ixz,
            "fx_N": fx, "fy_N": fy, "fz_N": fz,
            "mx_Nm": mx, "my_Nm": my, "mz_Nm": mz,
        },
    }


# ---------------------------------------------------------------------------
# Tool 18: aero_staging
# ---------------------------------------------------------------------------

def aero_staging(
    stages: list | None = None,
    total_delta_v: float | None = None,
    n_stages: int = 2,
    isp_per_stage: float | list = 350.0,
    payload_mass: float = 1000.0,
    structural_fraction: float = 0.1,
) -> dict:
    """
    Multi-stage rocket ΔV budgeting and optimal staging analysis.

    Two modes:
    1. Explicit staging: provide stages = [{isp, m0, mf, name?}, ...].
       Returns exact ΔV per stage and total.
    2. Optimal split: provide total_delta_v, n_stages, isp_per_stage, payload_mass.
       Returns optimal ΔV allocation maximising payload fraction.

    Based on the Tsiolkovsky rocket equation:
        ΔV_stage = Isp · g₀ · ln(m₀/mf)

    Input schema (mode 1 — explicit)
    ---------------------------------
    stages : list of dicts, each with:
        isp   : float — specific impulse [s]
        m0    : float — initial (wet) mass of this stage [kg]
        mf    : float — final (dry) mass [kg]
        name  : str   — label (optional)

    Input schema (mode 2 — optimal split)
    --------------------------------------
    total_delta_v     : float — mission total ΔV [m/s]
    n_stages          : int   — number of stages (default 2)
    isp_per_stage     : float or list — Isp [s] per stage (default 350)
    payload_mass      : float — payload mass [kg] (default 1000)
    structural_fraction : float or list — structural fraction ε per stage (default 0.1)

    Returns
    -------
    dict:
        ok                  : bool
        total_delta_v_m_s   : float — sum of all stage ΔVs [m/s]
        total_delta_v_km_s  : float — [km/s]
        n_stages            : int
        stage_results       : list — per-stage breakdown
        payload_fraction    : float — payload / initial total wet mass (mode 2)
        total_wet_mass_kg   : float — initial total mass (mode 2)

    Example output (mode 2)
    -----------------------
    aero_staging(total_delta_v=9200, n_stages=2, isp_per_stage=350, payload_mass=1000) ->
    {
      "total_delta_v_m_s": 9200.0,
      "n_stages": 2,
      "payload_fraction": 0.042,
      "total_wet_mass_kg": 23800.0,
      "stage_results": [...]
    }

    Raises
    ------
    ValueError: if stages list is empty, masses invalid, or total_delta_v <= 0.

    References
    ----------
    Sutton & Biblarz, "Rocket Propulsion Elements", 9th ed., Chap. 4.
    Turner, "Rocket and Spacecraft Propulsion", 3rd ed., Chap. 2.
    """
    if not _STAGING_OK:
        raise ImportError("kerf_aero.propulsion.staging not available")

    if stages is not None:
        # Mode 1: explicit stages
        if not stages:
            raise ValueError("stages list must not be empty")
        result = _multistage_dv(stages)
        if not result.get("ok", False):
            raise ValueError(result.get("reason", "staging computation failed"))
        return {
            "ok": True,
            "mode": "explicit",
            "total_delta_v_m_s": round(result["total_delta_v_ms"], 3),
            "total_delta_v_km_s": round(result["total_delta_v_kms"], 6),
            "n_stages": result["n_stages"],
            "stage_results": result["stage_results"],
            "payload_mass_kg": result["payload_mass"],
        }

    # Mode 2: optimal split
    if total_delta_v is None:
        raise ValueError(
            "Provide either 'stages' (explicit mode) or "
            "'total_delta_v' + 'n_stages' (optimal-split mode)"
        )
    if total_delta_v <= 0:
        raise ValueError(f"total_delta_v must be > 0 m/s, got {total_delta_v}")
    if n_stages < 1:
        raise ValueError(f"n_stages must be >= 1, got {n_stages}")
    if payload_mass <= 0:
        raise ValueError(f"payload_mass must be > 0 kg, got {payload_mass}")

    result = _optimal_dv_split(
        total_delta_v=float(total_delta_v),
        n_stages=int(n_stages),
        isp_per_stage=isp_per_stage,
        structural_fraction_per_stage=structural_fraction,
        payload_mass=float(payload_mass),
    )

    if not result.get("ok", False):
        raise ValueError(result.get("reason", "optimal staging failed"))

    return {
        "ok": True,
        "mode": "optimal_split",
        "total_delta_v_m_s": round(float(total_delta_v), 3),
        "total_delta_v_km_s": round(float(total_delta_v) / 1000.0, 6),
        "n_stages": n_stages,
        "payload_fraction": round(result["payload_fraction"], 6),
        "total_wet_mass_kg": round(result["total_wet_mass"], 3),
        "optimal_dv_split_m_s": [round(v, 3) for v in result["optimal_delta_v_split"]],
        "stage_mass_ratios": [round(r, 4) for r in result["stage_mass_ratios"]],
        "stage_results": result["stage_results"],
        "equal_split": result.get("equal_split", False),
        "inputs": {
            "total_delta_v_m_s": total_delta_v,
            "n_stages": n_stages,
            "isp_per_stage": isp_per_stage,
            "payload_mass_kg": payload_mass,
            "structural_fraction": structural_fraction,
        },
    }


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

AEROSPACE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "aero_airfoil_coords",
        "fn": aero_airfoil_coords,
        "description": "Return chord-normalised (x,y) surface coordinates for a named airfoil (NACA 4/5-digit or Selig slug).",
    },
    {
        "name": "aero_airfoil_polar",
        "fn": aero_airfoil_polar,
        "description": "CL vs alpha sweep using the 2D linear-vortex panel method.",
    },
    {
        "name": "aero_vlm_wing",
        "fn": aero_vlm_wing,
        "description": "Finite-wing VLM analysis: CL, CDi, Cm, span efficiency.",
    },
    {
        "name": "aero_orbital_elements_to_state",
        "fn": aero_orbital_elements_to_state,
        "description": "Convert Keplerian orbital elements to ECI Cartesian state vector.",
    },
    {
        "name": "aero_hohmann_transfer",
        "fn": aero_hohmann_transfer,
        "description": "Compute ΔV for a two-burn Hohmann transfer between circular orbits.",
    },
    {
        "name": "aero_lambert_solve",
        "fn": aero_lambert_solve,
        "description": "Solve Lambert's problem: velocities connecting two positions in given TOF.",
    },
    {
        "name": "aero_rocket_dv",
        "fn": aero_rocket_dv,
        "description": "Tsiolkovsky ΔV = Isp·g0·ln(m0/mf) from mass ratio and Isp.",
    },
    {
        "name": "aero_cea_lite",
        "fn": aero_cea_lite,
        "description": "Simplified NASA CEA: Tc, γ, c*, Isp_vac for canonical bipropellants.",
    },
    {
        "name": "aero_atmosphere",
        "fn": aero_atmosphere,
        "description": "U.S. Standard Atmosphere 1976: T, P, ρ, speed of sound, viscosity at altitude.",
    },
    {
        "name": "aero_attitude_propagate",
        "fn": aero_attitude_propagate,
        "description": "Propagate spacecraft attitude (quaternion + ω) via Euler's equation + RK4.",
    },
    {
        "name": "aero_thermal_steady_state",
        "fn": aero_thermal_steady_state,
        "description": "Solve spacecraft lumped thermal network for steady-state temperatures.",
    },
    {
        "name": "aero_material_lookup",
        "fn": aero_material_lookup,
        "description": "Look up aerospace material properties (Al, Ti, steel, CFRP, superalloys, TPS).",
    },
    {
        "name": "aero_orbit_determination",
        "fn": aero_orbit_determination,
        "description": (
            "Batch least-squares orbit determination (Differential Correction) from "
            "radar tracking observations (range and/or range-rate). "
            "Estimates 6-DOF ECI state [r(3) km, v(3) km/s] at epoch."
        ),
    },
    {
        "name": "aero_estimate_drag",
        "fn": aero_estimate_drag,
        "description": (
            "Estimate 3D body drag coefficient Cd using Hoerner 1965 empirical formulas "
            "(Schultz-Grunow skin friction + form factor from fineness ratio). "
            "Supports sphere, flat_plate, and ellipsoid bodies. "
            "Returns Cd, breakdown (friction/form), Re, frontal area, wetted area. "
            "NOT certified — low-fidelity preliminary estimate (±20-50%). "
            "Ref: Hoerner 1965 'Fluid-Dynamic Drag' §4+§6; Anderson 2017 §3.18."
        ),
    },
    {
        "name": "aero_flutter_typical_section",
        "fn": aero_flutter_typical_section,
        "description": (
            "V-g / V-f flutter analysis for a 2-DOF typical-section aeroelastic model "
            "using Theodorsen's unsteady aerodynamics and the p-k iteration method. "
            "Returns flutter speed, flutter frequency, and full V-g / V-f curve arrays "
            "for both plunge (bending) and torsion modes. "
            "Ref: Theodorsen NACA TR 496 (1935); Bisplinghoff, Ashley & Halfman (1955)."
        ),
    },
    {
        "name": "aero_reentry_heat_flux",
        "fn": aero_reentry_heat_flux,
        "description": (
            "Stagnation-point heat flux for atmospheric re-entry via Sutton-Graves "
            "convective (NASA TR R-376, 1971) + Tauber-Sutton radiative correlation. "
            "Point mode: altitude + velocity → q_conv, q_rad, q_total [W/m²]. "
            "Trajectory mode: list of [alt_km, vel_m_s] pairs → heat-flux time history. "
            "Air density from US Standard Atmosphere. Typical use: TPS sizing, ablator selection."
        ),
    },
    {
        "name": "aero_sixdof_simulate",
        "fn": aero_sixdof_simulate,
        "description": (
            "6-DOF rigid-body flight dynamics simulation in NED frame with quaternion "
            "attitude (Stevens & Lewis). State: [x_N, y_E, z_D, u, v, w, q0..q3, p, q, r]. "
            "Gravity applied internally; user supplies constant body-frame aerodynamic/thrust "
            "forces + moments. Returns trajectory summary, final state, Euler angles, "
            "altitude extremes. RK4 integration."
        ),
    },
    {
        "name": "aero_staging",
        "fn": aero_staging,
        "description": (
            "Multi-stage rocket Tsiolkovsky ΔV budgeting. "
            "Explicit mode: provide stage masses + Isp → per-stage and total ΔV. "
            "Optimal-split mode: provide total ΔV + n_stages → optimal ΔV allocation "
            "maximising payload fraction with structural mass model. "
            "Ref: Sutton & Biblarz RPE 9th ed. §4; Turner 'Rocket Propulsion' §2."
        ),
    },
]
