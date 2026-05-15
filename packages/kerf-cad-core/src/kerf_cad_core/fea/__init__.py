"""
kerf_cad_core.fea — 1D/2D finite-element solver seed.

Public API
----------
from kerf_cad_core.fea.solver import solve_truss, solve_bar_plastic

solve_truss(nodes, elements, supports, loads)
    Linear 2-D truss / bar assembler and solver.

solve_bar_plastic(length, area, E, sigma_y, H, force, steps)
    1-D bar with bilinear isotropic-hardening plasticity.
    Newton-Raphson load stepping with return-mapping.

Both functions return plain dicts and NEVER raise.
"""
from __future__ import annotations

from kerf_cad_core.fea.solver import solve_truss, solve_bar_plastic

__all__ = ["solve_truss", "solve_bar_plastic"]
