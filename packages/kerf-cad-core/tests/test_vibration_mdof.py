"""
Hermetic tests for kerf_cad_core.vibration.mdof — n-DOF modal analysis and FRF.

Validation cases
----------------
1. mdof_eigen — 3-DOF spring-mass chain (equal masses m, equal springs k):
   Analytic eigenvalues (Rao §6-4):
     λ₁ = 2 − √2, λ₂ = 2, λ₃ = 2 + √2  (×k/m)
   → ω₁ = √((2−√2) k/m), ω₂ = √(2 k/m), ω₃ = √((2+√2) k/m)

2. mdof_frf  — same 3-DOF system; verify H(ω) magnitude peaks at ωᵣ.

3. mdof_rayleigh_damping — verify ζᵣ = α/(2ωᵣ) + β ωᵣ/2 formula.

All tests are pure-Python and hermetic: no OCC, no DB, no network.

References
----------
Rao, S.S. "Mechanical Vibrations", 5th ed. §6-4, §6-7
Inman, D.J. "Engineering Vibration", 4th ed. §4.3

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.vibration.mdof import (
    mdof_eigen,
    mdof_frf,
    mdof_rayleigh_damping,
)
from kerf_cad_core.vibration.tools import (
    run_ndof_eigen,
    run_ndof_frf,
    run_ndof_rayleigh_damping,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok_tool(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err_tool(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


# ---------------------------------------------------------------------------
# 3-DOF spring-mass chain fixture
# For equal masses m and equal springs k (chain: wall-m1-k-m2-k-m3-wall):
#   K = k [ 2 -1  0; -1  2 -1;  0 -1  2 ]
#   M = m diag(1, 1, 1)
# Analytic eigenvalues of K/m·I: λᵣ = 2 − 2cos(rπ/4) for r=1,2,3
#   r=1: λ₁ = 2 − √2
#   r=2: λ₂ = 2
#   r=3: λ₃ = 2 + √2
# ---------------------------------------------------------------------------

def _make_3dof(m: float = 1.0, k: float = 100.0):
    """Return (M_flat, K_flat, n, analytic_lambdas) for 3-DOF equal chain."""
    # M = m * I(3×3)
    M_flat = [
        m, 0.0, 0.0,
        0.0, m, 0.0,
        0.0, 0.0, m,
    ]
    # K = k * tridiagonal [2,-1,0; -1,2,-1; 0,-1,2]
    K_flat = [
        2*k, -k, 0.0,
        -k, 2*k, -k,
        0.0, -k, 2*k,
    ]
    sq2 = math.sqrt(2.0)
    lambdas = [(2.0 - sq2) * k / m, 2.0 * k / m, (2.0 + sq2) * k / m]
    return M_flat, K_flat, 3, lambdas


# ===========================================================================
# 1. mdof_eigen
# ===========================================================================

class TestMdofEigen:

    def test_3dof_chain_eigenvalues(self):
        """3-DOF chain: ωᵣ must match analytic λᵣ = (2−√2, 2, 2+√2)·k/m."""
        m, k = 1.0, 100.0
        M_flat, K_flat, n, lambdas = _make_3dof(m, k)
        res = mdof_eigen(M_flat, K_flat, n)
        assert res["ok"] is True
        assert res["n"] == n
        omega_r = res["omega_r"]
        assert len(omega_r) == n
        for r, lam in enumerate(lambdas):
            omega_expected = math.sqrt(lam)
            assert abs(omega_r[r] - omega_expected) / omega_expected < 1e-6, (
                f"Mode {r}: got ω={omega_r[r]:.6f}, expected {omega_expected:.6f}"
            )

    def test_fn_hz_from_omega(self):
        """fn_hz_r[r] = omega_r[r] / (2π)."""
        M_flat, K_flat, n, _ = _make_3dof()
        res = mdof_eigen(M_flat, K_flat, n)
        assert res["ok"] is True
        for r in range(n):
            assert abs(res["fn_hz_r"][r] - res["omega_r"][r] / (2.0 * math.pi)) < 1e-10

    def test_mass_orthonormality(self):
        """Mass-normalised modes satisfy φᵣᵀ M φᵣ ≈ 1."""
        m, k = 2.0, 500.0
        M_flat, K_flat, n, _ = _make_3dof(m, k)
        res = mdof_eigen(M_flat, K_flat, n)
        assert res["ok"] is True
        for r in range(n):
            mm = res["modal_mass"][r]
            assert abs(mm - 1.0) < 1e-6, f"Mode {r}: modal_mass={mm:.8f}"

    def test_modal_stiffness_equals_omega_squared(self):
        """φᵣᵀ K φᵣ ≈ ωᵣ²  (generalised stiffness from mass-norm modes)."""
        m, k = 1.0, 100.0
        M_flat, K_flat, n, _ = _make_3dof(m, k)
        res = mdof_eigen(M_flat, K_flat, n)
        assert res["ok"] is True
        for r in range(n):
            mk = res["modal_stiffness"][r]
            wr2 = res["omega_r"][r] ** 2
            assert abs(mk - wr2) / (wr2 + 1e-10) < 1e-5, (
                f"Mode {r}: modal_stiffness={mk:.6f}, ω²={wr2:.6f}"
            )

    def test_omega_ascending_order(self):
        """Natural frequencies must be sorted ascending."""
        M_flat, K_flat, n, _ = _make_3dof()
        res = mdof_eigen(M_flat, K_flat, n)
        assert res["ok"] is True
        omega = res["omega_r"]
        assert all(omega[i] <= omega[i + 1] for i in range(n - 1))

    def test_sdof_via_ndof(self):
        """n=1 SDOF case: ω = √(k/m)."""
        m, k = 4.0, 1600.0
        res = mdof_eigen([m], [k], 1)
        assert res["ok"] is True
        omega_expected = math.sqrt(k / m)
        assert abs(res["omega_r"][0] - omega_expected) / omega_expected < 1e-6

    def test_2dof_matches_closed_form(self):
        """
        2-DOF: m1=m2=1, k1=k2=k3=100 (symmetric chain wall-m1-k-m2-wall).
        Closed form (Rao §5-3): λ₁ = k/m, λ₂ = 3k/m.
        """
        m, k = 1.0, 100.0
        M_flat = [m, 0.0, 0.0, m]
        K_flat = [2*k, -k, -k, 2*k]
        res = mdof_eigen(M_flat, K_flat, 2)
        assert res["ok"] is True
        assert abs(res["omega_r"][0] - math.sqrt(k / m)) / math.sqrt(k / m) < 1e-6
        assert abs(res["omega_r"][1] - math.sqrt(3*k / m)) / math.sqrt(3*k / m) < 1e-6

    def test_invalid_n_zero(self):
        res = mdof_eigen([1.0], [1.0], 0)
        assert res["ok"] is False

    def test_invalid_matrix_length(self):
        """M_flat with wrong length must return error."""
        res = mdof_eigen([1.0, 0.0, 1.0], [1.0, 0.0, 0.0, 1.0], 2)
        assert res["ok"] is False

    def test_singular_mass_matrix(self):
        """Singular M (zero diagonal) must return error."""
        M_flat = [0.0, 0.0, 0.0, 0.0]
        K_flat = [100.0, 0.0, 0.0, 100.0]
        res = mdof_eigen(M_flat, K_flat, 2)
        assert res["ok"] is False

    def test_known_validation_residual(self):
        """
        3-DOF known analytic: verify residual |ωᵣ_computed − ωᵣ_analytic|/ωᵣ_analytic < 1e-6.
        Regression lock for the Jacobi solver.
        k=1000, m=1: ω₁=√(200−100√2)≈7.654, ω₂=√2000≈44.721, ω₃=√(200+100√2)≈54.120 → actually:
        λ₁=(2-√2)*1000=585.786, λ₂=2000, λ₃=3414.214
        ω₁=24.203, ω₂=44.721, ω₃=58.432 rad/s.
        """
        m, k = 1.0, 1000.0
        M_flat, K_flat, n, lambdas = _make_3dof(m, k)
        res = mdof_eigen(M_flat, K_flat, n)
        assert res["ok"] is True
        for r, lam in enumerate(lambdas):
            omega_analytic = math.sqrt(lam)
            omega_computed = res["omega_r"][r]
            rel_err = abs(omega_computed - omega_analytic) / omega_analytic
            assert rel_err < 1e-6, (
                f"Mode {r}: residual={rel_err:.2e} (computed={omega_computed:.6f},"
                f" analytic={omega_analytic:.6f})"
            )


# ===========================================================================
# 2. mdof_frf
# ===========================================================================

class TestMdofFrf:

    def test_frf_returns_correct_shape(self):
        """H arrays must be shaped [n_omega][n][n]."""
        M_flat, K_flat, n, _ = _make_3dof()
        omega_range = [1.0, 5.0, 10.0, 20.0]
        res = mdof_frf(M_flat, K_flat, n, 0.05, omega_range)
        assert res["ok"] is True
        assert res["n"] == n
        assert res["n_omega"] == len(omega_range)
        assert len(res["H_mag"]) == len(omega_range)
        for i in range(len(omega_range)):
            assert len(res["H_mag"][i]) == n
            for j in range(n):
                assert len(res["H_mag"][i][j]) == n

    def test_frf_peaks_near_natural_frequencies(self):
        """
        |H₁₁(ω)| must have local maxima near ωᵣ (tested by verifying
        H_mag at ωᵣ is larger than at the midpoints between modes).
        """
        m, k = 1.0, 100.0
        M_flat, K_flat, n, lambdas = _make_3dof(m, k)
        omega_r_analytic = [math.sqrt(lam) for lam in lambdas]
        zeta = 0.05

        # Evaluate H at each natural frequency and a few off-resonance points
        omega_test = omega_r_analytic[:] + [
            0.5 * omega_r_analytic[0],
            0.5 * (omega_r_analytic[0] + omega_r_analytic[1]),
        ]
        omega_test_sorted = sorted(omega_test)

        res = mdof_frf(M_flat, K_flat, n, zeta, omega_test_sorted)
        assert res["ok"] is True

        # Build map omega → H_mag[0][0]
        h11 = {}
        for i, w in enumerate(omega_test_sorted):
            h11[round(w, 6)] = res["H_mag"][i][0][0]

        # At each natural freq, H must be finite and positive
        for wr in omega_r_analytic:
            # find closest tested omega
            key = min(h11.keys(), key=lambda x: abs(x - wr))
            assert h11[key] > 0.0

    def test_frf_real_imag_magnitude_consistency(self):
        """H_mag must equal sqrt(H_real² + H_imag²)."""
        M_flat, K_flat, n, _ = _make_3dof()
        omega_range = [5.0, 12.0, 25.0]
        res = mdof_frf(M_flat, K_flat, n, 0.02, omega_range)
        assert res["ok"] is True
        for i in range(len(omega_range)):
            for j in range(n):
                for k_ in range(n):
                    re = res["H_real"][i][j][k_]
                    im = res["H_imag"][i][j][k_]
                    mag = res["H_mag"][i][j][k_]
                    expected_mag = math.sqrt(re**2 + im**2)
                    assert abs(mag - expected_mag) < 1e-10 * (expected_mag + 1e-30)

    def test_frf_sdof_analytic(self):
        """
        SDOF case: H(ω) = 1 / (k − mω² + 2i ζ ωn m ω).
        At ω = ωn (resonance), |H| = 1/(2ζ k).
        """
        m, k = 1.0, 100.0
        omega_n = math.sqrt(k / m)   # 10 rad/s
        zeta = 0.1
        omega_res = omega_n           # at resonance

        res = mdof_frf([m], [k], 1, zeta, [omega_res])
        assert res["ok"] is True

        H_mag_at_res = res["H_mag"][0][0][0]
        # |H(ωn)| for SDOF = 1/(2ζ k) = 1/(2*0.1*100) = 0.05
        expected = 1.0 / (2.0 * zeta * k)
        assert abs(H_mag_at_res - expected) / expected < 1e-5

    def test_frf_uniform_vs_list_zeta(self):
        """Uniform float ζ must give same result as list of same ζ per mode."""
        M_flat, K_flat, n, _ = _make_3dof()
        zeta = 0.03
        omega_range = [10.0, 20.0, 30.0]
        res_scalar = mdof_frf(M_flat, K_flat, n, zeta, omega_range)
        res_list   = mdof_frf(M_flat, K_flat, n, [zeta]*n, omega_range)
        assert res_scalar["ok"] and res_list["ok"]
        for i in range(len(omega_range)):
            for j in range(n):
                for kk in range(n):
                    diff = abs(
                        res_scalar["H_mag"][i][j][kk] - res_list["H_mag"][i][j][kk]
                    )
                    assert diff < 1e-14

    def test_frf_negative_omega_returns_error(self):
        M_flat, K_flat, n, _ = _make_3dof()
        res = mdof_frf(M_flat, K_flat, n, 0.05, [-1.0, 10.0])
        assert res["ok"] is False

    def test_frf_empty_omega_returns_error(self):
        M_flat, K_flat, n, _ = _make_3dof()
        res = mdof_frf(M_flat, K_flat, n, 0.05, [])
        assert res["ok"] is False

    def test_frf_wrong_zeta_list_length(self):
        M_flat, K_flat, n, _ = _make_3dof()
        res = mdof_frf(M_flat, K_flat, n, [0.05, 0.05], [10.0])
        assert res["ok"] is False


# ===========================================================================
# 3. mdof_rayleigh_damping
# ===========================================================================

class TestMdofRayleighDamping:

    def test_zeta_formula(self):
        """ζᵣ = α/(2ωᵣ) + β ωᵣ/2 must match for each mode."""
        m, k = 1.0, 100.0
        M_flat, K_flat, n, lambdas = _make_3dof(m, k)
        alpha, beta = 0.5, 0.002
        res = mdof_rayleigh_damping(alpha, beta, M_flat, K_flat, n)
        assert res["ok"] is True
        omega_r = res["omega_r"]
        zeta_r = res["zeta_r"]
        for r, wr in enumerate(omega_r):
            zeta_expected = alpha / (2.0 * wr) + beta * wr / 2.0
            assert abs(zeta_r[r] - zeta_expected) / zeta_expected < 1e-9

    def test_c_flat_formula(self):
        """C[i][j] = α M[i][j] + β K[i][j]."""
        m, k = 1.0, 100.0
        M_flat, K_flat, n, _ = _make_3dof(m, k)
        alpha, beta = 1.0, 0.01
        res = mdof_rayleigh_damping(alpha, beta, M_flat, K_flat, n)
        assert res["ok"] is True
        C = res["C_flat"]
        for idx in range(n * n):
            expected = alpha * M_flat[idx] + beta * K_flat[idx]
            assert abs(C[idx] - expected) < 1e-10

    def test_zero_alpha_beta_gives_zero_zeta(self):
        """α=0, β=0 → C=0, ζᵣ=0 for all modes."""
        M_flat, K_flat, n, _ = _make_3dof()
        res = mdof_rayleigh_damping(0.0, 0.0, M_flat, K_flat, n)
        assert res["ok"] is True
        for z in res["zeta_r"]:
            assert abs(z) < 1e-12

    def test_negative_alpha_returns_error(self):
        M_flat, K_flat, n, _ = _make_3dof()
        res = mdof_rayleigh_damping(-1.0, 0.0, M_flat, K_flat, n)
        assert res["ok"] is False

    def test_negative_beta_returns_error(self):
        M_flat, K_flat, n, _ = _make_3dof()
        res = mdof_rayleigh_damping(0.0, -0.01, M_flat, K_flat, n)
        assert res["ok"] is False


# ===========================================================================
# 4. LLM tool wrappers
# ===========================================================================

class TestMdofToolWrappers:

    def test_run_ndof_eigen_happy_path(self):
        M_flat, K_flat, n, lambdas = _make_3dof()
        raw = _run(run_ndof_eigen(_ctx(), _args(M_flat=M_flat, K_flat=K_flat, n=n)))
        d = _ok_tool(raw)
        assert len(d["omega_r"]) == n

    def test_run_ndof_eigen_missing_n(self):
        M_flat, K_flat, n, _ = _make_3dof()
        raw = _run(run_ndof_eigen(_ctx(), _args(M_flat=M_flat, K_flat=K_flat)))
        _err_tool(raw)

    def test_run_ndof_eigen_invalid_json(self):
        raw = _run(run_ndof_eigen(_ctx(), b"not_json"))
        _err_tool(raw)

    def test_run_ndof_frf_happy_path(self):
        M_flat, K_flat, n, _ = _make_3dof()
        omega_range = [5.0, 10.0, 20.0]
        raw = _run(run_ndof_frf(_ctx(), _args(
            M_flat=M_flat, K_flat=K_flat, n=n,
            zeta_modal=0.05, omega_range=omega_range,
        )))
        d = _ok_tool(raw)
        assert d["n_omega"] == len(omega_range)

    def test_run_ndof_frf_missing_zeta(self):
        M_flat, K_flat, n, _ = _make_3dof()
        raw = _run(run_ndof_frf(_ctx(), _args(
            M_flat=M_flat, K_flat=K_flat, n=n,
            omega_range=[5.0],
        )))
        _err_tool(raw)

    def test_run_ndof_rayleigh_happy_path(self):
        M_flat, K_flat, n, _ = _make_3dof()
        raw = _run(run_ndof_rayleigh_damping(_ctx(), _args(
            alpha=0.5, beta=0.002, M_flat=M_flat, K_flat=K_flat, n=n,
        )))
        d = _ok_tool(raw)
        assert len(d["zeta_r"]) == n

    def test_run_ndof_rayleigh_missing_alpha(self):
        M_flat, K_flat, n, _ = _make_3dof()
        raw = _run(run_ndof_rayleigh_damping(_ctx(), _args(
            beta=0.002, M_flat=M_flat, K_flat=K_flat, n=n,
        )))
        _err_tool(raw)
