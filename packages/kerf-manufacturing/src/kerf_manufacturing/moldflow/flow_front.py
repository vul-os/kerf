"""Transient flow-front tracking with weld-line and air-trap prediction.

Theory
------
This module implements a 2-D time-marching Hele-Shaw fill simulation on a
regular rectangular grid.  The cavity is discretised into NX × NY cells;
each cell carries a scalar fill fraction φ ∈ [0, 1].

Algorithm
---------
1.  Solve the Laplace pressure equation on the **full** cavity at t=0:

        ∇·(S ∇P) = 0,   S = h³ / (12 μ)

    Gate cells: P = P_inject (Dirichlet)
    Vent/boundary cells: P = 0 (Dirichlet)
    All interior cavity cells: solved.

    This single full-domain solve gives a pressure field whose isoclines are
    the iso-fill-time surfaces (same approach as hele_shaw.py v1).

2.  Compute Darcy velocity field from the pressure gradient:

        u = -S ∇P / h   (m/s in the plane)

3.  Advance fill fraction via explicit upwind advection using the **pre-computed**
    velocity field.  The fill fraction at each cell advances as:

        φ_new[i] = min(1, φ[i] + (Σ_nbr upwind_flux) * Δt)

4.  Track which gate branch contributed to each cell's fill by propagating a
    branch-id integer alongside the fill fraction.

5.  **Weld-line detection** — when a filled cell is adjacent to a filled cell
    from a *different* branch, both cells are weld candidates.  The meeting
    angle is estimated from the velocity vectors at both cells.

6.  **Air-trap detection** — after fill is complete (or at a chosen step),
    identify cavity cells with φ < 1 that have no path through other unfilled
    cells to a vent boundary → air traps.

API
---
The public function is::

    weld_air_analysis(cavity_grid, gates, vents, material_props) -> dict

See :func:`weld_air_analysis` for full documentation.

LLM Tool Registration
---------------------
``TOOL_SPEC`` constant exposes this capability as a JSON-schema-style tool
for kerf's agent orchestration layer.

References
----------
C.A. Hieber & S.F. Shen, "A finite-element/finite-difference simulation of
the injection-molding filling process", J. Non-Newtonian Fluid Mech., 1980.
Z. Tadmor & C.G. Gogos, "Principles of Polymer Processing", 2nd ed., 2006.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


# ---------------------------------------------------------------------------
# LLM Tool registration
# ---------------------------------------------------------------------------

TOOL_SPEC: dict[str, Any] = {
    "name": "moldflow_weld_air_analysis",
    "description": (
        "Run a 2-D Hele-Shaw transient fill simulation on a rectangular cavity grid "
        "and predict weld lines (where two flow fronts meet) and air traps (enclosed "
        "unfilled regions).  Returns weld-line locations with meeting angles, "
        "air-trap centroids and sizes, fill time, and peak injection pressure."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "cavity_grid": {
                "type": "object",
                "description": (
                    "2-D boolean grid describing the cavity.  Keys: "
                    "'nx' (int), 'ny' (int), 'cell_size_m' (float, metres), "
                    "'cells' (list[list[bool]] — True = cavity cell, False = wall)."
                ),
                "required": ["nx", "ny", "cell_size_m", "cells"],
            },
            "gates": {
                "type": "array",
                "description": "List of gate cells: [{row, col, pressure_pa}].",
                "items": {"type": "object", "required": ["row", "col"]},
            },
            "vents": {
                "type": "array",
                "description": (
                    "List of vent cells (P = 0 boundary): [{row, col}].  "
                    "If empty the outer boundary of the cavity is used."
                ),
                "items": {"type": "object", "required": ["row", "col"]},
            },
            "material_props": {
                "type": "object",
                "description": (
                    "Material properties.  Keys: "
                    "'viscosity_pa_s' (float), 'thickness_m' (float, cavity depth), "
                    "'injection_pressure_pa' (float, default 1.5e7)."
                ),
                "required": ["viscosity_pa_s", "thickness_m"],
            },
        },
        "required": ["cavity_grid", "gates", "material_props"],
    },
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CavityGrid:
    """Rectangular grid describing the mould cavity.

    Parameters
    ----------
    nx, ny : grid dimensions (number of cells in x and y).
    cell_size : physical size of each square cell (metres).
    cells : boolean (ny, nx) array — True where material can flow.
    """

    nx: int
    ny: int
    cell_size: float
    cells: np.ndarray  # (ny, nx) bool

    def __post_init__(self):
        self.cells = np.asarray(self.cells, dtype=bool)
        if self.cells.shape != (self.ny, self.nx):
            raise ValueError(
                f"cells shape {self.cells.shape} does not match (ny={self.ny}, nx={self.nx})"
            )

    @classmethod
    def from_dict(cls, d: dict) -> "CavityGrid":
        return cls(
            nx=int(d["nx"]),
            ny=int(d["ny"]),
            cell_size=float(d["cell_size_m"]),
            cells=np.array(d["cells"], dtype=bool),
        )


@dataclass
class GateSpec:
    """Injection gate at a grid cell."""

    row: int
    col: int
    pressure_pa: float = 1.5e7

    @classmethod
    def from_dict(cls, d: dict) -> "GateSpec":
        return cls(
            row=int(d["row"]),
            col=int(d["col"]),
            pressure_pa=float(d.get("pressure_pa", 1.5e7)),
        )


@dataclass
class VentSpec:
    """Vent location (P = 0 boundary condition)."""

    row: int
    col: int

    @classmethod
    def from_dict(cls, d: dict) -> "VentSpec":
        return cls(row=int(d["row"]), col=int(d["col"]))


@dataclass
class MaterialProps:
    """Material properties for the fill simulation."""

    viscosity_pa_s: float = 0.1      # effective viscosity (Pa·s)
    thickness_m: float = 2e-3        # cavity depth (m)
    injection_pressure_pa: float = 1.5e7

    @classmethod
    def from_dict(cls, d: dict) -> "MaterialProps":
        return cls(
            viscosity_pa_s=float(d.get("viscosity_pa_s", 0.1)),
            thickness_m=float(d.get("thickness_m", 2e-3)),
            injection_pressure_pa=float(d.get("injection_pressure_pa", 1.5e7)),
        )

    @property
    def fluidity(self) -> float:
        """S = h³ / (12 μ) — Hele-Shaw fluidity (m³·s/kg)."""
        return self.thickness_m ** 3 / (12.0 * self.viscosity_pa_s)


# ---------------------------------------------------------------------------
# Pressure solver on full cavity (finite-difference, 5-point stencil)
# ---------------------------------------------------------------------------

def _solve_pressure_full(
    cavity: np.ndarray,        # (ny, nx) bool — cavity mask
    gate_mask: np.ndarray,     # (ny, nx) bool — gate cells (P = P_inject)
    vent_mask: np.ndarray,     # (ny, nx) bool — vent cells (P = 0)
    fluidity: float,
    p_inject: float,
) -> np.ndarray:
    """Solve ∇·(S ∇P) = 0 on the full cavity using finite differences.

    Returns P (ny, nx) — pressure in Pa, 0 outside cavity.
    The full-domain solve gives the quasi-static pressure field that encodes
    fill order (iso-P lines = iso-fill-time lines for Hele-Shaw).
    """
    ny, nx = cavity.shape
    N = ny * nx

    def idx(r: int, c: int) -> int:
        return r * nx + c

    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    rhs = np.zeros(N)

    for r in range(ny):
        for c in range(nx):
            i = idx(r, c)
            if not cavity[r, c]:
                # Outside cavity — identity equation P = 0
                rows.append(i); cols.append(i); vals.append(1.0)
                continue

            if gate_mask[r, c]:
                rows.append(i); cols.append(i); vals.append(1.0)
                rhs[i] = p_inject
                continue

            if vent_mask[r, c]:
                rows.append(i); cols.append(i); vals.append(1.0)
                rhs[i] = 0.0
                continue

            # Interior cavity cell — 5-point Laplacian (no-flux at walls)
            diag = 0.0
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < ny and 0 <= nc < nx and cavity[nr, nc]:
                    j = idx(nr, nc)
                    rows.append(i); cols.append(j); vals.append(-fluidity)
                    diag += fluidity
            if diag < 1e-30:
                rows.append(i); cols.append(i); vals.append(1.0)
            else:
                rows.append(i); cols.append(i); vals.append(diag)

    A = sp.csr_matrix((vals, (rows, cols)), shape=(N, N))
    try:
        x = spla.spsolve(A, rhs)
    except Exception:
        x = np.zeros(N)

    return np.asarray(x, dtype=np.float64).reshape(ny, nx)


# ---------------------------------------------------------------------------
# Velocity field from pressure gradient
# ---------------------------------------------------------------------------

def _compute_velocity(
    pressure: np.ndarray,   # (ny, nx)
    cavity: np.ndarray,     # (ny, nx) bool
    fluidity: float,
    dx: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute cell-centred Darcy velocity (ux, uy) from pressure gradient.

    u = -S ∇P   (m/s × h factor is absorbed into fluidity definition)

    We use central differences where both neighbours are in the cavity,
    and one-sided differences at cavity boundaries.
    """
    ny, nx = pressure.shape
    ux = np.zeros((ny, nx))
    uy = np.zeros((ny, nx))

    for r in range(ny):
        for c in range(nx):
            if not cavity[r, c]:
                continue

            # x-gradient
            have_r = (c + 1 < nx) and cavity[r, c + 1]
            have_l = (c - 1 >= 0) and cavity[r, c - 1]
            if have_r and have_l:
                dpdx = (pressure[r, c + 1] - pressure[r, c - 1]) / (2.0 * dx)
            elif have_r:
                dpdx = (pressure[r, c + 1] - pressure[r, c]) / dx
            elif have_l:
                dpdx = (pressure[r, c] - pressure[r, c - 1]) / dx
            else:
                dpdx = 0.0
            ux[r, c] = -fluidity * dpdx

            # y-gradient  (row increases downward → +y)
            have_d = (r + 1 < ny) and cavity[r + 1, c]
            have_u = (r - 1 >= 0) and cavity[r - 1, c]
            if have_d and have_u:
                dpdy = (pressure[r + 1, c] - pressure[r - 1, c]) / (2.0 * dx)
            elif have_d:
                dpdy = (pressure[r + 1, c] - pressure[r, c]) / dx
            elif have_u:
                dpdy = (pressure[r, c] - pressure[r - 1, c]) / dx
            else:
                dpdy = 0.0
            uy[r, c] = -fluidity * dpdy

    return ux, uy


# ---------------------------------------------------------------------------
# Fill advancement — explicit Euler upwind advection
# ---------------------------------------------------------------------------

def _advance_fill(
    phi: np.ndarray,          # (ny, nx) fill fraction
    branch: np.ndarray,       # (ny, nx) int — dominant branch id per cell (-1=empty)
    ux: np.ndarray,
    uy: np.ndarray,
    cavity: np.ndarray,       # (ny, nx) bool
    dx: float,
    dt: float,
) -> tuple[np.ndarray, np.ndarray, set[tuple[int, int]]]:
    """Advance fill fraction one explicit Euler step using upwind advection.

    Returns
    -------
    phi_new   : updated fill fraction (ny, nx)
    branch_new: updated branch id (ny, nx)
    weld_set  : set of (row, col) cells that became weld nodes in this step
    """
    ny, nx = phi.shape
    phi_new = phi.copy()
    branch_new = branch.copy()
    weld_set: set[tuple[int, int]] = set()

    for r in range(ny):
        for c in range(nx):
            if not cavity[r, c] or phi[r, c] >= 1.0:
                continue

            flux = 0.0
            branch_contributions: dict[int, float] = {}

            # Upwind advection: accumulate flux from each neighbour
            # Flow from neighbour (nr,nc) → (r,c) when velocity points inward.
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if not (0 <= nr < ny and 0 <= nc < nx):
                    continue
                if not cavity[nr, nc] or phi[nr, nc] <= 0.0:
                    continue

                # Inward normal component: velocity at (nr,nc) dotted with
                # the direction from (nr,nc) → (r,c) = (-dr, -dc)
                # v_inward = ux[nr,nc]*(-dc) + uy[nr,nc]*(-dr)
                v_in = -ux[nr, nc] * dc - uy[nr, nc] * dr

                if v_in > 0:
                    incoming = v_in * phi[nr, nc] * dt / dx
                    flux += incoming
                    b = int(branch[nr, nc])
                    if b >= 0:
                        branch_contributions[b] = branch_contributions.get(b, 0.0) + incoming

            phi_new[r, c] = min(1.0, phi[r, c] + flux)

            # Branch tracking: majority branch wins
            if branch_contributions:
                dominant = max(branch_contributions, key=branch_contributions.__getitem__)
                if branch_new[r, c] < 0:
                    branch_new[r, c] = dominant
                elif branch_new[r, c] != dominant:
                    # Cell receives flux from a different branch → weld candidate
                    if phi_new[r, c] >= 0.5:
                        weld_set.add((r, c))

    return phi_new, branch_new, weld_set


# ---------------------------------------------------------------------------
# Weld-line angle helper
# ---------------------------------------------------------------------------

def _weld_angle(v1: np.ndarray, v2: np.ndarray) -> float:
    """Angle in degrees between two 2-D velocity vectors (0–180)."""
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-12 or n2 < 1e-12:
        return 180.0
    cos_a = float(np.clip((v1 / n1) @ (v2 / n2), -1.0, 1.0))
    return math.degrees(math.acos(cos_a))


# ---------------------------------------------------------------------------
# Air-trap detection via BFS from vent boundary
# ---------------------------------------------------------------------------

def _detect_air_traps(
    phi: np.ndarray,           # (ny, nx) final fill fraction
    cavity: np.ndarray,        # (ny, nx) bool
    vent_mask: np.ndarray,     # (ny, nx) bool
    threshold: float = 0.99,
) -> list[tuple[int, int]]:
    """Return list of (row, col) cells that are enclosed unfilled air traps.

    A cell is an air trap if it is a cavity cell with phi < threshold AND has
    no connected path through other unfilled cavity cells to a vent or grid
    boundary cell.

    Algorithm: BFS from all vent cells (and grid-edge cavity cells) through
    unfilled cells.  Any unfilled cavity cell not reached = air trap.
    """
    ny, nx = phi.shape
    unfilled = cavity & (phi < threshold)
    trap_candidates = set(zip(*np.where(unfilled)))

    if not trap_candidates:
        return []

    # BFS from vent / boundary unfilled cells
    reachable: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque()

    for r in range(ny):
        for c in range(nx):
            if not unfilled[r, c]:
                continue
            on_boundary = (r == 0 or r == ny - 1 or c == 0 or c == nx - 1)
            is_vent = bool(vent_mask[r, c])
            if on_boundary or is_vent:
                rc = (r, c)
                if rc not in reachable:
                    reachable.add(rc)
                    queue.append(rc)

    while queue:
        r, c = queue.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            nrc = (nr, nc)
            if 0 <= nr < ny and 0 <= nc < nx and nrc in trap_candidates and nrc not in reachable:
                reachable.add(nrc)
                queue.append(nrc)

    return [rc for rc in trap_candidates if rc not in reachable]


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def _run_simulation(
    grid: CavityGrid,
    gates: list[GateSpec],
    vents: list[VentSpec],
    mat: MaterialProps,
    n_steps: int = 200,
    cfl: float = 0.4,
) -> dict[str, Any]:
    """Time-marching Hele-Shaw fill simulation on a rectangular grid.

    Uses a pre-computed full-cavity pressure field (quasi-static) to drive
    the front advancement.  Returns raw result dict.
    """
    ny, nx = grid.ny, grid.nx
    dx = grid.cell_size
    cavity = grid.cells.copy()

    # --- Gate and vent masks ---
    gate_mask = np.zeros((ny, nx), dtype=bool)
    for g in gates:
        if 0 <= g.row < ny and 0 <= g.col < nx and cavity[g.row, g.col]:
            gate_mask[g.row, g.col] = True

    vent_mask = np.zeros((ny, nx), dtype=bool)
    if vents:
        for v in vents:
            if 0 <= v.row < ny and 0 <= v.col < nx:
                vent_mask[v.row, v.col] = True
    else:
        # Default: outer boundary of cavity (excluding gate cells)
        for r in range(ny):
            for c in range(nx):
                if cavity[r, c] and (r == 0 or r == ny - 1 or c == 0 or c == nx - 1):
                    if not gate_mask[r, c]:
                        vent_mask[r, c] = True

    # Fallback: if no vent cells exist (fully enclosed cavity, or no boundary cells),
    # use the cell(s) farthest from any gate as the vent.
    if not vent_mask.any():
        if gates:
            gate_r = np.mean([g.row for g in gates])
            gate_c = np.mean([g.col for g in gates])
            best_dist = -1.0
            best_rc: tuple[int, int] | None = None
            for r in range(ny):
                for c in range(nx):
                    if cavity[r, c] and not gate_mask[r, c]:
                        d = math.sqrt((r - gate_r) ** 2 + (c - gate_c) ** 2)
                        if d > best_dist:
                            best_dist = d
                            best_rc = (r, c)
            if best_rc is not None:
                vent_mask[best_rc[0], best_rc[1]] = True
        else:
            # No gates at all — just pick any non-gate cavity cell
            for r in range(ny):
                for c in range(nx):
                    if cavity[r, c]:
                        vent_mask[r, c] = True
                        break
                if vent_mask.any():
                    break

    # --- Full-cavity pressure solve ---
    p_inject = max(g.pressure_pa for g in gates) if gates else mat.injection_pressure_pa
    P = _solve_pressure_full(cavity, gate_mask, vent_mask, mat.fluidity, p_inject)

    max_pressure = float(P.max())

    # Compute velocity field (static, driven by full-domain pressure)
    ux, uy = _compute_velocity(P, cavity, mat.fluidity, dx)

    # --- CFL time step ---
    vmax = max(float(np.abs(ux).max()), float(np.abs(uy).max()), 1e-30)
    dt = cfl * dx / vmax

    # --- Initial fill state ---
    phi = np.zeros((ny, nx))
    branch = np.full((ny, nx), -1, dtype=int)
    for bid, g in enumerate(gates):
        if 0 <= g.row < ny and 0 <= g.col < nx and cavity[g.row, g.col]:
            phi[g.row, g.col] = 1.0
            branch[g.row, g.col] = bid
            # Also seed immediate cavity neighbours to bootstrap flow
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = g.row + dr, g.col + dc
                if 0 <= nr < ny and 0 <= nc < nx and cavity[nr, nc]:
                    phi[nr, nc] = max(phi[nr, nc], 0.5)
                    if branch[nr, nc] < 0:
                        branch[nr, nc] = bid

    # --- Time march ---
    all_weld_cells: set[tuple[int, int]] = set()
    total_time = 0.0

    n_cavity = int(cavity.sum())

    for _step in range(n_steps):
        phi_new, branch_new, weld_step = _advance_fill(phi, branch, ux, uy, cavity, dx, dt)
        all_weld_cells |= weld_step
        phi = phi_new
        branch = branch_new
        total_time += dt

        n_filled = int((phi >= 0.99).sum())
        if n_cavity > 0 and n_filled >= n_cavity:
            break

    return {
        "phi": phi,
        "branch": branch,
        "ux": ux,
        "uy": uy,
        "weld_cells": all_weld_cells,
        "vent_mask": vent_mask,
        "total_time": total_time,
        "max_pressure": max_pressure,
        "dx": dx,
        "cavity": cavity,
    }


# ---------------------------------------------------------------------------
# Weld-line extraction from branch boundary
# ---------------------------------------------------------------------------

def _extract_weld_lines(
    phi: np.ndarray,
    branch: np.ndarray,
    ux: np.ndarray,
    uy: np.ndarray,
    cavity: np.ndarray,
    gates: list[GateSpec],
    dx: float,
    fill_threshold: float = 0.5,
) -> list[tuple[float, float, float]]:
    """Find all cells at which two distinct branches meet.

    For each filled cavity cell, check all 4-connected neighbours.  When a
    neighbour belongs to a different branch, record the midpoint as a weld
    location and compute the angle between the two velocity vectors.

    Deduplication: merge weld points within 2 cell widths.
    """
    ny, nx = phi.shape
    seen: set[tuple[int, int]] = set()
    welds: list[tuple[float, float, float]] = []

    for r in range(ny):
        for c in range(nx):
            if not cavity[r, c] or phi[r, c] < fill_threshold:
                continue
            b_here = int(branch[r, c])
            if b_here < 0:
                continue
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if not (0 <= nr < ny and 0 <= nc < nx):
                    continue
                if not cavity[nr, nc] or phi[nr, nc] < fill_threshold:
                    continue
                b_nbr = int(branch[nr, nc])
                if b_nbr < 0 or b_nbr == b_here:
                    continue

                # Canonical key to avoid double-counting
                key = (min(r, nr), min(c, nc), max(r, nr), max(c, nc))
                key2 = (min(r, nr), min(c, nc))
                if key2 in seen:
                    continue
                seen.add(key2)

                # Midpoint in physical coordinates
                x = ((c + nc) / 2.0) * dx + dx / 2.0
                y = ((r + nr) / 2.0) * dx + dx / 2.0

                # Angle between the two velocity vectors at the meeting cells
                v1 = np.array([ux[r, c], uy[r, c]])
                v2 = np.array([ux[nr, nc], uy[nr, nc]])
                # Fall back to gate-to-cell direction if velocity is negligible
                if np.linalg.norm(v1) < 1e-12 and b_here < len(gates):
                    g = gates[b_here]
                    v1 = np.array([float(c - g.col), float(r - g.row)])
                if np.linalg.norm(v2) < 1e-12 and b_nbr < len(gates):
                    g2 = gates[b_nbr]
                    v2 = np.array([float(nc - g2.col), float(nr - g2.row)])
                angle = _weld_angle(v1, v2)
                welds.append((x, y, angle))

    # Deduplicate by proximity (merge within 2 cell widths)
    dedup: list[tuple[float, float, float]] = []
    tol = 2.0 * dx
    for wl in welds:
        close = any(
            abs(wl[0] - e[0]) < tol and abs(wl[1] - e[1]) < tol
            for e in dedup
        )
        if not close:
            dedup.append(wl)

    return dedup


# ---------------------------------------------------------------------------
# Supplementary weld-line detector: velocity convergence
# ---------------------------------------------------------------------------

def _extract_weld_lines_velocity(
    phi: np.ndarray,
    ux: np.ndarray,
    uy: np.ndarray,
    cavity: np.ndarray,
    dx: float,
    fill_threshold: float = 0.5,
    converge_cos_threshold: float = -0.5,  # angle > 120°
) -> list[tuple[float, float, float]]:
    """Detect weld lines by finding cells where flow from opposing directions converges.

    For each filled interior cell, look at each pair of opposite neighbours.
    When the incoming flows from opposite neighbours point toward each other
    (dot product < converge_cos_threshold), the cell is a weld-line candidate.

    This catches single-gate T-cavity welds where two sub-fronts from the same
    gate race around the T and meet with opposing velocities.
    """
    ny, nx = phi.shape
    welds: list[tuple[float, float, float]] = []

    for r in range(ny):
        for c in range(nx):
            if not cavity[r, c] or phi[r, c] < fill_threshold:
                continue

            # Check horizontal pair: left neighbour vs right neighbour
            v_from_left: np.ndarray | None = None
            v_from_right: np.ndarray | None = None
            v_from_above: np.ndarray | None = None
            v_from_below: np.ndarray | None = None

            # Left neighbour (dc=-1): flow comes in if ux[r,c-1] > 0
            if c - 1 >= 0 and cavity[r, c - 1] and phi[r, c - 1] >= fill_threshold:
                if ux[r, c - 1] > 1e-12:
                    v_from_left = np.array([ux[r, c - 1], uy[r, c - 1]])

            # Right neighbour (dc=+1): flow comes in if ux[r,c+1] < 0
            if c + 1 < nx and cavity[r, c + 1] and phi[r, c + 1] >= fill_threshold:
                if ux[r, c + 1] < -1e-12:
                    v_from_right = np.array([ux[r, c + 1], uy[r, c + 1]])

            # Above neighbour (dr=-1): flow comes in if uy[r-1,c] > 0
            if r - 1 >= 0 and cavity[r - 1, c] and phi[r - 1, c] >= fill_threshold:
                if uy[r - 1, c] > 1e-12:
                    v_from_above = np.array([ux[r - 1, c], uy[r - 1, c]])

            # Below neighbour (dr=+1): flow comes in if uy[r+1,c] < 0
            if r + 1 < ny and cavity[r + 1, c] and phi[r + 1, c] >= fill_threshold:
                if uy[r + 1, c] < -1e-12:
                    v_from_below = np.array([ux[r + 1, c], uy[r + 1, c]])

            # Check all converging pairs
            pairs = [
                (v_from_left, v_from_right),
                (v_from_above, v_from_below),
            ]
            for va, vb in pairs:
                if va is None or vb is None:
                    continue
                na, nb = np.linalg.norm(va), np.linalg.norm(vb)
                if na < 1e-12 or nb < 1e-12:
                    continue
                dot = float((va / na) @ (vb / nb))
                if dot < converge_cos_threshold:
                    angle = math.degrees(math.acos(max(-1.0, min(1.0, dot))))
                    x = c * dx + dx / 2.0
                    y = r * dx + dx / 2.0
                    welds.append((x, y, angle))
                    break  # one weld per cell

    # Deduplicate within 2 cell widths
    dedup: list[tuple[float, float, float]] = []
    tol = 2.0 * dx
    for wl in welds:
        close = any(
            abs(wl[0] - e[0]) < tol and abs(wl[1] - e[1]) < tol
            for e in dedup
        )
        if not close:
            dedup.append(wl)

    return dedup


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def weld_air_analysis(
    cavity_grid: dict | CavityGrid,
    gates: list[dict | GateSpec],
    vents: list[dict | VentSpec] | None,
    material_props: dict | MaterialProps,
    *,
    n_steps: int = 200,
    cfl: float = 0.4,
    weld_angle_threshold_deg: float = 135.0,
    air_trap_fill_threshold: float = 0.99,
) -> dict[str, Any]:
    """Run 2-D Hele-Shaw transient fill and predict weld lines and air traps.

    Parameters
    ----------
    cavity_grid : CavityGrid or dict
        Grid description of the cavity.  If dict, must have keys:
        ``nx``, ``ny``, ``cell_size_m``, ``cells``.
    gates : list of GateSpec or dict
        Injection gate locations (``row``, ``col``, optional ``pressure_pa``).
    vents : list of VentSpec or dict, or None
        Vent locations (P = 0).  If None or empty the outer cavity boundary
        is used as the vent.
    material_props : MaterialProps or dict
        Material properties (viscosity_pa_s, thickness_m, injection_pressure_pa).
    n_steps : int
        Maximum number of time steps.
    cfl : float
        CFL number for time step selection (default 0.4).
    weld_angle_threshold_deg : float
        Meeting angles below this value are flagged as poor-quality welds.
    air_trap_fill_threshold : float
        Cells with fill fraction below this are considered unfilled.

    Returns
    -------
    dict with keys:

    ``weld_lines`` : list of (x, y, angle_deg)
        Weld-line locations in metres with meeting angle in degrees.
        Angle < weld_angle_threshold_deg = poor-quality weld.
    ``air_traps`` : list of (x, y, size_m2)
        Air-trap centroids in metres with cluster area.
    ``fill_time`` : float
        Simulated fill time (seconds).
    ``max_pressure`` : float
        Peak injection pressure observed (Pa).
    ``fill_fraction`` : float
        Fraction of cavity cells filled at end of simulation.
    """
    # --- Normalise inputs ---
    if isinstance(cavity_grid, dict):
        cavity_grid = CavityGrid.from_dict(cavity_grid)
    if isinstance(material_props, dict):
        material_props = MaterialProps.from_dict(material_props)
    gate_specs = [
        g if isinstance(g, GateSpec) else GateSpec.from_dict(g)
        for g in (gates or [])
    ]
    vent_specs: list[VentSpec] = [
        v if isinstance(v, VentSpec) else VentSpec.from_dict(v)
        for v in (vents or [])
    ]

    # --- Run simulation ---
    sim = _run_simulation(
        cavity_grid, gate_specs, vent_specs, material_props, n_steps, cfl
    )

    phi = sim["phi"]
    branch = sim["branch"]
    ux = sim["ux"]
    uy = sim["uy"]
    vent_mask = sim["vent_mask"]
    dx = sim["dx"]
    cavity = sim["cavity"]

    # --- Weld-line extraction ---
    # Primary: branch-boundary detection (multi-gate case)
    weld_lines = _extract_weld_lines(
        phi, branch, ux, uy, cavity, gate_specs, dx, fill_threshold=0.5
    )
    # Supplementary: velocity-convergence detection (single/multi gate)
    weld_lines_vel = _extract_weld_lines_velocity(phi, ux, uy, cavity, dx, fill_threshold=0.5)
    # Merge, deduplicating within 2 cell widths
    tol = 2.0 * dx
    for wl in weld_lines_vel:
        close = any(
            abs(wl[0] - e[0]) < tol and abs(wl[1] - e[1]) < tol
            for e in weld_lines
        )
        if not close:
            weld_lines.append(wl)

    # --- Air-trap detection ---
    trap_cells = _detect_air_traps(
        phi, cavity, vent_mask, threshold=air_trap_fill_threshold
    )
    cell_area = dx * dx
    air_traps: list[tuple[float, float, float]] = []

    # Cluster contiguous trap cells into regions
    trap_set = set(trap_cells)
    visited: set[tuple[int, int]] = set()
    for seed in trap_cells:
        if seed in visited:
            continue
        cluster: list[tuple[int, int]] = []
        q: deque[tuple[int, int]] = deque([seed])
        visited.add(seed)
        while q:
            rc = q.popleft()
            cluster.append(rc)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nrc = (rc[0] + dr, rc[1] + dc)
                if nrc in trap_set and nrc not in visited:
                    visited.add(nrc)
                    q.append(nrc)
        centroid_r = float(sum(rc[0] for rc in cluster)) / len(cluster)
        centroid_c = float(sum(rc[1] for rc in cluster)) / len(cluster)
        x = centroid_c * dx + dx / 2.0
        y = centroid_r * dx + dx / 2.0
        size = len(cluster) * cell_area
        air_traps.append((x, y, size))

    # --- Summary ---
    n_cavity = int(cavity.sum())
    n_filled = int((phi >= air_trap_fill_threshold).sum())
    fill_fraction = n_filled / n_cavity if n_cavity > 0 else 0.0

    return {
        "weld_lines": weld_lines,
        "air_traps": air_traps,
        "fill_time": sim["total_time"],
        "max_pressure": sim["max_pressure"],
        "fill_fraction": fill_fraction,
    }


# ---------------------------------------------------------------------------
# Convenience: grid builders for test/demo cavities
# ---------------------------------------------------------------------------

def make_t_cavity(
    stem_height: int = 8,
    bar_width: int = 16,
    bar_height: int = 4,
    stem_width: int = 4,
) -> CavityGrid:
    """Build a T-shaped cavity on a rectangular grid.

    The T is oriented with the stem at the bottom and the crossbar at the top.
    The gate goes at the bottom-centre of the stem (row=ny-1, col=nx//2).

    Returns a CavityGrid with cell_size = 5 mm.
    """
    ny = stem_height + bar_height
    nx = bar_width
    cells = np.zeros((ny, nx), dtype=bool)

    # Crossbar (top bar_height rows — row 0..bar_height-1)
    cells[:bar_height, :] = True

    # Stem (bottom stem_height rows, centred horizontally)
    stem_col_start = (nx - stem_width) // 2
    stem_col_end = stem_col_start + stem_width
    cells[bar_height:, stem_col_start:stem_col_end] = True

    return CavityGrid(nx=nx, ny=ny, cell_size=0.005, cells=cells)


def make_donut_cavity(
    outer_r: int = 7,
    inner_r: int = 3,
    margin: int = 1,
) -> CavityGrid:
    """Build a donut (annulus) shaped cavity on a square grid.

    The ring is fully enclosed within the grid (no cells touch the outer boundary)
    when margin ≥ 1.  This ensures the vent auto-detection uses the farthest-cell
    fallback, giving the donut scenario where:
    - Gate: leftmost ring cell in the middle row.
    - Flow wraps around both arcs of the ring.
    - Far side (rightmost cells) has no vent path → air trap detected.

    Returns a CavityGrid with cell_size = 5 mm.
    """
    size = 2 * outer_r + 2 * margin + 1
    cx, cy = size // 2, size // 2
    cells = np.zeros((size, size), dtype=bool)
    for r in range(size):
        for c in range(size):
            d = math.sqrt((r - cy) ** 2 + (c - cx) ** 2)
            if inner_r < d <= outer_r:
                cells[r, c] = True
    return CavityGrid(nx=size, ny=size, cell_size=0.005, cells=cells)
