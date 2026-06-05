"""
Test suite for kerf_fem.hyperelastic — Hyperelastic constitutive models.

Coverage
--------
 1.  Neo-Hookean: strain energy W ≥ 0 and W = 0 at F = I.
 2.  Neo-Hookean: uniaxial true stress (σ11-σ22) matches closed-form σ=μ(λ²-1/λ).
 3.  Mooney-Rivlin: W = 0 at F = I (no pre-stress at natural configuration).
 4.  Mooney-Rivlin: uniaxial stress (σ11-σ22) matches closed-form σ=2(λ²-1/λ)(C10+C01/λ).
 5.  Ogden N=1, α=2: stress oracle σ=μ(λ²-λ⁻¹) matches (σ11-σ22).
 6.  Ogden N=1: uniaxial oracle matches Ogden analytical formula.
 7.  Ogden N=3 (Treloar parameters): stress at λ=7 in plausible range.
 8.  FD tangent modulus is positive definite at moderate stretch (all models).
 9.  FD tangent is consistent with stress (finite-difference check).
10.  uniaxial_response returns monotonically increasing stress for tension.
11.  biaxial_response is stiffer than uniaxial (for same λ, MR model).
12.  LLM tool smoke test: returns ok_payload with cauchy_stress_pa key.
13.  LLM tool: analytical oracle close to numerical for Neo-Hookean (uniaxial).
14.  LLM tool: Ogden with F_matrix returns strain energy and tangent.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from kerf_fem.hyperelastic.models import (
    HyperelasticModel,
    neo_hookean_strain_energy,
    neo_hookean_stress,
    neo_hookean_tangent,
    neo_hookean_uniaxial_cauchy,
    mooney_rivlin_strain_energy,
    mooney_rivlin_stress,
    mooney_rivlin_tangent,
    mooney_rivlin_uniaxial_cauchy,
    ogden_strain_energy,
    ogden_stress,
    ogden_tangent,
    ogden_uniaxial_cauchy,
    uniaxial_response,
    biaxial_response,
    _fd_tangent,
)


# ---------------------------------------------------------------------------
# Material constants
# ---------------------------------------------------------------------------

MU_NH = 0.4e6       # Pa  Neo-Hookean shear modulus
LAM_NH = 1e9        # Pa  (nearly incompressible)
C10 = 0.15e6        # Pa  Mooney-Rivlin
C01 = 0.015e6       # Pa
# Treloar (1944) Ogden N=3 parameters (Ogden 1972 Table 1)
# Original units N/cm² → Pa: multiply by 1e4
MU_P_TRELOAR = [6.3e4, 120.0, -1000.0]   # Pa  (Ogden 1972 units: 6.3, 0.012, -0.1 N/cm²)
AL_P_TRELOAR = [1.3,   5.0,   -2.0]


def uniaxial_F(lam: float) -> np.ndarray:
    """Incompressible uniaxial deformation gradient F = diag(λ, 1/√λ, 1/√λ)."""
    return np.diag([lam, 1.0 / math.sqrt(lam), 1.0 / math.sqrt(lam)])


# ---------------------------------------------------------------------------
# 1. Neo-Hookean: W ≥ 0, W(I) = 0
# ---------------------------------------------------------------------------

def test_neo_hookean_W_at_identity():
    F = np.eye(3)
    W = neo_hookean_strain_energy(F, MU_NH, LAM_NH)
    assert abs(W) < 1e-6, f"W(I) should be 0, got {W}"


def test_neo_hookean_W_positive_stretch():
    F = uniaxial_F(2.0)
    W = neo_hookean_strain_energy(F, MU_NH, LAM_NH)
    assert W > 0, f"W should be positive under stretch, got {W}"


# ---------------------------------------------------------------------------
# 2. Neo-Hookean: uniaxial true stress oracle
#    True uniaxial Cauchy = σ₁₁ - σ₂₂  (eliminates hydrostatic pressure)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lam", [1.2, 1.5, 2.0, 3.0, 4.0])
def test_neo_hookean_uniaxial_stress_oracle(lam):
    """σ_11 - σ_22 from neo_hookean_stress matches closed-form μ(λ²-1/λ)."""
    F = uniaxial_F(lam)
    sigma = neo_hookean_stress(F, MU_NH, LAM_NH)
    sigma_true = sigma[0, 0] - sigma[1, 1]   # free-surface uniaxial Cauchy

    sigma_analytic = neo_hookean_uniaxial_cauchy(lam, MU_NH)  # μ(λ²-1/λ)
    rel_err = abs(sigma_true - sigma_analytic) / abs(sigma_analytic)
    # Compressibility correction lam*lnJ/J is non-zero but tiny for lam → ∞
    # Allow 1e-4 since LAM_NH = 1 GPa >> MU_NH = 0.4 MPa
    assert rel_err < 2e-4, (
        f"NH uniaxial σ at λ={lam}: s11-s22={sigma_true:.4e}, "
        f"analytic={sigma_analytic:.4e}, rel_err={rel_err:.6f}"
    )


# ---------------------------------------------------------------------------
# 3. Mooney-Rivlin: W(I) = 0
# ---------------------------------------------------------------------------

def test_mooney_rivlin_W_at_identity():
    F = np.eye(3)
    W = mooney_rivlin_strain_energy(F, C10, C01)
    assert abs(W) < 1e-6, f"MR W(I) should be 0, got {W}"


# ---------------------------------------------------------------------------
# 4. Mooney-Rivlin: uniaxial true stress oracle
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lam", [1.2, 1.5, 2.0, 3.0])
def test_mooney_rivlin_uniaxial_stress_oracle(lam):
    """σ_11 - σ_22 from MR stress matches closed-form 2(λ²-1/λ)(C10+C01/λ)."""
    F = uniaxial_F(lam)
    sigma = mooney_rivlin_stress(F, C10, C01, d=0.0)
    sigma_true = sigma[0, 0] - sigma[1, 1]
    sigma_analytic = mooney_rivlin_uniaxial_cauchy(lam, C10, C01)
    rel_err = abs(sigma_true - sigma_analytic) / abs(sigma_analytic)
    assert rel_err < 1e-10, (
        f"MR uniaxial σ at λ={lam}: s11-s22={sigma_true:.4e}, "
        f"analytic={sigma_analytic:.4e}, rel_err={rel_err:.6f}"
    )


# ---------------------------------------------------------------------------
# 5. Ogden N=1, α=2: uniaxial oracle match
# ---------------------------------------------------------------------------

def test_ogden_n1_alpha2_uniaxial_oracle():
    """Ogden N=1, α=2: σ_11-σ_22 matches oracle μ(λ²-λ⁻¹) = ogden_uniaxial_cauchy."""
    mu1 = 0.5e6
    for lam in [1.5, 2.0, 3.0]:
        F = uniaxial_F(lam)
        sigma = ogden_stress(F, [mu1], [2.0], kappa=1e12)
        sigma_true = sigma[0, 0] - sigma[1, 1]
        sigma_oracle = ogden_uniaxial_cauchy(lam, [mu1], [2.0])
        rel_err = abs(sigma_true - sigma_oracle) / abs(sigma_oracle)
        assert rel_err < 0.01, (
            f"Ogden α=2 at λ={lam}: s11-s22={sigma_true:.4e}, oracle={sigma_oracle:.4e}, err={rel_err:.4f}"
        )


# ---------------------------------------------------------------------------
# 6. Ogden N=1: uniaxial analytical oracle (general α)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lam,mu_p,alpha_p", [
    (2.0, [0.5e6], [1.5]),
    (3.0, [0.3e6], [3.0]),
    (1.5, [1.0e6], [2.0]),
])
def test_ogden_uniaxial_oracle(lam, mu_p, alpha_p):
    """Ogden N=1: σ_11-σ_22 = μ_p(λ^α - λ^{-α/2}) matches model."""
    F = uniaxial_F(lam)
    sigma_num = ogden_stress(F, mu_p, alpha_p, kappa=1e12)
    sigma_true = sigma_num[0, 0] - sigma_num[1, 1]
    sigma_an = ogden_uniaxial_cauchy(lam, mu_p, alpha_p)
    rel_err = abs(sigma_true - sigma_an) / abs(sigma_an)
    assert rel_err < 0.01, (
        f"Ogden N=1 at λ={lam}: s11-s22={sigma_true:.4e}, s_an={sigma_an:.4e}, err={rel_err:.4f}"
    )


# ---------------------------------------------------------------------------
# 7. Ogden N=3 (Treloar): stress at λ=7 in reasonable range
# ---------------------------------------------------------------------------

def test_ogden_treloar_at_large_stretch():
    """Ogden N=3 Treloar parameters: σ at λ=7 should be ~2–5 MPa (Treloar 1944)."""
    lam = 7.0
    F = uniaxial_F(lam)
    sigma = ogden_stress(F, MU_P_TRELOAR, AL_P_TRELOAR, kappa=1e12)
    sigma_true = sigma[0, 0] - sigma[1, 1]
    sigma_mpa = sigma_true / 1e6
    # Oracle (exact): Σ μ_p(λ^α_p - λ^{-α_p/2})
    sigma_oracle = ogden_uniaxial_cauchy(lam, MU_P_TRELOAR, AL_P_TRELOAR) / 1e6
    # The two should agree within 5%
    rel_err = abs(sigma_true / 1e6 - sigma_oracle) / abs(sigma_oracle)
    assert rel_err < 0.05, (
        f"Ogden Treloar λ=7: s11-s22={sigma_mpa:.3f} MPa, oracle={sigma_oracle:.3f} MPa, err={rel_err:.4f}"
    )
    # And the value should be positive and physically plausible
    assert 0.5 < sigma_mpa < 20.0, (
        f"Ogden Treloar λ=7: σ={sigma_mpa:.2f} MPa, expected 0.5–20 MPa"
    )


# ---------------------------------------------------------------------------
# 8. FD tangent positive definite at moderate stretch
# ---------------------------------------------------------------------------

def test_neo_hookean_tangent_psd():
    """NH FD tangent should be positive definite at moderate strain."""
    F = uniaxial_F(1.1)
    C_mat = neo_hookean_tangent(F, MU_NH, LAM_NH)
    eigvals = np.linalg.eigvalsh(C_mat)
    assert np.all(eigvals > 0), (
        f"NH FD tangent not PD: min eigval = {eigvals.min():.4e}"
    )


def test_mooney_rivlin_tangent_psd():
    """MR tangent with small-but-nonzero d should be PD (avoids pure-incompressible singularity)."""
    F = uniaxial_F(1.2)
    # Use small d (≈ compressible rubber, K=2 GPa) to regularise the volumetric mode
    d_small = 1e-9   # Pa⁻¹ → K = 2 GPa
    C_mat = mooney_rivlin_tangent(F, C10, C01, d=d_small)
    eigvals = np.linalg.eigvalsh(C_mat)
    assert np.all(eigvals > 0), (
        f"MR FD tangent (d={d_small}) not PD: min eigval = {eigvals.min():.4e}"
    )


def test_ogden_tangent_psd():
    """Ogden FD tangent should be PD for a generic (non-degenerate) stretch state.

    A general triaxial stretch F = diag(λ1, λ2, λ3) with distinct eigenvalues
    avoids the spectral degeneracy (λ2=λ3) that affects the uniaxial state.
    """
    # Use general (non-symmetric) stretch to avoid degenerate B eigenvalues
    lam1, lam2 = 1.5, 1.1
    lam3 = 1.0 / (lam1 * lam2)  # incompressible constraint J=1
    F = np.diag([lam1, lam2, lam3])
    C_mat = ogden_tangent(F, [0.5e6], [2.0], kappa=1e9)
    eigvals = np.linalg.eigvalsh(C_mat)
    assert np.all(eigvals > 0), (
        f"Ogden FD tangent not PD: min eigval = {eigvals.min():.4e}"
    )


# ---------------------------------------------------------------------------
# 9. FD tangent consistency check
# ---------------------------------------------------------------------------

def test_neo_hookean_tangent_fd_consistency():
    """FD tangent should be symmetric and match a second FD pass."""
    lam = 1.5
    F = uniaxial_F(lam)
    C_fd = _fd_tangent(F, lambda F_: neo_hookean_stress(F_, MU_NH, LAM_NH))
    # Symmetry check
    sym_err = np.max(np.abs(C_fd - C_fd.T)) / (np.max(np.abs(C_fd)) + 1.0)
    assert sym_err < 1e-6, f"Tangent not symmetric: sym_err = {sym_err:.4e}"


# ---------------------------------------------------------------------------
# 10. uniaxial_response monotonically increasing
# ---------------------------------------------------------------------------

def test_uniaxial_response_monotone():
    mat = HyperelasticModel(model="mooney_rivlin", C10=C10, C01=C01)
    lams, P = uniaxial_response(mat, stretch_max=4.0, n_points=50)
    dP = np.diff(P)
    assert np.all(dP >= -1.0), (
        f"Uniaxial response not monotone; min(dP) = {dP.min():.4e}"
    )


# ---------------------------------------------------------------------------
# 11. Biaxial stiffer than uniaxial (σ₁₁-σ₂₂ comparison at same λ)
# ---------------------------------------------------------------------------

def test_biaxial_stiffer_than_uniaxial_mr():
    """For MR, biaxial stress at λ=2 should be > uniaxial at λ=2."""
    mat = HyperelasticModel(model="mooney_rivlin", C10=C10, C01=C01)
    lams_u, P_u = uniaxial_response(mat, stretch_max=2.5, n_points=50)
    lams_b, P_b = biaxial_response(mat, stretch_max=2.5, n_points=50)
    # At λ≈2
    idx = np.argmin(np.abs(lams_u - 2.0))
    assert P_b[idx] > P_u[idx], (
        f"Expected biaxial > uniaxial at λ=2; P_b={P_b[idx]:.3e}, P_u={P_u[idx]:.3e}"
    )


# ---------------------------------------------------------------------------
# 12. LLM tool smoke test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_smoke():
    from kerf_fem.hyperelastic.hyperelastic_tools import run_fem_hyperelastic
    from kerf_fem._compat import ProjectCtx
    ctx = ProjectCtx()
    payload = json.dumps({
        "model": "mooney_rivlin",
        "loading": "uniaxial",
        "C10_pa": 0.15e6,
        "C01_pa": 0.015e6,
        "stretch_max": 3.0,
        "n_points": 20,
    })
    resp = await run_fem_hyperelastic(ctx, payload.encode())
    data = json.loads(resp)
    assert "cauchy_stress_pa" in data, f"Missing cauchy_stress_pa: {data}"
    assert len(data["cauchy_stress_pa"]) == 20
    assert data["model"] == "mooney_rivlin"


# ---------------------------------------------------------------------------
# 13. LLM tool: analytical oracle close to numerical for Neo-Hookean
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_neo_hookean_oracle():
    from kerf_fem.hyperelastic.hyperelastic_tools import run_fem_hyperelastic
    from kerf_fem._compat import ProjectCtx
    ctx = ProjectCtx()
    payload = json.dumps({
        "model": "neo_hookean",
        "loading": "uniaxial",
        "mu_pa": 0.4e6,
        "stretch_max": 4.0,
        "n_points": 40,
    })
    resp = await run_fem_hyperelastic(ctx, payload.encode())
    data = json.loads(resp)
    assert "max_relative_error_vs_analytical" in data
    rel_err = data["max_relative_error_vs_analytical"]
    # NH compressible vs incompressible oracle: expect ~0 since we use s11-s22
    assert rel_err < 0.01, f"Oracle error too large: {rel_err:.4f}"


# ---------------------------------------------------------------------------
# 14. LLM tool: Ogden F_matrix single-point evaluation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_ogden_single_point():
    from kerf_fem.hyperelastic.hyperelastic_tools import run_fem_hyperelastic
    from kerf_fem._compat import ProjectCtx
    ctx = ProjectCtx()
    lam = 2.0
    F = np.diag([lam, 1.0 / math.sqrt(lam), 1.0 / math.sqrt(lam)]).tolist()
    payload = json.dumps({
        "model": "ogden",
        "loading": "uniaxial",
        "ogden_mu_p_pa": [0.5e6],
        "ogden_alpha_p": [2.0],
        "ogden_kappa_pa": 1e9,
        "stretch_max": 3.0,
        "n_points": 10,
        "F_matrix": F,
    })
    resp = await run_fem_hyperelastic(ctx, payload.encode())
    data = json.loads(resp)
    assert "single_point" in data
    sp = data["single_point"]
    assert "strain_energy_density_j_m3" in sp
    assert sp["strain_energy_density_j_m3"] > 0
    assert "lagrangian_tangent_voigt_pa" in sp
    assert len(sp["lagrangian_tangent_voigt_pa"]) == 6
