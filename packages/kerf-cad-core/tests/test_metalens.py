"""
Tests for kerf_cad_core.optics.metalens — Zemax metalens design engine.

Test plan
---------
 1. test_hyperbolic_phase_monotone_decreasing
        design_hyperbolic_metalens with f=100mm, λ=532nm → target phase decreases
        (becomes more negative) monotonically with r from the centre outward.
 2. test_pillar_count_approx
        Metalens diameter=1mm, period=450nm → pillar count ≤ (D/period)² max.
 3. test_pillar_count_positive
        Any designed metalens has at least one pillar.
 4. test_rms_phase_error_below_pi_over_4
        For a well-designed TiO₂ lens, RMS phase error < π/4 rad.
 5. test_efficiency_positive
        Estimated efficiency is positive.
 6. test_efficiency_lte_100
        Estimated efficiency ≤ 100%.
 7. test_efficiency_at_design_wavelength_is_peak
        metalens_efficiency_at(design, λ_design) returns the design efficiency.
 8. test_efficiency_drops_off_design_wavelength
        metalens_efficiency_at at ±100 nm off design < efficiency at design λ.
 9. test_efficiency_at_far_off_wavelength_very_low
        At 2× design wavelength, efficiency is significantly reduced.
10. test_nanopillar_phase_target_in_range
        All NanoPillar.phase_target_rad are in [0, 2π).
11. test_nanopillar_radius_positive
        All NanoPillar.radius_nm > 0.
12. test_design_returns_metalens_design_type
        Return type is MetalensDesign.
13. test_spec_preserved
        MetalensDesign.spec matches the input spec.
14. test_phase_profile_length_matches_pillars
        len(target_phase_profile) == len(pillars).
15. test_unknown_material_raises
        Unknown pillar material raises ValueError.
16. test_unknown_substrate_raises
        Unknown substrate material raises ValueError.
17. test_633nm_red_laser
        Design at 633 nm, f=50 mm, d=2 mm completes without error.
18. test_si3n4_material
        design_hyperbolic_metalens with pillar_material='Si3N4' completes.
19. test_gan_material
        design_hyperbolic_metalens with pillar_material='GaN' completes.
20. test_phase_profile_array_dtype
        target_phase_profile and achieved_phase_profile are numpy float arrays.

All tests: pure-Python, no network, no DB, no OCC.

References
----------
Khorasaninejad, M. et al. (2016). "Metalenses at visible wavelengths."
    Science 352:1190–1194.
Aieta, F. et al. (2015). "Multiwavelength achromatic metasurfaces."
    Science 347:1342–1345.

Author: imranparuk
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.optics.metalens import (
    MetalensDesign,
    MetalensSpec,
    NanoPillar,
    design_hyperbolic_metalens,
    metalens_efficiency_at,
    _hyperbolic_phase,
    _wrap_phase,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def spec_532nm():
    """Standard TiO₂ metalens at 532 nm, f=100 mm, d=1 mm."""
    return MetalensSpec(
        diameter_mm=1.0,
        focal_length_mm=100.0,
        target_wavelength_nm=532.0,
        unit_cell_period_nm=450.0,
        pillar_material="TiO2",
        substrate_material="fused_silica",
        pillar_height_nm=600.0,
    )


@pytest.fixture
def design_532nm(spec_532nm):
    return design_hyperbolic_metalens(spec_532nm)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_hyperbolic_phase_monotone_decreasing(spec_532nm):
    """Phase profile decreases monotonically (becomes more negative) with r."""
    radii = np.linspace(0.001, spec_532nm.diameter_mm / 2, 20)
    phases = [_hyperbolic_phase(r, spec_532nm.focal_length_mm, spec_532nm.target_wavelength_nm)
              for r in radii]
    for i in range(len(phases) - 1):
        assert phases[i] > phases[i + 1], (
            f"Phase did not decrease at r index {i}: φ[{i}]={phases[i]:.4f}, φ[{i+1}]={phases[i+1]:.4f}"
        )


def test_pillar_count_approx(spec_532nm):
    """Pillar count ≤ (D/period_mm)² (maximum for a square grid fully inside circle)."""
    design = design_hyperbolic_metalens(spec_532nm)
    period_mm = spec_532nm.unit_cell_period_nm * 1e-6
    max_pillars = (spec_532nm.diameter_mm / period_mm) ** 2
    assert len(design.pillars) <= max_pillars * 1.05, (
        f"Pillar count {len(design.pillars)} > max {max_pillars:.0f}"
    )


def test_pillar_count_positive(design_532nm):
    """Design must have at least one pillar."""
    assert len(design_532nm.pillars) > 0


def test_rms_phase_error_below_pi_over_4(design_532nm):
    """RMS phase error < π/4 for a well-designed lens."""
    assert design_532nm.rms_phase_error_rad < math.pi / 4, (
        f"RMS phase error {design_532nm.rms_phase_error_rad:.4f} ≥ π/4={math.pi/4:.4f}"
    )


def test_efficiency_positive(design_532nm):
    """Estimated efficiency must be positive."""
    assert design_532nm.estimated_efficiency_pct > 0.0


def test_efficiency_lte_100(design_532nm):
    """Estimated efficiency cannot exceed 100%."""
    assert design_532nm.estimated_efficiency_pct <= 100.0


def test_efficiency_at_design_wavelength_is_peak(design_532nm):
    """metalens_efficiency_at at design wavelength ≈ design efficiency."""
    eta_at_design = metalens_efficiency_at(design_532nm, design_532nm.spec.target_wavelength_nm)
    eta_design = design_532nm.estimated_efficiency_pct
    assert abs(eta_at_design - eta_design) < 0.01, (
        f"η at design λ ({eta_at_design:.4f}) should match design η ({eta_design:.4f})"
    )


def test_efficiency_drops_off_design_wavelength(design_532nm):
    """Efficiency at ±100 nm off design < efficiency at design λ."""
    lambda_0 = design_532nm.spec.target_wavelength_nm
    eta_0 = metalens_efficiency_at(design_532nm, lambda_0)
    eta_plus = metalens_efficiency_at(design_532nm, lambda_0 + 100.0)
    eta_minus = metalens_efficiency_at(design_532nm, lambda_0 - 100.0)
    assert eta_plus < eta_0, f"Efficiency at λ+100 ({eta_plus:.3f}) should be less than η_0 ({eta_0:.3f})"
    assert eta_minus < eta_0, f"Efficiency at λ-100 ({eta_minus:.3f}) should be less than η_0 ({eta_0:.3f})"


def test_efficiency_at_far_off_wavelength_very_low(design_532nm):
    """At 2× design wavelength, efficiency drops significantly."""
    lambda_0 = design_532nm.spec.target_wavelength_nm
    eta_0 = metalens_efficiency_at(design_532nm, lambda_0)
    eta_far = metalens_efficiency_at(design_532nm, lambda_0 * 2.0)
    assert eta_far < eta_0 * 0.5, (
        f"Efficiency at 2×λ ({eta_far:.3f}) should be <50% of peak ({eta_0:.3f})"
    )


def test_nanopillar_phase_target_in_range(design_532nm):
    """All NanoPillar.phase_target_rad are in [0, 2π)."""
    two_pi = 2.0 * math.pi
    for p in design_532nm.pillars:
        assert 0.0 <= p.phase_target_rad < two_pi + 1e-9, (
            f"Phase {p.phase_target_rad:.4f} outside [0, 2π)"
        )


def test_nanopillar_radius_positive(design_532nm):
    """All NanoPillar.radius_nm must be positive."""
    for p in design_532nm.pillars:
        assert p.radius_nm > 0.0, f"Negative/zero radius {p.radius_nm}"


def test_design_returns_metalens_design_type(design_532nm):
    """design_hyperbolic_metalens returns a MetalensDesign instance."""
    assert isinstance(design_532nm, MetalensDesign)


def test_spec_preserved(spec_532nm, design_532nm):
    """MetalensDesign.spec is the same object as the input spec."""
    assert design_532nm.spec is spec_532nm


def test_phase_profile_length_matches_pillars(design_532nm):
    """len(target_phase_profile) == len(pillars)."""
    assert len(design_532nm.target_phase_profile) == len(design_532nm.pillars)
    assert len(design_532nm.achieved_phase_profile) == len(design_532nm.pillars)


def test_unknown_material_raises():
    """Unknown pillar material raises ValueError."""
    spec = MetalensSpec(
        diameter_mm=1.0,
        focal_length_mm=100.0,
        target_wavelength_nm=532.0,
        unit_cell_period_nm=450.0,
        pillar_material="Unobtainium",
        substrate_material="fused_silica",
        pillar_height_nm=600.0,
    )
    with pytest.raises(ValueError, match="Unknown pillar material"):
        design_hyperbolic_metalens(spec)


def test_unknown_substrate_raises():
    """Unknown substrate material raises ValueError."""
    spec = MetalensSpec(
        diameter_mm=1.0,
        focal_length_mm=100.0,
        target_wavelength_nm=532.0,
        unit_cell_period_nm=450.0,
        pillar_material="TiO2",
        substrate_material="kryptonite",
        pillar_height_nm=600.0,
    )
    with pytest.raises(ValueError, match="Unknown substrate material"):
        design_hyperbolic_metalens(spec)


def test_633nm_red_laser():
    """Design at 633 nm, f=50 mm, d=2 mm completes without error."""
    spec = MetalensSpec(
        diameter_mm=2.0,
        focal_length_mm=50.0,
        target_wavelength_nm=633.0,
        unit_cell_period_nm=550.0,
        pillar_material="TiO2",
        substrate_material="fused_silica",
        pillar_height_nm=700.0,
    )
    design = design_hyperbolic_metalens(spec)
    assert len(design.pillars) > 0
    assert design.rms_phase_error_rad >= 0.0


def test_si3n4_material():
    """design_hyperbolic_metalens with pillar_material='Si3N4' completes."""
    spec = MetalensSpec(
        diameter_mm=0.5,
        focal_length_mm=50.0,
        target_wavelength_nm=532.0,
        unit_cell_period_nm=400.0,
        pillar_material="Si3N4",
        substrate_material="fused_silica",
        pillar_height_nm=800.0,
    )
    design = design_hyperbolic_metalens(spec)
    assert isinstance(design, MetalensDesign)
    assert len(design.pillars) > 0


def test_gan_material():
    """design_hyperbolic_metalens with pillar_material='GaN' completes."""
    spec = MetalensSpec(
        diameter_mm=0.5,
        focal_length_mm=50.0,
        target_wavelength_nm=450.0,
        unit_cell_period_nm=380.0,
        pillar_material="GaN",
        substrate_material="sapphire",
        pillar_height_nm=500.0,
    )
    design = design_hyperbolic_metalens(spec)
    assert isinstance(design, MetalensDesign)
    assert len(design.pillars) > 0


def test_phase_profile_array_dtype(design_532nm):
    """target_phase_profile and achieved_phase_profile are numpy float arrays."""
    assert isinstance(design_532nm.target_phase_profile, np.ndarray)
    assert isinstance(design_532nm.achieved_phase_profile, np.ndarray)
    assert design_532nm.target_phase_profile.dtype.kind == "f"
    assert design_532nm.achieved_phase_profile.dtype.kind == "f"
