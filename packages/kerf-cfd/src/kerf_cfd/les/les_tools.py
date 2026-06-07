"""
LLM tool wrappers for LES, DES/DDES, and overset rotating-mesh solvers.

Registers:
  cfd_les_simulate     — in-house LES (Smagorinsky + WALE) on structured grid
  cfd_des_simulate     — hybrid DES/DDES (RANS near-wall, LES off-wall)
  cfd_overset_rotating — Chimera overset + rotating sub-grid scalar transport

All results are JSON-serialisable dicts.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any


# ---------------------------------------------------------------------------
# Tool 1: cfd_les_simulate
# ---------------------------------------------------------------------------

cfd_les_simulate_spec = {
    "name": "cfd_les_simulate",
    "description": (
        "Run an in-house Large-Eddy Simulation (LES) of incompressible flow on a "
        "structured 3-D Cartesian grid.  Supports Smagorinsky (1963) and WALE "
        "(Nicoud & Ducros 1999) subgrid-scale models.  Time-integration by "
        "Adams-Bashforth 2 + fractional-step projection.  Reports resolved vs "
        "modeled TKE, energy spectrum trend, and velocity statistics.\n\n"
        "Honest scope: structured grids; modest Re_λ ≤ ~500; not HPC-validated.\n"
        "Cases: 'hit_decay' (homogeneous isotropic turbulence) or 'shear_layer'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "nx": {"type": "integer", "default": 16,
                   "description": "Grid cells in x.  Product nx·ny·nz ≤ ~32768 recommended."},
            "ny": {"type": "integer", "default": 16, "description": "Grid cells in y."},
            "nz": {"type": "integer", "default": 16, "description": "Grid cells in z."},
            "Re_lambda": {"type": "number", "default": 50.0,
                          "description": "Approximate Taylor Reynolds number Re_λ."},
            "sgs_model": {"type": "string", "default": "smagorinsky",
                          "enum": ["smagorinsky", "wale"],
                          "description": "Subgrid-scale model: 'smagorinsky' (1963) or 'wale' (Nicoud & Ducros 1999)."},
            "n_steps": {"type": "integer", "default": 40,
                        "description": "Number of time steps to advance."},
            "case": {"type": "string", "default": "hit_decay",
                     "enum": ["hit_decay", "shear_layer"],
                     "description": "Flow case."},
            "U_ref": {"type": "number", "default": 1.0, "description": "Reference velocity [m/s]."},
            "seed": {"type": "integer", "default": 42, "description": "RNG seed."},
        },
        "required": [],
    },
}


def run_cfd_les_simulate(params: dict[str, Any]) -> dict[str, Any]:
    """Execute LES simulation and return result dict."""
    from kerf_cfd.les.les_solver import LESConfig, run_les

    cfg = LESConfig(
        nx       = int(params.get("nx", 16)),
        ny       = int(params.get("ny", 16)),
        nz       = int(params.get("nz", 16)),
        Re_lambda= float(params.get("Re_lambda", 50.0)),
        sgs_model= str(params.get("sgs_model", "smagorinsky")),
        n_steps  = int(params.get("n_steps", 40)),
        case     = str(params.get("case", "hit_decay")),
        U_ref    = float(params.get("U_ref", 1.0)),
        seed     = int(params.get("seed", 42)),
    )
    res = run_les(cfg)
    d = asdict(res)

    # Trim large arrays for JSON
    d["u_centreline"] = d["u_centreline"][:16]  # first 16 pts
    d["v_centreline"] = d["v_centreline"][:16]
    d["wavenumbers"]  = d["wavenumbers"][:16]
    d["energy_spectrum"] = d["energy_spectrum"][:16]

    # Add summary flags
    d["ok"] = True
    d["unsteady"] = res.temporal_u_fluctuation > 1.0e-6
    d["tke_decaying"] = res.tke_decay_ratio < 0.99 if cfg.case == "hit_decay" else True
    d["energy_at_multiple_scales"] = len([e for e in res.energy_spectrum if e > 1.0e-12]) >= 3
    return d


# ---------------------------------------------------------------------------
# Tool 2: cfd_des_simulate
# ---------------------------------------------------------------------------

cfd_des_simulate_spec = {
    "name": "cfd_des_simulate",
    "description": (
        "Run a hybrid Detached-Eddy Simulation (DES or DDES) on a 2-D structured "
        "channel-like domain.  RANS (k-ω SST mixing-length) near the wall; "
        "Smagorinsky LES in off-wall separated regions.  Reports wall-normal "
        "model_index (0 = RANS, 1 = LES) vs wall distance — demonstrating the "
        "DES switching criterion d_w vs C_DES·Δ_max.\n\n"
        "Honest scope: 2-D Cartesian; mixing-length RANS proxy; not validated vs DNS."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "nx": {"type": "integer", "default": 32, "description": "Streamwise cells."},
            "ny": {"type": "integer", "default": 32, "description": "Wall-normal cells."},
            "Re_tau": {"type": "number", "default": 180.0,
                       "description": "Friction Reynolds number Re_τ = u_τ h / ν."},
            "U_bulk": {"type": "number", "default": 1.0, "description": "Bulk velocity [m/s]."},
            "n_steps": {"type": "integer", "default": 40, "description": "Time steps."},
            "variant": {"type": "string", "default": "ddes",
                        "enum": ["des", "ddes"],
                        "description": "'des' (Spalart 1997) or 'ddes' (Spalart 2006 with shielding)."},
            "seed": {"type": "integer", "default": 42, "description": "RNG seed."},
        },
        "required": [],
    },
}


def run_cfd_des_simulate(params: dict[str, Any]) -> dict[str, Any]:
    """Execute DES/DDES simulation and return result dict."""
    from kerf_cfd.les.des_solver import DESConfig, run_des

    cfg = DESConfig(
        nx      = int(params.get("nx", 32)),
        ny      = int(params.get("ny", 32)),
        Re_tau  = float(params.get("Re_tau", 180.0)),
        U_bulk  = float(params.get("U_bulk", 1.0)),
        n_steps = int(params.get("n_steps", 40)),
        variant = str(params.get("variant", "ddes")),
        seed    = int(params.get("seed", 42)),
    )
    res = run_des(cfg)
    d = asdict(res)
    d["ok"] = True
    # Verify DES switching: near wall = RANS, away from wall = LES
    ny = cfg.ny
    near_wall_rans = all(mi == 0 for mi in res.model_index[:ny // 4]) if res.model_index else False
    d["near_wall_rans"] = near_wall_rans
    d["has_les_region"] = res.n_les_cells > 0
    d["rans_fraction"] = res.n_rans_cells / max(ny, 1)
    return d


# ---------------------------------------------------------------------------
# Tool 3: cfd_overset_rotating
# ---------------------------------------------------------------------------

cfd_overset_rotating_spec = {
    "name": "cfd_overset_rotating",
    "description": (
        "Simulate a rotating sub-grid (paddle / rotor patch) embedded in a "
        "background Cartesian domain using Chimera/overset interpolation.  "
        "A Gaussian scalar feature on the rotating sub-grid is carried around; "
        "the background receives interpolated values via hole-cutting + bilinear "
        "stencil.  Reports final scalar fields, rotation angle, interpolation "
        "and conservation diagnostics.\n\n"
        "Honest scope: 2-D; bilinear (1st-order) interpolation; no turbulence; "
        "not validated vs OpenFOAM overset.  Demonstrates Chimera data-exchange "
        "and rotating-feature transport."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "nx_bg": {"type": "integer", "default": 32,
                      "description": "Background grid cells in x."},
            "ny_bg": {"type": "integer", "default": 32,
                      "description": "Background grid cells in y."},
            "nxs":   {"type": "integer", "default": 16,
                      "description": "Sub-grid cells in x."},
            "nys":   {"type": "integer", "default": 16,
                      "description": "Sub-grid cells in y."},
            "omega_rad_s": {"type": "number", "default": 1.0,
                            "description": "Sub-grid rotation rate [rad/s]."},
            "n_steps": {"type": "integer", "default": 36,
                        "description": "Time steps (36 steps × dt ≈ 1 revolution at ω=1)."},
            "U_bg": {"type": "number", "default": 0.2,
                     "description": "Background flow velocity [m/s]."},
            "nu": {"type": "number", "default": 0.005,
                   "description": "Kinematic viscosity [m²/s] (for scalar diffusion)."},
        },
        "required": [],
    },
}


def run_cfd_overset_rotating(params: dict[str, Any]) -> dict[str, Any]:
    """Execute overset rotating-mesh simulation and return result dict."""
    from kerf_cfd.les.overset_mesh import OversetConfig, run_overset_rotating

    cfg = OversetConfig(
        nx_bg     = int(params.get("nx_bg", 32)),
        ny_bg     = int(params.get("ny_bg", 32)),
        nxs       = int(params.get("nxs", 16)),
        nys       = int(params.get("nys", 16)),
        omega_rad_s = float(params.get("omega_rad_s", 1.0)),
        n_steps   = int(params.get("n_steps", 36)),
        U_bg      = float(params.get("U_bg", 0.2)),
        nu        = float(params.get("nu", 0.005)),
    )
    res = run_overset_rotating(cfg)
    d = asdict(res)

    # Trim large arrays for JSON response
    d["phi_background"] = d["phi_background"][:64]   # first 64 cells
    d["phi_subgrid"]    = d["phi_subgrid"][:32]
    d["xsg_final"]      = d["xsg_final"][:16]
    d["ysg_final"]      = d["ysg_final"][:16]
    d["hole_mask"]      = d["hole_mask"][:64]

    d["ok"] = True
    d["feature_rotated"] = res.angle_deg > 5.0   # sub-grid actually rotated
    d["interpolation_ok"] = res.interpolation_error < 1.0  # no blow-up
    return d
