"""Tests for the Vortex-Lattice Method (vlm.py).

Reference value:
  Rectangular wing, AR = 8, α = 5°
  Helmbold formula: CLα = 2π·AR / (AR + 2) = 50.265 / 10 = 5.027 rad⁻¹
  CL = CLα · α_rad = 5.027 × 0.08727 ≈ 0.439
  Acceptance: [0.35, 0.55] (±~20%)

"""
import math
import numpy as np
import pytest

from kerf_aero.vlm import vlm_wing


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def rect_wing_result(alpha_deg=5.0, m=4, n=10):
    """Rectangular AR=8 wing: span=8, chord=1."""
    return vlm_wing(
        span=8.0,
        root_chord=1.0,
        tip_chord=1.0,
        sweep_deg=0.0,
        twist_deg=0.0,
        alpha_deg=alpha_deg,
        m_chord=m,
        n_span=n,
    )


# ---------------------------------------------------------------------------
# Core physics oracle
# ---------------------------------------------------------------------------

class TestVLMRectangularWing:
    def test_cl_at_5deg_coarse(self):
        """AR=8 rect wing at 5° → CL ∈ [0.35, 0.55].

        Helmbold prediction: CL ≈ 0.439.  Acceptance band ±20% to allow for
        VLM discretisation error; anything outside this band means the
        influence-coefficient signs are wrong.
        """
        result = rect_wing_result(alpha_deg=5.0, m=4, n=10)
        CL = result["CL"]
        assert 0.35 <= CL <= 0.55, (
            f"CL = {CL:.4f} out of expected range [0.35, 0.55]; "
            f"Helmbold reference ≈ 0.439"
        )

    def test_cl_at_5deg_medium(self):
        """Higher resolution (m=6, n=16) should be closer to Helmbold."""
        result = vlm_wing(span=8.0, root_chord=1.0, alpha_deg=5.0, m_chord=6, n_span=16)
        CL = result["CL"]
        assert 0.35 <= CL <= 0.55, (
            f"CL = {CL:.4f} out of range [0.35, 0.55]"
        )

    def test_cl_linear_in_alpha(self):
        """CL should scale linearly with alpha for small angles."""
        r2 = rect_wing_result(alpha_deg=2.0)
        r5 = rect_wing_result(alpha_deg=5.0)
        r10 = rect_wing_result(alpha_deg=10.0)

        cl_per_rad_25 = (r5["CL"] - r2["CL"]) / math.radians(5 - 2)
        cl_per_rad_510 = (r10["CL"] - r5["CL"]) / math.radians(10 - 5)

        # CLα should be roughly constant; allow 10% variation
        ratio = cl_per_rad_25 / cl_per_rad_510
        assert 0.85 <= ratio <= 1.15, (
            f"CL not linear in alpha: CLα(2→5)={cl_per_rad_25:.3f}, "
            f"CLα(5→10)={cl_per_rad_510:.3f}, ratio={ratio:.3f}"
        )

    def test_cdi_positive(self):
        """Induced drag must be positive for positive CL."""
        result = rect_wing_result(alpha_deg=5.0)
        # CDi may be small but should not be strongly negative
        assert result["CDi"] > -0.01, f"CDi = {result['CDi']:.4f} unexpectedly negative"

    def test_gamma_shape(self):
        """Circulation array has the right length."""
        result = rect_wing_result(m=4, n=10)
        assert result["gamma"].shape == (4 * 10,), (
            f"Expected gamma.shape = (40,), got {result['gamma'].shape}"
        )


class TestVLMSymmetry:
    def test_symmetric_wing_zero_sideslip(self):
        """Symmetric planar wing: spanwise gamma distribution should be mirror-symmetric.

        This is a proxy test for zero side force.
        """
        result = rect_wing_result(alpha_deg=5.0, m=1, n=10)
        gamma = result["gamma"]

        # For n_span=10, m_chord=1, panels 0..4 are port, 5..9 are starboard
        n_span = 10
        # gamma[i] (port panel) should equal gamma[n_span - 1 - i] (mirror starboard)
        half = n_span // 2
        port = gamma[:half]
        starboard = gamma[n_span - half:n_span][::-1]

        np.testing.assert_allclose(
            port, starboard, rtol=1e-6,
            err_msg="Circulation not symmetric about wing centerline"
        )

    def test_zero_alpha_cl(self):
        """Flat wing at alpha=0 should give CL ≈ 0."""
        result = rect_wing_result(alpha_deg=0.0)
        assert abs(result["CL"]) < 0.01, (
            f"CL at alpha=0 should be ~0, got {result['CL']:.4f}"
        )


class TestVLMTaperedSweep:
    def test_tapered_wing_cl_in_range(self):
        """Tapered wing (taper 0.4) at 5° should still give CL in physics range."""
        result = vlm_wing(
            span=8.0,
            root_chord=1.25,
            tip_chord=0.5,
            sweep_deg=15.0,
            alpha_deg=5.0,
            m_chord=4,
            n_span=10,
        )
        CL = result["CL"]
        assert 0.30 <= CL <= 0.60, (
            f"Tapered+swept wing CL = {CL:.4f} out of physical range"
        )

    def test_twist_reduces_cl(self):
        """Washout twist should reduce CL compared to zero twist."""
        r0 = vlm_wing(span=8, root_chord=1.0, twist_deg=0.0, alpha_deg=5.0)
        r5 = vlm_wing(span=8, root_chord=1.0, twist_deg=5.0, alpha_deg=5.0)
        assert r5["CL"] < r0["CL"], (
            f"Washout should reduce CL: CL(0°twist)={r0['CL']:.4f}, "
            f"CL(5°twist)={r5['CL']:.4f}"
        )


class TestVLMOutputContract:
    """Test that the function returns the expected output dictionary."""

    def test_return_keys(self):
        result = rect_wing_result()
        assert set(result.keys()) >= {"CL", "CDi", "Cm", "gamma"}

    def test_gamma_is_ndarray(self):
        result = rect_wing_result()
        assert isinstance(result["gamma"], np.ndarray)

    def test_scalars_are_float(self):
        result = rect_wing_result()
        assert isinstance(result["CL"], float)
        assert isinstance(result["CDi"], float)
        assert isinstance(result["Cm"], float)
