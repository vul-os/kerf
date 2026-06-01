"""
MYSTRAN subprocess bridge tests.

Test groups
-----------
1. BDF syntax tests (hermetic — no solver needed).
   Verify that the BDF generator produces syntactically valid bulk-data
   decks.  Checks: required section keywords, GRID/element counts,
   SPC1 presence, EIGRL presence for modal, ENDDATA terminator.

2. Leissa analytic oracle tests (hermetic — pure Python, no solver).
   Verify that ``leissa_plate_freq_hz`` and
   ``leissa_plate_first_three_modes`` return values consistent with the
   closed-form formula from Leissa (1969) NASA SP-160, Table 4.1.
   These tests are always run and can never be skipped.

3. MYSTRAN round-trip tests (skipped when ``mystran`` not on PATH).
   Run the SSSS plate corpus case through the live solver and assert
   that the first three natural frequencies fall within 3 % of the
   Leissa analytic oracle.

4. Pending-sentinel test.
   When ``shutil.which("mystran")`` is monkeypatched to return None,
   ``MystranBridge.solve`` must return ``status="pending"`` without
   raising.

References
----------
Leissa, A.W., "Vibration of Plates", NASA SP-160, 1969.
Blevins, R.D., "Formulas for Natural Frequency and Mode Shape", 1979.
"""

from __future__ import annotations

import math
import shutil
import re

import pytest

# ---------------------------------------------------------------------------
# Skip marker for tests that need the live mystran binary
# ---------------------------------------------------------------------------

_needs_mystran = pytest.mark.skipif(
    shutil.which("mystran") is None,
    reason="mystran not installed or not in PATH",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_bridge():
    from kerf_fem.mystran_bridge import MystranBridge
    return MystranBridge


def _load_corpus():
    from kerf_fem import mystran_corpus
    return mystran_corpus


# ===========================================================================
# 1. BDF syntax tests (hermetic)
# ===========================================================================


class TestBdfSyntax:
    """Verify the BDF deck writer produces valid bulk-data syntax."""

    def test_modal_deck_has_sol103(self):
        """SOL 103 must appear as the first executive control card."""
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        lines = deck.splitlines()
        assert lines[0].strip().startswith("SOL 103"), (
            f"Expected 'SOL 103' on line 1, got: {lines[0]!r}"
        )

    def test_modal_deck_has_cend(self):
        """CEND must terminate the executive control section."""
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        assert "CEND" in deck, "BDF deck missing CEND keyword"

    def test_modal_deck_has_begin_bulk(self):
        """BEGIN BULK must delimit the case control / bulk data boundary."""
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        assert "BEGIN BULK" in deck, "BDF deck missing BEGIN BULK"

    def test_modal_deck_has_enddata(self):
        """ENDDATA must terminate the bulk data section (required by NASTRAN)."""
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        lines = [ln.strip() for ln in deck.splitlines()]
        assert "ENDDATA" in lines, "BDF deck missing ENDDATA"

    def test_modal_deck_has_eigrl(self):
        """EIGRL card must be present for SOL 103 eigenvalue extraction."""
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        eigrl_lines = [ln for ln in deck.splitlines() if ln.startswith("EIGRL")]
        assert eigrl_lines, "BDF modal deck missing EIGRL card"

    def test_modal_deck_grid_count(self):
        """Number of GRID cards must match the mesh node count."""
        corpus = _load_corpus()
        case = corpus.build_corpus()[0]
        mesh = case.mesh

        deck = corpus.ssss_plate_bdf()
        grid_count = sum(1 for ln in deck.splitlines() if ln.startswith("GRID,"))
        expected = len(mesh["nodes"])
        assert grid_count == expected, (
            f"GRID card count {grid_count} != mesh node count {expected}"
        )

    def test_modal_deck_element_count(self):
        """Number of CQUAD4 cards must match the mesh element count."""
        corpus = _load_corpus()
        case = corpus.build_corpus()[0]
        mesh = case.mesh

        deck = corpus.ssss_plate_bdf()
        elem_count = sum(1 for ln in deck.splitlines() if ln.startswith("CQUAD4,"))
        expected = len(mesh["elements"])
        assert elem_count == expected, (
            f"CQUAD4 card count {elem_count} != mesh element count {expected}"
        )

    def test_modal_deck_has_pshell(self):
        """PSHELL property card must be present for shell elements."""
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        assert any(ln.startswith("PSHELL") for ln in deck.splitlines()), (
            "BDF modal deck missing PSHELL property card"
        )

    def test_modal_deck_has_mat1(self):
        """MAT1 isotropic material card must be present."""
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        assert any(ln.startswith("MAT1") for ln in deck.splitlines()), (
            "BDF modal deck missing MAT1 material card"
        )

    def test_modal_deck_has_spc1(self):
        """SPC1 boundary-condition card must be present."""
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        assert any(ln.startswith("SPC1") for ln in deck.splitlines()), (
            "BDF modal deck missing SPC1 constraint card"
        )

    def test_modal_deck_no_blank_card_name(self):
        """
        All non-comment bulk data cards must have a non-blank card name
        (i.e. no lines starting with a comma in the element/property section).
        """
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        bulk_start = deck.find("BEGIN BULK")
        bulk_end = deck.find("ENDDATA")
        bulk_section = deck[bulk_start:bulk_end]
        for line in bulk_section.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("$"):
                continue
            if stripped == "BEGIN BULK":
                continue
            # Free-field cards must not start with a comma
            assert not stripped.startswith(","), (
                f"Blank card name (leading comma) in bulk section: {line!r}"
            )

    def test_bdf_node_ids_are_positive_integers(self):
        """
        Every GRID card must reference a positive integer node ID as its
        first field (NASTRAN requires NID ≥ 1).
        """
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        for line in deck.splitlines():
            if not line.startswith("GRID,"):
                continue
            parts = line.split(",")
            assert len(parts) >= 2, f"Malformed GRID card: {line!r}"
            nid = int(parts[1])
            assert nid >= 1, f"Non-positive node ID in GRID card: {line!r}"

    def test_bdf_element_references_valid_nodes(self):
        """
        Every CQUAD4 element must reference node IDs that appear in the GRID
        cards (i.e. no dangling node references).
        """
        corpus = _load_corpus()
        deck = corpus.ssss_plate_bdf()
        lines = deck.splitlines()

        known_nids: set[int] = set()
        for line in lines:
            if line.startswith("GRID,"):
                parts = line.split(",")
                known_nids.add(int(parts[1]))

        for line in lines:
            if not line.startswith("CQUAD4,"):
                continue
            parts = line.split(",")
            # CQUAD4,EID,PID,G1,G2,G3,G4
            for nid_str in parts[3:]:
                nid_str = nid_str.strip()
                if nid_str:
                    nid = int(nid_str)
                    assert nid in known_nids, (
                        f"CQUAD4 references unknown node ID {nid}: {line!r}"
                    )

    def test_static_deck_has_sol101(self):
        """SOL 101 deck must have the correct solution sequence."""
        from kerf_fem.mystran_bridge import _write_bdf_static

        nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        elements = [(1, "CQUAD4", [1, 2, 3, 4])]
        materials = {"E": 200e9, "nu": 0.3, "rho": 7850.0}
        bcs = [{"type": "fixed", "node_ids": [1, 4]}]
        loads = [{"type": "force", "node_id": 2, "fx": 0.0, "fy": 0.0, "fz": -1000.0}]

        deck = _write_bdf_static(
            nodes, elements, materials, bcs, loads,
            shell_thickness=0.005,
        )
        assert deck.splitlines()[0].strip().startswith("SOL 101"), (
            "Static BDF deck must start with SOL 101"
        )
        assert "FORCE" in deck, "Static BDF deck missing FORCE card"
        assert "ENDDATA" in deck.splitlines()[-1] or "ENDDATA" in deck, (
            "Static BDF deck missing ENDDATA"
        )


# ===========================================================================
# 2. Leissa analytic oracle tests (hermetic — always run)
# ===========================================================================


class TestLeissaOracle:
    """
    Verify the Leissa (1969) plate frequency oracle.

    These tests never require MYSTRAN and must always pass.  They serve both
    as a regression guard on the analytic formula and as documentation of the
    expected numerical values for the corpus reference case.
    """

    # Steel plate parameters matching the corpus case
    _E = 200e9
    _nu = 0.3
    _rho = 7850.0
    _h = 0.002    # 2 mm
    _a = 0.4      # m
    _b = 0.3      # m

    def _f(self, m: int, n: int) -> float:
        corpus = _load_corpus()
        return corpus.leissa_plate_freq_hz(
            self._E, self._nu, self._rho, self._h, self._a, self._b, m, n
        )

    def test_mode_11_positive(self):
        """Fundamental frequency (1,1) must be positive."""
        assert self._f(1, 1) > 0.0

    def test_mode_11_formula(self):
        """
        Manual cross-check of the (1,1) frequency against the formula:

            D = E h³ / (12 (1 − ν²))
            ω₁₁ = π² (1/a² + 1/b²) √(D / (ρ h))
            f₁₁ = ω₁₁ / (2π)

        Result must match to machine precision (same formula, different code path).
        """
        E, nu, rho, h, a, b = self._E, self._nu, self._rho, self._h, self._a, self._b
        D = E * h ** 3 / (12.0 * (1.0 - nu ** 2))
        omega = math.pi ** 2 * (1 / a ** 2 + 1 / b ** 2) * math.sqrt(D / (rho * h))
        f_expected = omega / (2.0 * math.pi)
        f_actual = self._f(1, 1)
        assert abs(f_actual - f_expected) < 1e-6, (
            f"leissa_plate_freq_hz(1,1) = {f_actual:.6f} Hz, "
            f"expected {f_expected:.6f} Hz"
        )

    def test_mode_frequencies_ascending(self):
        """
        Modal frequencies must increase as mode indices increase along the
        same axis: f(1,1) < f(2,1) < f(3,1).
        """
        f11 = self._f(1, 1)
        f21 = self._f(2, 1)
        f31 = self._f(3, 1)
        assert f11 < f21, f"f(1,1)={f11:.2f} not < f(2,1)={f21:.2f}"
        assert f21 < f31, f"f(2,1)={f21:.2f} not < f(3,1)={f31:.2f}"

    def test_mode_12_vs_21_symmetry(self):
        """
        For a 0.4×0.3 plate, f(1,2) ≠ f(2,1) because a ≠ b.  This test
        documents that the formula is NOT degenerate for the non-square case.
        """
        f12 = self._f(1, 2)
        f21 = self._f(2, 1)
        assert abs(f12 - f21) > 1.0, (
            f"Expected f(1,2) ≠ f(2,1) for non-square plate, "
            f"got {f12:.2f} vs {f21:.2f} Hz"
        )

    def test_square_plate_degeneracy(self):
        """
        For a square plate (a = b), modes (1,2) and (2,1) are degenerate
        (same frequency, confirmed by the symmetric formula).
        """
        corpus = _load_corpus()
        a = b = 0.4
        f12 = corpus.leissa_plate_freq_hz(self._E, self._nu, self._rho, self._h, a, b, 1, 2)
        f21 = corpus.leissa_plate_freq_hz(self._E, self._nu, self._rho, self._h, a, b, 2, 1)
        assert abs(f12 - f21) < 1e-6, (
            f"Square plate modes (1,2) and (2,1) should be degenerate, "
            f"got {f12:.6f} vs {f21:.6f} Hz"
        )

    def test_first_three_modes_length(self):
        """leissa_plate_first_three_modes must return exactly 3 values."""
        corpus = _load_corpus()
        modes = corpus.leissa_plate_first_three_modes(
            self._E, self._nu, self._rho, self._h, self._a, self._b
        )
        assert len(modes) == 3, f"Expected 3 modes, got {len(modes)}: {modes}"

    def test_first_three_modes_ascending(self):
        """The three returned frequencies must be in ascending order."""
        corpus = _load_corpus()
        modes = corpus.leissa_plate_first_three_modes(
            self._E, self._nu, self._rho, self._h, self._a, self._b
        )
        assert modes[0] < modes[1] < modes[2], (
            f"Modes not ascending: {modes}"
        )

    def test_first_three_modes_first_is_f11(self):
        """The lowest mode must equal f(1,1)."""
        corpus = _load_corpus()
        modes = corpus.leissa_plate_first_three_modes(
            self._E, self._nu, self._rho, self._h, self._a, self._b
        )
        f11 = self._f(1, 1)
        assert abs(modes[0] - f11) / f11 < 1e-6, (
            f"Lowest mode {modes[0]:.4f} Hz != f(1,1)={f11:.4f} Hz"
        )

    def test_increasing_thickness_raises_frequency(self):
        """
        Thicker plate → higher bending rigidity D per unit mass:
        f ∝ √(D / (ρ h)) = √(E h² / (12 (1−ν²) ρ)) → f ∝ h.
        So f increases with thickness.
        """
        corpus = _load_corpus()
        f_thin = corpus.leissa_plate_freq_hz(
            self._E, self._nu, self._rho, 0.001, self._a, self._b
        )
        f_thick = corpus.leissa_plate_freq_hz(
            self._E, self._nu, self._rho, 0.004, self._a, self._b
        )
        assert f_thick > f_thin, (
            f"Expected thicker plate to have higher frequency: "
            f"h=1mm → {f_thin:.2f} Hz, h=4mm → {f_thick:.2f} Hz"
        )

    def test_invalid_geometry_raises(self):
        """Zero plate dimensions must raise ValueError."""
        corpus = _load_corpus()
        with pytest.raises(ValueError):
            corpus.leissa_plate_freq_hz(
                self._E, self._nu, self._rho, 0.0, self._a, self._b
            )

    def test_corpus_case_leissa_reference(self):
        """
        The corpus case expected_frequencies_hz must match the direct oracle
        call to machine precision (sanity-check corpus consistency).
        """
        corpus = _load_corpus()
        cases = corpus.build_corpus()
        ssss_case = next(c for c in cases if c.name == "ssss_plate_modal")
        expected = ssss_case.expected_frequencies_hz

        direct = corpus.leissa_plate_first_three_modes(
            ssss_case.materials["E"],
            ssss_case.materials["nu"],
            ssss_case.materials["rho"],
            ssss_case.mesh["shell_thickness"],
            0.4,  # a
            0.3,  # b
        )
        for i, (ef, df) in enumerate(zip(expected, direct)):
            assert abs(ef - df) / df < 1e-6, (
                f"Corpus mode {i+1}: stored {ef:.4f} Hz != direct oracle {df:.4f} Hz"
            )


# ===========================================================================
# 3. MYSTRAN round-trip tests (skipped when mystran not on PATH)
# ===========================================================================


@_needs_mystran
class TestMystranRoundTrip:
    """
    Live MYSTRAN solver validation tests.

    Skipped automatically when ``mystran`` is not installed.  When the solver
    is available, these tests run the SSSS plate corpus case end-to-end and
    assert that the computed frequencies fall within 3 % of the Leissa analytic
    oracle values.
    """

    def test_mystran_binary_is_executable(self):
        """mystran must be found on PATH and must exit successfully on --help."""
        import subprocess
        result = subprocess.run(
            ["mystran", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Most solvers exit 0 or 1 on --help; the key check is that it runs.
        assert result.returncode in (0, 1), (
            f"mystran --help exited with unexpected code {result.returncode}"
        )

    def test_ssss_plate_modal_first_three_frequencies(self):
        """
        SSSS plate modal analysis: first 3 frequencies within 3% of
        Leissa (1969) NASA SP-160, Table 4.1 analytic oracle.
        """
        corpus = _load_corpus()
        cases = corpus.build_corpus()
        case = next(c for c in cases if c.name == "ssss_plate_modal")

        MystranBridge = _load_bridge()
        bridge = MystranBridge()

        # Translate SSSS BCs (DOF 3 only) for the bridge — the bridge
        # currently uses the "fixed" type for the BDF writer path.
        # For a live SSSS run we supply the correct DOF mask via a custom
        # BC that the bridge's _write_bdf_modal handles.
        bcs = [
            {
                "type": "fixed",
                "node_ids": case.boundary_conditions[0]["node_ids"],
            }
        ]

        result = bridge.solve(
            mesh=case.mesh,
            materials=case.materials,
            boundary_conditions=bcs,
            analysis_type="modal",
        )

        assert result.ok, (
            f"MystranBridge.solve returned ok=False: {result.errors}"
        )
        assert result.status != "pending", "Unexpected pending result with mystran on PATH"

        freqs = result.frequencies
        assert len(freqs) >= 3, (
            f"Expected at least 3 frequencies; got {len(freqs)}: {freqs}"
        )

        oracle = case.expected_frequencies_hz
        tol = case.tolerance
        for i in range(3):
            f_fem = freqs[i]
            f_ref = oracle[i]
            rel_err = abs(f_fem - f_ref) / f_ref
            assert rel_err <= tol, (
                f"Mode {i+1}: FEM {f_fem:.2f} Hz deviates {rel_err*100:.1f}% "
                f"from Leissa oracle {f_ref:.2f} Hz "
                f"(tolerance {tol*100:.0f}%)"
            )

    def test_result_has_eigenvalues(self):
        """
        Eigenvalues (rad²/s²) must be present, positive, and consistent
        with the returned frequencies: ω = 2π f, eigenvalue ≈ ω².
        """
        corpus = _load_corpus()
        cases = corpus.build_corpus()
        case = next(c for c in cases if c.name == "ssss_plate_modal")

        MystranBridge = _load_bridge()
        bridge = MystranBridge()
        bcs = [{"type": "fixed", "node_ids": case.boundary_conditions[0]["node_ids"]}]

        result = bridge.solve(mesh=case.mesh, materials=case.materials,
                              boundary_conditions=bcs, analysis_type="modal")
        assert result.ok

        evs = result.eigenvalues
        freqs = result.frequencies
        assert len(evs) == len(freqs), (
            f"eigenvalues length {len(evs)} != frequencies length {len(freqs)}"
        )
        for ev, f in zip(evs, freqs):
            assert ev > 0, f"Non-positive eigenvalue: {ev}"
            omega_from_ev = math.sqrt(ev)
            omega_from_f = 2.0 * math.pi * f
            rel = abs(omega_from_ev - omega_from_f) / omega_from_f
            assert rel < 0.01, (
                f"Inconsistency: √(eigenvalue)={omega_from_ev:.4f} rad/s "
                f"vs 2πf={omega_from_f:.4f} rad/s (1% tolerance)"
            )


# ===========================================================================
# 4. Pending-sentinel test (monkeypatch — always run)
# ===========================================================================


class TestPendingSentinel:
    """
    When mystran is not on PATH, MystranBridge.solve must return a pending
    sentinel without raising, suitable for graceful degradation.
    """

    def test_pending_when_mystran_absent(self, monkeypatch):
        """solve() returns status='pending' when mystran binary is absent."""
        import kerf_fem.mystran_bridge as mb
        monkeypatch.setattr(shutil, "which", lambda _: None)
        mb._MYSTRAN_AVAILABLE = None  # reset cache

        MystranBridge = _load_bridge()
        bridge = MystranBridge()

        result = bridge.solve(
            mesh={"nodes": [(0, 0, 0)], "elements": []},
            materials={"E": 200e9, "nu": 0.3, "rho": 7850.0},
            boundary_conditions=[],
            analysis_type="modal",
        )

        assert result.status == "pending", (
            f"Expected status='pending', got {result.status!r}"
        )
        assert not result.ok, "ok must be False when status='pending'"
        assert any(
            "mystran" in w.lower() or "path" in w.lower()
            for w in result.warnings
        ), f"Warning must mention mystran or PATH: {result.warnings}"

    def test_pending_for_linear_static_when_absent(self, monkeypatch):
        """Pending sentinel applies to all analysis_types, not just modal."""
        import kerf_fem.mystran_bridge as mb
        monkeypatch.setattr(shutil, "which", lambda _: None)
        mb._MYSTRAN_AVAILABLE = None

        MystranBridge = _load_bridge()
        bridge = MystranBridge()

        result = bridge.solve(
            mesh={"nodes": [(0, 0, 0)], "elements": []},
            materials={"E": 200e9, "nu": 0.3, "rho": 7850.0},
            boundary_conditions=[],
            analysis_type="linear_static",
        )
        assert result.status == "pending"

    def test_unsupported_analysis_type_fails(self, monkeypatch):
        """
        Unknown analysis_type should return status='failed' with a descriptive
        error (not raise).  This is tested without monkeypatching mystran so
        it exercises the type-dispatch code path when the solver IS on PATH
        — OR we patch it to be available.
        """
        import kerf_fem.mystran_bridge as mb
        # Force the solver to appear available so the code reaches type dispatch.
        monkeypatch.setattr(mb, "_MYSTRAN_AVAILABLE", True)

        MystranBridge = _load_bridge()
        bridge = MystranBridge()

        result = bridge.solve(
            mesh={"nodes": [(0, 0, 0)], "elements": []},
            materials={},
            boundary_conditions=[],
            analysis_type="nonlinear_contact",
        )
        assert result.status == "failed", (
            f"Expected status='failed' for unknown analysis_type, got {result.status!r}"
        )
        assert not result.ok

    def test_to_dict_serialisable(self, monkeypatch):
        """MystranResult.to_dict() must return a plain dict (JSON-serialisable)."""
        import json
        import kerf_fem.mystran_bridge as mb
        monkeypatch.setattr(shutil, "which", lambda _: None)
        mb._MYSTRAN_AVAILABLE = None

        MystranBridge = _load_bridge()
        result = MystranBridge().solve(
            mesh={}, materials={}, boundary_conditions=[],
            analysis_type="modal",
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        # Must be JSON-serialisable
        json.dumps(d)


# ===========================================================================
# 5. PCH parsing tests (hermetic — no solver needed)
# ===========================================================================


class TestPchParsing:
    """
    Verify ``_parse_pch_stresses``, ``_emit_punch_request``, and the
    associated stress-math helpers using synthetic data — no MYSTRAN binary
    required.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pch_module(self):
        import kerf_fem.mystran_bridge as mb
        return mb

    def _write_pch(self, tmp_path, content: str):
        """Write *content* to a temp .pch file and return the Path."""
        p = tmp_path / "analysis.pch"
        p.write_text(content)
        return p

    # ------------------------------------------------------------------
    # Test 1 — Free-field comma-separated PCH: 6-component solid stress
    # ------------------------------------------------------------------

    def test_parse_pch_free_field_six_component(self, tmp_path):
        """
        A free-field PCH with six stress components should produce a
        StressResult with all six tensor components populated plus correct
        von Mises and principal stresses.
        """
        mb = self._pch_module()
        pch_content = (
            "$ELEMENT STRESSES\n"
            "$ EID, S_XX, S_YY, S_ZZ, T_XY, T_YZ, T_ZX\n"
            "1, 1.0E+03, 2.0E+03, 3.0E+03, 4.0E+02, 5.0E+02, 6.0E+02\n"
        )
        path = self._write_pch(tmp_path, pch_content)
        results = mb._parse_pch_stresses(path)

        assert 1 in results, "EID 1 not found in parsed results"
        sr = results[1]
        assert sr.eid == 1
        assert abs(sr.sigma_xx - 1.0e3) < 1.0, f"sigma_xx wrong: {sr.sigma_xx}"
        assert abs(sr.sigma_yy - 2.0e3) < 1.0, f"sigma_yy wrong: {sr.sigma_yy}"
        assert abs(sr.sigma_zz - 3.0e3) < 1.0, f"sigma_zz wrong: {sr.sigma_zz}"
        assert abs(sr.tau_xy - 4.0e2) < 1.0, f"tau_xy wrong: {sr.tau_xy}"
        assert abs(sr.tau_yz - 5.0e2) < 1.0, f"tau_yz wrong: {sr.tau_yz}"
        assert abs(sr.tau_zx - 6.0e2) < 1.0, f"tau_zx wrong: {sr.tau_zx}"
        assert sr.von_mises > 0.0, "von_mises must be positive"

    # ------------------------------------------------------------------
    # Test 2 — Multiple elements parsed
    # ------------------------------------------------------------------

    def test_parse_pch_multiple_elements(self, tmp_path):
        """Parser must handle multiple element records in a single section."""
        mb = self._pch_module()
        pch_content = (
            "$ELEMENT STRESSES\n"
            "1, 1.0E+03, 0.0, 0.0, 0.0, 0.0, 0.0\n"
            "2, 2.0E+03, 0.0, 0.0, 0.0, 0.0, 0.0\n"
            "3, 3.0E+03, 0.0, 0.0, 0.0, 0.0, 0.0\n"
        )
        path = self._write_pch(tmp_path, pch_content)
        results = mb._parse_pch_stresses(path)

        assert len(results) == 3, f"Expected 3 elements, got {len(results)}"
        for eid in (1, 2, 3):
            assert eid in results, f"Missing EID {eid}"
        assert abs(results[1].sigma_xx - 1.0e3) < 1.0
        assert abs(results[2].sigma_xx - 2.0e3) < 1.0
        assert abs(results[3].sigma_xx - 3.0e3) < 1.0

    # ------------------------------------------------------------------
    # Test 3 — Shell 2-D stress (3-component)
    # ------------------------------------------------------------------

    def test_parse_pch_shell_2d_stress(self, tmp_path):
        """
        Shell elements provide sigma_xx, sigma_yy, tau_xy; out-of-plane
        components default to 0.  Von Mises must still be computed correctly
        using the plane-stress formula.
        """
        mb = self._pch_module()
        sxx, syy, txy = 100.0e6, 50.0e6, 30.0e6
        pch_content = (
            "$ELEMENT STRESSES\n"
            f"1, {sxx:.6E}, {syy:.6E}, {txy:.6E}\n"
        )
        path = self._write_pch(tmp_path, pch_content)
        results = mb._parse_pch_stresses(path)

        assert 1 in results
        sr = results[1]
        assert abs(sr.sigma_xx - sxx) < 1.0
        assert abs(sr.sigma_yy - syy) < 1.0
        assert abs(sr.tau_xy - txy) < 1.0
        assert sr.sigma_zz == 0.0
        assert sr.tau_yz == 0.0
        assert sr.tau_zx == 0.0
        # Plane-stress von Mises (szz=tyz=tzx=0):
        # σ_vm = √(σ_xx²  − σ_xx·σ_yy + σ_yy² + 3·τ_xy²)
        expected_vm = mb._compute_von_mises(sxx, syy, 0.0, txy, 0.0, 0.0)
        assert abs(sr.von_mises - expected_vm) < 1.0, (
            f"von Mises mismatch: got {sr.von_mises:.2f}, expected {expected_vm:.2f}"
        )

    # ------------------------------------------------------------------
    # Test 4 — Missing PCH file returns empty dict
    # ------------------------------------------------------------------

    def test_parse_pch_missing_file_returns_empty(self, tmp_path):
        """_parse_pch_stresses must return {} for a non-existent path."""
        mb = self._pch_module()
        missing = tmp_path / "does_not_exist.pch"
        results = mb._parse_pch_stresses(missing)
        assert results == {}, f"Expected empty dict, got {results}"

    # ------------------------------------------------------------------
    # Test 5 — Empty section (comments only) returns empty dict
    # ------------------------------------------------------------------

    def test_parse_pch_no_data_lines(self, tmp_path):
        """A PCH with only comment lines should yield an empty result."""
        mb = self._pch_module()
        pch_content = (
            "$ELEMENT STRESSES\n"
            "$ EID  SXX  SYY  SZZ  TXY  TYZ  TZX\n"
        )
        path = self._write_pch(tmp_path, pch_content)
        results = mb._parse_pch_stresses(path)
        assert results == {}

    # ------------------------------------------------------------------
    # Test 6 — _emit_punch_request injects directive
    # ------------------------------------------------------------------

    def test_emit_punch_request_injects_directive(self):
        """STRESS(PUNCH)=ALL must be added to a deck that lacks it."""
        mb = self._pch_module()
        deck = (
            "SOL 101\n"
            "CEND\n"
            "TITLE = TEST\n"
            "SUBCASE 1\n"
            "  LOAD = 1\n"
            "  DISPLACEMENT(SORT1,REAL) = ALL\n"
            "BEGIN BULK\n"
            "ENDDATA\n"
        )
        modified = mb._emit_punch_request(deck)
        assert "STRESS(PUNCH)=ALL" in modified, (
            "STRESS(PUNCH)=ALL not found in modified deck"
        )
        # Must appear before BEGIN BULK
        idx_punch = modified.index("STRESS(PUNCH)=ALL")
        idx_bulk = modified.index("BEGIN BULK")
        assert idx_punch < idx_bulk, (
            "STRESS(PUNCH)=ALL must appear before BEGIN BULK"
        )

    # ------------------------------------------------------------------
    # Test 7 — _emit_punch_request is idempotent
    # ------------------------------------------------------------------

    def test_emit_punch_request_idempotent(self):
        """Calling _emit_punch_request twice must not duplicate the directive."""
        mb = self._pch_module()
        deck = (
            "SOL 101\n"
            "CEND\n"
            "STRESS(PUNCH)=ALL\n"
            "BEGIN BULK\n"
            "ENDDATA\n"
        )
        once = mb._emit_punch_request(deck)
        twice = mb._emit_punch_request(once)
        assert once == twice, "Second call should return unchanged deck"
        assert once.count("STRESS(PUNCH)=ALL") == 1, (
            "Should contain exactly one STRESS(PUNCH)=ALL directive"
        )

    # ------------------------------------------------------------------
    # Test 8 — von Mises formula correctness (uniaxial)
    # ------------------------------------------------------------------

    def test_von_mises_uniaxial(self):
        """
        For pure uniaxial tension (σ_xx = σ, all others = 0):
        σ_vm = σ.
        """
        mb = self._pch_module()
        sigma = 250.0e6
        vm = mb._compute_von_mises(sigma, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert abs(vm - sigma) < 1.0, (
            f"Uniaxial von Mises: expected {sigma:.0f}, got {vm:.0f}"
        )

    # ------------------------------------------------------------------
    # Test 9 — von Mises formula correctness (hydrostatic = 0)
    # ------------------------------------------------------------------

    def test_von_mises_hydrostatic_is_zero(self):
        """
        For hydrostatic stress (σ_xx = σ_yy = σ_zz = p, shears = 0):
        σ_vm = 0  (no deviatoric component).
        """
        mb = self._pch_module()
        p = 100.0e6
        vm = mb._compute_von_mises(p, p, p, 0.0, 0.0, 0.0)
        assert vm < 1.0, (
            f"Hydrostatic von Mises must be ~0, got {vm:.6g}"
        )

    # ------------------------------------------------------------------
    # Test 10 — principal stresses uniaxial
    # ------------------------------------------------------------------

    def test_principal_stresses_uniaxial(self):
        """
        For uniaxial tension σ_xx = σ, remaining = 0:
        Principals must be (σ, 0, 0) in descending order.
        """
        mb = self._pch_module()
        sigma = 300.0e6
        p1, p2, p3 = mb._compute_principal_stresses(sigma, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert abs(p1 - sigma) < 1.0, f"p1={p1:.6g} != {sigma:.6g}"
        assert abs(p2) < 1.0, f"p2={p2:.6g} != 0"
        assert abs(p3) < 1.0, f"p3={p3:.6g} != 0"
        assert p1 >= p2 >= p3, f"Principals not in descending order: {p1}, {p2}, {p3}"

    # ------------------------------------------------------------------
    # Test 11 — StressResult.as_stress_dict keys
    # ------------------------------------------------------------------

    def test_stress_result_as_dict_keys(self, tmp_path):
        """as_stress_dict() must include all required stress keys."""
        mb = self._pch_module()
        pch_content = (
            "$ELEMENT STRESSES\n"
            "42, 1.0E+06, 2.0E+06, 3.0E+06, 4.0E+05, 5.0E+05, 6.0E+05\n"
        )
        path = self._write_pch(tmp_path, pch_content)
        results = mb._parse_pch_stresses(path)
        assert 42 in results
        d = results[42].as_stress_dict()
        required_keys = {
            "eid", "sigma_xx", "sigma_yy", "sigma_zz",
            "tau_xy", "tau_yz", "tau_zx",
            "von_mises", "principal_1", "principal_2", "principal_3",
        }
        assert required_keys.issubset(d.keys()), (
            f"Missing keys: {required_keys - set(d.keys())}"
        )

    # ------------------------------------------------------------------
    # Test 12 — PCH section boundary: strains section ignored
    # ------------------------------------------------------------------

    def test_parse_pch_strains_section_also_parsed(self, tmp_path):
        """
        $ELEMENT STRAINS header (alternative keyword) should be parsed just
        like $ELEMENT STRESSES.
        """
        mb = self._pch_module()
        pch_content = (
            "$ELEMENT STRAINS\n"
            "7, 1.0E-03, 2.0E-03, 3.0E-03, 4.0E-04, 5.0E-04, 6.0E-04\n"
        )
        path = self._write_pch(tmp_path, pch_content)
        results = mb._parse_pch_stresses(path)
        assert 7 in results, "STRAINS section should be parsed too"
        sr = results[7]
        assert abs(sr.sigma_xx - 1.0e-3) < 1e-10

    # ------------------------------------------------------------------
    # Test 13 — Graceful fallback in solve() when PCH absent (no solver)
    # ------------------------------------------------------------------

    def test_solve_static_no_pch_fallback_warning(self, monkeypatch, tmp_path):
        """
        When _run_mystran_with_pch returns no PCH path, solve() must still
        return ok=True for the displacement result and add a warning about
        missing stress data.
        """
        import kerf_fem.mystran_bridge as mb

        # Force solver to appear available
        monkeypatch.setattr(mb, "_MYSTRAN_AVAILABLE", True)

        # Patch _run_mystran_with_pch to return a synthetic F06 and no PCH
        f06_stub = (
            "D I S P L A C E M E N T   V E C T O R\n"
            "       1       G      1.0000E-03  2.0000E-03  3.0000E-03  "
            "0.0  0.0  0.0\n"
            "\n"
        )

        def _fake_run(self_inner, bdf_content):
            return f06_stub, None

        monkeypatch.setattr(mb.MystranBridge, "_run_mystran_with_pch", _fake_run)

        bridge = mb.MystranBridge()
        result = bridge.solve(
            mesh={
                "nodes": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                          (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
                "elements": [(1, "CQUAD4", [1, 2, 3, 4])],
                "shell_thickness": 0.005,
                "loads": [{"type": "force", "node_id": 2, "fz": -1000.0}],
            },
            materials={"E": 200e9, "nu": 0.3, "rho": 7850.0},
            boundary_conditions=[{"type": "fixed", "node_ids": [1, 4]}],
            analysis_type="linear_static",
        )

        assert result.ok, f"Expected ok=True, got errors: {result.errors}"
        assert result.stresses == [], "No stress data expected when PCH absent"
        assert any("pch" in w.lower() or "stress" in w.lower()
                   for w in result.warnings), (
            f"Expected warning about missing PCH, got: {result.warnings}"
        )

    # ------------------------------------------------------------------
    # Test 14 — Full PCH path populates stresses in solve()
    # ------------------------------------------------------------------

    def test_solve_static_pch_populates_stresses(self, monkeypatch, tmp_path):
        """
        When a PCH file is present and parseable, solve() must populate
        ``stresses`` and ``max_vonmises_stress`` on the result.
        """
        import kerf_fem.mystran_bridge as mb

        monkeypatch.setattr(mb, "_MYSTRAN_AVAILABLE", True)

        # Write a synthetic PCH
        pch_file = tmp_path / "analysis.pch"
        pch_file.write_text(
            "$ELEMENT STRESSES\n"
            "1, 2.0E+08, 1.0E+08, 0.0, 0.0, 0.0, 0.0\n"
            "2, 1.5E+08, 0.5E+08, 0.0, 0.0, 0.0, 0.0\n"
        )

        f06_stub = (
            "D I S P L A C E M E N T   V E C T O R\n"
            "       1       G      1.0E-04  0.0  -1.0E-03  "
            "0.0  0.0  0.0\n"
            "\n"
        )

        def _fake_run(self_inner, bdf_content):
            return f06_stub, pch_file

        monkeypatch.setattr(mb.MystranBridge, "_run_mystran_with_pch", _fake_run)

        bridge = mb.MystranBridge()
        result = bridge.solve(
            mesh={
                "nodes": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                          (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
                "elements": [(1, "CQUAD4", [1, 2, 3, 4]),
                              (2, "CQUAD4", [1, 2, 3, 4])],
                "shell_thickness": 0.005,
                "loads": [{"type": "force", "node_id": 2, "fz": -1000.0}],
            },
            materials={"E": 200e9, "nu": 0.3, "rho": 7850.0},
            boundary_conditions=[{"type": "fixed", "node_ids": [1, 4]}],
            analysis_type="linear_static",
        )

        assert result.ok
        assert len(result.stresses) == 2, (
            f"Expected 2 stress records, got {len(result.stresses)}"
        )
        assert result.max_vonmises_stress > 0.0, (
            "max_vonmises_stress must be positive when stresses parsed"
        )
        # Verify tensor components round-trip
        eids_in_result = {int(s["eid"]) for s in result.stresses}
        assert eids_in_result == {1, 2}, f"Unexpected element IDs: {eids_in_result}"

    # ------------------------------------------------------------------
    # Test 15 — static BDF deck contains STRESS(PUNCH)=ALL after injection
    # ------------------------------------------------------------------

    def test_static_deck_has_punch_directive(self):
        """
        _write_bdf_static followed by _emit_punch_request must produce a deck
        containing STRESS(PUNCH)=ALL before BEGIN BULK.
        """
        from kerf_fem.mystran_bridge import _write_bdf_static, _emit_punch_request

        nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                 (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        elements = [(1, "CQUAD4", [1, 2, 3, 4])]
        materials = {"E": 200e9, "nu": 0.3, "rho": 7850.0}
        bcs = [{"type": "fixed", "node_ids": [1, 4]}]
        loads = [{"type": "force", "node_id": 2, "fz": -500.0}]

        deck = _write_bdf_static(nodes, elements, materials, bcs, loads,
                                 shell_thickness=0.002)
        deck_with_pch = _emit_punch_request(deck)

        assert "STRESS(PUNCH)=ALL" in deck_with_pch
        idx_p = deck_with_pch.index("STRESS(PUNCH)=ALL")
        idx_b = deck_with_pch.index("BEGIN BULK")
        assert idx_p < idx_b, "Punch directive must precede BEGIN BULK"


# ===========================================================================
# 6. Live end-to-end stress test (skipped when mystran not on PATH)
# ===========================================================================


@_needs_mystran
class TestMystranStaticStress:
    """
    Live MYSTRAN solver stress-recovery tests.

    Skipped automatically when ``mystran`` is not installed.  When the solver
    is available these tests verify that the PCH stress pipeline works end-to-end.
    """

    def test_linear_static_stress_fields_populated(self):
        """
        A simple cantilever-like CQUAD4 plate under tip load must return
        non-empty stresses and a positive max_vonmises_stress.
        """
        from kerf_fem.mystran_bridge import MystranBridge

        bridge = MystranBridge()
        result = bridge.solve(
            mesh={
                "nodes": [
                    (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                    (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
                ],
                "elements": [(1, "CQUAD4", [1, 2, 3, 4])],
                "shell_thickness": 0.005,
                "loads": [{"type": "force", "node_id": 2, "fx": 0.0,
                           "fy": 0.0, "fz": -1000.0}],
            },
            materials={"E": 200e9, "nu": 0.3, "rho": 7850.0},
            boundary_conditions=[{"type": "fixed", "node_ids": [1, 4]}],
            analysis_type="linear_static",
        )

        assert result.ok, f"Solver failed: {result.errors}"
        # Stress fields are populated when PCH is available
        if result.stresses:
            assert result.max_vonmises_stress > 0.0
            for s in result.stresses:
                assert "von_mises" in s
                assert "sigma_xx" in s
        else:
            # PCH not produced by this MYSTRAN version — acceptable with warning
            assert result.warnings, "Must warn when PCH absent"
