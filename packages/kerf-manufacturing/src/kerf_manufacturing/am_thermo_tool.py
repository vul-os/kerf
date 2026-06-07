"""
LLM tool: am_thermomechanical_simulate
--------------------------------------
Coupled transient thermo-mechanical AM simulation.

Exposes simulate_am_thermomechanical() as a kerf LLM tool.  Returns:
  - Thermal history (peak temperature per layer)
  - Melt-pool size metrics (depth, width) per layer
  - Residual stress (von-Mises, element-wise Cauchy 6-component)
  - Distortion field (nodal displacement)
  - Energy balance flag
  - Honest model-limitation warnings
"""

from __future__ import annotations

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_manufacturing._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

am_thermomechanical_simulate_spec = ToolSpec(
    name="am_thermomechanical_simulate",
    description=(
        "Run a coupled transient thermo-mechanical additive-manufacturing "
        "simulation.\n"
        "\n"
        "Physical model:\n"
        "  1. TRANSIENT THERMAL — Goldak double-ellipsoid moving heat source "
        "deposited layer-by-layer; explicit Euler 1-D FD per layer column with "
        "temperature-dependent conductivity (k(T)), apparent specific heat "
        "(including latent heat of fusion via Gaussian enthalpy smear, "
        "Voller & Prakash 1987), convection + radiation surface losses. "
        "Tracks melt-pool depth and width per layer.\n"
        "  2. THERMO-MECHANICAL COUPLING — thermal strain ε*=α·ΔT(x) fed into "
        "a Tet4 FEM per layer (element-specific thermal eigenstrain from the "
        "transient temperature field). Temperature-dependent E(T)=E₀·(1−β·ΔT). "
        "Quasi-static thermo-elastic solve gives distortion + residual stress.\n"
        "\n"
        "HONEST LIMITATIONS:\n"
        "  - Thermo-elastic only — no return-mapping plasticity; residual stress "
        "magnitudes underestimated ~30-50% vs full TEP (Vastola et al. 2016).\n"
        "  - 1-D thermal column per layer — no lateral inter-layer heat flow.\n"
        "  - Goldak source idealised — no keyhole, evaporation, or Marangoni.\n"
        "  - Small-mesh FEM (O(10³) elements); no GPU acceleration.\n"
        "  - Tet4 elements are stiff in bending; use fine mesh for accuracy.\n"
        "\n"
        "Defaults: Ti-6Al-4V LPBF (200 W laser, 0.8 m/s, 30 µm layer).\n"
        "\n"
        "Mesh (optional — defaults to 2×2×4 block 10×10×20 mm):\n"
        "  nodes : [[x,y,z],…] in metres\n"
        "  tets  : [[i,j,k,l],…] Tet4 node indices\n"
        "  — or — nx, ny, nz, lx, ly, lz for auto block mesh\n"
        "\n"
        "Laser / process:\n"
        "  laser_power_w     : float — laser power [W] (default 200)\n"
        "  scan_speed_m_s    : float — scan speed [m/s] (default 0.8)\n"
        "  beam_radius_m     : float — beam radius [m] (default 50e-6)\n"
        "  absorptivity      : float — beam absorptivity 0–1 (default 0.35)\n"
        "  layer_time_s      : float — time per layer inc. recoat [s] (default 10)\n"
        "  layer_thickness_m : float — layer height [m] (default 30e-6)\n"
        "\n"
        "Material (Ti-6Al-4V defaults):\n"
        "  rho_kg_m3         : float — density (default 4430)\n"
        "  cp_j_kg_k         : float — specific heat (default 526)\n"
        "  k_w_m_k           : float — conductivity (default 6.7)\n"
        "  T_melt_k          : float — melt/solidus temperature [K] (default 1878)\n"
        "  L_fusion_j_kg     : float — latent heat of fusion (default 286000)\n"
        "  alpha_therm       : float — CTE [1/K] (default 8.6e-6)\n"
        "  T_ref_k           : float — stress-free reference T [K] (default 298.15)\n"
        "  T_preheat_k       : float — build-plate preheat [K] (default 298.15)\n"
        "  E_pa              : float — Young's modulus at T_ref [Pa] (default 114e9)\n"
        "  nu                : float — Poisson's ratio (default 0.342)\n"
        "\n"
        "Returns:\n"
        "  ok                    : bool\n"
        "  n_layers              : int\n"
        "  n_nodes               : int\n"
        "  n_elems               : int\n"
        "  layer_peak_temp_k     : list[float] — peak T per layer [K]\n"
        "  melt_pool_depth_mm    : list[float] — melt-pool depth per layer [mm]\n"
        "  melt_pool_width_mm    : list[float] — melt-pool width per layer [mm]\n"
        "  melt_pool_reached     : list[bool]  — did layer reach T_melt?\n"
        "  energy_input_j        : float — total thermal energy deposited [J]\n"
        "  energy_balance_ok     : bool\n"
        "  max_deviation_mm      : float — max nodal displacement [mm]\n"
        "  max_von_mises_mpa     : float — max residual stress [MPa]\n"
        "  layer_max_disp_mm     : list[float] — max displacement after each layer\n"
        "  distortion_field      : list[[dx,dy,dz]] shape (N,3) in metres\n"
        "  residual_stress_mpa   : list[[sxx,syy,szz,txy,tyz,txz]] shape (M,6) MPa\n"
        "  recoater_interference : bool\n"
        "  support_elem_count    : int\n"
        "  warnings              : list[str] — model limitations + process warnings\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            # Mesh
            "nodes": {
                "type": "array",
                "description": "Node coordinates [[x,y,z],…] in metres.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "tets": {
                "type": "array",
                "description": "Tet4 connectivity [[i,j,k,l],…], 0-based node indices.",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 4,
                    "maxItems": 4,
                },
            },
            # Block mesh generator
            "nx": {"type": "integer", "default": 2},
            "ny": {"type": "integer", "default": 2},
            "nz": {"type": "integer", "default": 4},
            "lx": {"type": "number", "default": 0.01},
            "ly": {"type": "number", "default": 0.01},
            "lz": {"type": "number", "default": 0.02},
            # Laser / process
            "laser_power_w":     {"type": "number", "default": 200.0},
            "scan_speed_m_s":    {"type": "number", "default": 0.8},
            "beam_radius_m":     {"type": "number", "default": 50e-6},
            "absorptivity":      {"type": "number", "default": 0.35},
            "layer_time_s":      {"type": "number", "default": 10.0},
            "layer_thickness_m": {"type": "number", "default": 30e-6},
            # Thermophysical
            "rho_kg_m3":      {"type": "number", "default": 4430.0},
            "cp_j_kg_k":      {"type": "number", "default": 526.0},
            "k_w_m_k":        {"type": "number", "default": 6.7},
            "T_melt_k":       {"type": "number", "default": 1878.0},
            "L_fusion_j_kg":  {"type": "number", "default": 286000.0},
            "alpha_therm":    {"type": "number", "default": 8.6e-6},
            "T_ref_k":        {"type": "number", "default": 298.15},
            "T_preheat_k":    {"type": "number", "default": 298.15},
            "T_ambient_k":    {"type": "number", "default": 298.15},
            "h_conv_w_m2_k":  {"type": "number", "default": 20.0},
            "emissivity":     {"type": "number", "default": 0.3},
            # Mechanical
            "E_pa":           {"type": "number", "default": 114e9},
            "nu":             {"type": "number", "default": 0.342},
            "beta_E_per_k":   {"type": "number", "default": 3.5e-4},
            # Misc
            "build_dir": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "default": [0, 0, 1],
            },
            "distortion_tol_m": {"type": "number", "default": 1e-3},
        },
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_am_thermomechanical_simulate(params: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_manufacturing.am_process_sim import AMMesh, make_block_mesh
        from kerf_manufacturing.am_thermomechanical import (
            AMThermoMechParams, simulate_am_thermomechanical,
        )

        # ---- Build mesh -------------------------------------------------------
        raw_nodes = params.get("nodes")
        raw_tets = params.get("tets")

        if raw_nodes is not None and raw_tets is not None:
            nodes = np.array(raw_nodes, dtype=float)
            tets = np.array(raw_tets, dtype=int)
            if nodes.ndim != 2 or nodes.shape[1] != 3:
                return err_payload("nodes must be [[x,y,z],…]", "BAD_ARGS")
            if tets.ndim != 2 or tets.shape[1] != 4:
                return err_payload("tets must be [[i,j,k,l],…]", "BAD_ARGS")
            mesh = AMMesh(nodes=nodes, tets=tets)
        else:
            nx = int(params.get("nx", 2))
            ny = int(params.get("ny", 2))
            nz = int(params.get("nz", 4))
            lx = float(params.get("lx", 0.01))
            ly = float(params.get("ly", 0.01))
            lz = float(params.get("lz", 0.02))
            if any(v < 1 for v in [nx, ny, nz]):
                return err_payload("nx, ny, nz must each be >= 1", "BAD_ARGS")
            if any(v <= 0 for v in [lx, ly, lz]):
                return err_payload("lx, ly, lz must be positive", "BAD_ARGS")
            mesh = make_block_mesh(nx=nx, ny=ny, nz=nz, lx=lx, ly=ly, lz=lz)

        # ---- Build params -----------------------------------------------------
        tm_params = AMThermoMechParams(
            laser_power_w=float(params.get("laser_power_w", 200.0)),
            scan_speed_m_s=float(params.get("scan_speed_m_s", 0.8)),
            beam_radius_m=float(params.get("beam_radius_m", 50e-6)),
            absorptivity=float(params.get("absorptivity", 0.35)),
            layer_time_s=float(params.get("layer_time_s", 10.0)),
            layer_thickness_m=float(params.get("layer_thickness_m", 30e-6)),
            rho_kg_m3=float(params.get("rho_kg_m3", 4430.0)),
            cp_j_kg_k=float(params.get("cp_j_kg_k", 526.0)),
            k_w_m_k=float(params.get("k_w_m_k", 6.7)),
            T_melt_k=float(params.get("T_melt_k", 1878.0)),
            T_liquidus_k=float(params.get("T_liquidus_k", 1928.0)),
            L_fusion_j_kg=float(params.get("L_fusion_j_kg", 286_000.0)),
            alpha_therm=float(params.get("alpha_therm", 8.6e-6)),
            T_ref_k=float(params.get("T_ref_k", 298.15)),
            T_preheat_k=float(params.get("T_preheat_k", 298.15)),
            T_ambient_k=float(params.get("T_ambient_k", 298.15)),
            h_conv_w_m2_k=float(params.get("h_conv_w_m2_k", 20.0)),
            emissivity=float(params.get("emissivity", 0.3)),
            E_pa=float(params.get("E_pa", 114e9)),
            nu=float(params.get("nu", 0.342)),
            beta_E_per_k=float(params.get("beta_E_per_k", 3.5e-4)),
            build_dir=tuple(params.get("build_dir", [0.0, 0.0, 1.0])),
            distortion_tolerance_m=float(params.get("distortion_tol_m", 1e-3)),
        )

        # ---- Simulate ---------------------------------------------------------
        res = simulate_am_thermomechanical(mesh, tm_params)

        if not res.ok:
            return err_payload(res.reason, "AM_THERMO_SIM_ERROR")

        # ---- Serialise --------------------------------------------------------
        def _rnd(v: float) -> float:
            return round(v, 9)

        disp_field = [[_rnd(float(u)) for u in row] for row in res.displacement]
        stress_mpa = [
            [round(float(s) / 1e6, 4) for s in row]
            for row in res.residual_stress
        ]
        layer_mm = [round(d * 1e3, 6) for d in res.layer_max_disp_m]

        melt_reached = [
            m.peak_temperature_k >= tm_params.T_melt_k
            for m in res.melt_pool_metrics
        ]
        melt_depth_mm = [
            round(m.melt_pool_depth_m * 1e3, 4)
            for m in res.melt_pool_metrics
        ]
        melt_width_mm = [
            round(m.melt_pool_width_m * 1e3, 4)
            for m in res.melt_pool_metrics
        ]

        support_count = sum(1 for f in res.support_elem_flags if f)

        return ok_payload({
            "ok": True,
            "n_layers": res.n_layers,
            "n_nodes": res.n_nodes,
            "n_elems": res.n_elems,
            # Thermal
            "layer_peak_temp_k": [round(t, 2) for t in res.layer_peak_temp_k],
            "melt_pool_depth_mm": melt_depth_mm,
            "melt_pool_width_mm": melt_width_mm,
            "melt_pool_reached": melt_reached,
            "energy_input_j": round(res.energy_input_j, 4),
            "energy_balance_ok": bool(res.energy_balance_ok),
            # Mechanical
            "max_deviation_mm": round(res.max_deviation_m * 1e3, 6),
            "max_von_mises_mpa": round(res.max_von_mises_pa / 1e6, 4),
            "layer_max_disp_mm": layer_mm,
            "recoater_interference": res.recoater_interference,
            "support_elem_count": support_count,
            "distortion_field": disp_field,
            "residual_stress_mpa": stress_mpa,
            "warnings": res.warnings,
        })

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "AM_THERMO_SIMULATE_ERROR")


# ---------------------------------------------------------------------------
# Exported list (consumed by tools.py)
# ---------------------------------------------------------------------------

AM_THERMO_TOOLS = [
    (
        "am_thermomechanical_simulate",
        am_thermomechanical_simulate_spec,
        run_am_thermomechanical_simulate,
    ),
]
