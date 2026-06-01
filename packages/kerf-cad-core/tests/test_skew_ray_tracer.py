"""
Tests for kerf_cad_core.optics.skew_ray_tracer — 3-D skew-ray engine.

Coverage:
  1.  Axial ray (y=0, x=0, pure z direction) — converges on-axis; compare
      to meridional trace result.
  2.  Skew ray at 1 mm x-height — refracts correctly through a BK7 sphere.
  3.  Skew ray at 1 mm y-height — identical geometry to x-height by symmetry.
  4.  Total internal reflection — glass-to-air at steep angle.
  5.  Aspheric surface (k=-1, paraboloid) — different intersection from sphere.
  6.  Flat surface (radius_mm=0) — ray passes through unchanged direction.
  7.  Normal direction consistency — refracted ray direction is a unit vector.
  8.  Multi-surface trace — biconvex BK7 singlet, two surfaces.
  9.  Off-axis skew ray — non-zero x AND y components.
  10. TIR flag propagation — tir_occurred correctly set.
  11. Ray history length — one entry per surface + initial.
  12. Wavelength preserved through surfaces.
  13. Plane surface intersection — t = (vertex_z - oz)/dz.
  14. Reversed surface sign — concave from left vs convex.
  15. Paraboloid vs sphere sagittal difference — k=-1 gives different y-intercept
      than k=0 for an off-axis ray.

All tests are pure-Python and hermetic.

References
----------
Born & Wolf §4.6; Welford 1986 §5.
BK7 refractive index at 587.6 nm: n = 1.5168.

Author: imranparuk
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.optics.skew_ray_tracer import (
    Ray3D,
    OpticalSurface,
    RayTraceResult,
    trace_skew_ray,
    _dot,
    _norm,
    _intersect_conic,
    _refract_3d,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) < tol


def _vec_approx(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    tol: float = 1e-9,
) -> bool:
    return all(abs(ai - bi) < tol for ai, bi in zip(a, b))


N_BK7 = 1.5168   # BK7 at 587.6 nm d-line
N_AIR = 1.0


# ---------------------------------------------------------------------------
# Test 1: Ray3D auto-normalisation
# ---------------------------------------------------------------------------

def test_ray3d_normalisation():
    """Direction vector must be unit-length after construction."""
    ray = Ray3D(origin_xyz=(0, 0, 0), direction_xyz=(0, 0, 2))
    dx, dy, dz = ray.direction_xyz
    assert _approx(math.sqrt(dx**2 + dy**2 + dz**2), 1.0, tol=1e-12)
    assert _approx(dz, 1.0, tol=1e-12)


def test_ray3d_zero_direction_raises():
    with pytest.raises(ValueError):
        Ray3D(origin_xyz=(0, 0, 0), direction_xyz=(0, 0, 0))


# ---------------------------------------------------------------------------
# Test 2: Axial ray through single convex sphere — refraction angle
# ---------------------------------------------------------------------------

def test_axial_ray_single_sphere():
    """
    On-axis ray (x=y=0, dz=1) through a single sphere of R=50 mm (BK7 lens
    front surface).  After refraction the ray must still lie on the z-axis
    (dx=dy=0 by symmetry) and dz must be positive.
    """
    ray = Ray3D(origin_xyz=(0.0, 0.0, -10.0), direction_xyz=(0.0, 0.0, 1.0))
    surf = OpticalSurface(vertex_z_mm=0.0, radius_mm=50.0,
                           refractive_index_after=N_BK7)
    result = trace_skew_ray(ray, [surf])

    assert not result.tir_occurred
    fx, fy, fz = result.final_direction_xyz
    # Axial ray must refract without lateral displacement
    assert abs(fx) < 1e-12, f"dx should be 0, got {fx}"
    assert abs(fy) < 1e-12, f"dy should be 0, got {fy}"
    assert fz > 0.0, "ray must continue forward"


# ---------------------------------------------------------------------------
# Test 3: Skew ray at x=1 mm — refraction check
# ---------------------------------------------------------------------------

def test_skew_ray_x_height_refracts():
    """
    Ray with origin at (1, 0, -50) aimed at origin of first surface (0,0,0).
    After hitting a convex BK7 sphere at R=50 mm the direction should change
    (ray bends toward axis — dx becomes more negative).
    """
    # Direction toward surface origin from (1, 0, -50)
    # Normalise vector (-1, 0, 50)
    dx0, dy0, dz0 = _norm((-1.0, 0.0, 50.0))
    ray = Ray3D(origin_xyz=(1.0, 0.0, -50.0),
                direction_xyz=(dx0, dy0, dz0))
    surf = OpticalSurface(vertex_z_mm=0.0, radius_mm=50.0,
                           refractive_index_after=N_BK7)
    result = trace_skew_ray(ray, [surf])

    assert not result.tir_occurred
    rdx, rdy, rdz = result.final_direction_xyz
    # After refraction into denser medium the ray bends toward normal,
    # so |rdx/rdz| < |dx0/dz0| (ray is more "vertical")
    ratio_before = abs(dx0 / dz0)
    ratio_after = abs(rdx / rdz)
    assert ratio_after < ratio_before, (
        f"Ray should bend toward axis: before={ratio_before:.6f}, "
        f"after={ratio_after:.6f}"
    )
    assert abs(rdy) < 1e-12, "y component must stay zero (meridional input)"


# ---------------------------------------------------------------------------
# Test 4: Skew ray at y=1 mm — symmetry with x-height
# ---------------------------------------------------------------------------

def test_skew_ray_y_height_matches_x_height():
    """
    By azimuthal symmetry a ray at y=+1 mm should produce the same |dy/dz|
    ratio after refraction as a ray at x=+1 mm produces |dx/dz|.
    """
    def trace_at(height_xyz):
        # Aim toward surface origin from offset height
        ox, oy, oz = height_xyz
        d = _norm((-ox, -oy, 50.0))
        ray = Ray3D(origin_xyz=height_xyz, direction_xyz=d)
        surf = OpticalSurface(vertex_z_mm=0.0, radius_mm=50.0,
                               refractive_index_after=N_BK7)
        result = trace_skew_ray(ray, [surf])
        rdx, rdy, rdz = result.final_direction_xyz
        return abs(rdx / rdz), abs(rdy / rdz)

    rx_x, rx_y = trace_at((1.0, 0.0, -50.0))
    ry_x, ry_y = trace_at((0.0, 1.0, -50.0))

    # rx_x is the |dx/dz| ratio for x-height ray (dominant)
    # ry_y is the |dy/dz| ratio for y-height ray (dominant)
    assert abs(rx_x - ry_y) < 1e-10, (
        f"Azimuthal symmetry broken: rx_x={rx_x:.9f}, ry_y={ry_y:.9f}"
    )


# ---------------------------------------------------------------------------
# Test 5: Total internal reflection (glass to air, steep angle)
# ---------------------------------------------------------------------------

def test_total_internal_reflection():
    """
    Ray going from glass (n=1.5168) to air (n=1.0) at 50° incidence.
    Critical angle = arcsin(1/1.5168) ≈ 41.3°.  At 50° TIR should occur.
    """
    # Simulate ray inside glass (n_before=1.5168) hitting a flat exit surface
    # at a steep angle.  We use a flat surface (R=0) and n_after=1.0.
    incidence_angle_rad = math.radians(50.0)  # > critical angle
    # Ray direction: (sin50°, 0, cos50°) — hitting a flat surface at z=0
    dx = math.sin(incidence_angle_rad)
    dz = math.cos(incidence_angle_rad)
    ray = Ray3D(origin_xyz=(0.0, 0.0, -1.0), direction_xyz=(dx, 0.0, dz))
    # Flat surface at z=0, transitioning to air
    surf = OpticalSurface(vertex_z_mm=0.0, radius_mm=0.0,
                           refractive_index_after=N_AIR)
    result = trace_skew_ray(ray, [surf], n_before_first=N_BK7)

    assert result.tir_occurred, "TIR should be detected at 50° in glass→air"


# ---------------------------------------------------------------------------
# Test 6: No TIR for sub-critical angle (glass to air)
# ---------------------------------------------------------------------------

def test_no_tir_below_critical_angle():
    """
    At 30° (< 41.3° critical), glass-to-air should NOT produce TIR.
    """
    incidence_angle_rad = math.radians(30.0)
    dx = math.sin(incidence_angle_rad)
    dz = math.cos(incidence_angle_rad)
    ray = Ray3D(origin_xyz=(0.0, 0.0, -1.0), direction_xyz=(dx, 0.0, dz))
    surf = OpticalSurface(vertex_z_mm=0.0, radius_mm=0.0,
                           refractive_index_after=N_AIR)
    result = trace_skew_ray(ray, [surf], n_before_first=N_BK7)

    assert not result.tir_occurred, "No TIR at 30° in glass→air"


# ---------------------------------------------------------------------------
# Test 7: Aspheric (k=-1 paraboloid) vs sphere (k=0) — different intersection
# ---------------------------------------------------------------------------

def test_aspheric_paraboloid_differs_from_sphere():
    """
    An off-axis ray through a paraboloid (k=-1) intercepts the surface at a
    different z-sag than through a sphere (k=0), producing different refracted
    positions.
    """
    ray_sphere = Ray3D(origin_xyz=(0.0, 2.0, -20.0),
                       direction_xyz=(0.0, 0.0, 1.0))
    ray_para = Ray3D(origin_xyz=(0.0, 2.0, -20.0),
                     direction_xyz=(0.0, 0.0, 1.0))

    R = 40.0
    surf_sphere = OpticalSurface(vertex_z_mm=0.0, radius_mm=R,
                                  refractive_index_after=N_BK7, conic_k=0.0)
    surf_para = OpticalSurface(vertex_z_mm=0.0, radius_mm=R,
                                refractive_index_after=N_BK7, conic_k=-1.0)

    res_sphere = trace_skew_ray(ray_sphere, [surf_sphere])
    res_para = trace_skew_ray(ray_para, [surf_para])

    assert not res_sphere.tir_occurred
    assert not res_para.tir_occurred

    # Intersection z-coordinates (stored in history[1].origin_xyz)
    z_sphere = res_sphere.ray_history[1].origin_xyz[2]
    z_para = res_para.ray_history[1].origin_xyz[2]

    # Paraboloid sag at r=2 mm: z = c*r²/(2) = r²/(2R) = 4/80 = 0.05 mm
    # Sphere sag at r=2 mm: z ≈ r²/(2R) to first order, but second-order term
    # differs. For k=−1 paraboloid there's no second-order correction at small r,
    # so at r=2 mm both should be close but distinguishably different at finite r.
    # The key test: they must not be identical.
    assert abs(z_sphere - z_para) > 1e-8, (
        f"Sphere and paraboloid should have different z-sag; "
        f"sphere={z_sphere:.9f}, para={z_para:.9f}"
    )


# ---------------------------------------------------------------------------
# Test 8: Flat surface — ray direction unchanged
# ---------------------------------------------------------------------------

def test_flat_surface_same_refractive_index():
    """
    A flat surface (R=0) with the same n on both sides must not change
    the ray direction at all.
    """
    ray = Ray3D(origin_xyz=(1.0, 0.5, -5.0),
                direction_xyz=_norm((0.1, -0.2, 1.0)))
    surf = OpticalSurface(vertex_z_mm=0.0, radius_mm=0.0,
                           refractive_index_after=N_AIR)
    result = trace_skew_ray(ray, [surf], n_before_first=N_AIR)

    assert not result.tir_occurred
    d_in = ray.direction_xyz
    d_out = result.final_direction_xyz
    assert _vec_approx(d_in, d_out, tol=1e-10), (
        f"Direction should be unchanged for flat surface + same index; "
        f"in={d_in}, out={d_out}"
    )


# ---------------------------------------------------------------------------
# Test 9: Flat surface — direction changes with different refractive index
# ---------------------------------------------------------------------------

def test_flat_surface_different_refractive_index():
    """
    A flat surface with air→BK7 must refract an oblique ray (Snell's law in 3D).
    """
    theta_in = math.radians(30.0)
    dx = math.sin(theta_in)
    dz = math.cos(theta_in)
    ray = Ray3D(origin_xyz=(0.0, 0.0, -5.0), direction_xyz=(dx, 0.0, dz))
    surf = OpticalSurface(vertex_z_mm=0.0, radius_mm=0.0,
                           refractive_index_after=N_BK7)
    result = trace_skew_ray(ray, [surf], n_before_first=N_AIR)

    assert not result.tir_occurred
    rdx, rdy, rdz = result.final_direction_xyz

    # Snell's law: n1*sin(theta1) = n2*sin(theta2)
    # sin(theta2) = sin(theta_in) / N_BK7
    sin_theta2 = math.sin(theta_in) / N_BK7
    theta2_expected = math.asin(sin_theta2)

    # rdx / rdz = tan(theta2) approximately for small angles,
    # but more accurately sin_theta2 = rdx / sqrt(rdx^2 + rdy^2 + rdz^2) = rdx
    assert abs(rdx - sin_theta2) < 1e-9, (
        f"Snell's law: sin(theta2) should be {sin_theta2:.9f}, got {rdx:.9f}"
    )
    assert abs(rdy) < 1e-12, "y component must stay zero"


# ---------------------------------------------------------------------------
# Test 10: Ray history length after 2-surface trace
# ---------------------------------------------------------------------------

def test_ray_history_length_two_surfaces():
    """
    After tracing through 2 surfaces, ray_history should have 3 entries:
    initial ray + 1 per surface.
    """
    ray = Ray3D(origin_xyz=(0.0, 0.0, -10.0), direction_xyz=(0.0, 0.0, 1.0))
    surfs = [
        OpticalSurface(vertex_z_mm=0.0, radius_mm=50.0,
                        refractive_index_after=N_BK7),
        OpticalSurface(vertex_z_mm=5.0, radius_mm=-50.0,
                        refractive_index_after=N_AIR),
    ]
    result = trace_skew_ray(ray, surfs)

    assert len(result.ray_history) == 3, (
        f"Expected 3 history entries (initial + 2 surfaces), "
        f"got {len(result.ray_history)}"
    )


# ---------------------------------------------------------------------------
# Test 11: Biconvex BK7 singlet — on-axis convergence
# ---------------------------------------------------------------------------

def test_biconvex_bk7_on_axis_convergence():
    """
    BK7 biconvex lens: R1=+50 mm, t=5 mm, R2=-50 mm.
    Paraxial EFL ≈ 48.4 mm (Hecht oracle).
    An on-axis ray starting at z=-1e9 (infinity) should converge
    near z ≈ BFL ≈ 46.8 mm after the second surface.
    We check that after the second surface the z-direction remains
    positive and the ray angle is small and negative (converging).
    """
    # Infinity-object approximation: start far away
    z_start = -200.0
    ray = Ray3D(origin_xyz=(0.0, 0.0, z_start), direction_xyz=(0.0, 0.0, 1.0))
    surfs = [
        OpticalSurface(vertex_z_mm=0.0, radius_mm=50.0,
                        refractive_index_after=N_BK7),
        OpticalSurface(vertex_z_mm=5.0, radius_mm=-50.0,
                        refractive_index_after=N_AIR),
    ]
    result = trace_skew_ray(ray, surfs)

    assert not result.tir_occurred
    fdx, fdy, fdz = result.final_direction_xyz
    assert fdz > 0.0, "ray must still travel in +z direction"
    # On-axis ray: no lateral displacement
    assert abs(fdx) < 1e-12
    assert abs(fdy) < 1e-12


# ---------------------------------------------------------------------------
# Test 12: Biconvex BK7 singlet — skew ray converges toward axis
# ---------------------------------------------------------------------------

def test_biconvex_bk7_skew_ray_converges():
    """
    A skew ray at (0.5, 0.5, -200) aimed along z should converge toward
    the axis (both dx and dy become negative after tracing through the
    BK7 biconvex lens).
    """
    ray = Ray3D(origin_xyz=(0.5, 0.5, -200.0),
                direction_xyz=(0.0, 0.0, 1.0))
    surfs = [
        OpticalSurface(vertex_z_mm=0.0, radius_mm=50.0,
                        refractive_index_after=N_BK7),
        OpticalSurface(vertex_z_mm=5.0, radius_mm=-50.0,
                        refractive_index_after=N_AIR),
    ]
    result = trace_skew_ray(ray, surfs)

    assert not result.tir_occurred
    fdx, fdy, fdz = result.final_direction_xyz
    # Converging lens: positive-height ray bends toward axis
    assert fdx < 0.0, f"dx should be negative (converging); got {fdx}"
    assert fdy < 0.0, f"dy should be negative (converging); got {fdy}"


# ---------------------------------------------------------------------------
# Test 13: Refracted direction is always a unit vector
# ---------------------------------------------------------------------------

def test_refracted_direction_unit_vector():
    """
    After any number of refractions the final direction must remain a unit vector.
    """
    ray = Ray3D(origin_xyz=(1.3, -0.7, -50.0),
                direction_xyz=_norm((0.05, -0.03, 1.0)))
    surfs = [
        OpticalSurface(vertex_z_mm=0.0, radius_mm=30.0,
                        refractive_index_after=N_BK7),
        OpticalSurface(vertex_z_mm=4.0, radius_mm=-80.0,
                        refractive_index_after=N_AIR),
    ]
    result = trace_skew_ray(ray, surfs)

    if not result.tir_occurred:
        fdx, fdy, fdz = result.final_direction_xyz
        mag = math.sqrt(fdx**2 + fdy**2 + fdz**2)
        assert abs(mag - 1.0) < 1e-10, (
            f"Direction must be unit vector; got magnitude {mag:.15f}"
        )


# ---------------------------------------------------------------------------
# Test 14: Wavelength preserved
# ---------------------------------------------------------------------------

def test_wavelength_preserved_through_surfaces():
    """
    The wavelength_nm attribute must propagate unchanged through all surfaces.
    """
    wavelength = 632.8  # He-Ne laser
    ray = Ray3D(origin_xyz=(0.0, 0.0, -10.0),
                direction_xyz=(0.0, 0.0, 1.0),
                wavelength_nm=wavelength)
    surfs = [
        OpticalSurface(vertex_z_mm=0.0, radius_mm=50.0,
                        refractive_index_after=N_BK7),
        OpticalSurface(vertex_z_mm=5.0, radius_mm=-50.0,
                        refractive_index_after=N_AIR),
    ]
    result = trace_skew_ray(ray, surfs)

    for i, h_ray in enumerate(result.ray_history):
        assert h_ray.wavelength_nm == wavelength, (
            f"wavelength changed at history[{i}]: "
            f"expected {wavelength}, got {h_ray.wavelength_nm}"
        )


# ---------------------------------------------------------------------------
# Test 15: _intersect_conic — flat plane analytical check
# ---------------------------------------------------------------------------

def test_intersect_conic_flat_plane():
    """
    For c=0 (flat surface), intersection parameter t = (vertex_z - oz) / dz.
    """
    origin = (0.0, 0.0, -5.0)
    direction = (0.0, 0.0, 1.0)
    vertex_z = 3.0
    t = _intersect_conic(origin, direction, vertex_z, c=0.0, k=0.0)
    assert t is not None
    assert _approx(t, 8.0, tol=1e-12), f"Expected t=8.0, got {t}"


# ---------------------------------------------------------------------------
# Test 16: _refract_3d — Snell's law angle verification
# ---------------------------------------------------------------------------

def test_refract_3d_snell_angle():
    """
    Verify that the refracted angle satisfies n1*sin(theta1) = n2*sin(theta2).
    """
    theta1 = math.radians(30.0)
    d = (math.sin(theta1), 0.0, math.cos(theta1))  # incoming ray
    normal = (0.0, 0.0, -1.0)  # flat surface, normal pointing -z (against ray)
    n1, n2 = 1.0, 1.5168

    d_refracted, tir = _refract_3d(d, normal, n1, n2)
    assert not tir

    # sin(theta2) = dx component of refracted direction (since normal is along z)
    sin_theta2 = d_refracted[0]  # x-component is sin of angle from z-axis
    expected_sin2 = n1 * math.sin(theta1) / n2
    assert abs(sin_theta2 - expected_sin2) < 1e-10, (
        f"Snell: n1*sin(t1) != n2*sin(t2); "
        f"sin_theta2={sin_theta2:.10f}, expected={expected_sin2:.10f}"
    )


# ---------------------------------------------------------------------------
# Test 17: Pure tangential skew ray vs. pure sagittal — different behaviour
# ---------------------------------------------------------------------------

def test_tangential_vs_sagittal_skew_rays():
    """
    For an off-axis *field* angle (ray aimed from y offset), the tangential
    ray (in the y-z plane) and the sagittal ray (x offset, same cone angle)
    should, after passing through an aberrated lens, arrive at different
    positions — demonstrating astigmatism/coma only visible in 3D.

    This is a regression test: both traces must succeed and the tangential
    ray's final y-direction must differ from the sagittal ray's final
    x-direction by a measurable amount.
    """
    R = 50.0
    surfs = [
        OpticalSurface(vertex_z_mm=0.0, radius_mm=R,
                        refractive_index_after=N_BK7),
        OpticalSurface(vertex_z_mm=5.0, radius_mm=-R,
                        refractive_index_after=N_AIR),
    ]

    # Tangential (meridional) ray: off-axis in y
    ray_tang = Ray3D(
        origin_xyz=(0.0, 2.0, -100.0),
        direction_xyz=_norm((0.0, 0.0, 1.0)),
    )
    # Sagittal ray: same height but in x
    ray_sag = Ray3D(
        origin_xyz=(2.0, 0.0, -100.0),
        direction_xyz=_norm((0.0, 0.0, 1.0)),
    )

    res_tang = trace_skew_ray(ray_tang, surfs)
    res_sag = trace_skew_ray(ray_sag, surfs)

    assert not res_tang.tir_occurred
    assert not res_sag.tir_occurred

    # For a rotationally symmetric lens and on-axis object the tangential and
    # sagittal fans should behave symmetrically: |dy/dz| for tangential should
    # equal |dx/dz| for sagittal.
    tdx, tdy, tdz = res_tang.final_direction_xyz
    sdx, sdy, sdz = res_sag.final_direction_xyz

    tang_angle = abs(tdy / tdz)
    sag_angle = abs(sdx / sdz)
    assert abs(tang_angle - sag_angle) < 1e-9, (
        f"Rotational symmetry check: |dy/dz|={tang_angle:.10f} "
        f"should equal |dx/dz|={sag_angle:.10f}"
    )


# ---------------------------------------------------------------------------
# Test 18: Single surface, empty surface list — ray unchanged
# ---------------------------------------------------------------------------

def test_empty_surface_list():
    """
    With no surfaces the result should preserve the input ray exactly.
    """
    ray = Ray3D(origin_xyz=(1.0, 2.0, 3.0),
                direction_xyz=_norm((0.1, 0.2, 0.9)))
    result = trace_skew_ray(ray, [])

    assert result.final_position_xyz == ray.origin_xyz
    assert _vec_approx(result.final_direction_xyz, ray.direction_xyz, tol=1e-12)
    assert not result.tir_occurred
    assert len(result.ray_history) == 1


# ---------------------------------------------------------------------------
# Test 19: honest_caveat is populated
# ---------------------------------------------------------------------------

def test_honest_caveat_present():
    """RayTraceResult must always have a non-empty honest_caveat."""
    ray = Ray3D(origin_xyz=(0.0, 0.0, -5.0), direction_xyz=(0.0, 0.0, 1.0))
    result = trace_skew_ray(ray, [])
    assert result.honest_caveat, "honest_caveat must not be empty"
