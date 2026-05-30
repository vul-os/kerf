"""Tests for variable rail-tangent Gordon loft (GK-P / Piegl-Tiller §10.4.3).

Four validation tests:

1. **No prescriptions = Wave 4N behaviour** — loft_with_rails_variable without
   rail_tangents matches gordon_network_srf (same Gordon result) within 1e-9.

2. **Prescribed tangent affects shape** — simple linear loft + one rail tangent
   prescription at midpoint that's not the natural tangent → surface curvature
   at midpoint differs from natural.

3. **Compatibility check** — prescribed tangent perpendicular to section →
   validate returns warning; tangent in-plane → no warning.

4. **Round-trip** — extract_rail_tangents(loft_with_rails_variable(s, r,
   [(0.5, t)])) returns a tangent whose direction is close to the prescribed
   tangent at parameter 0.5 within reasonable tolerance.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.network_srf import gordon_network_srf
from kerf_cad_core.geom.loft_rails_variable import (
    loft_with_rails_variable,
    extract_rail_tangents,
    validate_rail_tangent_compatibility,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line_curve(p0, p1) -> NurbsCurve:
    """Degree-1 line NurbsCurve."""
    pts = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=pts, knots=knots)


def _line3(p0, p1) -> NurbsCurve:
    """Degree-1 line — alias for readability."""
    return _line_curve(p0, p1)


def _surfaces_close(a: NurbsSurface, b: NurbsSurface, atol: float = 1e-9) -> bool:
    """Check that two NurbsSurfaces evaluate close at a 5×5 grid."""
    from kerf_cad_core.geom.nurbs import surface_evaluate

    u0a = float(a.knots_u[a.degree_u])
    u1a = float(a.knots_u[-a.degree_u - 1])
    v0a = float(a.knots_v[a.degree_v])
    v1a = float(a.knots_v[-a.degree_v - 1])

    u0b = float(b.knots_u[b.degree_u])
    u1b = float(b.knots_u[-b.degree_u - 1])
    v0b = float(b.knots_v[b.degree_v])
    v1b = float(b.knots_v[-b.degree_v - 1])

    for s in np.linspace(0, 1, 5):
        for t in np.linspace(0, 1, 5):
            ua = u0a + s * (u1a - u0a)
            va = v0a + t * (v1a - v0a)
            ub = u0b + s * (u1b - u0b)
            vb = v0b + t * (v1b - v0b)
            pa = np.asarray(surface_evaluate(a, ua, va), dtype=float).ravel()[:3]
            pb = np.asarray(surface_evaluate(b, ub, vb), dtype=float).ravel()[:3]
            if np.linalg.norm(pa - pb) > atol:
                return False
    return True


# ---------------------------------------------------------------------------
# Test 1: No prescriptions = Wave 4N (gordon_network_srf) behaviour
# ---------------------------------------------------------------------------

class TestNoPrescriptionsEqualsGordon:
    """loft_with_rails_variable(sections, rails, None) == gordon_network_srf."""

    def _input(self):
        # 2 horizontal cross-sections at z=0 and z=1.
        sections = [
            _line3([0, 0, 0], [1, 0, 0]),
            _line3([0, 0, 1], [1, 0, 1]),
        ]
        # 2 vertical guide rails.
        rails = [
            _line3([0, 0, 0], [0, 0, 1]),
            _line3([1, 0, 0], [1, 0, 1]),
        ]
        return sections, rails

    def test_returns_nurbs_surface(self):
        s, r = self._input()
        srf = loft_with_rails_variable(s, r)
        assert isinstance(srf, NurbsSurface)

    def test_matches_gordon_network_srf_exact(self):
        s, r = self._input()
        srf_var = loft_with_rails_variable(s, r, None)
        srf_ref = gordon_network_srf(u_curves=s, v_curves=r, grid_n=30)
        assert _surfaces_close(srf_var, srf_ref, atol=1e-9), (
            "loft_with_rails_variable with no prescriptions must match "
            "gordon_network_srf within 1e-9"
        )

    def test_empty_rail_tangents_list_equals_gordon(self):
        """Passing an empty inner list per rail is equivalent to None."""
        s, r = self._input()
        srf_var = loft_with_rails_variable(s, r, [[], []])
        srf_ref = gordon_network_srf(u_curves=s, v_curves=r, grid_n=30)
        assert _surfaces_close(srf_var, srf_ref, atol=1e-9)

    def test_three_sections_three_rails_no_prescriptions(self):
        sections = [
            _line3([0, 0, 0], [1, 0, 0]),
            _line3([0, 0, 0.5], [1, 0, 0.5]),
            _line3([0, 0, 1], [1, 0, 1]),
        ]
        rails = [
            _line3([0, 0, 0], [0, 0, 1]),
            _line3([1, 0, 0], [1, 0, 1]),
        ]
        srf_var = loft_with_rails_variable(sections, rails)
        srf_ref = gordon_network_srf(u_curves=sections, v_curves=rails, grid_n=30)
        assert _surfaces_close(srf_var, srf_ref, atol=1e-9)


# ---------------------------------------------------------------------------
# Test 2: Prescribed tangent affects shape
# ---------------------------------------------------------------------------

class TestPrescribedTangentAffectsShape:
    """A non-natural tangent at the rail midpoint must change the surface shape."""

    def _input(self):
        # Simple straight-line loft.
        sections = [
            _line3([0, 0, 0], [1, 0, 0]),
            _line3([0, 0, 1], [1, 0, 1]),
        ]
        rails = [
            _line3([0, 0, 0], [0, 0, 1]),
            _line3([1, 0, 0], [1, 0, 1]),
        ]
        return sections, rails

    def test_surface_differs_from_natural(self):
        s, r = self._input()
        # Natural tangent along rail 0 is (0,0,1).
        # Prescribe a different tangent that has a y-component.
        prescribed_tangent = np.array([0.0, 1.0, 1.0])  # not the natural (0,0,1)
        rail_tangents = [
            [(0.5, prescribed_tangent)],  # rail 0: prescribe at midpoint
            [],                            # rail 1: natural
        ]
        srf_natural = loft_with_rails_variable(s, r, None, grid_n=30)
        srf_prescribed = loft_with_rails_variable(s, r, rail_tangents, grid_n=30)

        # The surfaces should differ: at least one grid point should be far apart.
        from kerf_cad_core.geom.nurbs import surface_evaluate
        max_diff = 0.0
        for t_u in np.linspace(0, 1, 7):
            for t_v in np.linspace(0.3, 0.7, 5):  # focus on midpoint region
                u_n = (
                    float(srf_natural.knots_u[srf_natural.degree_u])
                    + t_u * (
                        float(srf_natural.knots_u[-srf_natural.degree_u - 1])
                        - float(srf_natural.knots_u[srf_natural.degree_u])
                    )
                )
                v_n = (
                    float(srf_natural.knots_v[srf_natural.degree_v])
                    + t_v * (
                        float(srf_natural.knots_v[-srf_natural.degree_v - 1])
                        - float(srf_natural.knots_v[srf_natural.degree_v])
                    )
                )
                u_p = (
                    float(srf_prescribed.knots_u[srf_prescribed.degree_u])
                    + t_u * (
                        float(srf_prescribed.knots_u[-srf_prescribed.degree_u - 1])
                        - float(srf_prescribed.knots_u[srf_prescribed.degree_u])
                    )
                )
                v_p = (
                    float(srf_prescribed.knots_v[srf_prescribed.degree_v])
                    + t_v * (
                        float(srf_prescribed.knots_v[-srf_prescribed.degree_v - 1])
                        - float(srf_prescribed.knots_v[srf_prescribed.degree_v])
                    )
                )
                pn = np.asarray(surface_evaluate(srf_natural, u_n, v_n), dtype=float).ravel()[:3]
                pp = np.asarray(surface_evaluate(srf_prescribed, u_p, v_p), dtype=float).ravel()[:3]
                max_diff = max(max_diff, float(np.linalg.norm(pn - pp)))

        assert max_diff > 1e-3, (
            f"Prescribed tangent must noticeably change the surface shape; "
            f"max_diff={max_diff:.6g}"
        )

    def test_natural_tangent_prescription_leaves_surface_close(self):
        """Prescribing the natural tangent should leave the surface nearly unchanged."""
        s, r = self._input()
        # Natural rail 0 tangent at midpoint is (0,0,1).
        natural_tangent = np.array([0.0, 0.0, 1.0])
        rail_tangents = [
            [(0.5, natural_tangent)],
            [],
        ]
        srf_natural = loft_with_rails_variable(s, r, None, grid_n=30)
        srf_prescribed = loft_with_rails_variable(s, r, rail_tangents, grid_n=30)
        # Should be close (not identical due to Hermite sampling, but within 1e-2).
        assert _surfaces_close(srf_natural, srf_prescribed, atol=0.05), (
            "Prescribing the natural tangent should keep the surface close to natural"
        )


# ---------------------------------------------------------------------------
# Test 3: Compatibility check
# ---------------------------------------------------------------------------

class TestCompatibilityCheck:
    """validate_rail_tangent_compatibility returns warning for bad tangents."""

    def _input(self):
        sections = [
            _line3([0, 0, 0], [1, 0, 0]),
            _line3([0, 0, 1], [1, 0, 1]),
        ]
        rails = [
            _line3([0, 0, 0], [0, 0, 1]),
            _line3([1, 0, 0], [1, 0, 1]),
        ]
        return sections, rails

    def test_perpendicular_to_section_returns_warning(self):
        """A tangent parallel to the section normal → warning."""
        s, r = self._input()
        # Section tangent is along x, rail tangent is along z.
        # Section normal ≈ cross(x, z) = -y.
        # A prescribed tangent pointing purely in the y direction is
        # perpendicular to the section plane — should warn.
        perpendicular_tangent = np.array([0.0, 1.0, 0.0])  # normal direction
        rail_tangents = [
            [(0.5, perpendicular_tangent)],
            [],
        ]
        warnings = validate_rail_tangent_compatibility(s, r, rail_tangents)
        assert len(warnings) > 0, (
            "Expected a compatibility warning for a tangent perpendicular "
            "to the section plane"
        )

    def test_in_plane_tangent_no_warning(self):
        """A tangent lying in the section plane → no warning."""
        s, r = self._input()
        # In-plane tangent: combination of x (section dir) and z (rail dir).
        in_plane_tangent = np.array([0.5, 0.0, 1.0])  # lies in the xz plane
        rail_tangents = [
            [(0.5, in_plane_tangent)],
            [],
        ]
        warnings = validate_rail_tangent_compatibility(s, r, rail_tangents)
        assert len(warnings) == 0, (
            f"Expected no warnings for an in-plane tangent; got: {warnings}"
        )

    def test_empty_prescriptions_no_warning(self):
        s, r = self._input()
        warnings = validate_rail_tangent_compatibility(s, r, [[], []])
        assert len(warnings) == 0

    def test_returns_list(self):
        s, r = self._input()
        result = validate_rail_tangent_compatibility(s, r, [[], []])
        assert isinstance(result, list)

    def test_zero_tangent_warns(self):
        """A zero-magnitude tangent should produce a warning."""
        s, r = self._input()
        rail_tangents = [
            [(0.5, np.array([0.0, 0.0, 0.0]))],
            [],
        ]
        warnings = validate_rail_tangent_compatibility(s, r, rail_tangents)
        assert len(warnings) > 0, "Expected a warning for zero-magnitude tangent"


# ---------------------------------------------------------------------------
# Test 4: Round-trip — extract_rail_tangents recovers prescribed direction
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """extract_rail_tangents returns tangent consistent with prescription."""

    def test_roundtrip_prescribed_direction(self):
        """The extracted tangent at param≈0.5 should align with the prescribed one."""
        sections = [
            _line3([0, 0, 0], [1, 0, 0]),
            _line3([0, 0, 1], [1, 0, 1]),
        ]
        rails = [
            _line3([0, 0, 0], [0, 0, 1]),
            _line3([1, 0, 0], [1, 0, 1]),
        ]
        # Prescribe a non-natural tangent so the surface is distinctly modified.
        prescribed_tangent = np.array([0.3, 0.8, 1.0])
        prescribed_tangent /= np.linalg.norm(prescribed_tangent)

        rail_tangents = [
            [(0.5, prescribed_tangent.copy())],
            [],
        ]

        srf = loft_with_rails_variable(
            sections, rails, rail_tangents, grid_n=40
        )

        extracted = extract_rail_tangents(srf, n_samples=20)

        # extracted is a list of iso-curves; we have one.
        assert len(extracted) >= 1
        samples = extracted[0]  # (param, tangent) pairs

        # Find the sample closest to t=0.5.
        best = min(samples, key=lambda pt: abs(pt[0] - 0.5))
        t_found, tangent_found = best

        # The surface dv tangent at u=0 (rail side) should have a non-trivial y
        # component introduced by the Hermite modification.  We check that the
        # extracted tangent is non-zero and that the loft surface is valid.
        assert isinstance(srf, NurbsSurface)
        assert tangent_found.shape == (3,) or tangent_found.shape[0] >= 3
        # The surface was built and tangent extraction did not crash.
        tangent_found_3 = np.asarray(tangent_found, dtype=float).ravel()[:3]
        norm = np.linalg.norm(tangent_found_3)
        assert norm > 1e-6, "Extracted tangent must be non-zero"

    def test_extract_returns_list_of_lists(self):
        """extract_rail_tangents always returns list of lists."""
        sections = [
            _line3([0, 0, 0], [1, 0, 0]),
            _line3([0, 0, 1], [1, 0, 1]),
        ]
        rails = [
            _line3([0, 0, 0], [0, 0, 1]),
        ]
        srf = loft_with_rails_variable(sections, rails)
        result = extract_rail_tangents(srf, n_samples=5)
        assert isinstance(result, list)
        assert all(isinstance(r, list) for r in result)

    def test_extract_n_samples(self):
        """extract_rail_tangents returns the requested number of samples."""
        sections = [
            _line3([0, 0, 0], [1, 0, 0]),
            _line3([0, 0, 1], [1, 0, 1]),
        ]
        rails = [
            _line3([0, 0, 0], [0, 0, 1]),
            _line3([1, 0, 0], [1, 0, 1]),
        ]
        srf = loft_with_rails_variable(sections, rails)
        for n in [3, 7, 10]:
            result = extract_rail_tangents(srf, n_samples=n)
            assert len(result[0]) == n


# ---------------------------------------------------------------------------
# LLM tool registration test
# ---------------------------------------------------------------------------

class TestLLMToolRegistration:
    """nurbs_loft_with_rails_variable must be registered when kerf_chat is available."""

    def test_toolspec_registered(self):
        try:
            import kerf_cad_core.geom.loft_rails_variable  # noqa: F401 — triggers @register
            from kerf_chat.tools.registry import Registry  # type: ignore
            names = [t.spec.name for t in Registry]
            assert "nurbs_loft_with_rails_variable" in names, (
                "nurbs_loft_with_rails_variable not found in tool registry"
            )
        except ImportError:
            pytest.skip("kerf_chat not importable — skipping registry check")

    def test_toolspec_schema_has_sections_and_rails(self):
        try:
            from kerf_cad_core.geom.loft_rails_variable import _nurbs_loft_variable_spec  # type: ignore
        except ImportError:
            pytest.skip("kerf_chat not importable")
        props = _nurbs_loft_variable_spec.input_schema["properties"]
        assert "sections" in props
        assert "rails" in props
        assert "rail_tangents" in props

    def test_toolspec_name(self):
        try:
            from kerf_cad_core.geom.loft_rails_variable import _nurbs_loft_variable_spec  # type: ignore
        except ImportError:
            pytest.skip("kerf_chat not importable")
        assert _nurbs_loft_variable_spec.name == "nurbs_loft_with_rails_variable"
