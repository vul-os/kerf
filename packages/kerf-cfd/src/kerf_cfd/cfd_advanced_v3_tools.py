"""
LLM tool wrappers for Wave 12B: CFD advanced physics
(compressible / conjugate-HT / multiphase / marine).

Exposes four LLM-callable tools:

  cfd_compressible_shock     — normal shock relations + Mach analysis (Roe 1981)
  cfd_conjugate_ht           — conjugate fluid-solid heat transfer (Quarteroni-Valli)
  cfd_vof_mixture            — VOF mixture density query (Hirt-Nichols 1981)
  cfd_marine_resistance      — ship resistance prediction (Holtrop-Mennen 1982)
  cfd_marine_wave_spectrum   — JONSWAP/P-M wave spectrum statistics
  cfd_marine_wave_force      — Froude-Krylov + diffraction wave forces (Faltinsen 1990)

HONEST FLAG: Design-exploration accuracy only.  Not validated against
OpenFOAM, ANSYS, Star-CCM+, WAMIT, or physical model testing.

References
----------
Roe, P.L. (1981). J. Comput. Phys. 43, 357–372.
Anderson, J.D. (2003). "Modern Compressible Flow." McGraw-Hill.
Quarteroni, A., Valli, A. (1999). "Domain Decomposition Methods." Oxford.
Hirt, C., Nichols, B. (1981). J. Comput. Phys. 39, 201–225.
Holtrop, J., Mennen, G.G.J. (1982). Int. Shipbuilding Progress 29.
Faltinsen, O.M. (1990). "Sea Loads on Ships and Offshore Structures." Cambridge.

# Wave 12B: CFD advanced physics (compressible/conjugate-HT/multiphase/marine)
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cfd._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Tool: cfd_compressible_shock
# ---------------------------------------------------------------------------

_compressible_spec = ToolSpec(
    name="cfd_compressible_shock",
    description=(
        "Compressible flow analysis: normal shock relations (Rankine-Hugoniot) "
        "and Mach number from flow conditions.\n"
        "Inputs: upstream Mach number M1, optional heat-capacity ratio gamma.\n"
        "Returns: pressure ratio p2/p1, density ratio, temperature ratio, "
        "downstream Mach M2.\n"
        "Reference: Roe (1981), Anderson (2003) Modern Compressible Flow.\n"
        "DESIGN EXPLORATION ONLY — not validated against experimental data."
    ),
    input_schema={
        "type": "object",
        "required": ["M1"],
        "properties": {
            "M1": {
                "type": "number",
                "description": "Upstream Mach number (must be >= 1.0 for normal shock).",
                "minimum": 1.0,
            },
            "gamma": {
                "type": "number",
                "description": "Heat-capacity ratio (default 1.4 for air).",
                "default": 1.4,
            },
        },
    },
)


@register(_compressible_spec)
async def run_cfd_compressible_shock(params: dict, ctx: Any) -> str:
    try:
        from kerf_cfd.compressible.compressible_flow import normal_shock_relations
        M1 = float(params["M1"])
        gamma = float(params.get("gamma", 1.4))
        result = normal_shock_relations(M1, gamma)
        return ok_payload({
            "M1": M1,
            "gamma": gamma,
            **result,
            "note": (
                "Rankine-Hugoniot normal shock relations. "
                "Anderson (2003) §3.6. DESIGN EXPLORATION ONLY."
            ),
        })
    except Exception as exc:
        return err_payload(str(exc), "COMPRESSIBLE_ERROR")


# ---------------------------------------------------------------------------
# Tool: cfd_conjugate_ht
# ---------------------------------------------------------------------------

_conj_ht_spec = ToolSpec(
    name="cfd_conjugate_ht",
    description=(
        "Conjugate heat transfer coupling at a fluid-solid interface.\n"
        "Iterates Dirichlet-Neumann domain decomposition until interface "
        "temperatures converge (Quarteroni-Valli 1999).\n"
        "Inputs: hot fluid temperature, cold solid temperature, "
        "convection coefficient h, solid conductivity k.\n"
        "Returns: converged interface temperature and heat flux.\n"
        "DESIGN EXPLORATION ONLY."
    ),
    input_schema={
        "type": "object",
        "required": ["T_fluid_K", "T_solid_K", "h_W_m2K", "k_W_mK"],
        "properties": {
            "T_fluid_K": {"type": "number", "description": "Fluid bulk temperature [K]."},
            "T_solid_K": {"type": "number", "description": "Solid bulk temperature [K]."},
            "h_W_m2K": {"type": "number", "description": "Convection coefficient h [W/(m²·K)]."},
            "k_W_mK": {"type": "number", "description": "Solid thermal conductivity k [W/(m·K)]."},
            "n_iter": {"type": "integer", "default": 50, "description": "Max coupling iterations."},
        },
    },
)


@register(_conj_ht_spec)
async def run_cfd_conjugate_ht(params: dict, ctx: Any) -> str:
    try:
        from kerf_cfd.conjugate_ht.conjugate_solver import (
            FluidSolidInterface,
            couple_fluid_solid_temperature,
            heat_flux_at_interface,
        )
        T_f = float(params["T_fluid_K"])
        T_s = float(params["T_solid_K"])
        h = float(params["h_W_m2K"])
        k = float(params["k_W_mK"])
        n_iter = int(params.get("n_iter", 50))

        # Single interface cell
        interface = FluidSolidInterface(
            fluid_cell_ids=[0],
            solid_cell_ids=[0],
            face_pairs=[(0, 0)],
            face_areas=np.array([1.0]),
        )
        fluid_T, solid_T = couple_fluid_solid_temperature(
            np.array([T_f]),
            np.array([T_s]),
            interface,
            fluid_h=h,
            solid_k=k,
            n_iter=n_iter,
            relaxation=0.5,
        )
        T_f_conv = float(fluid_T[0])
        T_s_conv = float(solid_T[0])
        q = heat_flux_at_interface(T_f_conv, T_s_conv, h)

        return ok_payload({
            "T_fluid_converged_K": T_f_conv,
            "T_solid_converged_K": T_s_conv,
            "interface_heat_flux_W_m2": float(q),
            "note": (
                "Dirichlet-Neumann CHT coupling. "
                "Quarteroni-Valli (1999). DESIGN EXPLORATION ONLY."
            ),
        })
    except Exception as exc:
        return err_payload(str(exc), "CONJUGATE_HT_ERROR")


# ---------------------------------------------------------------------------
# Tool: cfd_vof_mixture
# ---------------------------------------------------------------------------

_vof_spec = ToolSpec(
    name="cfd_vof_mixture",
    description=(
        "Volume of Fluid (VOF) mixture property query.\n"
        "Given phase fractions α (0=air, 1=water) for N cells, "
        "returns mixture density per cell and total water volume fraction.\n"
        "Reference: Hirt-Nichols (1981). DESIGN EXPLORATION ONLY."
    ),
    input_schema={
        "type": "object",
        "required": ["alpha"],
        "properties": {
            "alpha": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Per-cell volume fraction of water (0–1).",
            },
            "rho_water": {"type": "number", "default": 1000.0},
            "rho_air": {"type": "number", "default": 1.225},
        },
    },
)


@register(_vof_spec)
async def run_cfd_vof_mixture(params: dict, ctx: Any) -> str:
    try:
        from kerf_cfd.multiphase.vof import VofState, mixture_density

        alpha = np.array(params["alpha"], dtype=float)
        ndim = 2
        velocity = np.zeros((len(alpha), ndim))
        state = VofState(
            alpha=alpha,
            velocity=velocity,
            rho_phase1=float(params.get("rho_water", 1000.0)),
            rho_phase2=float(params.get("rho_air", 1.225)),
        )
        rho_mix = mixture_density(state).tolist()
        return ok_payload({
            "mixture_density_kg_m3": rho_mix,
            "mean_alpha": float(np.mean(alpha)),
            "note": (
                "VOF mixture density ρ = α·ρ₁+(1-α)·ρ₂. "
                "Hirt-Nichols (1981). DESIGN EXPLORATION ONLY."
            ),
        })
    except Exception as exc:
        return err_payload(str(exc), "VOF_ERROR")


# ---------------------------------------------------------------------------
# Tool: cfd_marine_resistance
# ---------------------------------------------------------------------------

_marine_resist_spec = ToolSpec(
    name="cfd_marine_resistance",
    description=(
        "Ship resistance prediction using Holtrop-Mennen (1982/1984) method.\n"
        "Computes frictional (ITTC-1957), residuary (wave-making), and total "
        "calm-water resistance for a displacement ship at given speed.\n"
        "Valid: displacement hulls, Froude 0.1–0.5, Cb 0.55–0.85.\n"
        "Reference: Holtrop & Mennen (1982), ITTC (1957). DESIGN EXPLORATION ONLY."
    ),
    input_schema={
        "type": "object",
        "required": ["LWL_m", "beam_m", "draft_m", "displacement_tonnes",
                     "block_coeff", "prismatic_coeff", "speed_kn"],
        "properties": {
            "LWL_m": {"type": "number", "description": "Waterline length [m]."},
            "beam_m": {"type": "number", "description": "Maximum beam [m]."},
            "draft_m": {"type": "number", "description": "Design draft [m]."},
            "displacement_tonnes": {"type": "number", "description": "Volume displacement [tonnes]."},
            "block_coeff": {"type": "number", "description": "Block coefficient Cb."},
            "prismatic_coeff": {"type": "number", "description": "Prismatic coefficient Cp."},
            "speed_kn": {"type": "number", "description": "Ship speed [knots]."},
        },
    },
)


@register(_marine_resist_spec)
async def run_cfd_marine_resistance(params: dict, ctx: Any) -> str:
    try:
        from kerf_cfd.marine.hydrodynamics import ShipHull, holtrop_mennen_resistance

        hull = ShipHull(
            length_water_line_m=float(params["LWL_m"]),
            beam_m=float(params["beam_m"]),
            draft_m=float(params["draft_m"]),
            displacement_tonnes=float(params["displacement_tonnes"]),
            block_coefficient=float(params["block_coeff"]),
            prismatic_coefficient=float(params["prismatic_coeff"]),
        )
        V_ms = float(params["speed_kn"]) * 0.5144   # knots to m/s
        report = holtrop_mennen_resistance(hull, V_ms)

        return ok_payload({
            "velocity_m_s": report.velocity_m_s,
            "froude_number": report.froude_number,
            "frictional_resistance_kN": report.frictional_resistance_n / 1000.0,
            "residual_resistance_kN": report.residual_resistance_n / 1000.0,
            "total_resistance_kN": report.total_resistance_n / 1000.0,
            "effective_power_kW": report.effective_power_kw,
            "note": (
                "Holtrop-Mennen (1982/1984) + ITTC-1957 friction. "
                "DESIGN EXPLORATION ONLY — validate with model tests."
            ),
        })
    except Exception as exc:
        return err_payload(str(exc), "MARINE_RESISTANCE_ERROR")


# ---------------------------------------------------------------------------
# Tool: cfd_marine_wave_spectrum
# ---------------------------------------------------------------------------

_wave_spec_tool = ToolSpec(
    name="cfd_marine_wave_spectrum",
    description=(
        "Compute JONSWAP or Pierson-Moskowitz wave spectrum S(ω) and statistics.\n"
        "Returns spectral variance m₀ ≈ (Hs/4)², peak period, significant wave height.\n"
        "Reference: Hasselmann (1973) JONSWAP, ISSC (1964). DESIGN EXPLORATION ONLY."
    ),
    input_schema={
        "type": "object",
        "required": ["Hs_m", "Tp_s"],
        "properties": {
            "Hs_m": {"type": "number", "description": "Significant wave height [m]."},
            "Tp_s": {"type": "number", "description": "Peak wave period [s]."},
            "gamma": {"type": "number", "default": 3.3, "description": "JONSWAP peak factor (3.3 default; 1.0 = P-M)."},
            "n_freq": {"type": "integer", "default": 200, "description": "Number of frequency points."},
        },
    },
)


@register(_wave_spec_tool)
async def run_cfd_marine_wave_spectrum(params: dict, ctx: Any) -> str:
    try:
        from kerf_cfd.marine.hydrodynamics import jonswap_spectrum

        Hs = float(params["Hs_m"])
        Tp = float(params["Tp_s"])
        gamma = float(params.get("gamma", 3.3))
        n_freq = int(params.get("n_freq", 200))

        omega = np.linspace(0.1, 4.0 * 2.0 * np.pi / Tp, n_freq)
        S = jonswap_spectrum(omega, Hs, Tp, gamma)
        d_omega = omega[1] - omega[0]
        m0 = float(np.trapz(S, omega))
        Hs_computed = float(4.0 * np.sqrt(max(m0, 0.0)))

        return ok_payload({
            "Hs_input_m": Hs,
            "Tp_s": Tp,
            "gamma": gamma,
            "m0_variance_m2": m0,
            "Hs_from_spectrum_m": Hs_computed,
            "peak_omega_rad_s": float(2.0 * np.pi / Tp),
            "note": (
                "JONSWAP spectrum. Hasselmann (1973), ISSC (1964). DESIGN EXPLORATION ONLY."
            ),
        })
    except Exception as exc:
        return err_payload(str(exc), "WAVE_SPECTRUM_ERROR")


# ---------------------------------------------------------------------------
# Tool: cfd_marine_wave_force
# ---------------------------------------------------------------------------

_wave_force_spec = ToolSpec(
    name="cfd_marine_wave_force",
    description=(
        "Linear Froude-Krylov + diffraction wave forces on a ship hull.\n"
        "Computes surge, sway, heave exciting forces from regular wave.\n"
        "Reference: Faltinsen (1990) Sea Loads on Ships. DESIGN EXPLORATION ONLY."
    ),
    input_schema={
        "type": "object",
        "required": ["LWL_m", "beam_m", "draft_m", "displacement_tonnes",
                     "block_coeff", "prismatic_coeff", "Hs_m", "Tp_s"],
        "properties": {
            "LWL_m": {"type": "number"},
            "beam_m": {"type": "number"},
            "draft_m": {"type": "number"},
            "displacement_tonnes": {"type": "number"},
            "block_coeff": {"type": "number"},
            "prismatic_coeff": {"type": "number"},
            "Hs_m": {"type": "number", "description": "Significant wave height [m]."},
            "Tp_s": {"type": "number", "description": "Peak period [s]."},
            "direction_deg": {"type": "number", "default": 0.0},
            "depth_m": {"type": "number", "default": 100.0},
        },
    },
)


@register(_wave_force_spec)
async def run_cfd_marine_wave_force(params: dict, ctx: Any) -> str:
    try:
        from kerf_cfd.marine.hydrodynamics import ShipHull, WaveSpec, linear_wave_diffraction_force

        hull = ShipHull(
            length_water_line_m=float(params["LWL_m"]),
            beam_m=float(params["beam_m"]),
            draft_m=float(params["draft_m"]),
            displacement_tonnes=float(params["displacement_tonnes"]),
            block_coefficient=float(params["block_coeff"]),
            prismatic_coefficient=float(params["prismatic_coeff"]),
        )
        wave = WaveSpec(
            height_m=float(params["Hs_m"]),
            period_s=float(params["Tp_s"]),
            direction_deg=float(params.get("direction_deg", 0.0)),
        )
        depth = float(params.get("depth_m", 100.0))
        result = linear_wave_diffraction_force(hull, wave, depth)
        result["note"] = (
            "Froude-Krylov + diffraction. Faltinsen (1990). DESIGN EXPLORATION ONLY."
        )
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "WAVE_FORCE_ERROR")
