"""
Z88 subprocess bridge tests.

Test categories
---------------
1. Input-file generators — syntax validity (hermetic, no solver required).
2. Analytic Euler-Bernoulli oracle — pure Python, always runs.
3. Z88 subprocess path — modal cantilever vs. analytic oracle (pytest.skip
   when z88r/z88 is not on PATH).
4. Skipped-path sentinel — monkeypatched to verify pending result.

Reference
---------
Blevins (1979) Table 8-1: clamped-free beam first 3 natural frequencies.
"""

from __future__ import annotations

import math
import shutil

import pytest

from kerf_fem.z88_bridge import (
    ENGINE_PENDING_WARNING,
    Z88Bridge,
    _z88_available,
    write_z88com_file,
    write_z88i1_file,
    write_z88i2_file,
    write_z88i5_file,
    write_z88i6_file,
    write_z88i7_file,
    _parse_z88o2,
    _parse_z88o3,
)
from kerf_fem.z88_corpus import (
    cantilever_modal_fixture,
    check_z88_modal_frequencies,
    euler_bernoulli_cantilever_frequencies,
)


# ===========================================================================
# Helpers
# ===========================================================================

_NEEDS_Z88 = pytest.mark.skipif(
    not _z88_available(),
    reason="z88r / z88 not installed or not in PATH",
)

# Minimal 2-tetra mesh (2 tetrahedra, 5 nodes).
_NODES_SIMPLE = [
    [0.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
    [1.0, 1.0, 1.0],
]
_ELEMS_SIMPLE = [
    [0, 1, 2, 3],  # tet 1 — 0-based node IDs
    [1, 2, 3, 4],  # tet 2
]
_MAT_SIMPLE = {"E": 200e9, "nu": 0.3, "rho": 7850.0, "yield_strength": 250e6}
_BCS_SIMPLE = [{"type": "fixed", "face": "xmin"}]


# ===========================================================================
# 1. Input-file generators: syntax validity
# ===========================================================================

class TestZ88InputFileGenerators:
    """Generators produce valid Z88 syntax without calling the solver."""

    def test_z88i1_header_format(self):
        """First line must be: n_nodes n_elems dim dof_per_node n_dof_constrained."""
        content = write_z88i1_file(_NODES_SIMPLE, n_elems=2, n_dof_constrained=6)
        first_line = content.splitlines()[0]
        parts = first_line.split()
        assert len(parts) == 5, f"Header must have 5 fields, got {len(parts)}: {first_line!r}"
        assert int(parts[0]) == len(_NODES_SIMPLE)  # n_nodes
        assert int(parts[1]) == 2                   # n_elems
        assert int(parts[2]) == 3                   # dim
        assert int(parts[3]) == 3                   # dof_per_node
        assert int(parts[4]) == 6                   # n_dof_constrained

    def test_z88i1_node_count(self):
        """z88i1 must contain exactly n_nodes coordinate lines after the header."""
        content = write_z88i1_file(_NODES_SIMPLE, n_elems=2, n_dof_constrained=0)
        lines = [l for l in content.splitlines() if l.strip()]
        # First line is header; remaining are node coordinates.
        assert len(lines) - 1 == len(_NODES_SIMPLE)

    def test_z88i1_node_id_sequence(self):
        """Node IDs must start at 1 and be consecutive."""
        content = write_z88i1_file(_NODES_SIMPLE, n_elems=2, n_dof_constrained=0)
        coord_lines = content.splitlines()[1:]
        for i, line in enumerate(coord_lines):
            if not line.strip():
                continue
            node_id = int(line.split()[0])
            assert node_id == i + 1

    def test_z88i1_node_coordinates_match(self):
        """Node coordinates must be reproduced correctly."""
        content = write_z88i1_file(_NODES_SIMPLE, n_elems=2, n_dof_constrained=0)
        for i, line in enumerate(content.splitlines()[1:]):
            if not line.strip():
                continue
            parts = line.split()
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            assert abs(x - _NODES_SIMPLE[i][0]) < 1e-9
            assert abs(y - _NODES_SIMPLE[i][1]) < 1e-9
            assert abs(z - _NODES_SIMPLE[i][2]) < 1e-9

    def test_z88i2_element_count(self):
        """z88i2 must have exactly n_elements lines."""
        from kerf_fem.z88_bridge import _mesh_to_z88_elements
        nodes, elems = _mesh_to_z88_elements(
            {"nodes": _NODES_SIMPLE, "elements": _ELEMS_SIMPLE}
        )
        content = write_z88i2_file(elems)
        data_lines = [l for l in content.splitlines() if l.strip()]
        assert len(data_lines) == len(_ELEMS_SIMPLE)

    def test_z88i2_element_id_sequence(self):
        """Element IDs start at 1 and are consecutive."""
        from kerf_fem.z88_bridge import _mesh_to_z88_elements
        nodes, elems = _mesh_to_z88_elements(
            {"nodes": _NODES_SIMPLE, "elements": _ELEMS_SIMPLE}
        )
        content = write_z88i2_file(elems)
        for i, line in enumerate(content.splitlines()):
            if not line.strip():
                continue
            eid = int(line.split()[0])
            assert eid == i + 1

    def test_z88i2_node_connectivity_is_1based(self):
        """Element connectivity in z88i2 must use 1-based node IDs."""
        from kerf_fem.z88_bridge import _mesh_to_z88_elements
        nodes, elems = _mesh_to_z88_elements(
            {"nodes": _NODES_SIMPLE, "elements": _ELEMS_SIMPLE}
        )
        content = write_z88i2_file(elems)
        for line in content.splitlines():
            if not line.strip():
                continue
            # Format: eid  etype  dof_per_node  n1 n2 n3 n4 ...
            parts = line.split()
            # Node IDs start at position 3.
            node_ids = [int(p) for p in parts[3:]]
            assert all(n >= 1 for n in node_ids), (
                f"Node IDs must be ≥ 1 (1-based), found: {node_ids}"
            )

    def test_z88i5_material_line_format(self):
        """z88i5 must have a header count line then one material line per set."""
        content = write_z88i5_file(200e9, 0.3, 7850.0)
        lines = [l for l in content.splitlines() if l.strip()]
        assert int(lines[0]) == 1  # n_material_sets
        mat_parts = lines[1].split()
        assert int(mat_parts[0]) == 1       # set_id = 1
        assert float(mat_parts[1]) == 200e9  # E
        assert float(mat_parts[2]) == 0.3    # nu
        assert float(mat_parts[3]) == 7850.0 # rho

    def test_z88i6_header_count(self):
        """First line of z88i6 must equal total number of constraint entries."""
        content = write_z88i6_file(_BCS_SIMPLE, _NODES_SIMPLE)
        lines = [l for l in content.splitlines() if l.strip()]
        header_count = int(lines[0])
        assert header_count == len(lines) - 1

    def test_z88i6_dof_range(self):
        """All DOF numbers in z88i6 must be in range [1, 6]."""
        content = write_z88i6_file(_BCS_SIMPLE, _NODES_SIMPLE)
        lines = content.splitlines()
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split()
            dof = int(parts[1])
            assert 1 <= dof <= 6, f"DOF out of range: {dof} in line {line!r}"

    def test_z88i6_zero_constraint_value(self):
        """Fixed BC must produce zero displacement values."""
        content = write_z88i6_file(_BCS_SIMPLE, _NODES_SIMPLE)
        lines = content.splitlines()
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split()
            assert float(parts[2]) == 0.0

    def test_z88i7_no_loads(self):
        """Empty loads list must produce '0' as the only line."""
        content = write_z88i7_file([])
        assert content.strip() == "0"

    def test_z88i7_force_load_format(self):
        """Force load must appear as: node_id  dof  value."""
        loads = [{"type": "force", "node_id": 3, "dof": 2, "value": -500.0}]
        content = write_z88i7_file(loads)
        lines = [l for l in content.splitlines() if l.strip()]
        assert int(lines[0]) == 1
        parts = lines[1].split()
        assert int(parts[0]) == 3
        assert int(parts[1]) == 2
        assert float(parts[2]) == -500.0

    def test_z88com_static_ibflag(self):
        """z88com for linear_static must set IBFLAG 1."""
        content = write_z88com_file("linear_static")
        assert "IBFLAG 1" in content

    def test_z88com_modal_ibflag(self):
        """z88com for modal must set IBFLAG 2."""
        content = write_z88com_file("modal", n_modes=5)
        assert "IBFLAG 2" in content
        assert "NFREQ 5" in content

    def test_z88com_nonlinear_ibflag(self):
        """z88com for nonlinear must set IBFLAG 3."""
        content = write_z88com_file("nonlinear")
        assert "IBFLAG 3" in content


# ===========================================================================
# 2. Analytic Euler-Bernoulli oracle (pure Python, always runs)
# ===========================================================================

class TestEulerBernoulliOracle:
    """
    Analytic oracle tests — fully hermetic, no external dependencies.

    Reference values from Blevins (1979) Table 8-1.
    """

    # Beam: steel, 0.5 m long, 50 mm × 50 mm cross-section.
    _E = 200e9      # Pa
    _b = 0.05       # m
    _h = 0.05       # m
    _rho = 7850.0   # kg/m³
    _L = 0.5        # m

    @property
    def _I(self):
        return self._b * self._h ** 3 / 12.0

    @property
    def _A(self):
        return self._b * self._h

    def _oracle_freqs(self, n=3):
        return euler_bernoulli_cantilever_frequencies(
            self._E, self._I, self._rho, self._A, self._L, n_modes=n
        )

    def test_returns_n_modes(self):
        """Oracle returns exactly n_modes values."""
        for n in (1, 2, 3):
            freqs = self._oracle_freqs(n)
            assert len(freqs) == n

    def test_frequencies_are_positive(self):
        """All natural frequencies must be strictly positive."""
        freqs = self._oracle_freqs(3)
        assert all(f > 0 for f in freqs)

    def test_frequencies_are_ascending(self):
        """Natural frequencies must be in ascending order."""
        freqs = self._oracle_freqs(3)
        for i in range(len(freqs) - 1):
            assert freqs[i] < freqs[i + 1]

    def test_first_mode_blevins_reference(self):
        """
        First natural frequency: Blevins Table 8-1, mode 1.

        For the reference beam (E=200 GPa, 50×50 mm, L=0.5 m, rho=7850):
            β₁L = 1.8751, f₁ ≈ (1.8751/0.5)² / (2π) · √(EI / (ρA))

        We verify < 0.1 % relative to the formula, not a hard-coded Hz value,
        to ensure the oracle is independent of any particular floating-point
        result (cross-check computed externally below).
        """
        I = self._I
        A = self._A
        beta1_L = 1.8751040687
        c = math.sqrt(self._E * I / (self._rho * A))
        omega1 = (beta1_L / self._L) ** 2 * c
        f1_expected = omega1 / (2.0 * math.pi)

        freqs = self._oracle_freqs(1)
        assert abs(freqs[0] - f1_expected) / f1_expected < 1e-6

    def test_mode_ratio_blevins(self):
        """
        Ratio f₂/f₁ must match the Blevins β values squared.

        (β₂L / β₁L)² = (4.6941 / 1.8751)² ≈ 6.267
        """
        freqs = self._oracle_freqs(2)
        ratio = freqs[1] / freqs[0]
        expected_ratio = (4.6940911329 / 1.8751040687) ** 2
        assert abs(ratio - expected_ratio) / expected_ratio < 1e-6

    def test_mode3_ratio_blevins(self):
        """
        Ratio f₃/f₁ must match the Blevins β values squared.

        (β₃L / β₁L)² = (7.8548 / 1.8751)² ≈ 17.55
        """
        freqs = self._oracle_freqs(3)
        ratio = freqs[2] / freqs[0]
        expected_ratio = (7.8547574382 / 1.8751040687) ** 2
        assert abs(ratio - expected_ratio) / expected_ratio < 1e-6

    def test_frequency_scales_with_stiffness(self):
        """Doubling EI should increase frequencies by √2 (ω ∝ √(EI/ρAL⁴))."""
        f_base = self._oracle_freqs(1)[0]
        f_stiff = euler_bernoulli_cantilever_frequencies(
            self._E * 2, self._I, self._rho, self._A, self._L, n_modes=1
        )[0]
        assert abs(f_stiff / f_base - math.sqrt(2.0)) < 1e-6

    def test_frequency_scales_with_length(self):
        """Doubling L should reduce f₁ by 4× (ω ∝ 1/L²)."""
        f_short = self._oracle_freqs(1)[0]
        f_long = euler_bernoulli_cantilever_frequencies(
            self._E, self._I, self._rho, self._A, self._L * 2, n_modes=1
        )[0]
        assert abs(f_short / f_long - 4.0) < 1e-6

    def test_invalid_n_modes_raises(self):
        """n_modes=0 must raise ValueError."""
        with pytest.raises(ValueError):
            euler_bernoulli_cantilever_frequencies(
                self._E, self._I, self._rho, self._A, self._L, n_modes=0
            )

    def test_too_many_modes_raises(self):
        """n_modes > 6 must raise ValueError (only 6 β_n L values tabulated)."""
        with pytest.raises(ValueError):
            euler_bernoulli_cantilever_frequencies(
                self._E, self._I, self._rho, self._A, self._L, n_modes=7
            )


# ===========================================================================
# 3. Cantilever fixture generator
# ===========================================================================

class TestCantileverFixture:
    """Tests for the cantilever_modal_fixture mesh generator."""

    def _fix(self, **kwargs):
        return cantilever_modal_fixture(**kwargs)

    def test_returns_required_keys(self):
        f = self._fix()
        for key in ("mesh", "materials", "boundary_conditions", "analytic_frequencies"):
            assert key in f, f"Missing key: {key!r}"

    def test_mesh_has_nodes_and_elements(self):
        f = self._fix()
        assert len(f["mesh"]["nodes"]) > 0
        assert len(f["mesh"]["elements"]) > 0

    def test_node_count_formula(self):
        """Node count = (nx+1)(ny+1)(nz+1) for a structured hex mesh."""
        f = self._fix(n_elem_x=4, n_elem_y=2, n_elem_z=2)
        expected = (4 + 1) * (2 + 1) * (2 + 1)
        assert len(f["mesh"]["nodes"]) == expected

    def test_element_count_formula(self):
        """Element count = nx*ny*nz for a structured hex mesh."""
        f = self._fix(n_elem_x=4, n_elem_y=2, n_elem_z=2)
        expected = 4 * 2 * 2
        assert len(f["mesh"]["elements"]) == expected

    def test_elements_have_8_nodes(self):
        """All elements must have 8 nodes (hex8)."""
        f = self._fix(n_elem_x=2, n_elem_y=1, n_elem_z=1)
        for elem in f["mesh"]["elements"]:
            assert len(elem) == 8

    def test_analytic_frequencies_are_3(self):
        """Fixture must supply 3 analytic frequencies."""
        f = self._fix()
        assert len(f["analytic_frequencies"]) == 3

    def test_analytic_frequencies_positive_ascending(self):
        f = self._fix()
        freqs = f["analytic_frequencies"]
        assert all(v > 0 for v in freqs)
        for i in range(len(freqs) - 1):
            assert freqs[i] < freqs[i + 1]

    def test_boundary_condition_is_fixed_xmin(self):
        f = self._fix()
        bc = f["boundary_conditions"][0]
        assert bc["type"] == "fixed"
        assert bc["face"] == "xmin"

    def test_nodes_span_correct_length(self):
        """Node x-coordinates must span [0, L]."""
        L = 0.3
        f = self._fix(L=L)
        xs = [n[0] for n in f["mesh"]["nodes"]]
        assert abs(min(xs)) < 1e-9
        assert abs(max(xs) - L) < 1e-9

    def test_z88i1_file_valid_for_fixture(self):
        """z88i1 written from fixture must have correct header node count."""
        f = self._fix(n_elem_x=2, n_elem_y=1, n_elem_z=1)
        nodes = f["mesh"]["nodes"]
        elems = f["mesh"]["elements"]
        content = write_z88i1_file(nodes, n_elems=len(elems), n_dof_constrained=0)
        n_nodes_header = int(content.splitlines()[0].split()[0])
        assert n_nodes_header == len(nodes)


# ===========================================================================
# 4. Output parsers (no solver required)
# ===========================================================================

class TestOutputParsers:
    """Verify that the Z88 output parsers work on synthetic text."""

    def test_parse_z88o2_tabular(self):
        """Tabular displacement format must be parsed correctly."""
        text = (
            "NODE   UX           UY           UZ\n"
            "   1   1.234E-05  -2.345E-05   0.000E+00\n"
            "   2   3.100E-05  -4.200E-05   1.000E-06\n"
        )
        result = _parse_z88o2(text)
        disps = result["node_displacements"]
        assert len(disps) == 2
        assert abs(disps[0]["ux"] - 1.234e-5) < 1e-12
        assert abs(disps[0]["uy"] - (-2.345e-5)) < 1e-12
        assert abs(disps[0]["uz"]) < 1e-12

    def test_parse_z88o2_mag_computed(self):
        """Magnitude must equal sqrt(ux²+uy²+uz²)."""
        text = "NODE   UX  UY  UZ\n1  3.0  4.0  0.0\n"
        result = _parse_z88o2(text)
        disps = result["node_displacements"]
        assert abs(disps[0]["mag"] - 5.0) < 1e-9

    def test_parse_z88o3_freq_format(self):
        """Aurora FREQ format must return sorted frequencies."""
        text = (
            "FREQ   1   123.45\n"
            "FREQ   2   789.00\n"
            "FREQ   3   1500.5\n"
        )
        freqs = _parse_z88o3(text)
        assert freqs == sorted(freqs)
        assert abs(freqs[0] - 123.45) < 1e-6
        assert abs(freqs[1] - 789.00) < 1e-6
        assert abs(freqs[2] - 1500.5) < 1e-6

    def test_parse_z88o3_eigenfreq_format(self):
        """Block EIGENFREQUENCY format must be parsed."""
        text = (
            "EIGENFREQUENCY   1 :   2.3456E+02 Hz\n"
            "EIGENFREQUENCY   2 :   1.0123E+03 Hz\n"
        )
        freqs = _parse_z88o3(text)
        assert len(freqs) == 2
        assert abs(freqs[0] - 234.56) < 1e-3

    def test_parse_z88o3_empty(self):
        """Empty content must return an empty list."""
        assert _parse_z88o3("") == []

    def test_parse_z88o2_empty(self):
        """Empty content must return empty node_displacements list."""
        result = _parse_z88o2("")
        assert result["node_displacements"] == []


# ===========================================================================
# 5. Tolerance checker
# ===========================================================================

class TestToleranceChecker:

    def test_pass_when_within_tolerance(self):
        z88 = [100.0, 500.0, 1000.0]
        oracle = [100.0, 500.0, 1000.0]
        r = check_z88_modal_frequencies(z88, oracle, tolerance=0.03)
        assert r["ok"]
        assert r["n_checked"] == 3
        assert all(m["pass"] for m in r["modes"])

    def test_fail_when_outside_tolerance(self):
        z88 = [100.0, 550.0, 1000.0]  # mode 2 is 10% off
        oracle = [100.0, 500.0, 1000.0]
        r = check_z88_modal_frequencies(z88, oracle, tolerance=0.03)
        assert not r["ok"]
        assert len(r["failures"]) == 1
        assert r["modes"][1]["pass"] is False

    def test_partial_comparison_by_min_length(self):
        """If z88 returns fewer modes than oracle, only check available modes."""
        z88 = [100.0, 500.0]
        oracle = [100.0, 500.0, 1000.0]
        r = check_z88_modal_frequencies(z88, oracle)
        assert r["n_checked"] == 2

    def test_relative_error_computation(self):
        z88 = [103.0]
        oracle = [100.0]
        r = check_z88_modal_frequencies(z88, oracle, tolerance=0.05)
        assert abs(r["modes"][0]["rel_err"] - 0.03) < 1e-9
        assert r["modes"][0]["pass"]

    def test_exactly_at_tolerance_boundary(self):
        """Exactly at 3 % must pass (≤ not <)."""
        z88 = [103.0]
        oracle = [100.0]
        r = check_z88_modal_frequencies(z88, oracle, tolerance=0.03)
        assert r["modes"][0]["pass"]

    def test_empty_inputs(self):
        r = check_z88_modal_frequencies([], [], tolerance=0.03)
        assert not r["ok"]  # no modes checked → ok=False
        assert r["n_checked"] == 0


# ===========================================================================
# 6. Skipped-path sentinel (monkeypatched)
# ===========================================================================

class TestZ88SkippedPath:
    """Verify pending sentinel when z88 is not available."""

    def test_pending_when_z88_absent(self, monkeypatch):
        """
        When z88r / z88 are absent (monkeypatched), solve() must return
        status='pending' with the ENGINE_PENDING_WARNING.
        """
        import kerf_fem.z88_bridge as _bridge

        monkeypatch.setattr(_bridge, "_Z88_AVAILABLE", None)
        monkeypatch.setattr(shutil, "which", lambda _: None)

        bridge = Z88Bridge()
        result = bridge.solve(
            mesh={"nodes": _NODES_SIMPLE, "elements": _ELEMS_SIMPLE},
            materials=_MAT_SIMPLE,
            boundary_conditions=_BCS_SIMPLE,
            analysis_type="linear_static",
        )

        assert result.get("status") == "pending"
        assert result.get("ok") is False
        warnings = result.get("warnings", [])
        assert any(
            "z88" in w.lower() or "pending" in w.lower()
            for w in warnings
        ), f"Expected Z88 pending warning, got: {warnings}"

    def test_pending_warning_contains_engine_text(self, monkeypatch):
        """The pending warning must equal ENGINE_PENDING_WARNING."""
        import kerf_fem.z88_bridge as _bridge

        monkeypatch.setattr(_bridge, "_Z88_AVAILABLE", None)
        monkeypatch.setattr(shutil, "which", lambda _: None)

        bridge = Z88Bridge()
        result = bridge.solve(
            mesh={"nodes": _NODES_SIMPLE, "elements": _ELEMS_SIMPLE},
            materials=_MAT_SIMPLE,
            boundary_conditions=_BCS_SIMPLE,
        )
        assert ENGINE_PENDING_WARNING in result.get("warnings", [])


# ===========================================================================
# 7. Live Z88 modal: cantilever beam vs. Euler-Bernoulli oracle (skipped when
#    z88 is absent)
# ===========================================================================

@_NEEDS_Z88
class TestZ88ModalCantilever:
    """
    Integration tests that invoke the Z88 solver.  Skipped automatically when
    z88r / z88 is not on PATH.

    The reference is the Euler-Bernoulli analytic oracle for a clamped-free
    prismatic beam.  Tolerance: 3 %.

    Reference: Blevins (1979) Table 8-1.
    """

    def _run_modal(self, *, L=0.5, b=0.05, h=0.05, n_elem_x=8, n_modes=3):
        fixture = cantilever_modal_fixture(
            L=L, b=b, h=h,
            n_elem_x=n_elem_x, n_elem_y=2, n_elem_z=2,
        )
        bridge = Z88Bridge()
        result = bridge.solve(
            mesh=fixture["mesh"],
            materials=fixture["materials"],
            boundary_conditions=fixture["boundary_conditions"],
            analysis_type="modal",
            n_modes=n_modes,
        )
        return result, fixture["analytic_frequencies"]

    def test_modal_returns_ok(self):
        result, _ = self._run_modal()
        assert result.get("ok"), f"Z88 modal failed: {result.get('errors')}"

    def test_modal_returns_frequencies(self):
        result, _ = self._run_modal()
        freqs = result.get("frequencies", [])
        assert len(freqs) >= 1, "Z88 must return at least one frequency"

    def test_modal_first_3_modes_within_3pct(self):
        """
        First 3 natural frequencies must be within 3 % of the Euler-Bernoulli
        analytic oracle.

        Reference: Blevins (1979) Table 8-1 (clamped-free beam, bending modes).
        """
        result, analytic = self._run_modal(n_modes=3)
        z88_freqs = result.get("frequencies", [])

        report = check_z88_modal_frequencies(
            z88_freqs, analytic, tolerance=0.03
        )
        assert report["ok"], (
            "Z88 modal frequencies outside 3% tolerance.\n"
            + "\n".join(report["failures"])
        )

    def test_modal_frequencies_ascending(self):
        result, _ = self._run_modal()
        freqs = result.get("frequencies", [])
        for i in range(len(freqs) - 1):
            assert freqs[i] <= freqs[i + 1], (
                f"Frequencies not ascending: {freqs}"
            )
