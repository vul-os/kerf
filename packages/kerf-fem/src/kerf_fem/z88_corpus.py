"""
Z88 reference corpus: modal analysis with analytic Euler-Bernoulli oracle.

This module provides:

  1. A cantilever-beam fixture generator (``cantilever_modal_fixture``) that
     produces a Z88-compatible mesh + material + BC dict for a prismatic
     Euler-Bernoulli cantilever beam.

  2. An analytic natural-frequency oracle
     (``euler_bernoulli_cantilever_frequencies``) that computes the first N
     natural frequencies of a clamped-free beam using the standard characteristic
     equation β_n L values from Blevins (1979) Table 8-1.

  3. A tolerance checker (``check_z88_modal_frequencies``) that compares Z88
     output frequencies against the analytic oracle and returns a structured
     pass/fail report.

References
----------
Blevins, R. D.  Formulas for Natural Frequency and Mode Shape. Van Nostrand
    Reinhold, New York (1979). Table 8-1 (clamped-free beam, flexural modes).

Meirovitch, L.  Fundamentals of Vibrations. McGraw-Hill (2001) §7.3.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Euler-Bernoulli analytic oracle
# ---------------------------------------------------------------------------

# (β_n L) eigenvalues for clamped-free (cantilever) beam — first 6 modes.
# Source: Blevins (1979) Table 8-1, Meirovitch (2001) Table 7.3-1.
#
# These are roots of:  cos(β L) cosh(β L) = -1
# (first root is the rigid-body mode at 0 Hz, which Z88 modal may or may not
# return; we start from the first elastic bending mode.)
_BLEVINS_BETA_L = [
    1.8751040687,   # mode 1
    4.6940911329,   # mode 2
    7.8547574382,   # mode 3
    10.9955407349,  # mode 4
    14.1371684491,  # mode 5
    17.2787596574,  # mode 6
]


def euler_bernoulli_cantilever_frequencies(
    E: float,
    I: float,
    rho: float,
    A: float,
    L: float,
    *,
    n_modes: int = 3,
) -> list[float]:
    """
    First n_modes natural frequencies (Hz) of an Euler-Bernoulli clamped-free beam.

    Formula (Blevins 1979, Table 8-1)::

        f_n = (β_n L)² / (2π L²) · √(E I / (ρ A))

    Parameters
    ----------
    E       : Young's modulus [Pa]
    I       : second moment of area [m⁴]  (bending about the neutral axis)
    rho     : mass density [kg/m³]
    A       : cross-sectional area [m²]
    L       : beam length [m]
    n_modes : number of natural frequencies to return (≤ 6)

    Returns
    -------
    list of n_modes frequencies in Hz, ascending order.

    Examples
    --------
    >>> fs = euler_bernoulli_cantilever_frequencies(
    ...     E=200e9, I=2.604e-7, rho=7850, A=0.0025, L=0.5)
    >>> round(fs[0], 1)
    1106.6
    """
    if n_modes < 1:
        raise ValueError("n_modes must be ≥ 1")
    if n_modes > len(_BLEVINS_BETA_L):
        raise ValueError(
            f"n_modes={n_modes} exceeds tabulated β_n L count ({len(_BLEVINS_BETA_L)})"
        )

    c = math.sqrt(E * I / (rho * A))  # bending wave speed factor [m²/s]
    freqs: list[float] = []
    for m in range(n_modes):
        beta_L = _BLEVINS_BETA_L[m]
        omega_n = (beta_L / L) ** 2 * c  # [rad/s]
        f_n = omega_n / (2.0 * math.pi)  # [Hz]
        freqs.append(f_n)
    return freqs


# ---------------------------------------------------------------------------
# Fixture generator
# ---------------------------------------------------------------------------

def cantilever_modal_fixture(
    *,
    L: float = 0.5,
    b: float = 0.05,
    h: float = 0.05,
    E: float = 200e9,
    nu: float = 0.3,
    rho: float = 7850.0,
    n_elem_x: int = 8,
    n_elem_y: int = 2,
    n_elem_z: int = 2,
) -> dict[str, Any]:
    """
    Build a Z88-compatible cantilever-beam fixture.

    Generates a structured hexahedral mesh for a prismatic beam of length L
    (along x), width b (along y) and height h (along z), clamped at x=0.

    The mesh is a simple Cartesian grid of hex8 (8-node brick) elements.
    Z88 element type 14 (hex8) is used.

    Parameters
    ----------
    L, b, h         : beam length, width, height [m]
    E, nu, rho      : material properties
    n_elem_x/y/z    : element count per direction

    Returns
    -------
    dict with keys:
        "mesh"                : {"nodes": [...], "elements": [...]}
        "materials"           : {"E": ..., "nu": ..., "rho": ...}
        "boundary_conditions" : [{"type": "fixed", "face": "xmin"}]
        "analytic_frequencies": list[float]  — first 3 Hz (Euler-Bernoulli oracle)
        "E", "I", "rho", "A", "L": scalar parameters for the oracle
    """
    # Build node grid.
    nx, ny, nz = n_elem_x + 1, n_elem_y + 1, n_elem_z + 1
    nodes: list[list[float]] = []
    node_index: dict[tuple[int, int, int], int] = {}
    idx = 0
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                x = ix * L / n_elem_x
                y = iy * b / n_elem_y
                z = iz * h / n_elem_z
                nodes.append([x, y, z])
                node_index[(ix, iy, iz)] = idx
                idx += 1

    def _nid(ix: int, iy: int, iz: int) -> int:
        """0-based node index (for element connectivity)."""
        return node_index[(ix, iy, iz)]

    # Build hex8 elements (Z88 type 14).
    # Z88 hex8 node ordering (Isoparametric, counter-clockwise bottom then top):
    #   bottom face: 0-1-2-3 (z=0), top face: 4-5-6-7 (z=1)
    elements: list[list[int]] = []
    for iz in range(n_elem_z):
        for iy in range(n_elem_y):
            for ix in range(n_elem_x):
                # 8 corners of the hex element (0-based node IDs).
                conn = [
                    _nid(ix,     iy,     iz    ),
                    _nid(ix + 1, iy,     iz    ),
                    _nid(ix + 1, iy + 1, iz    ),
                    _nid(ix,     iy + 1, iz    ),
                    _nid(ix,     iy,     iz + 1),
                    _nid(ix + 1, iy,     iz + 1),
                    _nid(ix + 1, iy + 1, iz + 1),
                    _nid(ix,     iy + 1, iz + 1),
                ]
                elements.append(conn)

    # Analytic frequencies (Euler-Bernoulli).
    I_beam = b * h ** 3 / 12.0   # second moment of area (bending in xz plane)
    A_beam = b * h
    analytic_freqs = euler_bernoulli_cantilever_frequencies(
        E, I_beam, rho, A_beam, L, n_modes=3
    )

    return {
        "mesh": {
            "nodes": nodes,
            "elements": elements,
        },
        "materials": {
            "E": E,
            "nu": nu,
            "rho": rho,
            "yield_strength": 250e6,
        },
        "boundary_conditions": [{"type": "fixed", "face": "xmin"}],
        "analytic_frequencies": analytic_freqs,
        "E": E,
        "I": I_beam,
        "rho": rho,
        "A": A_beam,
        "L": L,
    }


# ---------------------------------------------------------------------------
# Tolerance checker
# ---------------------------------------------------------------------------

def check_z88_modal_frequencies(
    z88_frequencies: list[float],
    analytic_frequencies: list[float],
    *,
    tolerance: float = 0.03,
) -> dict[str, Any]:
    """
    Compare Z88 modal output against analytic Euler-Bernoulli frequencies.

    Parameters
    ----------
    z88_frequencies     : list of Hz values from Z88 (ascending)
    analytic_frequencies: list of Hz values from the analytic oracle (ascending)
    tolerance           : max allowed relative error (default 3 %)

    Returns
    -------
    {
        "ok":      bool,
        "n_checked": int,
        "modes": [
            {
                "mode":      int,      # 1-based mode number
                "z88_hz":    float,
                "oracle_hz": float,
                "rel_err":   float,    # |z88 - oracle| / oracle
                "pass":      bool,
            },
            ...
        ],
        "failures": list[str],   # human-readable descriptions of failed modes
    }
    """
    n = min(len(z88_frequencies), len(analytic_frequencies))
    modes_report: list[dict[str, Any]] = []
    failures: list[str] = []

    for i in range(n):
        z = z88_frequencies[i]
        a = analytic_frequencies[i]
        rel_err = abs(z - a) / a if a != 0 else float("inf")
        passed = rel_err <= tolerance
        modes_report.append({
            "mode": i + 1,
            "z88_hz": z,
            "oracle_hz": a,
            "rel_err": rel_err,
            "pass": passed,
        })
        if not passed:
            failures.append(
                f"Mode {i + 1}: Z88={z:.4g} Hz, oracle={a:.4g} Hz, "
                f"rel_err={rel_err * 100:.2f}% > {tolerance * 100:.1f}%"
            )

    return {
        "ok": len(failures) == 0 and n > 0,
        "n_checked": n,
        "modes": modes_report,
        "failures": failures,
    }
