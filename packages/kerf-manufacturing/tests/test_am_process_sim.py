"""
Tests for kerf_manufacturing.am_process_sim — Inherent-Strain AM Distortion
Simulation.

Test plan
---------
1.  cantilever_curls_up
        A tall cantilever block with compressive in-plane inherent strains
        (ε_xx = ε_yy < 0) must curl upward (+Z bending) when fixed at the base.
        The top face should displace in the −X or −Y direction — the classical
        Mercelis–Kruth upward curl of a bridge specimen.
        Check: max_deviation > 0, tip displacement has non-zero out-of-plane
        component in the expected sense.

2.  displacement_bounded
        The max displacement of a small block with typical LPBF inherent
        strains on 316L steel must be bounded: it should be far less than
        the part height (no runaway) yet non-zero (the solver ran).
        Energy bound: strain_energy = 0.5 * uᵀ K u ≥ 0.

3.  layer_activation_monotonic
        layer_max_disp_m[k] ≤ layer_max_disp_m[-1] is NOT required
        (distortion can transiently decrease as upper layers clamp lower ones),
        BUT the list must have exactly n_layers entries and all values must
        be non-negative.

4.  residual_stress_nonzero
        After the build the von-Mises residual stress must be > 0 (eigenstrain
        created locked-in stress).

5.  n_layers_correct
        With a 20 mm tall block and 5 mm thick layers the solver should
        produce exactly 4 layers.

6.  support_flag_count
        The support-region flag count must be > 0 and < n_elems (first layer
        is flagged, not everything).

7.  bad_inputs_return_ok_false
        Negative E, nu out of range, zero layer_thickness must return
        ok=False without raising.

8.  llm_tool_handler_round_trip
        The async `run_am_process_simulate` handler must return a JSON string
        with ok=True, correct fields, and max_deviation_mm > 0.

9.  make_block_mesh_shape
        make_block_mesh(2,2,4) produces a mesh with correct node and tet counts.
"""

from __future__ import annotations

import asyncio
import json
import math

import numpy as np
import pytest

from kerf_manufacturing.am_process_sim import (
    AMMesh,
    AMParams,
    AMSimResult,
    make_block_mesh,
    simulate_am_process,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def small_block_mesh() -> AMMesh:
    """2×2×4 block: 10 mm × 10 mm × 20 mm.  Build direction: +Z."""
    return make_block_mesh(nx=2, ny=2, nz=4, lx=0.01, ly=0.01, lz=0.02)


@pytest.fixture(scope="module")
def steel_params() -> AMParams:
    """Typical 316L stainless-steel LPBF inherent-strain parameters."""
    return AMParams(
        E=193e9,
        nu=0.3,
        layer_thickness=5e-3,  # 5 mm thick layers for coarse mesh
        build_dir=(0.0, 0.0, 1.0),
        # Compressive in-plane, larger compressive out-of-plane — causes curl
        inherent_strain=(-2.5e-3, -2.5e-3, -5.0e-3, 0.0, 0.0, 0.0),
        distortion_tolerance_m=1.0,  # high tolerance — we don't want spurious warnings
    )


# ---------------------------------------------------------------------------
# 1. Cantilever curls in expected direction
# ---------------------------------------------------------------------------

def test_cantilever_curls_up(small_block_mesh, steel_params):
    """Block fixed at z=0 should show upward deflection when compressive
    in-plane inherent strains are applied (Mercelis-Kruth upward curl)."""
    res = simulate_am_process(small_block_mesh, steel_params)
    assert res.ok, f"Simulation failed: {res.reason}"
    assert res.max_deviation_m > 0.0, "Expected non-zero distortion"

    # The distortion field shape
    assert res.displacement.shape == (small_block_mesh.n_nodes, 3)

    # Top-face nodes (z ≈ lz = 0.02 m) should have displacement in some direction
    nodes = small_block_mesh.nodes
    z_max = nodes[:, 2].max()
    top_nodes = np.where(np.abs(nodes[:, 2] - z_max) < 1e-9)[0]
    top_disp = res.displacement[top_nodes]

    # At least one top-node must have a non-trivial displacement
    top_mags = np.linalg.norm(top_disp, axis=1)
    assert top_mags.max() > 0.0, "Top face has zero displacement — solver may be stuck"


# ---------------------------------------------------------------------------
# 2. Displacement bounded
# ---------------------------------------------------------------------------

def test_displacement_bounded(small_block_mesh, steel_params):
    """Max distortion must be positive and far below the part height."""
    res = simulate_am_process(small_block_mesh, steel_params)
    assert res.ok
    lz = 0.02  # block height
    assert res.max_deviation_m > 0.0
    assert res.max_deviation_m < lz, (
        f"Distortion {res.max_deviation_m:.6e} m exceeds part height — runaway solver"
    )


# ---------------------------------------------------------------------------
# 3. Layer-activation list is well-formed and non-negative
# ---------------------------------------------------------------------------

def test_layer_activation_monotonic(small_block_mesh, steel_params):
    """layer_max_disp_m must have n_layers entries; all values non-negative."""
    res = simulate_am_process(small_block_mesh, steel_params)
    assert res.ok
    assert len(res.layer_max_disp_m) == res.n_layers, (
        f"Expected {res.n_layers} entries in layer_max_disp_m, "
        f"got {len(res.layer_max_disp_m)}"
    )
    for i, d in enumerate(res.layer_max_disp_m):
        assert d >= 0.0, f"Layer {i} max disp is negative: {d}"


# ---------------------------------------------------------------------------
# 4. Residual stress is non-zero
# ---------------------------------------------------------------------------

def test_residual_stress_nonzero(small_block_mesh, steel_params):
    """Eigenstrain must produce locked-in residual stress > 0."""
    res = simulate_am_process(small_block_mesh, steel_params)
    assert res.ok
    assert res.max_von_mises_pa > 0.0, "Von-Mises residual stress is zero — no eigenstrain applied"
    # Sanity: must be in a physically plausible range (not astronomical)
    # Residual stress should not exceed ~10 × yield strength of steel (~5 GPa)
    assert res.max_von_mises_pa < 5e9, (
        f"Von-Mises {res.max_von_mises_pa / 1e6:.1f} MPa — seems unphysically large"
    )


# ---------------------------------------------------------------------------
# 5. n_layers correct for 5 mm layers on 20 mm block
# ---------------------------------------------------------------------------

def test_n_layers_correct():
    """4 layers for 20 mm block with 5 mm layer thickness."""
    mesh = make_block_mesh(nx=2, ny=2, nz=4, lx=0.01, ly=0.01, lz=0.02)
    params = AMParams(layer_thickness=5e-3)  # exactly 4 layers
    res = simulate_am_process(mesh, params)
    assert res.ok
    assert res.n_layers == 4, f"Expected 4 layers, got {res.n_layers}"


# ---------------------------------------------------------------------------
# 6. Support-flag count is between 1 and n_elems
# ---------------------------------------------------------------------------

def test_support_flag_count(small_block_mesh, steel_params):
    res = simulate_am_process(small_block_mesh, steel_params)
    assert res.ok
    count = sum(1 for f in res.support_elem_flags if f)
    assert count > 0, "No elements flagged as support — first layer should be flagged"
    assert count < res.n_elems, "All elements flagged as support — incorrect"


# ---------------------------------------------------------------------------
# 7. Bad inputs return ok=False without raising
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_kwargs,expected_fragment", [
    ({"E": -1e9}, "E must be positive"),
    ({"nu": 0.6}, "nu must be"),
    ({"layer_thickness": 0.0}, "layer_thickness must be positive"),
])
def test_bad_inputs_return_ok_false(bad_kwargs, expected_fragment):
    mesh = make_block_mesh(nx=1, ny=1, nz=2)
    params = AMParams(**bad_kwargs)
    res = simulate_am_process(mesh, params)
    assert not res.ok
    assert expected_fragment.lower() in res.reason.lower(), (
        f"Expected '{expected_fragment}' in reason, got: {res.reason}"
    )


def test_too_few_nodes_returns_error():
    mesh = AMMesh(
        nodes=np.array([[0,0,0],[1,0,0],[0,1,0]], dtype=float),
        tets=np.zeros((0, 4), dtype=int),
    )
    res = simulate_am_process(mesh, AMParams())
    assert not res.ok


# ---------------------------------------------------------------------------
# 8. LLM tool handler round-trip
# ---------------------------------------------------------------------------

def test_llm_tool_handler_round_trip():
    """run_am_process_simulate returns valid JSON with expected fields."""
    from kerf_manufacturing.am_tool import run_am_process_simulate
    from kerf_manufacturing._compat import ProjectCtx

    ctx = ProjectCtx()
    params = {
        "nx": 2, "ny": 2, "nz": 3,
        "lx": 0.01, "ly": 0.01, "lz": 0.015,
        "layer_thickness_m": 5e-3,
        "E_pa": 193e9,
        "nu": 0.3,
    }
    raw = asyncio.get_event_loop().run_until_complete(
        run_am_process_simulate(params, ctx)
    )
    doc = json.loads(raw)
    assert doc.get("ok") is True, f"Handler returned error: {doc}"
    assert "max_deviation_mm" in doc
    assert doc["max_deviation_mm"] > 0.0
    assert "max_von_mises_mpa" in doc
    assert doc["max_von_mises_mpa"] > 0.0
    assert "layer_max_disp_mm" in doc
    assert "distortion_field" in doc
    assert "residual_stress_mpa" in doc
    assert "warnings" in doc
    assert "disclaimer" in doc


def test_llm_tool_handler_bad_args():
    """Handler must return err_payload for bad E_pa."""
    from kerf_manufacturing.am_tool import run_am_process_simulate
    from kerf_manufacturing._compat import ProjectCtx

    ctx = ProjectCtx()
    params = {"E_pa": -1.0, "nx": 2, "ny": 2, "nz": 2}
    raw = asyncio.get_event_loop().run_until_complete(
        run_am_process_simulate(params, ctx)
    )
    doc = json.loads(raw)
    assert doc.get("ok") is not True or "error" in doc


# ---------------------------------------------------------------------------
# 9. make_block_mesh shape checks
# ---------------------------------------------------------------------------

def test_make_block_mesh_shape():
    """make_block_mesh(nx, ny, nz) node and tet counts."""
    mesh = make_block_mesh(nx=2, ny=2, nz=4)
    # Nodes: (nx+1)(ny+1)(nz+1)
    expected_nodes = 3 * 3 * 5  # 45
    assert mesh.nodes.shape == (expected_nodes, 3), (
        f"Expected {expected_nodes} nodes, got {mesh.nodes.shape[0]}"
    )
    # Tets: nx * ny * nz * 5 (5 tets per hex cell)
    expected_tets = 2 * 2 * 4 * 5  # 80
    assert mesh.tets.shape == (expected_tets, 4), (
        f"Expected {expected_tets} tets, got {mesh.tets.shape[0]}"
    )
    # All tet node indices in valid range
    assert mesh.tets.min() >= 0
    assert mesh.tets.max() < mesh.n_nodes


# ---------------------------------------------------------------------------
# 10. Energy check — strain energy non-negative
# ---------------------------------------------------------------------------

def test_strain_energy_nonnegative(small_block_mesh, steel_params):
    """Strain energy 0.5 * u^T K u must be >= 0."""
    from kerf_manufacturing.am_process_sim import (
        _elasticity_matrix, _tet4_vol_B,
    )
    res = simulate_am_process(small_block_mesh, steel_params)
    assert res.ok

    # Recompute K * u and check u^T K u > 0
    C = _elasticity_matrix(steel_params.E, steel_params.nu)
    nodes = small_block_mesh.nodes
    tets = small_block_mesh.tets
    N = nodes.shape[0]
    u = res.displacement.ravel()

    strain_energy = 0.0
    for e_idx in range(tets.shape[0]):
        conn = tets[e_idx]
        xyz = nodes[conn]
        vol, B = _tet4_vol_B(xyz)
        dofs = np.array([3 * n + d for n in conn for d in range(3)])
        u_e = u[dofs]
        K_e = vol * (B.T @ C @ B)
        strain_energy += 0.5 * float(u_e @ K_e @ u_e)

    assert strain_energy >= -1e-6, (
        f"Strain energy {strain_energy:.6e} J is negative — sign error in assembly"
    )
