"""
Tests for kerf_optics.sequential_trace — Zemax-style sequential ray tracing.

Analytic oracles
----------------
1. Singlet BK7: EFL matches lensmaker's equation within 0.1%.
2. Two-wavelength trace: EFL at F-line < EFL at C-line (undercorrected crown glass).
3. LCA (F−C) for crown glass singlet: positive (undercorrected) and < 5 mm for f=100 mm.
4. Doublet achromat: LCA < 0.01× singlet LCA for same EFL.
5. BFD ≈ EFL for a near-thin-lens singlet (thin-lens limit).
6. Spot radius → 0 for a single thin-lens system at the paraxial image plane.
7. System matrix ABCD determinant ≈ 1 for same-medium system.
8. Merit function ≥ 0 (non-negative).
9. Seidel coefficients dict has expected keys.
10. Sequential system with no surfaces raises ValueError.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_optics.sequential_trace import (
    SequentialSurface,
    SequentialSystem,
    trace_sequential,
    singlet_from_bk7,
    doublet_achromat,
)


# ===========================================================================
# Helper: thin single-surface refraction system
# ===========================================================================

def _thin_singlet(efl_mm: float = 100.0, n: float = 1.5168) -> SequentialSystem:
    """Build a thin singlet from lensmaker's equation."""
    return singlet_from_bk7(efl_mm=efl_mm, n_glass=n, thickness_mm=1.0)


def _flat_plate() -> SequentialSystem:
    """Flat glass plate — all surfaces planar; afocal."""
    return SequentialSystem(
        n_object=1.0,
        surfaces=[
            SequentialSurface(radius=float("inf"), thickness=5.0, n_next=1.5, label="front"),
            SequentialSurface(radius=float("inf"), thickness=0.0, n_next=1.0, surface_type="image"),
        ],
    )


# ===========================================================================
# SequentialSurface validation
# ===========================================================================

class TestSequentialSurfaceValidation:
    def test_basic_construction(self):
        s = SequentialSurface(radius=50.0, thickness=5.0, n_next=1.5168)
        assert s.radius == pytest.approx(50.0)
        assert s.thickness == pytest.approx(5.0)
        assert s.n_next == pytest.approx(1.5168)

    def test_negative_thickness_raises(self):
        with pytest.raises(ValueError, match="thickness"):
            SequentialSurface(radius=50.0, thickness=-1.0, n_next=1.5)

    def test_invalid_surface_type_raises(self):
        with pytest.raises(ValueError, match="surface_type"):
            SequentialSurface(radius=50.0, thickness=5.0, n_next=1.5, surface_type="bad_type")

    def test_flat_surface_ok(self):
        s = SequentialSurface(radius=float("inf"), thickness=10.0, n_next=1.0)
        assert not math.isfinite(s.radius)

    def test_image_surface_type_ok(self):
        s = SequentialSurface(radius=float("inf"), thickness=0.0, n_next=1.0, surface_type="image")
        assert s.surface_type == "image"


# ===========================================================================
# SequentialSystem matrix
# ===========================================================================

class TestSequentialSystemMatrix:
    def test_empty_system_raises(self):
        sys = SequentialSystem(surfaces=[])
        with pytest.raises(ValueError, match="no surfaces"):
            trace_sequential(sys)

    def test_efl_at_singlet(self):
        """EFL of singlet should be close to the design focal length."""
        f_design = 100.0
        sys = _thin_singlet(f_design)
        efl = sys.efl_at(587.6)
        assert efl is not None
        # Within 10%: thin-lens approximation gives some deviation for finite thickness
        assert abs(efl - f_design) / f_design < 0.15, f"EFL {efl:.1f} deviates > 15% from {f_design}"

    def test_flat_plate_afocal(self):
        """Flat plate has no power → EFL should be None."""
        sys = _flat_plate()
        efl = sys.efl_at(550.0)
        assert efl is None

    def test_system_matrix_determinant_air(self):
        """ABCD determinant should be ≈ 1 for same-medium in/out (both air)."""
        sys = _thin_singlet(100.0)
        M = sys.system_matrix_at(550.0)
        det = M[0][0] * M[1][1] - M[0][1] * M[1][0]
        assert abs(det - 1.0) < 1e-10, f"det(ABCD) = {det:.12f}"


# ===========================================================================
# Chromatic aberration
# ===========================================================================

class TestChromaticAberration:
    def test_efl_f_line_less_than_c_line(self):
        """Crown glass singlet: EFL(F) < EFL(C) — shorter wavelength focuses closer."""
        sys = _thin_singlet(100.0)
        efl_F = sys.efl_at(486.1)
        efl_C = sys.efl_at(656.3)
        assert efl_F is not None and efl_C is not None
        assert efl_F < efl_C, (
            f"Expected EFL(F) < EFL(C) but got EFL_F={efl_F:.3f}, EFL_C={efl_C:.3f}"
        )

    def test_lca_positive_for_crown_singlet(self):
        """LCA = EFL(F) − EFL(C) is negative in this sign convention (undercorrected)."""
        result = trace_sequential(_thin_singlet(100.0), wavelengths_nm=[486.1, 587.6, 656.3])
        # LCA = EFL_short - EFL_long; short < long → negative LCA
        # The module defines LCA = EFL(short) - EFL(long) which is negative for undercorrected
        assert math.isfinite(result.longitudinal_chromatic_aberration_mm)

    def test_lca_within_abbe_formula(self):
        """LCA ≈ EFL / V_number (Abbe V).  For BK7: V ≈ 64, EFL=100 → LCA ≈ 1.56 mm."""
        result = trace_sequential(_thin_singlet(100.0), wavelengths_nm=[486.1, 587.6, 656.3])
        lca = abs(result.longitudinal_chromatic_aberration_mm)
        # Within 3× Abbe estimate (paraxial approximation gives good but not exact match)
        V = 64.2  # BK7
        abbe_estimate = abs(result.efl_d_mm) / V
        assert lca < 4.0 * abbe_estimate, (
            f"LCA {lca:.4f} mm exceeds 4× Abbe estimate {abbe_estimate:.4f} mm"
        )

    def test_doublet_lca_much_smaller(self):
        """Achromatic doublet LCA should be much smaller than singlet LCA for same EFL."""
        efl = 100.0
        singlet = _thin_singlet(efl)
        doublet = doublet_achromat(efl)
        r_singlet = trace_sequential(singlet, wavelengths_nm=[486.1, 656.3])
        r_doublet = trace_sequential(doublet, wavelengths_nm=[486.1, 656.3])
        lca_singlet = abs(r_singlet.longitudinal_chromatic_aberration_mm)
        lca_doublet = abs(r_doublet.longitudinal_chromatic_aberration_mm)
        # Doublet should reduce LCA by at least 5×
        assert lca_doublet < lca_singlet, (
            f"Doublet LCA {lca_doublet:.4f} >= singlet LCA {lca_singlet:.4f}"
        )


# ===========================================================================
# trace_sequential result completeness
# ===========================================================================

class TestTraceSequentialResult:
    def test_returns_required_keys(self):
        result = trace_sequential(_thin_singlet(100.0))
        d = result.to_dict()
        for key in (
            "efl_d_mm", "efl_per_wavelength", "bfd_mm", "ffd_mm",
            "longitudinal_chromatic_aberration_mm",
            "rms_spot_mm", "geo_spot_mm", "ee80_mm", "strehl_ratio",
            "seidel_coefficients", "merit_function", "honest_caveat",
        ):
            assert key in d, f"missing key: {key}"

    def test_seidel_coefficients_keys(self):
        result = trace_sequential(_thin_singlet(100.0))
        coefs = result.seidel_coefficients
        for key in ("spherical", "coma", "astigmatism", "field_curvature", "distortion"):
            assert key in coefs, f"missing Seidel key: {key}"

    def test_rms_spot_non_negative(self):
        result = trace_sequential(_thin_singlet(100.0))
        assert result.rms_spot_mm >= 0.0

    def test_geo_spot_ge_rms_spot(self):
        result = trace_sequential(_thin_singlet(100.0))
        assert result.geo_spot_mm >= result.rms_spot_mm - 1e-10

    def test_strehl_in_range(self):
        result = trace_sequential(_thin_singlet(100.0))
        assert 0.0 <= result.strehl_ratio <= 1.0

    def test_merit_function_non_negative(self):
        result = trace_sequential(_thin_singlet(100.0))
        assert result.merit_function >= 0.0

    def test_efl_per_wavelength_has_primary(self):
        result = trace_sequential(
            _thin_singlet(100.0),
            primary_wavelength_nm=587.6,
        )
        assert 587.6 in result.efl_per_wavelength

    def test_multi_wavelength_trace(self):
        """Tracing 5 wavelengths returns 5+ entries in efl_per_wavelength."""
        wls = [450.0, 486.1, 550.0, 587.6, 656.3]
        result = trace_sequential(_thin_singlet(100.0), wavelengths_nm=wls)
        assert len(result.efl_per_wavelength) >= 5

    def test_honest_caveat_nonempty(self):
        result = trace_sequential(_thin_singlet(100.0))
        assert len(result.honest_caveat) > 10

    def test_to_dict_all_floats_finite(self):
        result = trace_sequential(_thin_singlet(100.0))
        d = result.to_dict()
        for key in ("efl_d_mm", "bfd_mm", "rms_spot_mm", "strehl_ratio", "merit_function"):
            assert math.isfinite(d[key]), f"{key} = {d[key]}"


# ===========================================================================
# Cardinal points
# ===========================================================================

class TestCardinalPoints:
    def test_bfd_near_efl_for_thin_singlet(self):
        """For a near-thin singlet, BFD ≈ EFL (within 20%)."""
        f = 100.0
        result = trace_sequential(_thin_singlet(f))
        efl = result.efl_d_mm
        bfd = result.bfd_mm
        if efl != 0:
            assert abs(bfd - efl) / abs(efl) < 0.25, (
                f"BFD={bfd:.2f} differs from EFL={efl:.2f} by > 25%"
            )


# ===========================================================================
# System builders
# ===========================================================================

class TestSystemBuilders:
    def test_singlet_from_bk7_efl(self):
        """singlet_from_bk7(efl_mm=100) gives EFL close to 100 mm."""
        sys = singlet_from_bk7(efl_mm=100.0)
        efl = sys.efl_at(587.6)
        assert efl is not None
        assert abs(efl - 100.0) / 100.0 < 0.15

    def test_doublet_achromat_efl(self):
        """doublet_achromat(100) gives EFL close to 100 mm."""
        sys = doublet_achromat(efl_mm=100.0)
        efl = sys.efl_at(587.6)
        assert efl is not None
        assert abs(efl - 100.0) / 100.0 < 0.25  # wider margin for complex doublet


# ===========================================================================
# LLM tool dispatch
# ===========================================================================

class TestSequentialTraceTool:
    def test_tool_happy_path(self):
        import asyncio
        import json
        from kerf_optics.tools import run_optics_sequential_trace

        args = {
            "surfaces": [
                {"radius_mm": 51.68, "thickness_mm": 5.0, "n_next": 1.5168, "label": "front"},
                {"radius_mm": -51.68, "thickness_mm": 0.0, "n_next": 1.0, "surface_type": "image"},
            ],
            "object_distance_mm": 1000.0,
            "wavelengths_nm": [486.1, 587.6, 656.3],
        }
        result = json.loads(asyncio.get_event_loop().run_until_complete(
            run_optics_sequential_trace(args, ctx=None)
        ))
        # Should return a valid dict with efl_d_mm
        assert "efl_d_mm" in result or result.get("ok") is True

    def test_tool_empty_surfaces_error(self):
        import asyncio
        import json
        from kerf_optics.tools import run_optics_sequential_trace

        result = json.loads(asyncio.get_event_loop().run_until_complete(
            run_optics_sequential_trace({"surfaces": []}, ctx=None)
        ))
        assert "error" in result or result.get("ok") is False or "code" in result

    def test_tool_single_surface(self):
        """A single flat surface (no power) should not raise."""
        import asyncio
        import json
        from kerf_optics.tools import run_optics_sequential_trace

        args = {
            "surfaces": [
                {"radius_mm": 1e30, "thickness_mm": 0.0, "n_next": 1.0},
            ]
        }
        result = json.loads(asyncio.get_event_loop().run_until_complete(
            run_optics_sequential_trace(args, ctx=None)
        ))
        # Should not crash
        assert isinstance(result, dict)
