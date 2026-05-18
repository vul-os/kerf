"""
kerf_composites.interlaminar — Interlaminar shear stress (ILSS) at ply interfaces.

Uses equilibrium integration of in-plane stress gradients through the laminate
thickness (Pagano / Pipes-Pagano approach):

    τ_xz(z) = −∫_{z_bot}^{z} (∂σ_xx/∂x + ∂σ_xy/∂y) dz'

For the common case of a beam under pure bending (Navier beam solution) the
in-plane stress gradient is proportional to the through-thickness bending-
stress distribution, and the integration can be performed exactly.

The public API accepts a LaminateLayup together with an applied bending moment
(per unit width, N) or a normalised moment gradient and returns the
through-thickness τ_xz distribution plus the maximum value and its interface
location.

References
----------
Pagano, N. J. (1970). Exact solutions for composite laminates in cylindrical
    bending. J. Composite Materials, 4, 330–343.
Pipes, R. B. & Pagano, N. J. (1970). Interlaminar stresses in composite
    laminates under uniform axial extension. J. Composite Materials, 4, 538–548.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from kerf_composites.layup import LaminateLayup

from kerf_composites.clt import ply_Qbar_matrix


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ILSSResult:
    """
    Interlaminar shear stress distribution result.

    Attributes
    ----------
    tau_xz : np.ndarray, shape (n_interfaces,)
        τ_xz at each ply interface, from bottom to top [MPa].
        Interface 0 is the laminate bottom face; interface n is the top face.
    interface_z : np.ndarray, shape (n_interfaces,)
        Z-coordinates of the interfaces [mm].
    max_tau_xz : float
        Peak |τ_xz| across all interfaces [MPa].
    max_interface_index : int
        Index of the interface carrying the peak shear (0-based).
    max_interface_z : float
        Z-coordinate of the max-shear interface [mm].
    """
    tau_xz: np.ndarray
    interface_z: np.ndarray
    max_tau_xz: float
    max_interface_index: int
    max_interface_z: float


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def interlaminar_shear(
    layup: "LaminateLayup",
    Mx: float = 1.0,
    beam_length: float = 1.0,
) -> ILSSResult:
    """
    Compute interlaminar shear stress τ_xz at ply interfaces.

    Model: unit-width laminate beam under bending moment gradient
    dM/dx = Vx (transverse shear force per unit width).  The in-plane
    stress gradient ∂σ_xx/∂x is proportional to Vx / D₁₁_eff and the local
    bending stiffness contribution.

    For a beam of length L with moment Mx at the midspan, the shear force
    V = Mx / (L/2).

    The equilibrium integration gives:

        τ_xz(z_k) = −V · Σᵢ₌₀^{k−1} Q̄₁₁ⁱ · (z_{i+1}² − z_i²) / (2·D₁₁_eff)

    where D₁₁_eff is the (1,1) component of the D matrix [N·mm], converted
    consistently with Q̄₁₁ in [N/mm].

    Parameters
    ----------
    layup : LaminateLayup
        Laminate definition.
    Mx : float
        Applied bending moment [N·mm/mm].  Default 1 (normalised).
    beam_length : float
        Span length [mm].  Shear V = Mx / (beam_length / 2).

    Returns
    -------
    ILSSResult
    """
    from kerf_composites.clt import abd_matrices

    _, _, D = abd_matrices(layup)  # D in [N·mm]
    D11 = D[0, 0]  # N·mm

    V = Mx / (beam_length / 2.0)  # shear force per unit width [N/mm]

    z = np.array(layup.z_coords)  # length n+1
    n = layup.num_plies

    # τ_xz at each interface (n+1 values, starting from the bottom face)
    tau = np.zeros(n + 1)
    tau[0] = 0.0  # free surface at bottom

    # Running integral: ∫₋h/2^{z_k} Q̄₁₁(z') · z' dz'
    # For a uniform ply k: contribution = Q̄₁₁_k · (z_{k+1}² − z_k²) / 2
    running = 0.0
    for k in range(n):
        Qbar = ply_Qbar_matrix(layup.plies[k])
        Q11_bar = Qbar[0, 0]  # GPa — convert to N/mm² = MPa: ×1000
        Q11_bar_mpa = Q11_bar * 1.0e3  # MPa = N/mm²

        dz2 = z[k + 1] ** 2 - z[k] ** 2  # mm²
        running += Q11_bar_mpa * dz2 / 2.0  # N/mm² · mm² = N

        # τ_xz [N/mm²] = [MPa] = V [N/mm] · running [N] / D11 [N·mm]
        tau[k + 1] = -V * running / D11  # N/mm · N / (N·mm) = N/mm² = MPa

    # Free surface at the top should be zero; numerically it will be near zero
    # for a balanced laminate — leave as-is (useful diagnostic).

    abs_tau = np.abs(tau)
    max_idx = int(np.argmax(abs_tau))

    return ILSSResult(
        tau_xz=tau,
        interface_z=z,
        max_tau_xz=float(abs_tau[max_idx]),
        max_interface_index=max_idx,
        max_interface_z=float(z[max_idx]),
    )


# ---------------------------------------------------------------------------
# Interior (mid-plane) ILSS for a symmetric laminate — analytic formula
# ---------------------------------------------------------------------------

def ilss_neutral_axis(
    layup: "LaminateLayup",
    Mx: float = 1.0,
    beam_length: float = 1.0,
) -> float:
    """
    Return the ILSS value at the laminate neutral axis (z = 0).

    For a symmetric laminate the neutral axis coincides with the geometric
    mid-plane.  The shear stress peaks here for laminates with highest
    longitudinal stiffness in the outer plies (e.g. [0/90/0]).

    This is a convenience wrapper around :func:`interlaminar_shear` that
    returns the τ_xz value at the interface closest to z = 0.

    Parameters
    ----------
    layup, Mx, beam_length : same as :func:`interlaminar_shear`.

    Returns
    -------
    float
        |τ_xz| at the neutral axis [MPa].
    """
    result = interlaminar_shear(layup, Mx=Mx, beam_length=beam_length)
    z = result.interface_z
    mid_idx = int(np.argmin(np.abs(z)))
    return float(abs(result.tau_xz[mid_idx]))
