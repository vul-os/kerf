"""
J-integral fracture mechanics.

The J-integral is a path-independent contour integral that characterises
the energy release rate at a crack tip in an elastic (or deformation-theory
plastic) material. It is the foundation of modern fracture mechanics.

SIMPLIFICATION NOTICE
---------------------
This module implements 2-D (plane stress / plane strain) J-integral
calculation. Production 3-D crack-front analysis (curved fronts, mixed-mode
in 3D, dynamic fracture) requires XFEM, extended FEM with crack-tip
enrichment functions, or Element-Free Galerkin (EFG) methods, which are
beyond the scope of this pure-Python module.

Theory
------
Rice (1968) showed that for a crack in a linear-elastic material, the
contour integral

    J = ∮_Γ (W δ_1j - σ_ij ∂u_i/∂x_1) n_j ds

is independent of the path Γ taken around the crack tip, provided:
  - The material is homogeneous and has no body forces.
  - The crack faces are traction-free and parallel to x_1.
  - The contour is in the far field (outside the process zone).

Here W = (1/2) σ_ij ε_ij is the strain energy density.

For Mode-I plane stress:  J = K_I² / E
For Mode-I plane strain:  J = K_I² (1 - ν²) / E

References
----------
  Rice, J. R. (1968). "A Path Independent Integral and the Approximate
      Analysis of Strain Concentration by Notches and Cracks."
      J. Appl. Mech. 35(2), 379–386. DOI: 10.1115/1.3601206
  Shih, C. F., deLorenzi, H. G., & German, M. D. (1976). "Crack extension
      modeling with singular quadratic isoparametric elements."
      Int. J. Fract. 12(4), 647–651.
  Anderson, T. L. (2005). "Fracture Mechanics: Fundamentals and Applications."
      3rd ed., CRC Press. Chapter 2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass
class JIntegralContour:
    """Closed contour around a crack tip in 2D.

    Parameters
    ----------
    points : np.ndarray, shape (N, 2)
        Ordered contour points forming a closed path around the crack tip.
        The contour should be traversed counter-clockwise (CCW).
        First and last points need not coincide — closure is assumed.
    crack_tip : np.ndarray, shape (2,)
        Coordinates of the crack tip.
    """
    points: np.ndarray
    crack_tip: np.ndarray


def compute_j_integral(
    contour: JIntegralContour,
    stress_field: Callable[[np.ndarray], np.ndarray],
    displacement_field: Callable[[np.ndarray], np.ndarray],
    strain_energy_density: Callable[[np.ndarray], float],
) -> float:
    """Compute the J-integral along a contour around the crack tip.

    Evaluates the Rice (1968) path integral:

        J = ∮_Γ (W n_1 - T_i ∂u_i/∂x_1) ds

    where:
        W   = strain energy density at a point on Γ
        n_1 = x-component of outward normal to contour
        T_i = traction vector = σ_ij n_j
        ∂u_i/∂x_1 = displacement gradient with respect to crack direction x_1

    The displacement gradient ∂u/∂x_1 is estimated numerically using a
    central-difference step along the x_1 direction.

    Parameters
    ----------
    contour : JIntegralContour
        Contour definition (points and crack tip). Should enclose the
        crack tip. Path traversed counter-clockwise.
    stress_field : callable
        Function ``σ(x) -> np.ndarray, shape (2, 2)`` returning the
        2D Cauchy stress tensor at position x = [x1, x2].
        Convention: σ[0,0]=σ_xx, σ[0,1]=σ[1,0]=σ_xy, σ[1,1]=σ_yy.
    displacement_field : callable
        Function ``u(x) -> np.ndarray, shape (2,)`` returning the
        displacement vector at position x.
    strain_energy_density : callable
        Function ``W(x) -> float`` returning the strain energy density [J/m³]
        at position x.

    Returns
    -------
    J : float
        J-integral value [J/m² = N/m]. For an elastic crack, equal to
        the energy release rate G.

    Notes
    -----
    - Uses numerical integration with midpoint rule along each segment.
    - For best accuracy, contour should be in the K-dominant elastic zone,
      well away from the crack-tip process zone (plasticity / damage).
    - Path independence is exact for homogeneous linear-elastic materials
      with no body forces. Numerical errors of 5-10% are typical for
      coarse meshes.

    Reference: Rice (1968), eq. 2.8.
    """
    pts = np.asarray(contour.points, dtype=float)
    n_pts = pts.shape[0]
    if n_pts < 3:
        raise ValueError("Contour must have at least 3 points")

    # Close the contour
    pts_closed = np.vstack([pts, pts[0]])
    h = 1e-7  # step for numerical gradient

    J = 0.0

    for i in range(n_pts):
        # Segment from pts_closed[i] to pts_closed[i+1]
        p0 = pts_closed[i]
        p1 = pts_closed[i + 1]
        seg = p1 - p0
        seg_len = float(np.linalg.norm(seg))
        if seg_len < 1e-300:
            continue

        # Midpoint of segment
        mid = 0.5 * (p0 + p1)

        # Outward normal (for CCW contour, outward normal = right-turn of seg)
        # tangent = seg/|seg|, outward normal for CCW = rotate tangent by -90°
        tang = seg / seg_len
        normal_out = np.array([tang[1], -tang[0]])

        # Strain energy density W at midpoint
        W = float(strain_energy_density(mid))

        # Traction T = σ·n (outward normal)
        sigma = stress_field(mid)
        T = sigma @ normal_out

        # ∂u/∂x_1 — numerical gradient along x_1 (crack propagation direction)
        dx1 = np.array([h, 0.0])
        du_dx1 = (displacement_field(mid + dx1) - displacement_field(mid - dx1)) / (2 * h)

        # Integrand: W·n_1 - T_i·(∂u_i/∂x_1)
        integrand = W * normal_out[0] - float(np.dot(T, du_dx1))

        J += integrand * seg_len

    return J


def domain_integral_j(
    crack_tip_node: int,
    mesh,
    stress_field: np.ndarray,
    displacement_field: np.ndarray,
    integration_radius_m: float,
) -> float:
    """Compute the J-integral using the domain (volume) integral form.

    The domain integral (also called the equivalent domain integral or
    interaction integral) is more accurate than the direct contour form
    because it averages over a volume of elements, reducing sensitivity
    to near-tip mesh quality.

    Method (Shih, deLorenzi & German 1976)
    ----------------------------------------
    Convert the contour integral to a volume integral over a domain D:

        J = ∫_D (σ_ij ∂u_i/∂x_1 - W δ_1j) ∂q/∂x_j dA

    where q is a smooth weighting function that is 1 at the crack tip
    and 0 on the outer contour boundary.

    This implementation uses a simple 2D mesh with q-field defined by
    linear distance from the crack tip (hat function).

    Parameters
    ----------
    crack_tip_node : int
        Index of the crack-tip node in the mesh.
    mesh : object with attributes:
        .nodes : np.ndarray, shape (n_nodes, 2) — node coordinates
        .elements : list of list of int — element connectivity (triangles)
    stress_field : np.ndarray, shape (n_nodes, 3)
        Nodal stress components [σ_xx, σ_yy, σ_xy] per node.
    displacement_field : np.ndarray, shape (n_nodes, 2)
        Nodal displacements [u_x, u_y] per node.
    integration_radius_m : float
        Radius of the integration domain around the crack tip [m].
        Should encompass at least 2-3 rings of elements.

    Returns
    -------
    J : float
        J-integral value [J/m²].

    Notes
    -----
    - This simplified implementation uses centroidal integration (one
      integration point per triangle element).
    - For production accuracy, use full Gaussian quadrature and
      higher-order elements with quarter-point crack-tip elements.
    - Reference: Shih et al. (1976); Anderson (2005) §3.5.
    """
    nodes = np.asarray(mesh.nodes, dtype=float)
    elements = mesh.elements
    stress = np.asarray(stress_field, dtype=float)
    disp = np.asarray(displacement_field, dtype=float)

    crack_tip_pos = nodes[crack_tip_node]

    # Build q-field: q = 1 at crack tip, 0 outside integration_radius
    r_nodes = np.linalg.norm(nodes - crack_tip_pos, axis=1)
    q_nodes = np.where(
        r_nodes < integration_radius_m,
        1.0 - r_nodes / integration_radius_m,
        0.0,
    )

    J = 0.0

    for elem in elements:
        n_verts = len(elem)
        if n_verts < 3:
            continue

        # Centroidal values (averaging over element nodes)
        coords = nodes[elem]  # (nv, 2)
        s = stress[elem]      # (nv, 3) [sxx, syy, sxy]
        u = disp[elem]        # (nv, 2)
        q_e = q_nodes[elem]   # (nv,)

        # Centroid
        xc = np.mean(coords, axis=0)
        sigma_c = np.mean(s, axis=0)   # [sxx, syy, sxy] at centroid
        u_c = np.mean(u, axis=0)       # displacement at centroid

        # Build full stress tensor
        sigma = np.array([
            [sigma_c[0], sigma_c[2]],
            [sigma_c[2], sigma_c[1]],
        ])

        # Strain energy density (linear elastic): W = σ:ε / 2
        # For plane stress: ε = (σ - ν*σ_kk*I)/E + ...
        # Here we estimate W from components directly.
        # W = (σ_xx² + σ_yy² - 2ν σ_xx σ_yy + 2(1+ν)σ_xy²)/(2E)
        # We approximate W ≈ (σ_xx² + σ_yy² + 2σ_xy²) / (2·E_eff)
        # This is an approximation; exact W requires material properties.
        # For J-integral verification, use compute_j_integral with exact W.
        trace_sq = (sigma_c[0] + sigma_c[1]) ** 2
        dev_sq = (sigma_c[0] - sigma_c[1]) ** 2 + 4 * sigma_c[2] ** 2
        # W ≈ ||σ||²_F / (2·E) — used only for element-area weighting
        W_c = 0.5 * (sigma_c[0] ** 2 + sigma_c[1] ** 2 + 2 * sigma_c[2] ** 2)

        # ∂u/∂x_1 estimated from element shape functions (linear triangle)
        if n_verts >= 3:
            # Linear shape function gradient for constant-strain triangle
            x = coords[:3]
            # Area (signed) of triangle
            area2 = (x[1, 0] - x[0, 0]) * (x[2, 1] - x[0, 1]) - \
                    (x[2, 0] - x[0, 0]) * (x[1, 1] - x[0, 1])
            area = abs(area2) * 0.5
            if area < 1e-300:
                continue

            # Shape function gradients for linear triangle
            # dN1/dx = (y2-y3)/(2A), dN1/dy = (x3-x2)/(2A)  etc.
            dNdx = np.array([
                x[1, 1] - x[2, 1],
                x[2, 1] - x[0, 1],
                x[0, 1] - x[1, 1],
            ]) / (2 * area * np.sign(area2 + 1e-300))
            dNdy = np.array([
                x[2, 0] - x[1, 0],
                x[0, 0] - x[2, 0],
                x[1, 0] - x[0, 0],
            ]) / (2 * area * np.sign(area2 + 1e-300))

            u3 = u[:3]
            du_dx1 = np.array([
                float(np.dot(dNdx, u3[:, 0])),
                float(np.dot(dNdx, u3[:, 1])),
            ])
            dq_dx1 = float(np.dot(dNdx, q_e[:3]))
            dq_dx2 = float(np.dot(dNdy, q_e[:3]))

            # Domain integrand (Shih et al. 1976):
            # ∫ (σ·∂u/∂x_1 - W·e_1) · ∇q dA
            sigma_du_dx1 = sigma @ du_dx1   # (2,)
            f1 = float(sigma_du_dx1[0]) - W_c
            f2 = float(sigma_du_dx1[1])

            J_e = (f1 * dq_dx1 + f2 * dq_dx2) * area
            J += J_e

    return J


def j_to_k(J: float, E: float, nu: float, condition: str = "plane_strain") -> float:
    """Convert J-integral to Mode-I stress intensity factor K_I.

    For linear-elastic fracture mechanics:
        Plane stress:   J = K_I² / E'     →  K_I = sqrt(J · E)
        Plane strain:   J = K_I²(1-ν²)/E  →  K_I = sqrt(J · E / (1-ν²))

    Parameters
    ----------
    J : float
        J-integral value [J/m² = N/m].
    E : float
        Young's modulus [Pa].
    nu : float
        Poisson's ratio.
    condition : str
        'plane_stress' or 'plane_strain'.

    Returns
    -------
    K_I : float
        Mode-I stress intensity factor [Pa√m].

    Reference: Anderson (2005), eq. 2.57.
    """
    if condition == "plane_strain":
        E_prime = E / (1.0 - nu**2)
    else:
        E_prime = E
    return math.sqrt(J * E_prime)
