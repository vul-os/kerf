"""
T-40  FEM: linear static end-to-end
====================================
25 canonical problems covering cantilever, simply-supported, fixed-fixed beams,
axial bars, thermal-stress bars, nonlinear_bar return-mapping, CalculiX INP-deck
writers/parsers, and graceful-pending paths for dolfinx / ccx.

Scope: kerf-fem/calculix_utils.py  +  fenicsx_utils.py  +  nonlinear_bar.py
       (and the supporting linear_static.py for the analytic reference values).

All tests are hermetic — no external solvers, no DB, no network.  Tests that
exercise ccx or dolfinx are skipped gracefully when those engines are absent.

References
----------
* Roark's Formulas for Stress and Strain, 9th ed. (Young, Budynas, Sadegh 2020)
* Timoshenko & Goodier, Theory of Elasticity, 3rd ed. (1970)
* Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed. (2011)
"""

from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Optional-engine guards (no skip at collection time — guards are per-test)
# ---------------------------------------------------------------------------

_CCX_AVAILABLE = shutil.which("ccx") is not None

_needs_ccx = pytest.mark.skipif(
    not _CCX_AVAILABLE,
    reason="CalculiX (ccx) not installed",
)

try:
    import dolfinx  # noqa: F401
    _DOLFINX_AVAILABLE = True
except ImportError:
    _DOLFINX_AVAILABLE = False

_needs_dolfinx = pytest.mark.skipif(
    not _DOLFINX_AVAILABLE,
    reason="dolfinx not installed",
)

try:
    import gmsh  # noqa: F401
    _GMSH_AVAILABLE = True
except ImportError:
    _GMSH_AVAILABLE = False

_needs_gmsh = pytest.mark.skipif(
    not _GMSH_AVAILABLE,
    reason="gmsh not installed",
)

# ---------------------------------------------------------------------------
# Tolerance: spec says ±2% for FEM vs analytic; we use tighter for exact solvers
# ---------------------------------------------------------------------------
_FEM_TOL = 0.02   # 2% relative tolerance (spec ceiling)
_EXACT_TOL = 1e-6  # for the analytically-exact Hermite beam element


# ===========================================================================
# 1. Cantilever tip deflection — Roark 9th ed. Table 8.1 case 1a
#    δ = P L³ / (3 E I)
# ===========================================================================

def test_lss_01_cantilever_tip_deflection():
    """Roark Table 8.1-1a: cantilever tip load δ = PL³/(3EI). Within 1e-6."""
    from kerf_fem.linear_static import solve_beam

    E, I, L, P = 200e9, 1e-5, 1.0, -5000.0
    delta_exact = P * L**3 / (3.0 * E * I)

    res = solve_beam(E, I, L,
                     supports=[{"type": "fixed", "x": 0.0}],
                     loads=[{"type": "point", "x": L, "P": P}],
                     n_elem=10)
    assert res["ok"], f"Solve failed: {res}"
    assert abs(res["w"][-1] - delta_exact) / abs(delta_exact) < _EXACT_TOL


# ===========================================================================
# 2. Cantilever tip rotation — Roark Table 8.1 case 1a
#    θ_tip = P L² / (2 E I)
# ===========================================================================

def test_lss_02_cantilever_tip_rotation():
    """Roark Table 8.1-1a: cantilever tip rotation θ = PL²/(2EI)."""
    from kerf_fem.linear_static import solve_beam

    E, I, L, P = 200e9, 1e-5, 1.0, -5000.0
    theta_exact = P * L**2 / (2.0 * E * I)

    res = solve_beam(E, I, L,
                     supports=[{"type": "fixed", "x": 0.0}],
                     loads=[{"type": "point", "x": L, "P": P}],
                     n_elem=10)
    assert res["ok"]
    assert abs(res["theta"][-1] - theta_exact) / abs(theta_exact) < _EXACT_TOL


# ===========================================================================
# 3. Simply-supported beam, centre point load — Roark Table 8.1 case 5a
#    δ_max = P L³ / (48 E I)
# ===========================================================================

def test_lss_03_simply_supported_centre_load():
    """Roark Table 8.1-5a: SS beam centre load δ = PL³/(48EI)."""
    from kerf_fem.linear_static import solve_beam

    E, I, L, P = 200e9, 1e-5, 2.0, -10000.0
    delta_exact = P * L**3 / (48.0 * E * I)

    res = solve_beam(E, I, L,
                     supports=[{"type": "pinned", "x": 0.0},
                               {"type": "pinned", "x": L}],
                     loads=[{"type": "point", "x": L / 2.0, "P": P}],
                     n_elem=20)
    assert res["ok"]
    assert abs(res["max_w"] - abs(delta_exact)) / abs(delta_exact) < _EXACT_TOL


# ===========================================================================
# 4. Simply-supported beam, UDL — Roark Table 8.1 case 10a
#    δ_max = 5 w L⁴ / (384 E I)
# ===========================================================================

def test_lss_04_simply_supported_udl():
    """Roark Table 8.1-10a: SS beam UDL δ_max = 5wL⁴/(384EI)."""
    from kerf_fem.linear_static import solve_beam

    E, I, L, w = 200e9, 1e-5, 3.0, 1000.0  # w [N/m] downward
    delta_exact = 5.0 * w * L**4 / (384.0 * E * I)

    res = solve_beam(E, I, L,
                     supports=[{"type": "pinned", "x": 0.0},
                               {"type": "pinned", "x": L}],
                     loads=[{"type": "udl", "w": w}],
                     n_elem=20)
    assert res["ok"]
    assert abs(res["max_w"] - delta_exact) / delta_exact < _EXACT_TOL


# ===========================================================================
# 5. Fixed-fixed beam, UDL — Roark Table 8.1 case 11a
#    δ_max = w L⁴ / (384 E I)   at midspan
# ===========================================================================

def test_lss_05_fixed_fixed_udl_midspan():
    """Roark Table 8.1-11a: fixed-fixed UDL δ_mid = wL⁴/(384EI)."""
    from kerf_fem.linear_static import solve_beam

    E, I, L, w = 200e9, 1e-5, 2.0, 2000.0
    delta_exact = w * L**4 / (384.0 * E * I)

    res = solve_beam(E, I, L,
                     supports=[{"type": "fixed", "x": 0.0},
                               {"type": "fixed", "x": L}],
                     loads=[{"type": "udl", "w": w}],
                     n_elem=20)
    assert res["ok"]
    assert abs(res["max_w"] - delta_exact) / delta_exact < _EXACT_TOL


# ===========================================================================
# 6. Cantilever UDL — Roark Table 8.1 case 2a
#    δ_tip = w L⁴ / (8 E I)
# ===========================================================================

def test_lss_06_cantilever_udl_tip():
    """Roark Table 8.1-2a: cantilever UDL δ_tip = wL⁴/(8EI)."""
    from kerf_fem.linear_static import solve_beam

    E, I, L, w = 200e9, 2e-5, 1.5, 500.0
    delta_exact = w * L**4 / (8.0 * E * I)

    res = solve_beam(E, I, L,
                     supports=[{"type": "fixed", "x": 0.0}],
                     loads=[{"type": "udl", "w": w}],
                     n_elem=20)
    assert res["ok"]
    assert abs(res["max_w"] - delta_exact) / delta_exact < _EXACT_TOL


# ===========================================================================
# 7. Axial bar extension — PL/(AE)
# ===========================================================================

def test_lss_07_axial_bar_extension():
    """Axial bar fixed at x=0, load P at x=L: u(L) = PL/(AE)."""
    from kerf_fem.linear_static import solve_axial_bar

    E, A, L, P = 70e9, 1e-4, 0.5, 10000.0
    u_exact = P * L / (A * E)

    res = solve_axial_bar(E, A, L, P, n_elem=1)
    assert res["ok"]
    assert abs(res["displacement"] - u_exact) / u_exact < _EXACT_TOL


# ===========================================================================
# 8. Axial bar — stress = P/A
# ===========================================================================

def test_lss_08_axial_bar_stress():
    """Axial stress σ = P/A, regardless of E or L."""
    from kerf_fem.linear_static import solve_axial_bar

    E, A, L, P = 200e9, 5e-4, 2.0, 50000.0
    res = solve_axial_bar(E, A, L, P)
    assert res["ok"]
    assert math.isclose(res["stress"], P / A, rel_tol=1e-9)


# ===========================================================================
# 9. Axial bar — reaction equals −P
# ===========================================================================

def test_lss_09_axial_bar_reaction():
    """Newton's 3rd: wall reaction at fixed end must equal −P."""
    from kerf_fem.linear_static import solve_axial_bar

    E, A, L, P = 200e9, 1e-4, 1.0, -8000.0
    res = solve_axial_bar(E, A, L, P)
    assert res["ok"]
    assert math.isclose(res["reaction"], -P, rel_tol=1e-9)


# ===========================================================================
# 10. Thermal stress — fully constrained bar σ = −EαΔT
# ===========================================================================

def test_lss_10_thermal_stress_constrained_bar():
    """Incropera §13: constrained bar σ = −EαΔT (compressive for ΔT>0)."""
    from kerf_fem.linear_static import solve_thermal_stress_bar

    E, alpha, dT = 200e9, 12e-6, 100.0
    sigma_exact = -E * alpha * dT

    res = solve_thermal_stress_bar(E, alpha, dT)
    assert res["ok"]
    assert math.isclose(res["stress"], sigma_exact, rel_tol=1e-9)


# ===========================================================================
# 11. Thermal stress — negative ΔT (tensile)
# ===========================================================================

def test_lss_11_thermal_stress_cooling():
    """Cooling (ΔT < 0) produces tensile stress (σ > 0)."""
    from kerf_fem.linear_static import solve_thermal_stress_bar

    E, alpha, dT = 200e9, 12e-6, -50.0
    res = solve_thermal_stress_bar(E, alpha, dT)
    assert res["ok"]
    assert res["stress"] > 0.0
    assert math.isclose(res["stress"], -E * alpha * dT, rel_tol=1e-9)


# ===========================================================================
# 12. Thermal stress force = stress × area
# ===========================================================================

def test_lss_12_thermal_stress_force_area():
    """Thermal constraint force = σ × area."""
    from kerf_fem.linear_static import solve_thermal_stress_bar

    E, alpha, dT, area = 200e9, 12e-6, 80.0, 2e-4
    res = solve_thermal_stress_bar(E, alpha, dT, area=area)
    assert res["ok"]
    assert math.isclose(res["force"], res["stress"] * area, rel_tol=1e-9)


# ===========================================================================
# 13. Cantilever — mesh refinement convergence (idempotency up to round-off)
# ===========================================================================

def test_lss_13_cantilever_mesh_refinement_idempotency():
    """
    Hermite beam is exact: n_elem=1 and n_elem=10 must give identical tip
    deflection (within floating-point round-off, not just ±2%).
    """
    from kerf_fem.linear_static import solve_beam

    E, I, L, P = 200e9, 1e-5, 2.0, -3000.0

    kwargs = dict(
        E=E, I=I, L=L,
        supports=[{"type": "fixed", "x": 0.0}],
        loads=[{"type": "point", "x": L, "P": P}],
    )
    r1  = solve_beam(**kwargs, n_elem=1)
    r10 = solve_beam(**kwargs, n_elem=10)

    assert r1["ok"] and r10["ok"]
    assert abs(r1["w"][-1] - r10["w"][-1]) / abs(r10["w"][-1]) < 1e-6


# ===========================================================================
# 14. Invalid inputs — boundary/malformed checks for solve_beam
# ===========================================================================

@pytest.mark.parametrize("kwargs,match_fragment", [
    ({"E": -1.0,  "I": 1e-5, "L": 1.0, "supports": [], "loads": []}, "E"),
    ({"E": 200e9, "I": -1.0, "L": 1.0, "supports": [], "loads": []}, "I"),
    ({"E": 200e9, "I": 1e-5, "L": 0.0, "supports": [], "loads": []}, "L"),
    ({"E": 200e9, "I": 1e-5, "L": 1.0, "supports": [],
      "loads": [], "n_elem": 0}, "n_elem"),
])
def test_lss_14_beam_invalid_inputs(kwargs, match_fragment):
    """solve_beam returns ok=False (never raises) for degenerate inputs."""
    from kerf_fem.linear_static import solve_beam

    res = solve_beam(**kwargs)
    assert not res["ok"], f"Expected ok=False for {match_fragment!r} edge case"
    assert "reason" in res


# ===========================================================================
# 15. Invalid inputs — solve_axial_bar
# ===========================================================================

@pytest.mark.parametrize("kwargs", [
    {"E": 0.0,   "A": 1e-4, "L": 1.0, "P": 1000.0},
    {"E": 200e9, "A": -1.0, "L": 1.0, "P": 1000.0},
    {"E": 200e9, "A": 1e-4, "L": -1.0, "P": 1000.0},
])
def test_lss_15_axial_bar_invalid_inputs(kwargs):
    """solve_axial_bar returns ok=False for degenerate inputs."""
    from kerf_fem.linear_static import solve_axial_bar

    res = solve_axial_bar(**kwargs)
    assert not res["ok"]
    assert "reason" in res


# ===========================================================================
# 16. Invalid inputs — solve_thermal_stress_bar
# ===========================================================================

def test_lss_16_thermal_stress_invalid_E():
    """solve_thermal_stress_bar: E <= 0 returns ok=False."""
    from kerf_fem.linear_static import solve_thermal_stress_bar

    res = solve_thermal_stress_bar(E=0.0, alpha=12e-6, dT=100.0)
    assert not res["ok"]


# ===========================================================================
# 17. nonlinear_bar — elastic step: stress = E·ε
# ===========================================================================

def test_lss_17_nonlinear_bar_elastic_step():
    """
    Below yield: stress matches Hooke's law σ = E·ε exactly.
    Return-mapping must not activate.
    """
    from kerf_fem.nonlinear_bar import run_nonlinear_bar

    E, sigma_y0, H = 200e9, 250e6, 20e9
    eps_below_yield = 0.5 * sigma_y0 / E   # 50% of yield strain

    res = run_nonlinear_bar(E, sigma_y0, H, [eps_below_yield])
    assert res["ok"], res
    assert math.isclose(res["stress"][0], E * eps_below_yield, rel_tol=1e-9)
    assert math.isclose(res["plastic_strain"][0], 0.0, abs_tol=1e-15)


# ===========================================================================
# 18. nonlinear_bar — plastic step: stress capped at yield surface
# ===========================================================================

def test_lss_18_nonlinear_bar_plastic_step():
    """
    Above yield (linear hardening): σ = σ_y0 + H·εᵖ after return mapping.
    Analytic check for one-increment overshoot.
    """
    from kerf_fem.nonlinear_bar import run_nonlinear_bar

    E, sigma_y0, H = 200e9, 250e6, 20e9
    eps_y = sigma_y0 / E
    eps_total = 2.0 * eps_y   # well into plastic range

    res = run_nonlinear_bar(E, sigma_y0, H, [eps_total])
    assert res["ok"], res
    sigma = res["stress"][0]
    eps_p = res["plastic_strain"][0]

    # Check stress consistency: σ = σ_y0 + H·εᵖ
    assert math.isclose(sigma, sigma_y0 + H * eps_p, rel_tol=1e-6), (
        f"σ={sigma:.4e} != σ_y0+H·εᵖ={sigma_y0 + H * eps_p:.4e}"
    )
    assert eps_p > 0.0, "plastic strain must be positive above yield"


# ===========================================================================
# 19. nonlinear_bar — perfect plasticity (H=0): stress stays at σ_y0
# ===========================================================================

def test_lss_19_nonlinear_bar_perfect_plasticity():
    """H=0: once yielded, stress must remain exactly at σ_y0."""
    from kerf_fem.nonlinear_bar import run_nonlinear_bar

    E, sigma_y0, H = 200e9, 250e6, 0.0
    eps_y = sigma_y0 / E
    steps = [1.1 * eps_y, 2.0 * eps_y, 5.0 * eps_y]

    res = run_nonlinear_bar(E, sigma_y0, H, steps)
    assert res["ok"], res
    for i, sigma in enumerate(res["stress"]):
        assert abs(sigma - sigma_y0) / sigma_y0 < 1e-9, (
            f"step {i}: σ={sigma:.4e} should equal σ_y0={sigma_y0:.4e}"
        )


# ===========================================================================
# 20. nonlinear_bar — multi-step monotone loading: plastic_strain non-decreasing
# ===========================================================================

def test_lss_20_nonlinear_bar_plastic_strain_monotone():
    """Accumulated plastic strain must be non-decreasing under monotone loading."""
    from kerf_fem.nonlinear_bar import run_nonlinear_bar

    E, sigma_y0, H = 200e9, 250e6, 10e9
    eps_y = sigma_y0 / E
    steps = [eps_y * k * 0.5 for k in range(1, 8)]  # elastic → plastic

    res = run_nonlinear_bar(E, sigma_y0, H, steps)
    assert res["ok"], res
    for i in range(1, len(res["plastic_strain"])):
        assert res["plastic_strain"][i] >= res["plastic_strain"][i - 1], (
            f"εᵖ decreased at step {i}: {res['plastic_strain'][i-1]:.4e} "
            f"→ {res['plastic_strain'][i]:.4e}"
        )


# ===========================================================================
# 21. nonlinear_bar — invalid inputs
# ===========================================================================

@pytest.mark.parametrize("kwargs,key", [
    ({"E": -1.0,  "sigma_y0": 250e6, "H": 0.0, "load_steps": [0.001]}, "E"),
    ({"E": 200e9, "sigma_y0": -1.0,  "H": 0.0, "load_steps": [0.001]}, "sigma_y0"),
    ({"E": 200e9, "sigma_y0": 250e6, "H": -1.0, "load_steps": [0.001]}, "H"),
])
def test_lss_21_nonlinear_bar_invalid_inputs(kwargs, key):
    """run_nonlinear_bar returns ok=False (never raises) for degenerate params."""
    from kerf_fem.nonlinear_bar import run_nonlinear_bar

    res = run_nonlinear_bar(**kwargs)
    assert not res["ok"], f"Expected ok=False for bad {key!r}"
    assert "reason" in res


# ===========================================================================
# 22. calculix_utils — run_static_analysis returns pending when ccx absent
# ===========================================================================

def test_lss_22_calculix_pending_when_no_ccx(monkeypatch):
    """
    When ccx is not in PATH, run_static_analysis must return status='pending'
    with a non-empty warning, never raise.
    """
    from kerf_fem import calculix_utils

    monkeypatch.setattr(calculix_utils, "_CALCULIX_AVAILABLE", False)

    result = calculix_utils.run_static_analysis(
        mesh_path="/nonexistent/mesh.msh",
        material_props={"E": 200e9, "nu": 0.3},
        boundary_conditions=[],
        loads=[],
    )
    assert result["status"] == "pending"
    assert len(result["warnings"]) > 0
    assert result["errors"] == []


# ===========================================================================
# 23. calculix_utils — unknown analysis_type raises ValueError
# ===========================================================================

def test_lss_23_calculix_unknown_analysis_type(monkeypatch):
    """Passing an unknown analysis_type must raise ValueError."""
    from kerf_fem import calculix_utils

    # Pretend ccx is available so we reach the dispatch branch
    monkeypatch.setattr(calculix_utils, "_CALCULIX_AVAILABLE", True)

    with pytest.raises(ValueError, match="unknown analysis_type"):
        calculix_utils.run_static_analysis(
            mesh_path="/fake/mesh.msh",
            material_props={"E": 200e9, "nu": 0.3},
            boundary_conditions=[],
            loads=[],
            analysis_type="magic",
        )


# ===========================================================================
# 24. fenicsx_utils — run_static_analysis returns pending when dolfinx absent
# ===========================================================================

def test_lss_24_fenicsx_pending_when_no_dolfinx(monkeypatch):
    """
    When dolfinx is not installed, run_static_analysis must return
    status='pending' with a non-empty warning list and no errors.
    """
    from kerf_fem import fenicsx_utils

    monkeypatch.setattr(fenicsx_utils, "_DOLFINX_AVAILABLE", False)

    result = fenicsx_utils.run_static_analysis(
        mesh_path="/nonexistent/mesh.msh",
        material_props={"E": 200e9, "nu": 0.3},
        boundary_conditions=[],
        loads=[],
    )
    assert result["status"] == "pending"
    assert len(result["warnings"]) > 0
    assert result["errors"] == []


# ===========================================================================
# 25. fenicsx_utils — unknown analysis_type raises ValueError (engine mocked present)
# ===========================================================================

def test_lss_25_fenicsx_unknown_analysis_type(monkeypatch):
    """Passing an unknown analysis_type to fenicsx_utils must raise ValueError."""
    from kerf_fem import fenicsx_utils

    monkeypatch.setattr(fenicsx_utils, "_DOLFINX_AVAILABLE", True)

    with pytest.raises(ValueError, match="unknown analysis_type"):
        fenicsx_utils.run_static_analysis(
            mesh_path="/fake/mesh.msh",
            material_props={"E": 200e9, "nu": 0.3},
            boundary_conditions=[],
            loads=[],
            analysis_type="bogus",
        )


# ===========================================================================
# Bonus A. calculix_utils — _parse_dat_eigenvalues: empty string returns []
# ===========================================================================

def test_lss_bonus_a_parse_dat_eigenvalues_empty():
    """_parse_dat_eigenvalues('') must return an empty list, not raise."""
    from kerf_fem.calculix_utils import _parse_dat_eigenvalues

    assert _parse_dat_eigenvalues("") == []


# ===========================================================================
# Bonus B. calculix_utils — _parse_dat_eigenvalues: synthetic table
# ===========================================================================

def test_lss_bonus_b_parse_dat_eigenvalues_synthetic():
    """Eigenvalue table in CalculiX .dat format → correct Hz values."""
    from kerf_fem.calculix_utils import _parse_dat_eigenvalues

    synthetic = (
        "E I G E N V A L U E S\n"
        " 1  1.000000E+06  9.99E+05\n"
        " 2  4.000000E+06  3.99E+06\n"
    )
    freqs = _parse_dat_eigenvalues(synthetic)
    assert len(freqs) == 2
    f1_expected = math.sqrt(1e6) / (2.0 * math.pi)
    assert math.isclose(freqs[0], f1_expected, rel_tol=1e-6)
    f2_expected = math.sqrt(4e6) / (2.0 * math.pi)
    assert math.isclose(freqs[1], f2_expected, rel_tol=1e-6)


# ===========================================================================
# Bonus C. calculix_utils — build_nonlinear_plastic_inp round-trip
# ===========================================================================

def test_lss_bonus_c_nonlinear_plastic_inp_keywords():
    """
    build_nonlinear_plastic_inp must produce an INP deck containing
    the required CalculiX keywords for a nonlinear-plastic step.
    """
    from kerf_fem.calculix_utils import build_nonlinear_plastic_inp

    nodes = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    elements = [(1, "tetra", [1, 2, 3, 4])]
    material_props = {
        "E": 200e9, "nu": 0.3, "rho": 7850.0,
        "sigma_y0": 250e6, "H": 10e9,
    }

    inp = build_nonlinear_plastic_inp(
        nodes, elements, material_props,
        boundary_conditions=[],
        loads=[],
    )
    assert "*HEADING" in inp
    assert "*NODE" in inp
    assert "*ELEMENT" in inp
    assert "*ELASTIC" in inp
    assert "*PLASTIC" in inp
    assert "NLGEOM" in inp
    assert "*STATIC" in inp
    assert "*END STEP" in inp


# ===========================================================================
# Bonus D. nonlinear_bar — force-controlled mode converges for sub-yield target
# ===========================================================================

def test_lss_bonus_d_force_controlled_elastic():
    """Force-controlled: elastic target σ_target < σ_y0 → εᵖ = 0."""
    from kerf_fem.nonlinear_bar import run_nonlinear_bar

    E, sigma_y0, H = 200e9, 250e6, 20e9
    sigma_target = 0.8 * sigma_y0   # elastic

    res = run_nonlinear_bar(E, sigma_y0, H,
                            load_steps=[sigma_target],
                            force_controlled=True)
    assert res["ok"], res
    assert math.isclose(res["plastic_strain"][0], 0.0, abs_tol=1e-15)
    # Check Hooke: ε = σ/E
    eps_expected = sigma_target / E
    assert math.isclose(res["strain"][0], eps_expected, rel_tol=1e-6)


# ===========================================================================
# Bonus E. axial bar — multi-element result identical to single element
# ===========================================================================

def test_lss_bonus_e_axial_bar_multi_elem_invariance():
    """
    Axial bar solution is linear; n_elem should not change tip displacement.
    """
    from kerf_fem.linear_static import solve_axial_bar

    E, A, L, P = 200e9, 1e-4, 1.0, 10000.0
    r1 = solve_axial_bar(E, A, L, P, n_elem=1)
    r5 = solve_axial_bar(E, A, L, P, n_elem=5)

    assert r1["ok"] and r5["ok"]
    assert math.isclose(r1["displacement"], r5["displacement"], rel_tol=1e-10)
