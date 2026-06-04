"""
Test suite for kerf_fem.contact.hertzian — Hertzian contact mechanics.

Coverage
--------
1.  Sphere-on-flat: contact radius a ∝ F^(1/3)
2.  Sphere-on-flat: peak pressure p_0 ∝ F^(1/3)
3.  Sphere-on-flat: contact depth δ ∝ F^(2/3)
4.  von Mises max occurs ≈ 0.48·a below surface (textbook)
5.  von Mises_max ≈ 0.60·p0 (Johnson 1985)
6.  Effective radius: sphere on flat = R1 (R2 → ∞)
7.  Higher load → larger contact area (monotonicity)
8.  Cylinder-on-flat: a ∝ sqrt(F)  (line contact)
9.  Cylinder-on-flat: p0 ∝ F (load per length)
10. Harder material (higher E) → smaller contact radius
11. Sphere-on-sphere: reduced radius 1/R* = 1/R1 + 1/R2
12. Result fields are all positive
13. Very compliant material (low E) → large contact area
14. Hertz 1882: a³ = 3FR*/(4E*) check
15. CT specimen: K_I formula increases with crack length
"""

from __future__ import annotations

import math
import pytest

from kerf_fem.contact.hertzian import (
    HertzianContactSpec,
    HertzianContactResult,
    hertzian_sphere_on_flat,
    hertzian_cylinder_on_flat,
    _reduced_modulus,
    _effective_radius,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

STEEL_E = 200e9     # Pa
STEEL_NU = 0.3

GLASS_E = 70e9      # Pa
GLASS_NU = 0.22

RUBBER_E = 1e6      # Pa
RUBBER_NU = 0.49

R1_MM = 10.0        # sphere radius
F_N = 100.0         # normal load


def make_sphere_spec(F=F_N, E1=STEEL_E, nu1=STEEL_NU,
                     E2=STEEL_E, nu2=STEEL_NU, R1=R1_MM):
    return HertzianContactSpec(
        geometry="sphere_on_flat",
        radius_1_mm=R1,
        radius_2_mm=1e9,        # flat
        E1_pa=E1,
        nu1=nu1,
        E2_pa=E2,
        nu2=nu2,
        normal_load_n=F,
    )


# ---------------------------------------------------------------------------
# 1. a ∝ F^(1/3)
# ---------------------------------------------------------------------------

def test_contact_radius_scales_as_F_cuberoot():
    res1 = hertzian_sphere_on_flat(make_sphere_spec(F=100.0))
    res8 = hertzian_sphere_on_flat(make_sphere_spec(F=800.0))
    # a ∝ F^(1/3): ratio should be (8)^(1/3) = 2
    ratio = res8.contact_radius_mm / res1.contact_radius_mm
    assert abs(ratio - 8 ** (1 / 3)) < 0.01, f"Expected 2.0, got {ratio:.4f}"


# ---------------------------------------------------------------------------
# 2. p_0 ∝ F^(1/3)
# ---------------------------------------------------------------------------

def test_peak_pressure_scales_as_F_cuberoot():
    res1 = hertzian_sphere_on_flat(make_sphere_spec(F=100.0))
    res8 = hertzian_sphere_on_flat(make_sphere_spec(F=800.0))
    # p0 ∝ F^(1/3): ratio = 8^(1/3) = 2
    ratio = res8.contact_pressure_max_pa / res1.contact_pressure_max_pa
    assert abs(ratio - 8 ** (1 / 3)) < 0.01, f"Expected 2.0, got {ratio:.4f}"


# ---------------------------------------------------------------------------
# 3. δ ∝ F^(2/3)
# ---------------------------------------------------------------------------

def test_contact_depth_scales_as_F_twothirds():
    res1 = hertzian_sphere_on_flat(make_sphere_spec(F=100.0))
    res8 = hertzian_sphere_on_flat(make_sphere_spec(F=800.0))
    # δ = a²/R ∝ F^(2/3): ratio = 8^(2/3) = 4
    ratio = res8.contact_depth_mm / res1.contact_depth_mm
    assert abs(ratio - 8 ** (2 / 3)) < 0.05, f"Expected 4.0, got {ratio:.4f}"


# ---------------------------------------------------------------------------
# 4. von Mises max depth ≈ 0.48·a
# ---------------------------------------------------------------------------

def test_von_mises_depth_is_0p48a():
    res = hertzian_sphere_on_flat(make_sphere_spec())
    ratio = res.von_mises_depth_mm / res.contact_radius_mm
    assert abs(ratio - 0.48) < 0.02, f"Expected ≈0.48, got {ratio:.4f}"


# ---------------------------------------------------------------------------
# 5. von Mises max ≈ 0.60·p0
# ---------------------------------------------------------------------------

def test_von_mises_max_is_0p60_p0():
    res = hertzian_sphere_on_flat(make_sphere_spec())
    ratio = res.von_mises_max_pa / res.contact_pressure_max_pa
    assert abs(ratio - 0.60) < 0.02, f"Expected ≈0.60, got {ratio:.4f}"


# ---------------------------------------------------------------------------
# 6. Effective radius: sphere on flat R* = R1
# ---------------------------------------------------------------------------

def test_effective_radius_sphere_on_flat():
    R1 = 10.0   # mm
    R2 = 1e9    # effectively infinite flat
    R_star = _effective_radius(R1, R2)
    assert abs(R_star - R1) / R1 < 1e-6, f"R* should ≈ R1={R1}, got {R_star}"


# ---------------------------------------------------------------------------
# 7. Monotonicity: higher load → larger contact area
# ---------------------------------------------------------------------------

def test_contact_radius_monotonically_increases_with_load():
    loads = [10.0, 50.0, 100.0, 500.0, 1000.0]
    radii = [hertzian_sphere_on_flat(make_sphere_spec(F=F)).contact_radius_mm for F in loads]
    for i in range(len(radii) - 1):
        assert radii[i + 1] > radii[i], "Contact radius must increase with load"


# ---------------------------------------------------------------------------
# 8. Cylinder-on-flat: a ∝ sqrt(F/L)
# ---------------------------------------------------------------------------

def test_cylinder_contact_width_scales_as_sqrt_F():
    cyl_spec = HertzianContactSpec(
        geometry="cylinder_on_flat",
        radius_1_mm=R1_MM,
        radius_2_mm=1e9,
        E1_pa=STEEL_E, nu1=STEEL_NU,
        E2_pa=STEEL_E, nu2=STEEL_NU,
        normal_load_n=100.0,
    )
    res1 = hertzian_cylinder_on_flat(cyl_spec, length_mm=10.0)
    cyl_spec.normal_load_n = 400.0
    res4 = hertzian_cylinder_on_flat(cyl_spec, length_mm=10.0)
    # a ∝ sqrt(F): 4× load → 2× width
    ratio = res4.contact_radius_mm / res1.contact_radius_mm
    assert abs(ratio - 2.0) < 0.05, f"Expected 2.0, got {ratio:.4f}"


# ---------------------------------------------------------------------------
# 9. Cylinder-on-flat: p0 ∝ sqrt(F) (for same length)
# ---------------------------------------------------------------------------

def test_cylinder_pressure_scales_as_sqrt_F():
    cyl_spec = HertzianContactSpec(
        geometry="cylinder_on_flat",
        radius_1_mm=R1_MM,
        radius_2_mm=1e9,
        E1_pa=STEEL_E, nu1=STEEL_NU,
        E2_pa=STEEL_E, nu2=STEEL_NU,
        normal_load_n=100.0,
    )
    L = 10.0
    res1 = hertzian_cylinder_on_flat(cyl_spec, length_mm=L)
    cyl_spec.normal_load_n = 400.0
    res4 = hertzian_cylinder_on_flat(cyl_spec, length_mm=L)
    # p0 = 2F/(π·a·L); a ∝ sqrt(F) → p0 ∝ F/sqrt(F) = sqrt(F)
    ratio = res4.contact_pressure_max_pa / res1.contact_pressure_max_pa
    assert abs(ratio - 2.0) < 0.1, f"Expected ≈2.0, got {ratio:.4f}"


# ---------------------------------------------------------------------------
# 10. Higher E → smaller contact radius (stiffer → less deformation)
# ---------------------------------------------------------------------------

def test_higher_modulus_gives_smaller_contact_area():
    res_steel = hertzian_sphere_on_flat(make_sphere_spec(E1=STEEL_E))
    res_glass = hertzian_sphere_on_flat(make_sphere_spec(E1=GLASS_E))  # softer than steel
    # Glass has lower E → should have larger contact area
    assert res_glass.contact_radius_mm > res_steel.contact_radius_mm


# ---------------------------------------------------------------------------
# 11. Sphere-on-sphere: 1/R* = 1/R1 + 1/R2
# ---------------------------------------------------------------------------

def test_sphere_on_sphere_reduced_radius():
    R1, R2 = 10.0, 20.0
    R_star = _effective_radius(R1, R2)
    expected = 1.0 / (1.0 / R1 + 1.0 / R2)
    assert abs(R_star - expected) < 1e-10


# ---------------------------------------------------------------------------
# 12. All result fields are positive
# ---------------------------------------------------------------------------

def test_all_result_fields_positive():
    res = hertzian_sphere_on_flat(make_sphere_spec())
    assert res.contact_pressure_max_pa > 0
    assert res.contact_radius_mm > 0
    assert res.contact_depth_mm > 0
    assert res.von_mises_max_pa > 0
    assert res.von_mises_depth_mm > 0


# ---------------------------------------------------------------------------
# 13. Very compliant material (low E) → large contact area
# ---------------------------------------------------------------------------

def test_compliant_material_large_contact():
    res_steel = hertzian_sphere_on_flat(make_sphere_spec(E1=STEEL_E, E2=STEEL_E))
    res_rubber = hertzian_sphere_on_flat(make_sphere_spec(E1=RUBBER_E, E2=STEEL_E))
    assert res_rubber.contact_radius_mm > res_steel.contact_radius_mm * 10


# ---------------------------------------------------------------------------
# 14. Verify Hertz formula: a³ = 3FR*/(4E*)
# ---------------------------------------------------------------------------

def test_hertz_formula_a_cubed():
    F = 100.0  # N
    R1_m = R1_MM * 1e-3
    E_star = _reduced_modulus(STEEL_E, STEEL_NU, STEEL_E, STEEL_NU)
    R_star_m = R1_m  # flat surface

    a_expected_m = (3.0 * F * R_star_m / (4.0 * E_star)) ** (1.0 / 3.0)
    res = hertzian_sphere_on_flat(make_sphere_spec(F=F))
    a_computed_m = res.contact_radius_mm * 1e-3

    rel_err = abs(a_computed_m - a_expected_m) / a_expected_m
    assert rel_err < 1e-7, f"Hertz formula mismatch: rel_err={rel_err:.2e}"


# ---------------------------------------------------------------------------
# 15. Bad geometry raises ValueError
# ---------------------------------------------------------------------------

def test_bad_geometry_raises():
    spec = HertzianContactSpec(
        geometry="cube_on_flat",  # invalid
        radius_1_mm=10.0, radius_2_mm=1e9,
        E1_pa=STEEL_E, nu1=STEEL_NU,
        E2_pa=STEEL_E, nu2=STEEL_NU,
        normal_load_n=100.0,
    )
    with pytest.raises(ValueError, match="geometry"):
        hertzian_sphere_on_flat(spec)
