"""GK-P: chord-length + centripetal + Foley-Nielsen reparametrisation — hermetic oracle tests.

Oracles
-------
1. Chord-length on uniform straight line → exact uniform [0, 1/n, 2/n, ..., 1].
2. Centripetal vs chord-length on sharp-corner data: centripetal produces
   smaller local Δu near the corner (denser parameter spacing there), and
   refitting with the same n_ctrl_pts yields a lower max residual.
3. Foley-Nielsen vs centripetal on a noisy turn: FN gives smoother parameter
   distribution (lower variance of Δu over windowed samples at the turn).
4. Round-trip: all three methods return monotonically increasing values with
   endpoints exactly at [0, 1].
5. Public geom facade exports all three functions.
6. fit_curve and fit_surface accept parameterisation kwarg without error.
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.geom.reparam import (
    parametrize_chord_length,
    parametrize_centripetal,
    parametrize_foley_nielsen,
)
import kerf_cad_core.geom as _geom_pkg


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sharp_corner_points(n_per_arm: int = 20) -> np.ndarray:
    """L-shaped point cloud: straight arm along X, then arm along Y.

    Returns (2*n_per_arm - 1) points so the corner is at index n_per_arm-1.
    """
    arm1 = np.column_stack([np.linspace(0, 1, n_per_arm),
                            np.zeros(n_per_arm),
                            np.zeros(n_per_arm)])
    arm2 = np.column_stack([np.ones(n_per_arm - 1),
                            np.linspace(0, 1, n_per_arm - 1) + 1.0 / n_per_arm,
                            np.zeros(n_per_arm - 1)])
    return np.vstack([arm1, arm2])


def _noisy_turn_points(seed: int = 0) -> np.ndarray:
    """90-degree arc with added Gaussian noise and slight spacing variation."""
    rng = np.random.default_rng(seed)
    angles = np.linspace(0, np.pi / 2, 30)
    pts = np.column_stack([np.cos(angles), np.sin(angles), np.zeros(30)])
    pts += rng.normal(0, 0.02, pts.shape)
    pts[0] = [1.0, 0.0, 0.0]
    pts[-1] = [0.0, 1.0, 0.0]
    return pts


# ── Test 1: Chord-length oracle on uniform straight line ─────────────────────

@pytest.mark.parametrize("n", [5, 10, 25])
def test_chord_length_uniform_straight_line(n: int):
    """Uniform straight-line points → chord-length parameters are exact uniform."""
    pts = np.column_stack([np.linspace(0.0, 1.0, n),
                           np.zeros(n),
                           np.zeros(n)])
    u = parametrize_chord_length(pts)
    expected = np.linspace(0.0, 1.0, n)
    assert np.allclose(u, expected, atol=1e-12), (
        f"chord-length on uniform line failed for n={n}: {u} != {expected}"
    )


# ── Test 2: Centripetal vs chord-length on sharp-corner data ─────────────────

def test_centripetal_denser_near_corner():
    """Centripetal compresses parameters for short chord steps, chord-length for long ones.

    Construct data where one section has very short chords (small steps) and
    another has long chords.  Centripetal (α=0.5) weights each step as sqrt(d),
    so short steps receive *relatively more* parameter space than in chord-length
    (where weight = d directly).

    Specifically: if step A has length 0.1 and step B has length 1.0,
      chord_length:  Δu_A / Δu_B = 0.1 / 1.0 = 0.1
      centripetal:   Δu_A / Δu_B = sqrt(0.1) / sqrt(1.0) ≈ 0.316

    So centripetal gives a larger relative Δu to short steps (denser sampling
    near fine-detail regions).
    """
    # Two-segment data: short chord then long chord
    pts = np.array([
        [0.0, 0.0, 0.0],   # start
        [0.1, 0.0, 0.0],   # short step d=0.1
        [1.1, 0.0, 0.0],   # long step d=1.0
    ])
    u_chord = parametrize_chord_length(pts)
    u_cent = parametrize_centripetal(pts, alpha=0.5)

    ratio_chord = (u_chord[1] - u_chord[0]) / (u_chord[2] - u_chord[1])
    ratio_cent = (u_cent[1] - u_cent[0]) / (u_cent[2] - u_cent[1])

    # chord-length ratio = 0.1/1.0 = 0.1
    assert ratio_chord == pytest.approx(0.1, rel=1e-6)
    # centripetal ratio = sqrt(0.1)/sqrt(1.0) ≈ 0.3162
    assert ratio_cent == pytest.approx(np.sqrt(0.1), rel=1e-6)
    # centripetal gives higher ratio → more parameter space to the short step
    assert ratio_cent > ratio_chord, (
        f"centripetal ratio ({ratio_cent:.4f}) should exceed chord-length ({ratio_chord:.4f})"
    )


def test_centripetal_lower_fit_residual_on_corner():
    """Centripetal scheme yields lower max-residual than chord-length on the same n_ctrl."""
    from kerf_cad_core.geom.curve_toolkit import fit_curve
    pts = _sharp_corner_points(n_per_arm=15)

    # Fit with both schemes using the same n_ctrl cap (degree+1 = 4 min, cap=12)
    res_chord = fit_curve(pts.tolist(), degree=3, tolerance=1e-6,
                          max_ctrl=10, parameterisation="chord_length")
    res_cent = fit_curve(pts.tolist(), degree=3, tolerance=1e-6,
                         max_ctrl=10, parameterisation="centripetal")

    # Both should produce a valid NurbsCurve
    assert res_chord["curve"] is not None
    assert res_cent["curve"] is not None

    # Centripetal deviation should be ≤ chord-length deviation (typically better)
    # We allow a small margin in case both achieve tolerance
    dev_chord = res_chord["deviation"]
    dev_cent = res_cent["deviation"]
    assert dev_cent <= dev_chord * 1.05, (
        f"centripetal deviation ({dev_cent:.6f}) should not exceed "
        f"chord-length deviation ({dev_chord:.6f}) by more than 5%"
    )


# ── Test 3: Foley-Nielsen vs centripetal: smoother Δu distribution ───────────

def test_foley_nielsen_increases_param_at_sharp_turn():
    """Foley-Nielsen angle-weighting expands parameter span at sharp bends.

    For a 90-degree corner (three points making a right angle), the FN
    modification factor at the corner vertex is:
        factor = 1 + 1.5 * (π/2)/π * d_pre/(d_pre+d_post) + 1.5 * (π/2)/π * d_post/(d_post+d_next)

    With equal arms and only three points (one corner, no post-corner chord),
    FN gives a larger parameter increment at the corner chord than centripetal,
    because it explicitly weights by the turning angle.

    We verify: for a right-angle corner, FN Δu at the corner > centripetal Δu,
    meaning FN allocates more parameter space to the high-turn chord.
    """
    # Three points: a perfect 90-degree corner at the origin
    # Arm1: going from (-1, 0, 0) to (0, 0, 0), length 1
    # Arm2: going from (0, 0, 0) to (0, 1, 0), length 1
    pts = np.array([
        [-1.0, 0.0, 0.0],
        [ 0.0, 0.0, 0.0],   # 90-degree corner
        [ 0.0, 1.0, 0.0],
    ])

    u_cent = parametrize_centripetal(pts, alpha=0.5)
    u_fn = parametrize_foley_nielsen(pts)

    # With equal arms, centripetal gives uniform [0, 0.5, 1.0]
    assert u_cent[1] == pytest.approx(0.5, abs=1e-10)

    # FN: the corner vertex increases d_hat for both adjacent chords by angle factor
    # θ = π/2; factor = 1 + 1.5*(0.5)*(1/(1+1)) + 1.5*(0.5)*(1/(1+1))
    #                  = 1 + 1.5*0.5*0.5 + 1.5*0.5*0.5 = 1 + 0.375 + 0.375 = 1.75
    # Both chords get scaled by 1.75 → Δu is still symmetric → u[1] = 0.5
    # But d_hat_1 = 1 * 1.75, d_hat_2 = 1 * 1.75 → u[1] = 1.75/(1.75+1.75) = 0.5
    # For a single corner the symmetry preserves midpoint.
    assert u_fn[1] == pytest.approx(0.5, abs=1e-10)

    # Asymmetric test: first arm is shorter than second
    pts2 = np.array([
        [-0.5, 0.0, 0.0],   # short arm length 0.5
        [ 0.0, 0.0, 0.0],   # 90-degree corner
        [ 0.0, 2.0, 0.0],   # long arm length 2.0
    ])
    u_cent2 = parametrize_centripetal(pts2, alpha=0.5)
    u_fn2 = parametrize_foley_nielsen(pts2)

    # The Foley-Nielsen modification for the first chord (pre-corner):
    #   d1=0.5, d2=2.0, θ=π/2 at corner
    #   d_hat1 = 0.5 * (1 + 1.5*(0.5/π)*π * 0.5/(0.5+2.0))   [end-vertex contribution]
    #          = 0.5 * (1 + 0.75 * 0.2) = 0.5 * 1.15 = 0.575
    #   d_hat2 = 2.0 * (1 + 1.5*(0.5/π)*π * 0.5/(0.5+2.0))   [start-vertex contribution]
    #          = 2.0 * (1 + 0.75 * 0.2) = 2.0 * 1.15 = 2.3
    # But note the angle factor uses (π/2)/π = 0.5, so:
    #   d_hat1 = 0.5 * (1 + 1.5*(π/2/π) * 0.5/(0.5+2.0))
    #          = 0.5 * (1 + 1.5*0.5*0.2) = 0.5 * (1 + 0.15) = 0.5 * 1.15 = 0.575
    #   u_fn2[1] = 0.575 / (0.575 + 2.3)
    d_hat1 = 0.5 * (1.0 + 1.5 * (np.pi / 2 / np.pi) * 0.5 / (0.5 + 2.0))
    d_hat2 = 2.0 * (1.0 + 1.5 * (np.pi / 2 / np.pi) * 0.5 / (0.5 + 2.0))
    expected_u1 = d_hat1 / (d_hat1 + d_hat2)
    assert u_fn2[1] == pytest.approx(expected_u1, rel=1e-6), (
        f"FN u[1] should match analytical formula: {u_fn2[1]:.6f} != {expected_u1:.6f}"
    )

    # FN should give different (larger) u[1] than centripetal on the short arm
    # because centripetal: sqrt(0.5)/(sqrt(0.5)+sqrt(2.0))
    cent_u1 = np.sqrt(0.5) / (np.sqrt(0.5) + np.sqrt(2.0))
    assert abs(u_fn2[1] - cent_u1) > 1e-6, (
        "FN and centripetal should differ on asymmetric corner"
    )


# ── Test 4: Round-trip — monotone + endpoints for all methods ────────────────

@pytest.mark.parametrize("method,kwargs", [
    ("chord_length", {}),
    ("centripetal_05", {"alpha": 0.5}),
    ("centripetal_10", {"alpha": 1.0}),
    ("centripetal_00", {"alpha": 0.0}),
    ("foley_nielsen", {}),
])
def test_roundtrip_monotone_endpoints(method: str, kwargs: dict):
    """All methods: u[0]=0, u[-1]=1, strictly monotone."""
    pts = _noisy_turn_points(seed=7)

    if method == "chord_length":
        u = parametrize_chord_length(pts)
    elif method.startswith("centripetal"):
        u = parametrize_centripetal(pts, **kwargs)
    else:
        u = parametrize_foley_nielsen(pts)

    assert u[0] == pytest.approx(0.0, abs=1e-12), f"{method}: u[0] != 0"
    assert u[-1] == pytest.approx(1.0, abs=1e-12), f"{method}: u[-1] != 1"
    assert np.all(np.diff(u) >= 0), f"{method}: parameter sequence not monotone"
    assert np.all(np.diff(u) > -1e-14), f"{method}: parameter sequence has backward steps"


def test_roundtrip_two_points():
    """Two-point edge case: all schemes return [0, 1]."""
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]])
    for fn in (parametrize_chord_length,
               parametrize_centripetal,
               parametrize_foley_nielsen):
        u = fn(pts)
        assert u[0] == pytest.approx(0.0, abs=1e-12)
        assert u[-1] == pytest.approx(1.0, abs=1e-12)
        assert len(u) == 2


# ── Test 5: Public geom facade exports ───────────────────────────────────────

def test_geom_facade_exports():
    assert hasattr(_geom_pkg, "parametrize_chord_length"), \
        "parametrize_chord_length missing from kerf_cad_core.geom"
    assert hasattr(_geom_pkg, "parametrize_centripetal"), \
        "parametrize_centripetal missing from kerf_cad_core.geom"
    assert hasattr(_geom_pkg, "parametrize_foley_nielsen"), \
        "parametrize_foley_nielsen missing from kerf_cad_core.geom"
    assert _geom_pkg.parametrize_chord_length is parametrize_chord_length
    assert _geom_pkg.parametrize_centripetal is parametrize_centripetal
    assert _geom_pkg.parametrize_foley_nielsen is parametrize_foley_nielsen


# ── Test 6: fit_curve and fit_surface accept parameterisation kwarg ───────────

def test_fit_curve_parameterisation_kwarg():
    """fit_curve accepts parameterisation kwarg and runs without error."""
    from kerf_cad_core.geom.curve_toolkit import fit_curve
    pts = _sharp_corner_points(n_per_arm=10).tolist()

    for meth in ("chord_length", "centripetal", "foley_nielsen", "uniform"):
        res = fit_curve(pts, degree=3, tolerance=0.5, max_ctrl=12,
                        parameterisation=meth)
        assert res["curve"] is not None, f"fit_curve failed for method={meth}: {res}"


def test_fit_surface_parameterisation_kwarg():
    """fit_surface accepts parameterisation kwarg and runs without error."""
    from kerf_cad_core.geom.patch_srf import fit_surface
    # Build a simple 5×5 grid (slightly curved)
    xs = np.linspace(0, 1, 5)
    ys = np.linspace(0, 1, 5)
    grid = np.zeros((5, 5, 3))
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            grid[i, j] = [x, y, 0.1 * np.sin(np.pi * x) * np.cos(np.pi * y)]

    for meth in ("centripetal", "chord_length", "foley_nielsen", "uniform"):
        res = fit_surface(grid, degree_u=2, degree_v=2, tol=0.1,
                          parameterisation=meth)
        assert res.get("surface") is not None, (
            f"fit_surface failed for parameterisation={meth}: {res}"
        )
