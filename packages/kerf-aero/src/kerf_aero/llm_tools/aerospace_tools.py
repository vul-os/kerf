"""
kerf_aero.llm_tools.aerospace_tools — 12-tool LLM registry for aerospace simulation.

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

References
----------
Katz & Plotkin, "Low-Speed Aerodynamics", 2nd ed.
Bate, Mueller & White, "Fundamentals of Astrodynamics", Dover 1971.
Sutton & Biblarz, "Rocket Propulsion Elements", 9th ed.
NOAA/NASA/USAF, "U.S. Standard Atmosphere 1976".
Gilmore, "Spacecraft Thermal Control Handbook", 2nd ed., Aerospace Press 2002.
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
]
