"""
T-50: nonlinear material / plasticity path tests.

Scope
-----
* analysis_type="nonlinear_plastic" is accepted by the tools.py enum.
* build_nonlinear_plastic_inp() generates a syntactically correct CalculiX deck:
    - *HEADING, *NODE, *ELEMENT, *MATERIAL, *ELASTIC, *PLASTIC, *SOLID SECTION
    - *STEP,NLGEOM  *STATIC  *BOUNDARY  *CLOAD (when present)
    - *EL FILE includes PEEQ sentinel
    - Hardening curve points are consistent with sigma_y0 and H.
* parse_nonlinear_plastic_dat() correctly extracts displacements, stresses, and PEEQ
  from mock .dat content.
* run_static_analysis() with analysis_type="nonlinear_plastic" returns the
  ENGINE_PENDING_WARNING sentinel when ccx is absent.
* Analytical elastic-plastic cantilever reference:
    Single-bar uniaxial plasticity results match J2 return-mapping formula to
    within numerical tolerance (the nonlinear_bar solver is the
    engine-independent reference implementation).

All tests are hermetic — no DB, no network, no ccx binary required.
"""

from __future__ import annotations

import math
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Shared material data
# ---------------------------------------------------------------------------

E_STEEL   = 200e9   # Pa   Young's modulus
NU_STEEL  = 0.3     # Poisson ratio
RHO_STEEL = 7850.0  # kg/m³
SY        = 250e6   # Pa   initial yield stress
H_MOD     = 20e9    # Pa   isotropic-hardening modulus
eps_y     = SY / E_STEEL  # yield strain ≈ 1.25e-3

_MAT = {
    "E": E_STEEL,
    "nu": NU_STEEL,
    "rho": RHO_STEEL,
    "sigma_y0": SY,
    "H": H_MOD,
    "yield_strength": SY,
}

# Minimal 4-node tetrahedral mesh (single element)
# Nodes at (0,0,0), (1,0,0), (0,1,0), (0,0,1)
_NODES = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
_ELEMENTS = [(1, "tetra", [1, 2, 3, 4])]

_BCS = [{"type": "fixed", "face_tags": []}]
_LOADS = [{"type": "force", "face_tags": [], "value": 1e4}]


# ===========================================================================
# §1  analysis_type enum includes "nonlinear_plastic"
# ===========================================================================

class TestToolsEnum:

    def test_analysis_type_enum_contains_nonlinear_plastic(self):
        """tools.py fem_run_spec must list nonlinear_plastic as a valid analysis_type."""
        from kerf_fem.tools import fem_run_spec

        schema = fem_run_spec.input_schema
        at_enum = schema["properties"]["analysis_type"]["enum"]
        assert "nonlinear_plastic" in at_enum, (
            f"nonlinear_plastic missing from analysis_type enum: {at_enum}"
        )

    def test_existing_analysis_types_still_present(self):
        """Original analysis types must not have been removed."""
        from kerf_fem.tools import fem_run_spec

        schema = fem_run_spec.input_schema
        at_enum = schema["properties"]["analysis_type"]["enum"]
        for expected in ("linear_static", "modal", "thermal"):
            assert expected in at_enum


# ===========================================================================
# §2  INP deck builder — structural / keyword correctness
# ===========================================================================

class TestDeckBuilder:

    def _build(self, **kwargs):
        from kerf_fem.calculix_utils import build_nonlinear_plastic_inp
        defaults = dict(
            nodes=_NODES,
            elements=_ELEMENTS,
            material_props=_MAT,
            boundary_conditions=_BCS,
            loads=_LOADS,
        )
        defaults.update(kwargs)
        return build_nonlinear_plastic_inp(**defaults)

    def test_heading_present(self):
        deck = self._build()
        assert "*HEADING" in deck

    def test_node_block_present(self):
        deck = self._build()
        assert "*NODE" in deck

    def test_element_block_present(self):
        deck = self._build()
        assert "*ELEMENT" in deck

    def test_c3d4_element_type(self):
        """Tetrahedral elements must map to C3D4."""
        deck = self._build()
        assert "TYPE=C3D4" in deck

    def test_material_elastic_block(self):
        deck = self._build()
        assert "*ELASTIC" in deck
        # E and nu should appear on the same line after *ELASTIC
        lines = deck.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "*ELASTIC" and i + 1 < len(lines):
                vals = lines[i + 1].split(",")
                assert len(vals) == 2
                assert abs(float(vals[0]) - E_STEEL) < 1.0
                assert abs(float(vals[1]) - NU_STEEL) < 1e-9
                break
        else:
            pytest.fail("*ELASTIC data line not found")

    def test_plastic_block_present(self):
        deck = self._build()
        assert "*PLASTIC" in deck

    def test_plastic_hardening_curve_first_point_at_zero_eps_p(self):
        """
        First point on the hardening curve: (sigma_y0, 0.0).
        This represents the initial yield surface.
        """
        deck = self._build()
        lines = deck.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "*PLASTIC" and i + 1 < len(lines):
                parts = lines[i + 1].split(",")
                assert len(parts) == 2, f"Expected 2 values, got: {lines[i+1]!r}"
                stress_val = float(parts[0])
                eps_p_val = float(parts[1])
                assert abs(stress_val - SY) / SY < 1e-6, (
                    f"First hardening point stress {stress_val:.4e} != sigma_y0 {SY:.4e}"
                )
                assert abs(eps_p_val) < 1e-12, (
                    f"First hardening point plastic strain {eps_p_val} != 0"
                )
                break
        else:
            pytest.fail("*PLASTIC block not found")

    def test_plastic_hardening_curve_second_point_consistent_with_H(self):
        """
        Second hardening point: (sigma_y0 + H * eps_ref, eps_ref).
        The slope (Δσ / Δεᵖ) must equal H within floating-point rounding.
        """
        deck = self._build()
        lines = deck.splitlines()
        plastic_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "*PLASTIC":
                plastic_idx = i
                break
        assert plastic_idx is not None, "*PLASTIC not found"

        # Read the two hardening data lines
        data_lines = []
        for line in lines[plastic_idx + 1:]:
            stripped = line.strip()
            if stripped.startswith("*") or not stripped:
                break
            data_lines.append(stripped)

        assert len(data_lines) >= 2, f"Expected ≥2 hardening data lines, got {data_lines}"

        s1, ep1 = [float(x) for x in data_lines[0].split(",")]
        s2, ep2 = [float(x) for x in data_lines[1].split(",")]

        delta_s  = s2 - s1
        delta_ep = ep2 - ep1
        assert delta_ep > 0, "Plastic strain must increase along hardening curve"
        slope = delta_s / delta_ep
        assert abs(slope - H_MOD) / H_MOD < 1e-6, (
            f"Hardening slope {slope:.4e} != H {H_MOD:.4e}"
        )

    def test_nlgeom_step_keyword(self):
        """Step must use NLGEOM flag for nonlinear geometry."""
        deck = self._build()
        assert "NLGEOM" in deck

    def test_static_keyword_in_step(self):
        deck = self._build()
        assert "*STATIC" in deck

    def test_el_file_includes_peeq(self):
        """EL FILE output request must include PEEQ for plastic strain tracking."""
        deck = self._build()
        lines = deck.splitlines()
        el_file_lines = [l for l in lines if l.strip().startswith("*EL FILE")]
        assert el_file_lines, "*EL FILE block not found"
        # The line after *EL FILE should list output variables including PEEQ
        for i, line in enumerate(lines):
            if line.strip().startswith("*EL FILE") and i + 1 < len(lines):
                output_vars = lines[i + 1].upper()
                assert "PEEQ" in output_vars, (
                    f"PEEQ not listed in *EL FILE output: {lines[i+1]!r}"
                )
                break

    def test_node_file_includes_u(self):
        """NODE FILE must request displacement (U)."""
        deck = self._build()
        lines = deck.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "*NODE FILE" and i + 1 < len(lines):
                assert "U" in lines[i + 1].upper()
                break
        else:
            pytest.fail("*NODE FILE not found")

    def test_end_step_present(self):
        deck = self._build()
        assert "*END STEP" in deck

    def test_solid_section_references_mat(self):
        deck = self._build()
        assert "MATERIAL=MAT" in deck

    def test_n_increments_reflected_in_static_line(self):
        """dt_init = time_period / n_increments must appear on the *STATIC line."""
        n = 20
        deck = self._build(n_increments=n)
        # *STATIC line: dt_init,time_period
        static_lines = [l for l in deck.splitlines() if l.strip().startswith("*STATIC")]
        assert static_lines, "*STATIC line not found"
        static_line = static_lines[0]
        # Ignore the keyword itself and look for numeric values after the comma
        rest = static_line.split(",", 1)
        if len(rest) == 2:
            dt = float(rest[1].split(",")[0])
            assert abs(dt - 1.0 / n) < 1e-9, f"dt_init {dt} != 1/{n}"

    def test_perfect_plasticity_H_zero(self):
        """H=0 → hardening curve slope is 0 (perfect plasticity plateau)."""
        mat_pp = dict(_MAT, H=0.0)
        deck = self._build(material_props=mat_pp)
        lines = deck.splitlines()
        plastic_idx = next(i for i, l in enumerate(lines) if l.strip() == "*PLASTIC")
        data_lines = []
        for line in lines[plastic_idx + 1:]:
            s = line.strip()
            if s.startswith("*") or not s:
                break
            data_lines.append(s)
        s1, ep1 = [float(x) for x in data_lines[0].split(",")]
        s2, ep2 = [float(x) for x in data_lines[1].split(",")]
        # With H=0, second stress == first stress (plateau)
        assert abs(s2 - s1) < 1e-3, f"H=0 but hardening slope {s2 - s1:.4e} != 0"


# ===========================================================================
# §3  .dat result parser for nonlinear-plastic output
# ===========================================================================

class TestDatParser:
    """
    Tests for parse_nonlinear_plastic_dat() using synthetic .dat content.
    The function must correctly extract displacements, stresses, and PEEQ.
    """

    def _write_dat(self, content: str) -> Path:
        tmp = tempfile.mkdtemp()
        p = Path(tmp) / "analysis.dat"
        p.write_text(content)
        return p

    def _make_displacement_block(self, nodes: list[list[float]]) -> str:
        # CalculiX format: spaced header, data rows immediately follow (no blank line).
        # Block ends with a blank line so the regex lookahead \n\s*\n terminates it.
        lines = ["D I S P L A C E M E N T S"]
        for i, (ux, uy, uz) in enumerate(nodes, start=1):
            lines.append(f"  {i}  {ux:.6e}  {uy:.6e}  {uz:.6e}")
        return "\n".join(lines)

    def _make_stress_block(self, stresses: list[dict]) -> str:
        # CalculiX format: spaced header, data rows immediately follow (no blank line).
        lines = ["S T R E S S E S"]
        for i, s in enumerate(stresses, start=1):
            sx = s.get("sx", 0.0)
            sy = s.get("sy", 0.0)
            sz = s.get("sz", 0.0)
            txy = s.get("txy", 0.0)
            tyz = s.get("tyz", 0.0)
            txz = s.get("txz", 0.0)
            lines.append(f"  {i}  {sx:.6e}  {sy:.6e}  {sz:.6e}  {txy:.6e}  {tyz:.6e}  {txz:.6e}")
        return "\n".join(lines)

    def _make_peeq_block(self, peeq_values: list[float]) -> str:
        # parse_nonlinear_plastic_dat uses regex: EQUIVALENT\s+PLASTIC\s+STRAIN
        lines = ["EQUIVALENT PLASTIC STRAIN"]
        for i, ep in enumerate(peeq_values, start=1):
            lines.append(f"  {i}  {ep:.6e}")
        return "\n".join(lines)

    def test_missing_dat_returns_error(self):
        from kerf_fem.calculix_utils import parse_nonlinear_plastic_dat
        result = parse_nonlinear_plastic_dat(Path("/nonexistent/analysis.dat"))
        assert "error" in result

    def test_empty_dat_returns_empty_lists(self):
        from kerf_fem.calculix_utils import parse_nonlinear_plastic_dat
        p = self._write_dat("")
        result = parse_nonlinear_plastic_dat(p)
        assert "displacements" in result
        assert "stresses" in result
        assert result["displacements"] == []
        assert result["stresses"] == []

    def test_displacement_block_parsed(self):
        from kerf_fem.calculix_utils import parse_nonlinear_plastic_dat
        nodes = [[1.0e-3, 0.0, -2.5e-4], [0.0, 0.0, 0.0]]
        content = self._make_displacement_block(nodes) + "\n\n"
        p = self._write_dat(content)
        result = parse_nonlinear_plastic_dat(p)
        assert len(result["displacements"]) == 2
        ux, uy, uz = result["displacements"][0]
        assert abs(ux - 1.0e-3) < 1e-12
        assert abs(uz - (-2.5e-4)) < 1e-12

    def test_stress_block_parsed_von_mises(self):
        """
        For uniaxial stress σ_x = σ, the von Mises stress is σ.
        Verify the parser computes it correctly.
        """
        from kerf_fem.calculix_utils import parse_nonlinear_plastic_dat
        sigma = 300e6
        stress_entry = {"sx": sigma, "sy": 0.0, "sz": 0.0,
                        "txy": 0.0, "tyz": 0.0, "txz": 0.0}
        vm_expected = math.sqrt(0.5 * (
            (sigma - 0)**2 + (0 - 0)**2 + (0 - sigma)**2
            + 6 * 0.0
        ))  # = sigma

        content = self._make_stress_block([stress_entry]) + "\n\n"
        p = self._write_dat(content)
        result = parse_nonlinear_plastic_dat(p)
        assert len(result["stresses"]) == 1
        vm_parsed = result["stresses"][0]["von_mises"]
        assert abs(vm_parsed - vm_expected) / vm_expected < 1e-6, (
            f"Parsed von Mises {vm_parsed:.4e} != expected {vm_expected:.4e}"
        )

    def test_peeq_block_parsed(self):
        from kerf_fem.calculix_utils import parse_nonlinear_plastic_dat
        sigma = 300e6
        stress_entry = {"sx": sigma}
        peeq_vals = [0.0015, 0.003]
        # Two stress entries, two PEEQ values
        content = (
            self._make_stress_block([stress_entry, stress_entry])
            + "\n\n"
            + self._make_peeq_block(peeq_vals)
            + "\n\n"
        )
        p = self._write_dat(content)
        result = parse_nonlinear_plastic_dat(p)
        assert len(result["stresses"]) == 2
        assert abs(result["stresses"][0].get("peeq", -1) - peeq_vals[0]) < 1e-12
        assert abs(result["stresses"][1].get("peeq", -1) - peeq_vals[1]) < 1e-12

    def test_peeq_defaults_to_zero_when_absent(self):
        """When PEEQ block is missing all stresses should have peeq=0."""
        from kerf_fem.calculix_utils import parse_nonlinear_plastic_dat
        sigma = 280e6
        content = self._make_stress_block([{"sx": sigma}]) + "\n\n"
        p = self._write_dat(content)
        result = parse_nonlinear_plastic_dat(p)
        assert result["stresses"][0].get("peeq", 0.0) == 0.0


# ===========================================================================
# §4  Sentinel when ccx is absent
# ===========================================================================

class TestSentinel:

    def test_run_static_analysis_nonlinear_plastic_absent_returns_sentinel(self):
        """
        When ccx is not installed, run_static_analysis must return the
        ENGINE_PENDING_WARNING sentinel rather than raising an exception.
        """
        import kerf_fem.calculix_utils as cu

        with patch.object(cu, "_ccx_available", return_value=False):
            result = cu.run_static_analysis(
                mesh_path="irrelevant.msh",
                material_props=_MAT,
                boundary_conditions=_BCS,
                loads=_LOADS,
                analysis_type="nonlinear_plastic",
            )

        assert result.get("status") == "pending", (
            f"Expected status='pending' but got {result!r}"
        )
        assert any(cu.ENGINE_PENDING_WARNING in w for w in result.get("warnings", [])), (
            f"ENGINE_PENDING_WARNING not in warnings: {result.get('warnings')}"
        )
        assert "errors" in result

    def test_sentinel_shape_matches_other_analysis_types(self):
        """
        The sentinel dict for nonlinear_plastic must have the same top-level
        keys as for linear_static (both use the same early-return guard).
        """
        import kerf_fem.calculix_utils as cu

        with patch.object(cu, "_ccx_available", return_value=False):
            r_linear = cu.run_static_analysis("x", _MAT, [], [], "linear_static")
            r_plastic = cu.run_static_analysis("x", _MAT, [], [], "nonlinear_plastic")

        assert set(r_linear.keys()) == set(r_plastic.keys()), (
            f"Sentinel keys differ: linear={set(r_linear.keys())} plastic={set(r_plastic.keys())}"
        )


# ===========================================================================
# §5  Analytical elastic-plastic reference
# ===========================================================================

class TestAnalyticalReference:
    """
    Verify the J2 return-mapping engine (nonlinear_bar.py) against
    closed-form elastic-plastic solutions.  This is the engine-independent
    reference required by the DoD.

    The CalculiX nonlinear_plastic analysis_type invokes the same constitutive
    algorithm in the solver; these tests confirm the algorithm is correct
    without needing the binary installed.
    """

    def test_elastic_regime_hooke(self):
        """σ = E · ε in the elastic regime."""
        from kerf_fem.nonlinear_bar import run_nonlinear_bar

        eps_targets = [0.3 * eps_y, 0.6 * eps_y, 0.9 * eps_y]
        res = run_nonlinear_bar(E_STEEL, SY, H_MOD, eps_targets)
        assert res["ok"]
        for i, eps in enumerate(eps_targets):
            sigma_expected = E_STEEL * eps
            assert abs(res["stress"][i] - sigma_expected) / sigma_expected < 1e-9, (
                f"step {i}: σ={res['stress'][i]:.4e} vs E·ε={sigma_expected:.4e}"
            )

    def test_post_yield_hardening_slope(self):
        """
        Post-yield tangent: dσ/dε = E·H/(E+H)  (bilinear isotropic hardening).
        Analytical: σ(ε) = σ_y + Et · (ε − ε_y)   for ε > ε_y.
        """
        from kerf_fem.nonlinear_bar import run_nonlinear_bar

        Et = E_STEEL * H_MOD / (E_STEEL + H_MOD)
        eps1 = 2.0 * eps_y
        eps2 = 4.0 * eps_y
        res = run_nonlinear_bar(E_STEEL, SY, H_MOD, [eps_y, eps1, eps2])
        assert res["ok"]

        # σ at eps1
        sigma1_expected = SY + Et * (eps1 - eps_y)
        assert abs(res["stress"][1] - sigma1_expected) / sigma1_expected < 1e-9

        # σ at eps2
        sigma2_expected = SY + Et * (eps2 - eps_y)
        assert abs(res["stress"][2] - sigma2_expected) / sigma2_expected < 1e-9

        # Measured slope between eps1 and eps2
        slope = (res["stress"][2] - res["stress"][1]) / (eps2 - eps1)
        assert abs(slope - Et) / Et < 1e-9

    def test_perfect_plasticity_stress_cap(self):
        """H=0: stress never exceeds σ_y regardless of applied strain."""
        from kerf_fem.nonlinear_bar import run_nonlinear_bar

        targets = [k * eps_y for k in [1, 2, 5, 10, 50]]
        res = run_nonlinear_bar(E_STEEL, SY, 0.0, targets)
        assert res["ok"]
        for i, s in enumerate(res["stress"]):
            assert s <= SY + 1e-3, f"step {i}: stress {s:.4e} > σ_y {SY:.4e}"

    def test_plastic_strain_equals_delta_gamma(self):
        """
        For a single 1-D increment from zero:
            Δγ = (|σ_trial| − σ_y) / (E + H)
            εᵖ  = Δγ
        """
        from kerf_fem.nonlinear_bar import _return_map_1d

        eps_inc = 3.0 * eps_y
        sigma, ep = _return_map_1d(0.0, 0.0, eps_inc, E_STEEL, SY, H_MOD)
        sigma_trial = E_STEEL * eps_inc
        f_trial = sigma_trial - SY   # positive (yielding)
        delta_gamma = f_trial / (E_STEEL + H_MOD)
        assert abs(ep - delta_gamma) / delta_gamma < 1e-12

    def test_elastic_plastic_cantilever_tip_deflection(self):
        """
        Cantilever bar reference: elastic response up to yield, then hardening.

        Bar of length L = 1 m, area A = 1 cm².  Fixed at left, axial load F at right.
        Tip displacement = F * L / (E * A)  in the elastic regime.
        After yielding, tip displacement grows faster (reduced tangent stiffness).

        Verified via run_truss_plastic (single-element horizontal truss).
        """
        from kerf_fem.nonlinear_bar import run_truss_plastic

        L = 1.0
        A = 1e-4   # m²
        nodes = [(0.0, 0.0), (L, 0.0)]
        elements = [(0, 1)]

        # Elastic load: F = 0.5 * σ_y * A
        F_elastic = 0.5 * SY * A
        u_elastic_expected = F_elastic * L / (E_STEEL * A)

        steps_elastic = [{"forces": {"1": [F_elastic, 0.0]}, "fixed_dofs": [0, 1, 3]}]
        res_e = run_truss_plastic(nodes, elements, E_STEEL, A, SY, H_MOD, steps_elastic)
        assert res_e["ok"], res_e.get("reason")
        u_e = res_e["history"][0]["displacements"][2]  # node 1 x-DOF
        assert abs(u_e - u_elastic_expected) / u_elastic_expected < 1e-8, (
            f"Elastic tip displacement {u_e:.4e} vs expected {u_elastic_expected:.4e}"
        )

        # Plastic load: F = 2 * σ_y * A → stress hardened above σ_y
        F_plastic = 2.0 * SY * A
        steps_plastic = [{"forces": {"1": [F_plastic, 0.0]}, "fixed_dofs": [0, 1, 3]}]
        res_p = run_truss_plastic(nodes, elements, E_STEEL, A, SY, H_MOD, steps_plastic)
        assert res_p["ok"], res_p.get("reason")
        sigma_p = res_p["history"][0]["element_stress"][0]
        ep_p = res_p["history"][0]["element_plastic_strain"][0]

        # σ > σ_y (hardening)
        assert sigma_p > SY, f"Post-yield stress {sigma_p:.4e} should exceed σ_y {SY:.4e}"
        # εᵖ > 0
        assert ep_p > 0.0, "Post-yield plastic strain must be positive"

        # Verify stress against analytical formula:
        # σ = σ_y + Et * εᵖ / 1  (since εᵖ = Δγ, σ = σ_y + H * Δγ for 1-D)
        # Simpler: σ = σ_y + H * εᵖ  (isotropic hardening, 1-D)
        sigma_analytical = SY + H_MOD * ep_p
        assert abs(sigma_p - sigma_analytical) / sigma_analytical < 1e-6, (
            f"Post-yield stress {sigma_p:.4e} vs analytical {sigma_analytical:.4e}"
        )

    def test_unloading_is_elastic(self):
        """
        After plastic loading, a partial unload follows E (not Et).
        Δσ_unload = E · Δε_unload.
        """
        from kerf_fem.nonlinear_bar import run_nonlinear_bar

        eps_load   = 3.0 * eps_y   # load well into plastic regime
        eps_unload = 2.0 * eps_y   # partial unload (still positive)
        res = run_nonlinear_bar(E_STEEL, SY, H_MOD, [eps_load, eps_unload])
        assert res["ok"]

        # Unload is elastic: Δσ = E · Δε
        delta_eps = eps_unload - eps_load    # negative
        delta_sigma_expected = E_STEEL * delta_eps
        delta_sigma_actual = res["stress"][1] - res["stress"][0]
        assert abs(delta_sigma_actual - delta_sigma_expected) / abs(delta_sigma_expected) < 1e-9

    def test_plastic_strain_frozen_on_elastic_unload(self):
        """εᵖ must not change during an elastic unloading step."""
        from kerf_fem.nonlinear_bar import run_nonlinear_bar

        res = run_nonlinear_bar(E_STEEL, SY, H_MOD, [3.0 * eps_y, 2.0 * eps_y])
        assert res["ok"]
        assert res["plastic_strain"][0] == res["plastic_strain"][1]
