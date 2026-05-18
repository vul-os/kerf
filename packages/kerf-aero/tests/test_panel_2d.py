"""Tests for the 2D linear-vortex panel method (panel_2d.py).

Physics references:
  NACA 0012, α = 5°: thin-airfoil theory → CL = 2π·sin(α) ≈ 0.548
  Acceptance: [0.45, 0.65] (panel method within ~20%)

  NACA 0012, α = 0°: symmetric → |CL| < 0.05

  NACA 4412, α = 0°: cambered → CL due to camber ≈ 0.4–0.5
  Acceptance: [0.3, 0.7]
"""
import math
import numpy as np
import pytest

from kerf_aero.panel_2d import panel_solve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def solve_naca(profile: str, alpha_deg: float, n_panels: int = 120) -> dict:
    return panel_solve(profile, alpha_deg, n_panels=n_panels)


# ---------------------------------------------------------------------------
# Symmetric airfoil (NACA 0012)
# ---------------------------------------------------------------------------

class TestPanel2DNACA0012:
    def test_symmetric_zero_alpha_cl(self):
        """NACA 0012 at α=0° must give |CL| < 0.05 (symmetric airfoil)."""
        result = solve_naca("0012", alpha_deg=0.0)
        CL = result["CL"]
        assert abs(CL) < 0.05, (
            f"NACA 0012 at α=0°: |CL|={abs(CL):.4f} exceeds 0.05; "
            f"symmetric airfoil must have zero lift at zero incidence"
        )

    def test_5deg_cl_range(self):
        """NACA 0012 at α=5°: thin-airfoil CL ≈ 0.548; accept [0.45, 0.65]."""
        result = solve_naca("0012", alpha_deg=5.0)
        CL = result["CL"]
        assert 0.45 <= CL <= 0.65, (
            f"NACA 0012 at α=5°: CL={CL:.4f} outside [0.45, 0.65]; "
            f"thin-airfoil prediction ≈ 0.548"
        )

    def test_negative_alpha_sign(self):
        """CL at -5° should equal -CL at +5° for symmetric airfoil."""
        rp = solve_naca("0012", alpha_deg=5.0)
        rn = solve_naca("0012", alpha_deg=-5.0)
        assert abs(rp["CL"] + rn["CL"]) < 0.02, (
            f"Symmetry broken: CL(+5°)={rp['CL']:.4f}, CL(-5°)={rn['CL']:.4f}"
        )

    def test_cl_linear_with_alpha(self):
        """CL should increase roughly linearly with α for small angles."""
        r2 = solve_naca("0012", alpha_deg=2.0)
        r5 = solve_naca("0012", alpha_deg=5.0)
        r8 = solve_naca("0012", alpha_deg=8.0)

        slope_low = (r5["CL"] - r2["CL"]) / math.radians(3)
        slope_high = (r8["CL"] - r5["CL"]) / math.radians(3)

        # Both slopes should be in [4.5, 7.5] rad⁻¹ (near 2π = 6.28)
        assert 4.5 <= slope_low <= 7.5, (
            f"CLα (2→5°) = {slope_low:.3f} rad⁻¹, expected ~2π=6.28"
        )
        assert 4.5 <= slope_high <= 7.5, (
            f"CLα (5→8°) = {slope_high:.3f} rad⁻¹, expected ~2π=6.28"
        )

    def test_cp_array_shape(self):
        """Cp array has the same length as n_panels."""
        n_panels = 120
        result = panel_solve("0012", alpha_deg=5.0, n_panels=n_panels)
        assert result["Cp"].shape == (n_panels,), (
            f"Cp shape {result['Cp'].shape} != ({n_panels},)"
        )

    def test_cp_at_stagnation(self):
        """Cp near stagnation point should be close to 1 (V→0)."""
        # For NACA 0012 at small alpha the stagnation is near the leading edge.
        result = panel_solve("0012", alpha_deg=2.0, n_panels=160)
        Cp = result["Cp"]
        # The maximum Cp should be ≥ 0.9 somewhere (near stagnation)
        assert np.max(Cp) >= 0.85, (
            f"Maximum Cp = {np.max(Cp):.3f} < 0.85; stagnation not captured"
        )


# ---------------------------------------------------------------------------
# Cambered airfoil (NACA 4412)
# ---------------------------------------------------------------------------

class TestPanel2DNACA4412:
    def test_zero_alpha_cambered_cl(self):
        """NACA 4412 at α=0° has design CL ≈ 0.4 due to camber → accept [0.3, 0.7]."""
        result = solve_naca("4412", alpha_deg=0.0)
        CL = result["CL"]
        assert 0.3 <= CL <= 0.7, (
            f"NACA 4412 at α=0°: CL={CL:.4f} outside [0.3, 0.7]; "
            f"cambered airfoil should have positive CL at zero incidence"
        )

    def test_increasing_alpha_increases_cl(self):
        """CL should increase with alpha."""
        r0 = solve_naca("4412", alpha_deg=0.0)
        r5 = solve_naca("4412", alpha_deg=5.0)
        assert r5["CL"] > r0["CL"], (
            f"CL should increase with α: CL(0°)={r0['CL']:.4f}, CL(5°)={r5['CL']:.4f}"
        )

    def test_cambered_vs_symmetric_offset(self):
        """NACA 4412 should have higher CL than NACA 0012 at same alpha."""
        r_sym = solve_naca("0012", alpha_deg=5.0)
        r_cam = solve_naca("4412", alpha_deg=5.0)
        assert r_cam["CL"] > r_sym["CL"], (
            f"NACA 4412 should have higher CL than 0012 at same α=5°: "
            f"CL(4412)={r_cam['CL']:.4f}, CL(0012)={r_sym['CL']:.4f}"
        )


# ---------------------------------------------------------------------------
# Coordinate input (array form)
# ---------------------------------------------------------------------------

class TestPanel2DCoordInput:
    def test_array_coords_naca0012_matches_string(self):
        """Using explicit coordinate array should give same result as profile string."""
        from kerf_aero.panel_2d import _naca4_coords

        coords = _naca4_coords("0012", n_pts=200)
        result_array = panel_solve(coords, alpha_deg=5.0, n_panels=120)
        result_str = panel_solve("0012", alpha_deg=5.0, n_panels=120)

        assert abs(result_array["CL"] - result_str["CL"]) < 0.02, (
            f"Array vs string CL mismatch: {result_array['CL']:.4f} vs {result_str['CL']:.4f}"
        )

    def test_return_keys(self):
        result = solve_naca("0012", alpha_deg=5.0)
        assert "CL" in result
        assert "Cp" in result


# ---------------------------------------------------------------------------
# Convergence sanity check
# ---------------------------------------------------------------------------

class TestPanel2DConvergence:
    def test_convergence_with_refinement(self):
        """CL should not change wildly as panel count increases."""
        cl_80 = solve_naca("0012", alpha_deg=5.0, n_panels=80)["CL"]
        cl_160 = solve_naca("0012", alpha_deg=5.0, n_panels=160)["CL"]
        cl_240 = solve_naca("0012", alpha_deg=5.0, n_panels=240)["CL"]

        # CL change from 80→160 and 160→240 should be small (< 5% of CL)
        assert abs(cl_160 - cl_80) / abs(cl_160) < 0.05, (
            f"Poor convergence 80→160: {cl_80:.4f} → {cl_160:.4f}"
        )
        assert abs(cl_240 - cl_160) / abs(cl_240) < 0.03, (
            f"Poor convergence 160→240: {cl_160:.4f} → {cl_240:.4f}"
        )
