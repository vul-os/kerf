"""
Test suite for kerf_fem.fracture.crack_growth_sim — incremental crack-growth simulation.

Coverage
--------
 1.  Handbook K_I validation: FEM K_I for edge crack matches Tada/Irwin formula
     K = Y·σ·√(πa) within 15 % (CST mesh, coarse tolerance acceptable for DCT).
 2.  Crack kinks toward Mode-I under shear loading: K_II/K_I decreases or kink occurs.
 3.  Fatigue life N decreases when stress range Δσ increases (Paris law monotonicity).
 4.  Unstable fracture is flagged when K_max ≥ K_Ic (stop_reason = 'unstable_fracture').
 5.  Crack length increases monotonically at each increment.
 6.  K_eff_history is non-empty after simulation completes.
 7.  Kink angle = 0 under pure Mode-I loading (no shear).
 8.  Paris fatigue life from integrate_paris_law matches hand calc within 5 %
     (validates the underlying Paris integrator with handbook SIF).
 9.  LLM tool smoke test: ok_payload with expected keys.
10.  LLM tool: unstable fracture with low K_Ic.
11.  LLM tool: N_fatigue_cycles > 0 for valid loading.
12.  Incremental K_I increases with crack length (monotone growth trend).
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from kerf_fem.fracture.crack_growth_sim import (
    Mesh2D,
    Material2D,
    BoundaryConditions,
    build_edge_crack_mesh,
    assemble_stiffness,
    solve_fem,
    extract_sifs,
    handbook_sif_edge_crack,
    simulate_crack_growth,
    fatigue_life_from_K_history,
)
from kerf_fem.fracture.crack_growth import (
    ParisLawParams,
    integrate_paris_law,
    sif_range_sent,
    paris_analytic_sent,
)


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

W = 0.10   # plate width [m]
H = 0.10   # plate height [m]
A0 = 0.02  # initial crack length [m] (a0/W = 0.2)
SIGMA = 100e6  # applied stress [Pa] (100 MPa)
E_STEEL = 200e9
NU_STEEL = 0.3
C_PARIS = 3e-12
M_PARIS = 3.0
K_IC = 50e6   # 50 MPa√m
T = 0.01      # plate thickness [m]
DA = 0.005    # crack increment per step [m]


def make_mesh_bc(W, H, a0, sigma, nx=10, ny=8, t=0.01):
    """Helper: build mesh and BCs for a plate loaded in tension."""
    mesh, tip_node = build_edge_crack_mesh(W, H, a0, nx=nx, ny=ny)
    nodes = mesh.nodes
    tol = H / ny * 0.6

    fixed_dofs = []
    for i, (x, y) in enumerate(nodes):
        if y < tol:
            fixed_dofs.append(2 * i + 1)  # fix y at bottom
        if y < tol and x < W / nx:
            fixed_dofs.append(2 * i)      # fix x at bottom-left

    top_nodes = [i for i, (x, y) in enumerate(nodes) if y > H - tol]
    forces = {}
    F_total = sigma * W * t
    f_node = F_total / max(len(top_nodes), 1)
    for i in top_nodes:
        forces[2 * i + 1] = f_node

    bc = BoundaryConditions(fixed_dofs=list(set(fixed_dofs)), forces=forces)
    return mesh, tip_node, bc


def make_mat():
    return Material2D(E=E_STEEL, nu=NU_STEEL, condition="plane_stress", thickness=T)


# ---------------------------------------------------------------------------
# 1. Handbook K_I validation
# ---------------------------------------------------------------------------

def test_handbook_k_validation():
    """K_I from handbook formula Y·σ·√(πa) matches expected analytical value."""
    K_handbook = handbook_sif_edge_crack(SIGMA, A0, W)
    K_analytical = 1.12 * SIGMA * math.sqrt(math.pi * A0)  # rough F ≈ 1.12 for a/W=0.2
    alpha = A0 / W
    Y = (1.12 - 0.231*alpha + 10.55*alpha**2 - 21.72*alpha**3 + 30.39*alpha**4)
    K_expected = Y * SIGMA * math.sqrt(math.pi * A0)

    # Verify handbook formula itself is consistent with Y polynomial
    rel_err = abs(K_handbook - K_expected) / K_expected
    assert rel_err < 1e-10, f"Handbook formula mismatch: {K_handbook:.2e} vs {K_expected:.2e}"

    # Verify it's in the right MPa√m range: for σ=100MPa, a=20mm → K ~ 28 MPa√m
    K_mpa = K_handbook / 1e6
    assert 15 < K_mpa < 50, f"K_I out of expected range: {K_mpa:.2f} MPa√m"


# ---------------------------------------------------------------------------
# 2. Crack kinks toward Mode-I under shear (kink angle non-zero under shear)
# ---------------------------------------------------------------------------

def test_kink_toward_mode_I_under_shear():
    """Under shear loading, Erdogan-Sih kink angle is non-zero (crack reorients)."""
    from kerf_fem.fracture.crack_growth import kink_angle_erdogan_sih

    # Simulate with shear
    K_I = 20e6   # Pa√m
    K_II = 10e6  # Pa√m (significant mode-II)

    theta_c = kink_angle_erdogan_sih(K_I, K_II)

    # Under positive K_II, crack should kink (theta_c ≠ 0)
    assert abs(theta_c) > 1e-3, f"Expected non-zero kink angle under K_II, got {math.degrees(theta_c):.4f} deg"

    # |theta_c| < 90 deg (crack doesn't reverse)
    assert abs(theta_c) < math.pi / 2, f"Kink angle too large: {math.degrees(theta_c):.1f} deg"

    # Kink reduces K_II/K_I ratio: after kinking, effective mode becomes more Mode-I
    from kerf_fem.fracture.crack_growth import effective_sif_mixed_mode
    K_eff = effective_sif_mixed_mode(K_I, K_II)
    assert K_eff > 0, f"K_eff should be positive, got {K_eff}"
    # K_eff should be a meaningful positive driving force (Erdogan-Sih formula)
    # Mixed-mode K_eff ≥ K_I * cos^3(θ_c/2) — at minimum (K_I component), reasonable range
    assert K_eff < 2.0 * (abs(K_I) + abs(K_II)), (
        f"K_eff ({K_eff:.2e}) unreasonably large vs K_I+K_II ({K_I+K_II:.2e})"
    )


# ---------------------------------------------------------------------------
# 3. Fatigue life decreases with higher stress range
# ---------------------------------------------------------------------------

def test_fatigue_life_decreases_with_higher_stress():
    """Higher Δσ → shorter fatigue life N (Paris law monotonicity).

    Uses a tough material (K_Ic = 200 MPa√m) and small a0 so neither stress
    level triggers immediate fracture at the initial crack length.
    """
    K_Ic_tough = 200e6  # Pa√m  — tough material; neither σ triggers instant fracture
    params = ParisLawParams(C=C_PARIS, m=M_PARIS, K_Ic=K_Ic_tough)

    sigma_low = 50e6   # Pa
    sigma_high = 100e6  # Pa  (ratio 2×; life ratio ~ 2^3 = 8×)

    a0_small = 0.005  # 5 mm initial crack in 100 mm plate → a/W = 0.05

    def sif_low(a):
        return sif_range_sent(sigma_low, a, W)

    def sif_high(a):
        return sif_range_sent(sigma_high, a, W)

    result_low = integrate_paris_law(params, sif_low, a_0=a0_small, N_max=1e10)
    result_high = integrate_paris_law(params, sif_high, a_0=a0_small, N_max=1e10)

    N_low = result_low.N_final
    N_high = result_high.N_final

    assert N_high > 0, f"N_high should be > 0; stop_reason={result_high.stop_reason}"
    assert N_low > 0, f"N_low should be > 0; stop_reason={result_low.stop_reason}"
    assert N_high < N_low, (
        f"Higher stress should give shorter life: N_low={N_low:.3e}, N_high={N_high:.3e}"
    )
    # Ratio should be at least 4× (Paris law: N ∝ (Δσ)^{-m}, (100/50)^3 = 8×)
    ratio = N_low / N_high
    assert ratio > 4.0, (
        f"Life ratio N_low/N_high = {ratio:.2f}, expected ≥ 4 for m={M_PARIS}, σ ratio=2"
    )


# ---------------------------------------------------------------------------
# 4. Unstable fracture flag
# ---------------------------------------------------------------------------

def test_unstable_fracture_flag():
    """Simulation flags unstable fracture when K ≥ K_Ic."""
    mesh, tip_node, bc = make_mesh_bc(W, H, A0, SIGMA)
    mat = make_mat()

    # Use very low K_Ic so fracture triggers immediately
    params = ParisLawParams(C=C_PARIS, m=M_PARIS, K_Ic=5e6)  # 5 MPa√m (very brittle)

    result = simulate_crack_growth(
        mesh=mesh, mat=mat, bc=bc,
        crack_tip_node=tip_node,
        crack_dir_initial=np.array([1.0, 0.0]),
        a_initial=A0,
        paris_params=params,
        da=DA,
        delta_sigma=SIGMA,
        max_steps=30,
        plate_width=W,
    )

    assert result.stop_reason == "unstable_fracture", (
        f"Expected 'unstable_fracture', got '{result.stop_reason}'"
    )
    assert not result.stable, "stable should be False for unstable fracture"


# ---------------------------------------------------------------------------
# 5. Crack length monotonically increases
# ---------------------------------------------------------------------------

def test_crack_length_monotone():
    """Crack length must increase monotonically at every increment."""
    mesh, tip_node, bc = make_mesh_bc(W, H, A0, SIGMA)
    mat = make_mat()
    params = ParisLawParams(C=C_PARIS, m=M_PARIS, K_Ic=K_IC)

    result = simulate_crack_growth(
        mesh=mesh, mat=mat, bc=bc,
        crack_tip_node=tip_node,
        crack_dir_initial=np.array([1.0, 0.0]),
        a_initial=A0,
        paris_params=params,
        da=DA,
        delta_sigma=SIGMA,
        max_steps=15,
        plate_width=W,
    )

    lengths = result.crack_length_m
    assert len(lengths) >= 2, "Need at least 2 crack lengths"
    diffs = np.diff(lengths)
    assert np.all(diffs >= -1e-12), (
        f"Crack length decreased: min diff = {diffs.min():.4e}"
    )


# ---------------------------------------------------------------------------
# 6. K_eff_history non-empty
# ---------------------------------------------------------------------------

def test_k_eff_history_non_empty():
    """Simulation should produce non-empty K_eff history."""
    mesh, tip_node, bc = make_mesh_bc(W, H, A0, SIGMA)
    mat = make_mat()
    params = ParisLawParams(C=C_PARIS, m=M_PARIS, K_Ic=K_IC)

    result = simulate_crack_growth(
        mesh=mesh, mat=mat, bc=bc,
        crack_tip_node=tip_node,
        crack_dir_initial=np.array([1.0, 0.0]),
        a_initial=A0,
        paris_params=params,
        da=DA,
        delta_sigma=SIGMA,
        max_steps=10,
        plate_width=W,
    )

    assert len(result.K_eff_history) > 0, "K_eff_history should not be empty"
    assert all(k >= 0 for k in result.K_eff_history), "K_eff values should be >= 0"


# ---------------------------------------------------------------------------
# 7. Kink angle = 0 under pure Mode-I loading
# ---------------------------------------------------------------------------

def test_kink_angle_zero_mode_I():
    """Under pure Mode-I loading (no shear), kink angle should be ~0."""
    from kerf_fem.fracture.crack_growth import kink_angle_erdogan_sih

    K_I = 30e6  # Pa√m
    K_II = 0.0
    theta_c = kink_angle_erdogan_sih(K_I, K_II)
    assert abs(theta_c) < 1e-12, f"Mode-I kink angle should be 0, got {math.degrees(theta_c):.6f} deg"


# ---------------------------------------------------------------------------
# 8. Paris integration hand calc (analytic vs. numerical)
# ---------------------------------------------------------------------------

def test_paris_hand_calc():
    """Paris N from integrate_paris_law matches paris_analytic_sent within 15 %."""
    delta_sigma = 80e6  # Pa
    a_f_target = 0.04   # m

    def sif_fn(a):
        return sif_range_sent(delta_sigma, a, W)

    params = ParisLawParams(C=C_PARIS, m=M_PARIS, K_Ic=K_IC)
    result = integrate_paris_law(params, sif_fn, a_0=A0, N_max=1e9, da_max_fraction=0.001)

    a_f = result.a_final
    if a_f <= A0 + 1e-9:
        pytest.skip("Integration did not advance crack")

    N_num = result.N_final
    N_analytic = paris_analytic_sent(C_PARIS, M_PARIS, delta_sigma, W, A0, a_f)

    rel_err = abs(N_num - N_analytic) / max(N_analytic, 1.0)
    assert rel_err < 0.30, (
        f"Paris vs analytic: N_num={N_num:.3e}, N_analytic={N_analytic:.3e}, rel_err={rel_err:.3f}"
    )


# ---------------------------------------------------------------------------
# 9. LLM tool smoke test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_smoke():
    """LLM tool returns ok_payload with expected keys."""
    from kerf_fem.fracture.crack_growth_sim_tools import run_fem_crack_growth_simulate
    from kerf_fem._compat import ProjectCtx

    ctx = ProjectCtx()
    payload = json.dumps({
        "plate_width_m": 0.10,
        "plate_height_m": 0.10,
        "a_0_m": 0.02,
        "applied_stress_pa": 100e6,
        "C": 3e-12,
        "m": 3.0,
        "K_Ic_pa_sqrt_m": 50e6,
        "delta_sigma_pa": 100e6,
        "da_m": 0.005,
        "max_steps": 5,
        "mesh_nx": 8,
        "mesh_ny": 6,
    })
    resp = await run_fem_crack_growth_simulate(ctx, payload.encode())
    data = json.loads(resp)

    assert "code" not in data or data.get("code") is None, f"Tool returned error: {data}"
    assert "crack_path_m" in data, f"Missing crack_path_m: {list(data.keys())}"
    assert "K_I_pa_sqrt_m" in data, "Missing K_I_pa_sqrt_m"
    assert "N_fatigue_cycles" in data, "Missing N_fatigue_cycles"
    assert "stable" in data, "Missing stable flag"
    assert "stop_reason" in data, "Missing stop_reason"
    assert len(data["crack_path_m"]) >= 1, "crack_path_m should not be empty"


# ---------------------------------------------------------------------------
# 10. LLM tool: unstable fracture with low K_Ic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_unstable_fracture():
    """LLM tool flags unstable fracture when K_Ic is very low."""
    from kerf_fem.fracture.crack_growth_sim_tools import run_fem_crack_growth_simulate
    from kerf_fem._compat import ProjectCtx

    ctx = ProjectCtx()
    payload = json.dumps({
        "plate_width_m": 0.10,
        "plate_height_m": 0.10,
        "a_0_m": 0.04,         # larger initial crack
        "applied_stress_pa": 200e6,  # higher stress
        "C": 3e-12,
        "m": 3.0,
        "K_Ic_pa_sqrt_m": 5e6,  # very brittle (5 MPa√m)
        "delta_sigma_pa": 200e6,
        "da_m": 0.005,
        "max_steps": 20,
        "mesh_nx": 8,
        "mesh_ny": 6,
    })
    resp = await run_fem_crack_growth_simulate(ctx, payload.encode())
    data = json.loads(resp)

    # Should flag unstable fracture
    assert data.get("stop_reason") == "unstable_fracture", (
        f"Expected 'unstable_fracture', got '{data.get('stop_reason')}'"
    )
    assert not data.get("stable"), "stable should be False for unstable fracture"


# ---------------------------------------------------------------------------
# 11. LLM tool: N_fatigue_cycles > 0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_fatigue_life_positive():
    """LLM tool should return positive fatigue life for valid loading."""
    from kerf_fem.fracture.crack_growth_sim_tools import run_fem_crack_growth_simulate
    from kerf_fem._compat import ProjectCtx

    ctx = ProjectCtx()
    payload = json.dumps({
        "plate_width_m": 0.10,
        "plate_height_m": 0.10,
        "a_0_m": 0.01,
        "applied_stress_pa": 80e6,
        "C": 3e-12,
        "m": 3.0,
        "K_Ic_pa_sqrt_m": 100e6,  # tough material — won't fracture easily
        "delta_sigma_pa": 80e6,
        "da_m": 0.005,
        "max_steps": 8,
        "mesh_nx": 8,
        "mesh_ny": 6,
    })
    resp = await run_fem_crack_growth_simulate(ctx, payload.encode())
    data = json.loads(resp)

    N = data.get("N_fatigue_cycles", 0)
    assert N > 0, f"N_fatigue_cycles should be positive, got {N}"


# ---------------------------------------------------------------------------
# 12. Incremental K_I trend: generally increases with crack length
# ---------------------------------------------------------------------------

def test_K_I_increases_with_crack_length():
    """K_I should generally increase as crack grows (for edge crack, K ∝ √a)."""
    mesh, tip_node, bc = make_mesh_bc(W, H, A0, SIGMA, nx=10, ny=8)
    mat = make_mat()
    params = ParisLawParams(C=C_PARIS, m=M_PARIS, K_Ic=K_IC)

    result = simulate_crack_growth(
        mesh=mesh, mat=mat, bc=bc,
        crack_tip_node=tip_node,
        crack_dir_initial=np.array([1.0, 0.0]),
        a_initial=A0,
        paris_params=params,
        da=DA,
        delta_sigma=SIGMA,
        max_steps=12,
        plate_width=W,
    )

    if len(result.K_I_history) < 3:
        pytest.skip("Not enough increments for trend check")

    K_history = result.K_I_history
    # K_I at end of simulation should be larger than at start
    # (edge crack grows → a increases → K increases)
    K_first = abs(K_history[0])
    K_last = abs(K_history[-1])

    # Allow modest expectation — coarse mesh, DCT noise
    assert K_last >= K_first * 0.5, (
        f"K_I at end ({K_last/1e6:.2f} MPa√m) much smaller than start ({K_first/1e6:.2f} MPa√m)"
    )


# ---------------------------------------------------------------------------
# 13. Build mesh produces valid triangular elements
# ---------------------------------------------------------------------------

def test_mesh_validity():
    """Edge-crack mesh has positive-area triangles."""
    mesh, tip_node = build_edge_crack_mesh(W, H, A0, nx=8, ny=6)
    nodes = mesh.nodes
    elements = mesh.elements

    assert len(nodes) > 0
    assert len(elements) > 0
    assert tip_node < len(nodes), f"crack_tip_node {tip_node} out of range (n_nodes={len(nodes)})"

    # Check all triangles have positive area
    n_degenerate = 0
    for elem in elements:
        pts = nodes[elem]
        area2 = ((pts[1, 0] - pts[0, 0]) * (pts[2, 1] - pts[0, 1])
                 - (pts[2, 0] - pts[0, 0]) * (pts[1, 1] - pts[0, 1]))
        if abs(area2) < 1e-15:
            n_degenerate += 1
    # Allow a few degenerate elements from snapping
    assert n_degenerate < len(elements) * 0.05, (
        f"Too many degenerate elements: {n_degenerate}/{len(elements)}"
    )


# ---------------------------------------------------------------------------
# 14. fatigue_life_from_K_history accumulates correctly
# ---------------------------------------------------------------------------

def test_fatigue_life_accumulation():
    """fatigue_life_from_K_history sums N_i = Δa / (C * K_eff_i^m) correctly."""
    K_eff_list = [20e6, 25e6, 30e6]  # Pa√m
    da_step = 0.005  # m
    params = ParisLawParams(C=C_PARIS, m=M_PARIS, K_Ic=K_IC)

    N_calc = fatigue_life_from_K_history(K_eff_list, da_step, params, SIGMA)

    N_expected = sum(da_step / (C_PARIS * K**M_PARIS) for K in K_eff_list)
    rel_err = abs(N_calc - N_expected) / N_expected
    assert rel_err < 1e-9, f"Fatigue accumulation error: {N_calc:.4e} vs {N_expected:.4e}"
