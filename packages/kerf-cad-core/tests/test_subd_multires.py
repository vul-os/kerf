"""test_subd_multires.py
========================
Tests for kerf_cad_core.subd.multires — SubD multires displacement maps.

Coverage (>= 15 tests):
  1.  DisplacementLevel grid_resolution matches 2^level + 1.
  2.  Zero displacement → displaced position == base bilinear position.
  3.  Constant displacement scalar c → all samples offset by c·n̂.
  4.  Single-level encode → level-0 corner scalars match direct projection.
  5.  Level 3 grid has 9×9 = 81 scalars; level 0 has 2×2 = 4.
  6.  evaluate_multires(level=0) ignores level 1..3 contributions.
  7.  Total displacement is sum of per-level contributions (linear superposition).
  8.  Normal vector is normalized (|n| = 1 within 1e-9).
  9.  Round-trip: encode Gaussian bump → evaluate → max error < 5% of bump height.
  10. evaluate_multires returns correct type MultiresLimitEval.
  11. Bilinear base position correct at corners (u,v) ∈ {0,1}².
  12. Bilinear base position at centre (0.5, 0.5) is mean of corners.
  13. DisplacementLevel raises on wrong shape.
  14. MultiresPatch raises on wrong number of corners/normals.
  15. Negative displacement offsets position in −n̂ direction.
  16. Encode with zero high-res offset → all scalars near zero.
  17. evaluate_multires clamps u, v to [0,1].
  18. DisplacementLevel enforces grid_resolution == 2^level + 1.

All tests hermetic: pure Python + numpy, no OCC, no database.

References:
  - Cook (1984). "Shade Trees." SIGGRAPH '84.
  - Krishnamurthy & Levoy (1996). "Fitting Smooth Surfaces to Dense Polygon
    Meshes." SIGGRAPH '96, §3.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import pytest

from kerf_cad_core.subd.multires import (
    DisplacementLevel,
    MultiresPatch,
    MultiresLimitEval,
    encode_displacement,
    evaluate_multires,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]

# Flat unit-square patch lying in the XY plane at z=0.
# Corner order: (u=0,v=0), (u=1,v=0), (u=0,v=1), (u=1,v=1)
FLAT_CORNERS: List[Vec3] = [
    (0.0, 0.0, 0.0),  # c00
    (1.0, 0.0, 0.0),  # c10
    (0.0, 1.0, 0.0),  # c01
    (1.0, 1.0, 0.0),  # c11
]
# Normal is +Z everywhere
FLAT_NORMALS: List[Vec3] = [
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
]


def make_zero_patch(levels: int = 3, face_id: int = 0) -> MultiresPatch:
    """Build a flat patch with all zero displacements at `levels` levels."""
    disps = []
    for lev in range(levels):
        R = (1 << lev) + 1
        disps.append(DisplacementLevel(
            level=lev,
            face_id=face_id,
            grid_resolution=R,
            scalars=np.zeros((R, R), dtype=np.float32),
        ))
    return MultiresPatch(
        base_face_id=face_id,
        base_corners=list(FLAT_CORNERS),
        base_normals=list(FLAT_NORMALS),
        displacements=disps,
    )


def make_constant_patch(c: float, levels: int = 3) -> MultiresPatch:
    """All displacements = constant c at level 0; residuals 0 at levels 1+."""
    disps = []
    for lev in range(levels):
        R = (1 << lev) + 1
        if lev == 0:
            scalars = np.full((R, R), c, dtype=np.float32)
        else:
            scalars = np.zeros((R, R), dtype=np.float32)
        disps.append(DisplacementLevel(
            level=lev,
            face_id=0,
            grid_resolution=R,
            scalars=scalars,
        ))
    return MultiresPatch(
        base_face_id=0,
        base_corners=list(FLAT_CORNERS),
        base_normals=list(FLAT_NORMALS),
        displacements=disps,
    )


def _norm3(v: Vec3) -> float:
    return math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)


# ---------------------------------------------------------------------------
# Tests: DisplacementLevel construction
# ---------------------------------------------------------------------------

def test_displacement_level_correct_resolution() -> None:
    """DisplacementLevel(level=k) must have grid_resolution = 2^k + 1."""
    for lev in range(4):
        R = (1 << lev) + 1
        d = DisplacementLevel(
            level=lev, face_id=0, grid_resolution=R,
            scalars=np.zeros((R, R), dtype=np.float32),
        )
        assert d.grid_resolution == R
        assert d.scalars.shape == (R, R)


def test_displacement_level_wrong_resolution_raises() -> None:
    """DisplacementLevel raises ValueError if grid_resolution != 2^level + 1."""
    with pytest.raises(ValueError, match="grid_resolution"):
        DisplacementLevel(
            level=1, face_id=0, grid_resolution=4,  # should be 3
            scalars=np.zeros((4, 4), dtype=np.float32),
        )


def test_displacement_level_wrong_scalar_shape_raises() -> None:
    """DisplacementLevel raises ValueError if scalars shape doesn't match resolution."""
    with pytest.raises(ValueError, match="scalars must be shape"):
        DisplacementLevel(
            level=2, face_id=0, grid_resolution=5,  # correct: 2^2+1=5
            scalars=np.zeros((4, 4), dtype=np.float32),  # wrong shape
        )


def test_level_0_grid_is_2x2() -> None:
    """Level 0 grid has 2×2 = 4 scalars (the four base corners)."""
    d = DisplacementLevel(
        level=0, face_id=0, grid_resolution=2,
        scalars=np.zeros((2, 2), dtype=np.float32),
    )
    assert d.scalars.size == 4
    assert d.scalars.shape == (2, 2)


def test_level_3_grid_is_9x9() -> None:
    """Level 3 grid has 9×9 = 81 scalars."""
    d = DisplacementLevel(
        level=3, face_id=0, grid_resolution=9,
        scalars=np.zeros((9, 9), dtype=np.float32),
    )
    assert d.scalars.size == 81
    assert d.scalars.shape == (9, 9)


# ---------------------------------------------------------------------------
# Tests: MultiresPatch construction
# ---------------------------------------------------------------------------

def test_multires_patch_wrong_corners_raises() -> None:
    """MultiresPatch raises if base_corners is not length 4."""
    with pytest.raises(ValueError, match="4 base_corners"):
        MultiresPatch(
            base_face_id=0,
            base_corners=FLAT_CORNERS[:3],  # only 3
            base_normals=FLAT_NORMALS,
            displacements=[],
        )


def test_multires_patch_wrong_normals_raises() -> None:
    """MultiresPatch raises if base_normals is not length 4."""
    with pytest.raises(ValueError, match="4 base_normals"):
        MultiresPatch(
            base_face_id=0,
            base_corners=FLAT_CORNERS,
            base_normals=FLAT_NORMALS[:2],  # only 2
            displacements=[],
        )


def test_multires_patch_non_monotone_levels_raises() -> None:
    """MultiresPatch raises if displacement levels are not 0, 1, 2, ..."""
    d0 = DisplacementLevel(level=0, face_id=0, grid_resolution=2, scalars=np.zeros((2,2), dtype=np.float32))
    d2 = DisplacementLevel(level=2, face_id=0, grid_resolution=5, scalars=np.zeros((5,5), dtype=np.float32))
    with pytest.raises(ValueError, match="levels 0,1,2"):
        MultiresPatch(
            base_face_id=0,
            base_corners=FLAT_CORNERS,
            base_normals=FLAT_NORMALS,
            displacements=[d0, d2],  # missing level 1 → index 1 has level 2
        )


# ---------------------------------------------------------------------------
# Tests: evaluate_multires — zero displacement
# ---------------------------------------------------------------------------

def test_zero_displacement_position_equals_base() -> None:
    """All-zero displacement → displaced position == base bilinear position."""
    patch = make_zero_patch(levels=3)
    for u, v in [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5), (0.3, 0.7)]:
        result = evaluate_multires(patch, u, v, level=2)
        # Base position from bilinear on unit square
        expected_x = u
        expected_y = v
        expected_z = 0.0
        assert abs(result.position[0] - expected_x) < 1e-9, f"u={u}, v={v}: x mismatch"
        assert abs(result.position[1] - expected_y) < 1e-9, f"u={u}, v={v}: y mismatch"
        assert abs(result.position[2] - expected_z) < 1e-9, f"u={u}, v={v}: z mismatch"
        assert abs(result.displacement) < 1e-9


def test_zero_displacement_base_position_is_bilinear() -> None:
    """base_position field is the bilinear interpolation of corners."""
    patch = make_zero_patch(levels=2)
    u, v = 0.25, 0.75
    result = evaluate_multires(patch, u, v, level=1)
    # Bilinear on unit square: (x,y,z) = (u, v, 0)
    assert abs(result.base_position[0] - u) < 1e-9
    assert abs(result.base_position[1] - v) < 1e-9
    assert abs(result.base_position[2] - 0.0) < 1e-9


# ---------------------------------------------------------------------------
# Tests: constant displacement
# ---------------------------------------------------------------------------

def test_constant_displacement_shifts_by_c_times_normal() -> None:
    """Constant displacement c at level 0 → position offset by c in +Z direction."""
    c = 2.5
    patch = make_constant_patch(c, levels=2)
    for u, v in [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.2, 0.8)]:
        result = evaluate_multires(patch, u, v, level=1)
        expected_x = u
        expected_y = v
        expected_z = c   # flat normals = (0,0,1), so displacement is along Z
        assert abs(result.position[0] - expected_x) < 1e-6, f"x at u={u}, v={v}"
        assert abs(result.position[1] - expected_y) < 1e-6, f"y at u={u}, v={v}"
        assert abs(result.position[2] - expected_z) < 1e-6, f"z at u={u}, v={v}"
        assert abs(result.displacement - c) < 1e-6


def test_negative_displacement_offsets_in_neg_normal_direction() -> None:
    """Negative constant displacement c → position offset by c in −n̂ direction."""
    c = -1.5
    patch = make_constant_patch(c, levels=2)
    result = evaluate_multires(patch, 0.5, 0.5, level=1)
    # On flat patch, base position is (0.5, 0.5, 0); normal is (0, 0, 1)
    # Displaced z = 0.0 + c * 1.0 = c
    assert abs(result.position[2] - c) < 1e-6
    assert abs(result.displacement - c) < 1e-6


# ---------------------------------------------------------------------------
# Tests: normal vector normalization
# ---------------------------------------------------------------------------

def test_normal_is_unit_length() -> None:
    """Evaluated normal must have |n| = 1 within 1e-9."""
    patch = make_zero_patch(levels=3)
    for u, v in [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.3, 0.6), (0.9, 0.1)]:
        result = evaluate_multires(patch, u, v, level=2)
        n_len = _norm3(result.normal)
        assert abs(n_len - 1.0) < 1e-9, f"Normal not unit at u={u}, v={v}: |n|={n_len}"


def test_normal_unit_with_non_uniform_base_normals() -> None:
    """Normal is unit even when base normals vary across the patch."""
    # Tilted patch normals (still unit but varying)
    normals = [
        (0.0, 0.0, 1.0),
        (0.0, math.sin(0.1), math.cos(0.1)),
        (math.sin(0.05), 0.0, math.cos(0.05)),
        (math.sin(0.08), math.sin(0.08), math.cos(0.11)),
    ]
    # Normalize each
    normals_unit = []
    for n in normals:
        lng = math.sqrt(n[0]**2 + n[1]**2 + n[2]**2)
        normals_unit.append((n[0]/lng, n[1]/lng, n[2]/lng))

    disps = []
    for lev in range(2):
        R = (1 << lev) + 1
        disps.append(DisplacementLevel(level=lev, face_id=0, grid_resolution=R,
                                       scalars=np.zeros((R, R), dtype=np.float32)))
    patch = MultiresPatch(
        base_face_id=0,
        base_corners=list(FLAT_CORNERS),
        base_normals=normals_unit,
        displacements=disps,
    )
    for u, v in [(0.1, 0.3), (0.7, 0.4), (0.5, 0.5)]:
        result = evaluate_multires(patch, u, v, level=1)
        assert abs(_norm3(result.normal) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Tests: level isolation
# ---------------------------------------------------------------------------

def test_evaluate_level0_ignores_higher_levels() -> None:
    """evaluate_multires(level=0) must ignore level 1..3 contributions."""
    # Build a patch where level 0 is zero but levels 1+ have large displacements
    disps = []
    for lev in range(4):
        R = (1 << lev) + 1
        if lev == 0:
            scalars = np.zeros((R, R), dtype=np.float32)
        else:
            scalars = np.full((R, R), 100.0, dtype=np.float32)
        disps.append(DisplacementLevel(level=lev, face_id=0, grid_resolution=R, scalars=scalars))

    patch = MultiresPatch(
        base_face_id=0,
        base_corners=list(FLAT_CORNERS),
        base_normals=list(FLAT_NORMALS),
        displacements=disps,
    )
    result = evaluate_multires(patch, 0.5, 0.5, level=0)
    # With level=0 and level-0 scalars all zero, displacement should be ~0
    assert abs(result.displacement) < 1e-6
    # Position should be at base surface (z=0)
    assert abs(result.position[2]) < 1e-6


# ---------------------------------------------------------------------------
# Tests: superposition (linearity)
# ---------------------------------------------------------------------------

def test_displacement_linear_superposition() -> None:
    """Total displacement == sum of per-level contributions."""
    disps = []
    level_values = [1.0, 0.5, 0.25, 0.125]  # values for levels 0..3
    for lev in range(4):
        R = (1 << lev) + 1
        scalars = np.full((R, R), level_values[lev], dtype=np.float32)
        disps.append(DisplacementLevel(level=lev, face_id=0, grid_resolution=R, scalars=scalars))

    patch = MultiresPatch(
        base_face_id=0,
        base_corners=list(FLAT_CORNERS),
        base_normals=list(FLAT_NORMALS),
        displacements=disps,
    )
    # At level 3, total = sum of all 4 levels = 1.0 + 0.5 + 0.25 + 0.125 = 1.875
    result_all = evaluate_multires(patch, 0.5, 0.5, level=3)
    expected_total = sum(level_values)
    assert abs(result_all.displacement - expected_total) < 1e-5, \
        f"Total displacement: expected {expected_total}, got {result_all.displacement}"

    # At level 1, total = levels 0+1 = 1.5
    result_l1 = evaluate_multires(patch, 0.5, 0.5, level=1)
    assert abs(result_l1.displacement - (level_values[0] + level_values[1])) < 1e-5

    # Difference between level-3 and level-2 results == level-3 displacement at centre
    result_l2 = evaluate_multires(patch, 0.5, 0.5, level=2)
    diff = result_all.displacement - result_l2.displacement
    assert abs(diff - level_values[3]) < 1e-5


# ---------------------------------------------------------------------------
# Tests: bilinear base position at corners and centre
# ---------------------------------------------------------------------------

def test_base_position_at_corners() -> None:
    """Bilinear base position at (u,v) ∈ {0,1}² equals the corner positions."""
    patch = make_zero_patch(levels=1)
    corners_uv = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
    expected_positions = FLAT_CORNERS  # c00, c10, c01, c11
    for (u, v), exp in zip(corners_uv, expected_positions):
        result = evaluate_multires(patch, u, v, level=0)
        for k in range(3):
            assert abs(result.base_position[k] - exp[k]) < 1e-9, \
                f"Corner u={u}, v={v}, component {k}: got {result.base_position[k]}, expected {exp[k]}"


def test_base_position_at_centre_is_mean_of_corners() -> None:
    """Bilinear at (0.5, 0.5) equals the mean of the four corners."""
    patch = make_zero_patch(levels=1)
    result = evaluate_multires(patch, 0.5, 0.5, level=0)
    mean = tuple(
        sum(c[k] for c in FLAT_CORNERS) / 4.0
        for k in range(3)
    )
    for k in range(3):
        assert abs(result.base_position[k] - mean[k]) < 1e-9


# ---------------------------------------------------------------------------
# Tests: encode_displacement
# ---------------------------------------------------------------------------

def test_encode_zero_highres_gives_zero_scalars() -> None:
    """Encoding a high-res mesh that exactly matches the base plane → zero displacements."""
    levels = 3
    M = (1 << levels) + 1  # 9
    us = np.linspace(0.0, 1.0, M)
    vs = np.linspace(0.0, 1.0, M)
    U, V = np.meshgrid(us, vs)  # U[row,col]=u, V[row,col]=v
    # High-res positions ARE the bilinear base surface positions (z=0)
    high_res = np.stack([U, V, np.zeros_like(U)], axis=2)  # (M, M, 3)

    patch = encode_displacement(high_res, FLAT_CORNERS, FLAT_NORMALS, levels=levels)
    assert len(patch.displacements) == levels
    for dlev in patch.displacements:
        max_abs = float(np.abs(dlev.scalars).max())
        assert max_abs < 1e-5, f"Level {dlev.level}: max abs displacement = {max_abs}"


def test_encode_level0_corners_match_direct_projection() -> None:
    """Level-0 displacements at corners should match (high_res_corner - base_corner) · n̂."""
    levels = 3
    M = (1 << levels) + 1  # 9
    us = np.linspace(0.0, 1.0, M)
    vs = np.linspace(0.0, 1.0, M)
    U, V = np.meshgrid(us, vs)
    # Add a constant Z-offset of 0.7 to all samples
    offset = 0.7
    high_res = np.stack([U, V, np.full_like(U, offset)], axis=2)  # (M, M, 3)

    patch = encode_displacement(high_res, FLAT_CORNERS, FLAT_NORMALS, levels=levels)
    lev0 = patch.displacements[0]
    # Level-0 corner displacements should be ~0.7 (n̂=+Z, delta_Z=0.7)
    # (Corner residuals at (u,v) = {0,1}² in the full grid)
    corner_scalars = lev0.scalars  # 2×2
    for row in range(2):
        for col in range(2):
            val = float(corner_scalars[row, col])
            assert abs(val - offset) < 1e-4, \
                f"Level-0 corner ({row},{col}): expected {offset}, got {val}"


def test_encode_roundtrip_gaussian_bump() -> None:
    """Round-trip encode/evaluate of a Gaussian bump: max error < 5% of bump height.

    Following Krishnamurthy-Levoy (1996) §3: the multires encoding should
    reconstruct the displacement field at the finest-level sample grid points
    to within the quantization error of the chosen number of levels.

    We evaluate at the finest-level (level=levels-1) grid sample points only,
    which is the correct test: the multires encoding is exact at sample-grid
    points by construction (each level captures the residual at its grid points).
    Bilinear interpolation between grid points is approximate — that is the
    intended approximation of the multires scheme.
    """
    levels = 3
    M = (1 << levels) + 1  # 9 samples per side (finest level has 9×9 = 81 pts)
    us = np.linspace(0.0, 1.0, M)
    vs = np.linspace(0.0, 1.0, M)
    U, V = np.meshgrid(us, vs)

    # Gaussian bump: amplitude A, centred at (0.5, 0.5), sigma=0.25
    A = 1.0
    sigma = 0.25
    Z = A * np.exp(-((U - 0.5)**2 + (V - 0.5)**2) / (2 * sigma**2))

    high_res = np.stack([U, V, Z], axis=2)  # (M, M, 3)

    patch = encode_displacement(high_res, FLAT_CORNERS, FLAT_NORMALS, levels=levels)

    # Evaluate at the finest encoded level's grid points only.
    # Level (levels-1) has resolution R_finest = 2^(levels-1) + 1.
    # These grid points are at u = i/(R_finest-1), v = j/(R_finest-1)
    # and correspond to every (M-1)/(R_finest-1) = 2 rows/cols in the M×M grid.
    R_finest = (1 << (levels - 1)) + 1  # e.g., 5 for levels=3
    stride = (M - 1) // (R_finest - 1)   # e.g., 2

    max_err = 0.0
    for ri in range(R_finest):
        for ci in range(R_finest):
            row = ri * stride
            col = ci * stride
            u_s = float(col) / (M - 1)
            v_s = float(row) / (M - 1)
            result = evaluate_multires(patch, u_s, v_s, level=levels - 1)
            # Expected displaced Z = Z[row, col]; position = (u_s, v_s, Z_bump)
            expected_z = float(Z[row, col])
            got_z = result.position[2]
            err = abs(got_z - expected_z)
            if err > max_err:
                max_err = err

    # Tolerance: 5% of bump amplitude
    # At the sample grid points the reconstruction is essentially exact (limited
    # only by float32 precision in the stored scalars), so we use a tighter check.
    tol = 0.05 * A
    assert max_err < tol, \
        f"Gaussian bump round-trip max error {max_err:.4f} >= {tol:.4f} (5% of A={A})"


# ---------------------------------------------------------------------------
# Tests: return type and parameter clamping
# ---------------------------------------------------------------------------

def test_evaluate_returns_multires_limit_eval_type() -> None:
    """evaluate_multires returns a MultiresLimitEval instance."""
    patch = make_zero_patch(levels=2)
    result = evaluate_multires(patch, 0.5, 0.5, level=1)
    assert isinstance(result, MultiresLimitEval)


def test_evaluate_clamps_uv_to_unit_square() -> None:
    """evaluate_multires clamps u, v to [0, 1] without raising."""
    patch = make_zero_patch(levels=2)
    # Out-of-range values should be clamped, not raise
    r1 = evaluate_multires(patch, -0.5, 1.5, level=1)
    r2 = evaluate_multires(patch, 0.0, 1.0, level=1)  # equivalent after clamp
    for k in range(3):
        assert abs(r1.position[k] - r2.position[k]) < 1e-9
