"""
Hertzian contact mechanics — closed-form solutions.

Implements sphere-on-flat, cylinder-on-flat, and sphere-on-sphere contact
using the classical Hertz (1882) theory.

References
----------
  Hertz, H. (1882). "Ueber die Beruehrung fester elastischer Koerper."
      J. reine angew. Math. 92, 156-171.
  Johnson, K. L. (1985). "Contact Mechanics." Cambridge University Press.
      Chapter 3 (spherical contact) and Chapter 4 (cylindrical contact).

NOTE: This is a closed-form elastic solution. Elasto-plastic contact,
adhesion (JKR/DMT), rough-surface (Greenwood-Williamson), or dynamic
impact requires extensions beyond this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class HertzianContactSpec:
    """Parameters for a Hertzian contact problem.

    Parameters
    ----------
    geometry : str
        Contact geometry. One of:
          'sphere_on_flat'    — sphere (radius_1_mm) on infinite half-space
          'cylinder_on_flat'  — cylinder (radius_1_mm) on infinite half-space
          'sphere_on_sphere'  — two spheres (radius_1_mm, radius_2_mm)
    radius_1_mm : float
        Radius of body 1 [mm]. For a sphere: sphere radius.
    radius_2_mm : float
        Radius of body 2 [mm]. Use 1e9 for a flat surface.
    E1_pa : float
        Young's modulus of body 1 [Pa].
    nu1 : float
        Poisson's ratio of body 1 (dimensionless).
    E2_pa : float
        Young's modulus of body 2 [Pa].
    nu2 : float
        Poisson's ratio of body 2 (dimensionless).
    normal_load_n : float
        Applied normal load [N].
    """
    geometry: str
    radius_1_mm: float
    radius_2_mm: float
    E1_pa: float
    nu1: float
    E2_pa: float
    nu2: float
    normal_load_n: float


@dataclass
class HertzianContactResult:
    """Results from a Hertzian contact analysis.

    Parameters
    ----------
    contact_pressure_max_pa : float
        Peak contact pressure p_0 at the centre of the contact zone [Pa].
    contact_radius_mm : float
        Half-contact radius (sphere/sphere) or half-width (cylinder) [mm].
    contact_depth_mm : float
        Total elastic approach (rigid-body indentation) δ [mm].
    von_mises_max_pa : float
        Maximum von Mises stress below the surface [Pa].
        For sphere contact: occurs at approximately 0.48·a depth
        (Johnson 1985, §4.2).
    von_mises_depth_mm : float
        Depth below the surface at which maximum von Mises stress occurs [mm].
    """
    contact_pressure_max_pa: float
    contact_radius_mm: float
    contact_depth_mm: float
    von_mises_max_pa: float
    von_mises_depth_mm: float


def _reduced_modulus(E1: float, nu1: float, E2: float, nu2: float) -> float:
    """Compute the combined (reduced) modulus E*.

    E* = ((1 - ν1²)/E1 + (1 - ν2²)/E2)⁻¹

    Reference: Johnson (1985), eq. 4.22.
    """
    return 1.0 / ((1.0 - nu1**2) / E1 + (1.0 - nu2**2) / E2)


def _effective_radius(R1_mm: float, R2_mm: float) -> float:
    """Compute the effective radius R*.

    For sphere-on-sphere:  1/R* = 1/R1 + 1/R2
    For sphere-on-flat:   R2 → ∞, so R* = R1

    Returns R* in the same units as the input radii.
    """
    return 1.0 / (1.0 / R1_mm + 1.0 / R2_mm)


def _sphere_von_mises_subsurface(p0: float, a_m: float) -> tuple[float, float]:
    """Estimate maximum subsurface von Mises stress for spherical contact.

    For a Hertzian pressure distribution on a sphere contact, the maximum
    von Mises equivalent stress occurs below the surface at depth ≈ 0.48·a.
    This is the well-known result from Johnson (1985) §4.2, Table 4.1.

    Approximate formula (isotropic half-space, ν ≈ 0.3):
        σ_VM_max ≈ 0.60 · p0   at z ≈ 0.48 · a

    Parameters
    ----------
    p0 : float
        Maximum contact pressure [Pa].
    a_m : float
        Contact radius [m].

    Returns
    -------
    (von_mises_max_pa, depth_m)
    """
    # Johnson 1985 §4.2: maximum shear stress τ_max ≈ 0.31·p0 at z ≈ 0.48·a
    # von Mises = sqrt(3) · τ_max for pure shear, but the actual subsurface
    # stress state is triaxial. The accepted factor is σ_VM ≈ 0.60·p0.
    von_mises_max = 0.60 * p0
    depth_m = 0.48 * a_m
    return von_mises_max, depth_m


def hertzian_sphere_on_flat(spec: HertzianContactSpec) -> HertzianContactResult:
    """Hertz (1882) closed-form solution for sphere on flat (or sphere on sphere).

    Geometry
    --------
    A sphere of radius R1 pressed against a flat surface (R2 → ∞) or
    another sphere of radius R2 under normal load F.

    Formulae (Johnson 1985, Ch. 3)
    --------------------------------
        E* = ((1-ν1²)/E1 + (1-ν2²)/E2)⁻¹          [Pa]
        R* = (1/R1 + 1/R2)⁻¹                         [m]
        a  = (3·F·R*/(4·E*))^(1/3)                   [m]  contact radius
        p0 = 3F/(2π·a²)                               [Pa] peak pressure
        δ  = a²/R*                                    [m]  mutual approach

    Parameters
    ----------
    spec : HertzianContactSpec
        Contact parameters. geometry must be 'sphere_on_flat' or
        'sphere_on_sphere'.

    Returns
    -------
    HertzianContactResult
    """
    if spec.geometry not in ("sphere_on_flat", "sphere_on_sphere"):
        raise ValueError(
            f"hertzian_sphere_on_flat: geometry must be 'sphere_on_flat' or "
            f"'sphere_on_sphere', got '{spec.geometry}'"
        )

    F = spec.normal_load_n
    if F <= 0:
        raise ValueError("normal_load_n must be positive")

    # Convert mm → m
    R1_m = spec.radius_1_mm * 1e-3
    R2_m = spec.radius_2_mm * 1e-3

    E_star = _reduced_modulus(spec.E1_pa, spec.nu1, spec.E2_pa, spec.nu2)
    R_star_m = 1.0 / (1.0 / R1_m + 1.0 / R2_m)

    # Contact radius (Hertz 1882)
    a_m = (3.0 * F * R_star_m / (4.0 * E_star)) ** (1.0 / 3.0)

    # Peak contact pressure
    p0_pa = 3.0 * F / (2.0 * math.pi * a_m**2)

    # Mutual approach (indentation depth)
    delta_m = a_m**2 / R_star_m

    # Subsurface von Mises
    vm_max, vm_depth_m = _sphere_von_mises_subsurface(p0_pa, a_m)

    return HertzianContactResult(
        contact_pressure_max_pa=p0_pa,
        contact_radius_mm=a_m * 1e3,
        contact_depth_mm=delta_m * 1e3,
        von_mises_max_pa=vm_max,
        von_mises_depth_mm=vm_depth_m * 1e3,
    )


def hertzian_cylinder_on_flat(
    spec: HertzianContactSpec, length_mm: float
) -> HertzianContactResult:
    """Hertz (1882) closed-form solution for cylinder on flat (line contact).

    Geometry
    --------
    An infinitely long cylinder of radius R1 in contact with a flat
    surface over length L. This is 'plane strain' line contact.

    Formulae (Johnson 1985, Ch. 4)
    --------------------------------
        E* = ((1-ν1²)/E1 + (1-ν2²)/E2)⁻¹         [Pa]
        a  = sqrt(4·F·R*/(π·E*·L))                 [m]  half-contact width
        p0 = 2·F/(π·a·L)                            [Pa] peak pressure
        δ  = (F/(π·E*·L)) · (1 + 2·ln(4R*/a))      [m]  approach (approximate)

    where F/L is the load per unit length.

    NOTE: δ for line contact is computed as the approach between two remote
    points (not a material quantity). The formula given is the Hertz approach
    referenced to R* (Johnson 1985, eq. 4.28a).

    Parameters
    ----------
    spec : HertzianContactSpec
        Contact parameters. geometry should be 'cylinder_on_flat'.
    length_mm : float
        Contact length L [mm].

    Returns
    -------
    HertzianContactResult
        contact_radius_mm contains the half-contact *width* a (not a circular
        radius). contact_depth_mm contains the mutual approach δ.
    """
    if length_mm <= 0:
        raise ValueError("length_mm must be positive")
    if spec.normal_load_n <= 0:
        raise ValueError("normal_load_n must be positive")

    F = spec.normal_load_n
    L_m = length_mm * 1e-3
    R1_m = spec.radius_1_mm * 1e-3
    R2_m = spec.radius_2_mm * 1e-3  # 1e9 mm → ~1 m for flat

    E_star = _reduced_modulus(spec.E1_pa, spec.nu1, spec.E2_pa, spec.nu2)
    R_star_m = 1.0 / (1.0 / R1_m + 1.0 / R2_m)

    # Half-contact width (Johnson 1985, eq. 4.24)
    a_m = math.sqrt(4.0 * F * R_star_m / (math.pi * E_star * L_m))

    # Peak contact pressure (Johnson 1985, eq. 4.25)
    p0_pa = 2.0 * F / (math.pi * a_m * L_m)

    # Mutual approach (Johnson 1985, eq. 4.28a, simplified)
    # δ = (F/(π E* L)) · (1 + 2·ln(4R*/a))
    ratio = 4.0 * R_star_m / a_m
    if ratio <= 1.0:
        ratio = math.e  # avoid log(<=0); degenerate case
    delta_m = (F / (math.pi * E_star * L_m)) * (1.0 + 2.0 * math.log(ratio))

    # Subsurface von Mises for line contact:
    # Maximum shear stress ≈ 0.30·p0 at z ≈ 0.78·a (Johnson 1985, §4.3)
    # Approximate σ_VM ≈ 0.558·p0 (plane strain factor)
    von_mises_max = 0.558 * p0_pa
    vm_depth_m = 0.785 * a_m  # 0.78·a

    return HertzianContactResult(
        contact_pressure_max_pa=p0_pa,
        contact_radius_mm=a_m * 1e3,
        contact_depth_mm=delta_m * 1e3,
        von_mises_max_pa=von_mises_max,
        von_mises_depth_mm=vm_depth_m * 1e3,
    )
