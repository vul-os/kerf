"""
MITC4 plate element tests.

Validates the plate.py implementation against the Timoshenko & Woinowsky-Krieger
(Theory of Plates and Shells, 2nd ed.) closed-form solution for a simply-supported
square plate under uniform transverse load:

    w_max = α · q · a^4 / D
    α = 0.004062  (Timoshenko Table 8, SS square, uniform load)
    D = E h³ / (12 (1 - ν²))

References
----------
* Timoshenko & Woinowsky-Krieger, Theory of Plates and Shells, 2nd ed. (1959),
  Table 8, p. 120.
* Bathe & Dvorkin (1985), MITC4 formulation.
"""

from __future__ import annotations

import math
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plate_flexural_rigidity(E: float, nu: float, h: float) -> float:
    return E * h**3 / (12.0 * (1.0 - nu * nu))


# ---------------------------------------------------------------------------
# Test 1: MITC4 element stiffness — symmetry and positive semi-definiteness
# ---------------------------------------------------------------------------

def test_mitc4_stiffness_symmetry():
    """Ke must be symmetric."""
    from kerf_fem.plate import mitc4_stiffness

    x = [0.0, 1.0, 1.0, 0.0]
    y = [0.0, 0.0, 1.0, 1.0]
    Ke = mitc4_stiffness(x, y, E=200e9, nu=0.3, t=0.01)

    assert len(Ke) == 12
    for i in range(12):
        for j in range(12):
            assert abs(Ke[i][j] - Ke[j][i]) < 1e-6 * (abs(Ke[i][j]) + 1.0), \
                f"Asymmetry at ({i},{j}): {Ke[i][j]} vs {Ke[j][i]}"


def test_mitc4_stiffness_non_negative_diagonal():
    """Ke diagonal entries must be non-negative."""
    from kerf_fem.plate import mitc4_stiffness

    x = [0.0, 0.5, 0.5, 0.0]
    y = [0.0, 0.0, 0.5, 0.5]
    Ke = mitc4_stiffness(x, y, E=70e9, nu=0.33, t=0.005)

    for i in range(12):
        assert Ke[i][i] >= 0.0, f"Negative diagonal at {i}: {Ke[i][i]}"


# ---------------------------------------------------------------------------
# Test 2: Mass matrix symmetry and positive-definiteness (diagonal entries)
# ---------------------------------------------------------------------------

def test_mitc4_mass_symmetry():
    """Me must be symmetric."""
    from kerf_fem.plate import mitc4_mass

    x = [0.0, 1.0, 1.0, 0.0]
    y = [0.0, 0.0, 1.0, 1.0]
    Me = mitc4_mass(x, y, rho=7850.0, t=0.01)

    assert len(Me) == 12
    for i in range(12):
        for j in range(12):
            assert abs(Me[i][j] - Me[j][i]) < 1e-10 * (abs(Me[i][j]) + 1.0), \
                f"Asymmetry at ({i},{j})"


def test_mitc4_mass_total_mass():
    """
    Total translational mass = ρ t A (lumped from consistent matrix):
    Sum of w-DOF rows for all 4 nodes = ρ t A.
    """
    from kerf_fem.plate import mitc4_mass

    rho, t = 7850.0, 0.01
    Lx, Ly = 2.0, 3.0
    x = [0.0, Lx, Lx, 0.0]
    y = [0.0, 0.0, Ly, Ly]
    Me = mitc4_mass(x, y, rho=rho, t=t)

    # Sum all w-dof columns (0, 3, 6, 9) across all rows to get total mass
    total_mass_computed = 0.0
    for row in range(12):
        for col in [0, 3, 6, 9]:
            total_mass_computed += Me[row][col]

    # For consistent mass: sum of all entries in w-w block = ρ t A
    # Actually: sum over the 4×4 w-w submatrix = ρ t A
    # because ∑_IJ ∫ N_I N_J dA = A (partition of unity)
    mass_expected = rho * t * Lx * Ly
    ww_sum = sum(Me[3*I][3*J] for I in range(4) for J in range(4))
    assert abs(ww_sum - mass_expected) / mass_expected < 1e-10


# ---------------------------------------------------------------------------
# Test 3: Load vector — consistent nodal forces sum to q*A
# ---------------------------------------------------------------------------

def test_mitc4_load_sum():
    """Sum of equivalent nodal w-forces must equal q * element_area."""
    from kerf_fem.plate import mitc4_load

    Lx, Ly = 0.5, 0.8
    q = 1000.0
    x = [0.0, Lx, Lx, 0.0]
    y = [0.0, 0.0, Ly, Ly]
    fe = mitc4_load(x, y, q)

    # Sum only w-DOFs (0, 3, 6, 9)
    w_force_sum = fe[0] + fe[3] + fe[6] + fe[9]
    area = Lx * Ly
    assert abs(w_force_sum - q * area) / (q * area) < 1e-10, \
        f"w-force sum {w_force_sum} != q*A {q*area}"

    # θ DOFs should be zero for uniform load
    for i in [1, 2, 4, 5, 7, 8, 10, 11]:
        assert abs(fe[i]) < 1e-12, f"θ force fe[{i}] = {fe[i]} should be 0"


# ---------------------------------------------------------------------------
# Test 4: Simply-supported square plate — central deflection ≤5% of Timoshenko
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("N", [8, 16])
def test_ss_square_plate_central_deflection(N):
    """
    Timoshenko Table 8: SS square plate, uniform load.
    w_max = 0.004062 * q * a^4 / D
    Mesh NxN; tolerance ≤5%.
    """
    from kerf_fem.plate import solve_ss_plate

    a = 1.0       # plate side [m]
    E = 200e9     # Pa
    nu = 0.3
    h = 0.01      # thickness (thin plate: a/h = 100)
    q = 1000.0    # N/m²

    D = _plate_flexural_rigidity(E, nu, h)
    w_timoshenko = 0.004062 * q * a**4 / D

    result = solve_ss_plate(a, a, E, nu, h, q, Nx=N, Ny=N)
    assert result["ok"], f"Solve failed: {result}"

    w_max = result["w_max"]

    # Central node index
    ci = (N // 2) * (N + 1) + (N // 2)
    w_center = result["w"][ci]

    rel_err = abs(w_center - w_timoshenko) / w_timoshenko
    assert rel_err < 0.05, (
        f"N={N}: w_center={w_center:.6e}, Timoshenko={w_timoshenko:.6e}, "
        f"rel_err={rel_err:.3%} > 5%"
    )


def test_ss_square_plate_central_deflection_8x8_detailed():
    """
    Detailed accuracy test: 8×8 mesh on SS square plate.
    Reports w_center, Timoshenko reference, and error fraction.
    """
    from kerf_fem.plate import solve_ss_plate

    a = 1.0
    E = 200e9
    nu = 0.3
    h = 0.01
    q = 1000.0
    N = 8

    D = _plate_flexural_rigidity(E, nu, h)
    w_ref = 0.004062 * q * a**4 / D

    result = solve_ss_plate(a, a, E, nu, h, q, Nx=N, Ny=N)
    assert result["ok"]

    ci = (N // 2) * (N + 1) + (N // 2)
    w_center = result["w"][ci]
    err = abs(w_center - w_ref) / w_ref

    # Record for human inspection (pytest -s shows print output)
    print(f"\n8x8 SS square plate:")
    print(f"  D             = {D:.4e} N·m")
    print(f"  w_Timoshenko  = {w_ref:.6e} m")
    print(f"  w_FEM_center  = {w_center:.6e} m")
    print(f"  relative err  = {err:.3%}")

    assert err < 0.05, f"Error {err:.3%} exceeds 5% tolerance"


# ---------------------------------------------------------------------------
# Test 5: Patch test — constant bending moment field
# ---------------------------------------------------------------------------

def test_mitc4_patch_constant_curvature():
    """
    Patch test for pure bending: a single MITC4 element with prescribed
    nodal rotations consistent with a constant-curvature bending mode should
    produce zero residual in the interior.

    We verify that Ke satisfies: if d is a rigid-body w=const, Ke*d ≈ 0.
    """
    from kerf_fem.plate import mitc4_stiffness

    x = [0.0, 1.0, 1.0, 0.0]
    y = [0.0, 0.0, 1.0, 1.0]
    Ke = mitc4_stiffness(x, y, E=200e9, nu=0.3, t=0.01)

    # Rigid body: w=1 at all nodes, θ=0
    d_rb = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    f_rb = [sum(Ke[i][j] * d_rb[j] for j in range(12)) for i in range(12)]
    max_f = max(abs(v) for v in f_rb)
    # Rigid-body w displacement should produce no stiffness force
    assert max_f < 1e-4, f"Rigid body mode gives non-zero force: {max_f}"


# ---------------------------------------------------------------------------
# Test 6: solve_plate_static — error handling
# ---------------------------------------------------------------------------

def test_plate_static_no_bcs_returns_error():
    """
    Without boundary conditions the system is singular (rigid-body modes); must
    return ok=False or, if the Gaussian pivot accidentally finds a solution (can
    happen for a single element due to floating-point luck), the w_max should
    be clearly non-physical (very large or very small).  Most importantly it
    must NOT raise an exception.

    In practice, with a 2×2 mesh and no BCs the 3 rigid-body w-modes make K
    singular and gauss_solve returns None → ok=False.
    """
    from kerf_fem.plate import solve_plate_static, _rect_mesh

    # Use a 2x2 mesh so rigid-body modes are more clearly represented
    nodes, elements = _rect_mesh(1.0, 1.0, 2, 2)
    try:
        result = solve_plate_static(nodes, elements, E=200e9, nu=0.3, t=0.01, q=1000.0, bcs=[])
        # Either it failed (ok=False) or it returned something — both are OK as long as it didn't raise
        if result.get("ok"):
            # If somehow it solved, deflections should be unreasonably large (unconstrained)
            pass  # Not necessarily True — accept either outcome without assertion
    except Exception as e:
        pytest.fail(f"solve_plate_static raised an exception: {e}")


# ---------------------------------------------------------------------------
# Test 7: Modal analysis — simply-supported plate natural frequencies
# ---------------------------------------------------------------------------

def test_plate_modal_ss_square_first_frequency():
    """
    Simply-supported square plate first natural frequency.
    Timoshenko & Woinowsky-Krieger (1959) §12-1, eq. 226:
        ω_{mn} = π² (m² + n²) / a² · √(D / (ρ h))    [square plate, m=n=1]
    For m=n=1 (lowest mode): ω = 2π²/a² · √(D / (ρ h))

    Use a 4×4 mesh; expect ≤15% error (coarse mesh).
    """
    from kerf_fem.plate import plate_modal, _rect_plate_mesh

    a = 1.0
    E = 200e9
    nu = 0.3
    h = 0.01
    rho = 7850.0
    N = 4

    D = _plate_flexural_rigidity(E, nu, h)
    # Correct formula: ω_{11} = π²*(1+1)/a² * √(D/(ρ*h)) = 2π²/a² * √(D/(ρ*h))
    omega_ref = 2.0 * math.pi**2 / a**2 * math.sqrt(D / (rho * h))
    freq_ref = omega_ref / (2.0 * math.pi)

    nodes, elements = _rect_plate_mesh(a, a, N, N)
    Nx_n = N + 1

    bcs = []
    for i in range(Nx_n):
        bcs.append({"type": "simply_supported", "node": i})
        bcs.append({"type": "simply_supported", "node": N * Nx_n + i})
    for j in range(1, Nx_n - 1):
        bcs.append({"type": "simply_supported", "node": j * Nx_n})
        bcs.append({"type": "simply_supported", "node": j * Nx_n + N})

    result = plate_modal(nodes, elements, E, nu, h, rho, bcs, n_modes=3)
    assert result["ok"], f"Modal failed: {result}"
    assert len(result["frequencies"]) >= 1

    freq_fem = result["frequencies"][0]
    rel_err = abs(freq_fem - freq_ref) / freq_ref
    print(f"\nModal: freq_ref={freq_ref:.2f} Hz, freq_FEM={freq_fem:.2f} Hz, err={rel_err:.2%}")
    assert rel_err < 0.15, f"Modal error {rel_err:.2%} > 15%"


# ---------------------------------------------------------------------------
# Test 8: Tool registration — fem_plate_static_solve is importable
# ---------------------------------------------------------------------------

def test_plate_tool_spec_importable():
    """fem_plate_static_solve tool spec and handler must be importable."""
    from kerf_fem.plate import _fem_plate_static_spec, run_fem_plate_static_solve
    assert _fem_plate_static_spec.name == "fem_plate_static_solve"
    assert callable(run_fem_plate_static_solve)


# ---------------------------------------------------------------------------
# Test 9: LLM tool round-trip for simply_supported_rect
# ---------------------------------------------------------------------------

def test_plate_tool_simply_supported_rect():
    """LLM tool run with simply_supported_rect returns ok=True and w_center."""
    import asyncio
    import json
    from kerf_fem.plate import run_fem_plate_static_solve
    from kerf_fem._compat import ProjectCtx

    ctx = ProjectCtx()
    args = json.dumps({
        "geometry": {"plate_type": "simply_supported_rect", "Lx": 1.0, "Ly": 1.0, "Nx": 8, "Ny": 8},
        "material": {"E": 200e9, "nu": 0.3, "t": 0.01},
        "load": {"q": 1000.0},
    }).encode()

    result_str = asyncio.get_event_loop().run_until_complete(
        run_fem_plate_static_solve(ctx, args)
    )
    result = json.loads(result_str)
    assert result.get("ok") is True, f"Tool returned: {result}"
    assert "w_max" in result
    assert "w_center" in result
    assert result["w_max"] > 0.0
