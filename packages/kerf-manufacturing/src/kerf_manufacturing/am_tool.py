"""
LLM tool: am_process_simulate
------------------------------
Inherent-strain AM process distortion and residual-stress simulation.

Exposes the simulate_am_process() engine as a kerf LLM tool.
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

am_process_simulate_spec = ToolSpec(
    name="am_process_simulate",
    description=(
        "Run an additive-manufacturing (metal AM) process simulation using the "
        "inherent-strain method to predict thermal distortion and residual stress.\n"
        "\n"
        "Physical model: layer-by-layer element birth/death with an anisotropic "
        "inherent-strain tensor applied to each newly activated layer. Quasi-static "
        "linear-elastic solution per layer; stresses and displacements are accumulated "
        "through the full build sequence.\n"
        "\n"
        "HONEST LIMITATIONS:\n"
        "  - Elastic approximation only (no melt-pool thermomechanics).\n"
        "  - Isotropic material; temperature-independent properties.\n"
        "  - Constant-strain Tet4 elements (stiff in bending; use fine mesh for "
        "quantitative accuracy).\n"
        "  - Base-plate not removed post-build.\n"
        "\n"
        "Mesh format:\n"
        "  nodes : [[x, y, z], …]  — node coordinates in metres\n"
        "  tets  : [[i, j, k, l], …] — Tet4 connectivity (0-based node indices)\n"
        "\n"
        "  Alternatively omit nodes/tets and use the built-in block-mesh generator:\n"
        "    nx, ny, nz  : int — cell counts (default 2, 2, 4)\n"
        "    lx, ly, lz  : float — block dimensions in metres (default 0.01, 0.01, 0.02)\n"
        "\n"
        "Material (all optional):\n"
        "  E_pa       : float — Young's modulus [Pa] (default 200e9 — steel)\n"
        "  nu         : float — Poisson's ratio (default 0.3)\n"
        "\n"
        "Process parameters (all optional):\n"
        "  layer_thickness_m : float — build layer height [m] (default 5e-5 = 50 µm)\n"
        "  build_dir         : [dx, dy, dz] — build direction unit vector "
        "(default [0,0,1])\n"
        "  inherent_strain   : [ε_xx, ε_yy, ε_zz, γ_xy, γ_yz, γ_xz] — anisotropic "
        "inherent-strain tensor components. Default: [-2.5e-3, -2.5e-3, -5e-3, 0, 0, 0] "
        "(typical Ti-6Al-4V LPBF, Liang et al. 2019).\n"
        "  distortion_tol_m  : float — distortion warning threshold [m] (default 1e-3)\n"
        "\n"
        "Returns:\n"
        "  ok                  : bool\n"
        "  n_layers            : int\n"
        "  n_nodes             : int\n"
        "  n_elems             : int\n"
        "  max_deviation_mm    : float — maximum nodal displacement magnitude [mm]\n"
        "  max_von_mises_mpa   : float — maximum residual von-Mises stress [MPa]\n"
        "  layer_max_disp_mm   : list[float] — max displacement after each layer [mm]\n"
        "  recoater_interference : bool — geometric recoater-clearance flag\n"
        "  support_elem_count  : int — number of flagged support-region elements\n"
        "  distortion_field    : list[list[float]] shape (N, 3) — nodal displacement\n"
        "  residual_stress_mpa : list[list[float]] shape (M, 6) — element Cauchy stress "
        "[σ_xx, σ_yy, σ_zz, τ_xy, τ_yz, τ_xz] in MPa\n"
        "  warnings            : list[str]\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            # Mesh — either explicit or auto-generated block
            "nodes": {
                "type": "array",
                "description": "Node coordinates [[x,y,z], …] in metres.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "tets": {
                "type": "array",
                "description": "Tet4 element connectivity [[i,j,k,l], …], 0-based node indices.",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 4,
                    "maxItems": 4,
                },
            },
            # Block-mesh generator
            "nx": {"type": "integer", "default": 2,
                   "description": "Block mesh cells in X (used only if nodes/tets omitted)."},
            "ny": {"type": "integer", "default": 2,
                   "description": "Block mesh cells in Y."},
            "nz": {"type": "integer", "default": 4,
                   "description": "Block mesh cells in Z (build direction)."},
            "lx": {"type": "number", "default": 0.01,
                   "description": "Block X length [m]."},
            "ly": {"type": "number", "default": 0.01,
                   "description": "Block Y length [m]."},
            "lz": {"type": "number", "default": 0.02,
                   "description": "Block Z length [m] (build height)."},
            # Material
            "E_pa": {"type": "number", "default": 200e9,
                     "description": "Young's modulus [Pa]. Default 200 GPa (steel)."},
            "nu": {"type": "number", "default": 0.3,
                   "description": "Poisson's ratio."},
            # Process
            "layer_thickness_m": {
                "type": "number",
                "default": 5e-5,
                "description": "Build layer thickness [m]. Default 50 µm.",
            },
            "build_dir": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Build direction unit vector (default [0,0,1]).",
                "default": [0, 0, 1],
            },
            "inherent_strain": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 6,
                "maxItems": 6,
                "description": (
                    "Inherent-strain tensor [ε_xx,ε_yy,ε_zz,γ_xy,γ_yz,γ_xz]. "
                    "Default: [-2.5e-3,-2.5e-3,-5e-3,0,0,0] (Ti-6Al-4V LPBF typical)."
                ),
            },
            "distortion_tol_m": {
                "type": "number",
                "default": 1e-3,
                "description": "Distortion warning threshold [m].",
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_am_process_simulate(params: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_manufacturing.am_process_sim import (
            AMMesh, AMParams, simulate_am_process, make_block_mesh,
        )

        # --- Build mesh ---------------------------------------------------
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
            # Auto-generate block mesh
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

        # --- Build params -------------------------------------------------
        sim_params = AMParams(
            E=float(params.get("E_pa", 200e9)),
            nu=float(params.get("nu", 0.3)),
            layer_thickness=float(params.get("layer_thickness_m", 5e-5)),
            build_dir=tuple(params.get("build_dir", [0.0, 0.0, 1.0])),
            inherent_strain=tuple(
                params.get("inherent_strain", [-2.5e-3, -2.5e-3, -5.0e-3, 0.0, 0.0, 0.0])
            ),
            distortion_tolerance_m=float(params.get("distortion_tol_m", 1e-3)),
        )

        # --- Simulate -----------------------------------------------------
        res = simulate_am_process(mesh, sim_params)

        if not res.ok:
            return err_payload(res.reason, "AM_SIM_ERROR")

        # Serialise (cap distortion_field to keep response size reasonable)
        # Round to 6 significant figures
        def _rnd(v: float) -> float:
            return round(v, 9)

        disp_field = [
            [_rnd(float(u)) for u in row]
            for row in res.displacement
        ]
        stress_mpa = [
            [round(float(s) / 1e6, 4) for s in row]
            for row in res.residual_stress
        ]
        layer_mm = [round(d * 1e3, 6) for d in res.layer_max_disp_m]

        support_count = sum(1 for f in res.support_elem_flags if f)

        return ok_payload({
            "ok": True,
            "n_layers": res.n_layers,
            "n_nodes": res.n_nodes,
            "n_elems": res.n_elems,
            "max_deviation_mm": round(res.max_deviation_m * 1e3, 6),
            "max_von_mises_mpa": round(res.max_von_mises_pa / 1e6, 4),
            "layer_max_disp_mm": layer_mm,
            "recoater_interference": res.recoater_interference,
            "support_elem_count": support_count,
            "distortion_field": disp_field,
            "residual_stress_mpa": stress_mpa,
            "warnings": res.warnings,
            "disclaimer": (
                "Inherent-strain quasi-static elastic model. "
                "Not a full thermo-mechanical melt-pool simulation. "
                "Calibrate ε* from coupon tests for quantitative accuracy."
            ),
        })

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "AM_PROCESS_SIMULATE_ERROR")


# ---------------------------------------------------------------------------
# Exported list (consumed by plugin.py and tools.py)
# ---------------------------------------------------------------------------

AM_TOOLS = [
    ("am_process_simulate", am_process_simulate_spec, run_am_process_simulate),
]
