"""test_displacement_stack.py — GK-P21: hermetic tests for the displacement stack engine.

Tests cover:
1.  Single add layer 1mm: each vertex shifts 1mm along its normal.
2.  Two add layers (0.5 + 0.5 = 1mm): same net shift as test 1.
3.  Subtract mode: displacement applied in opposite direction.
4.  Multiply scales prior accumulator.
5.  Replace overrides everything before it.
6.  Masked region: only vertices with mask>0 are affected.
7.  Disabled layer is skipped entirely.
8.  Strength scalar scales the effective displacement.
9.  num_layers_applied counts only enabled layers.
10. layer_contributions per layer reported correctly.
11. max_displacement_mm and mean_displacement_mm are correct.
12. Mismatched vertex/normal count raises ValueError.
13. Mismatched layer displacement_values count raises ValueError.
14. Mismatched mask length raises ValueError.
15. Invalid mode raises ValueError.
16. Zero-vertex mesh produces empty output.
17. Replace after add: final result equals replace value.
18. Mask value 0 leaves vertex unchanged (masked region excluded).
19. Negative strength inverts displacement direction.
20. Multiply mode on non-zero accumulator scales correctly.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.mesh_displacement_stack import (
    DisplacementLayer,
    DisplacementStackResult,
    DisplacementStackSpec,
    apply_displacement_stack,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat_mesh(
    n: int = 4,
    normal: Tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[float, float, float]]]:
    """n vertices along x-axis at z=0, all normals pointing +Z."""
    verts = [(float(i), 0.0, 0.0) for i in range(n)]
    norms = [normal] * n
    return verts, norms


def _close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) < tol


# ---------------------------------------------------------------------------
# Test 1: single add layer 1mm shifts all vertices 1mm along normal
# ---------------------------------------------------------------------------

def test_single_add_layer_1mm_shift():
    verts, norms = _flat_mesh(3)
    layer = DisplacementLayer(
        name="form",
        displacement_values=[1.0, 1.0, 1.0],
        mode="add",
    )
    spec = DisplacementStackSpec(
        base_vertices_xyz=verts,
        base_normals_xyz=norms,
        layers=[layer],
    )
    result = apply_displacement_stack(spec)
    assert result.num_layers_applied == 1
    for i, (px, py, pz) in enumerate(result.output_vertices_xyz):
        ox, oy, oz = verts[i]
        # normal is (0,0,1): only z changes
        assert _close(px, ox)
        assert _close(py, oy)
        assert _close(pz, oz + 1.0), f"vertex {i}: expected z={oz + 1.0}, got {pz}"


# ---------------------------------------------------------------------------
# Test 2: two add layers (0.5 + 0.5) equal 1mm total
# ---------------------------------------------------------------------------

def test_two_add_layers_sum_to_1mm():
    verts, norms = _flat_mesh(3)
    l1 = DisplacementLayer("low", [0.5, 0.5, 0.5], mode="add")
    l2 = DisplacementLayer("hi", [0.5, 0.5, 0.5], mode="add")
    spec = DisplacementStackSpec(verts, norms, [l1, l2])
    result = apply_displacement_stack(spec)
    assert result.num_layers_applied == 2
    for i, (_, _, pz) in enumerate(result.output_vertices_xyz):
        _, _, oz = verts[i]
        assert _close(pz, oz + 1.0), f"vertex {i}: expected z={oz + 1.0}, got {pz}"


# ---------------------------------------------------------------------------
# Test 3: subtract mode — displacement in opposite direction
# ---------------------------------------------------------------------------

def test_subtract_mode_negative_direction():
    verts, norms = _flat_mesh(3)
    layer = DisplacementLayer("sub", [1.0, 1.0, 1.0], mode="subtract")
    spec = DisplacementStackSpec(verts, norms, [layer])
    result = apply_displacement_stack(spec)
    for i, (_, _, pz) in enumerate(result.output_vertices_xyz):
        _, _, oz = verts[i]
        # subtract: d_total = 0 - 1.0 = -1.0; P'_z = oz + (-1.0)
        assert _close(pz, oz - 1.0), f"vertex {i}: expected z={oz - 1.0}, got {pz}"


# ---------------------------------------------------------------------------
# Test 4: multiply scales prior accumulator
# ---------------------------------------------------------------------------

def test_multiply_scales_prior_accumulator():
    verts, norms = _flat_mesh(3)
    # First add 2.0, then multiply by 0.5 -> result should be 1.0
    l1 = DisplacementLayer("base", [2.0, 2.0, 2.0], mode="add")
    l2 = DisplacementLayer("scale", [0.5, 0.5, 0.5], mode="multiply")
    spec = DisplacementStackSpec(verts, norms, [l1, l2])
    result = apply_displacement_stack(spec)
    assert result.num_layers_applied == 2
    for i, (_, _, pz) in enumerate(result.output_vertices_xyz):
        _, _, oz = verts[i]
        assert _close(pz, oz + 1.0), f"vertex {i}: expected z={oz + 1.0}, got {pz}"


# ---------------------------------------------------------------------------
# Test 5: replace overrides prior layers
# ---------------------------------------------------------------------------

def test_replace_overrides_prior_layers():
    verts, norms = _flat_mesh(3)
    l1 = DisplacementLayer("ignore_me", [99.0, 99.0, 99.0], mode="add")
    l2 = DisplacementLayer("final", [2.0, 2.0, 2.0], mode="replace")
    spec = DisplacementStackSpec(verts, norms, [l1, l2])
    result = apply_displacement_stack(spec)
    for i, (_, _, pz) in enumerate(result.output_vertices_xyz):
        _, _, oz = verts[i]
        # replace sets d_total = 2.0 regardless of prior 99
        assert _close(pz, oz + 2.0), f"vertex {i}: expected z={oz + 2.0}, got {pz}"


# ---------------------------------------------------------------------------
# Test 6: mask restricts displacement to mask>0 vertices
# ---------------------------------------------------------------------------

def test_masked_region_only():
    # 4 vertices: mask=[1,1,0,0] — only first two should move
    verts, norms = _flat_mesh(4)
    mask = [1.0, 1.0, 0.0, 0.0]
    layer = DisplacementLayer("detail", [1.0, 1.0, 1.0, 1.0], mode="add", mask=mask)
    spec = DisplacementStackSpec(verts, norms, [layer])
    result = apply_displacement_stack(spec)

    for i, (_, _, pz) in enumerate(result.output_vertices_xyz):
        _, _, oz = verts[i]
        if mask[i] > 0:
            assert _close(pz, oz + 1.0), f"vertex {i} should shift"
        else:
            assert _close(pz, oz), f"vertex {i} should NOT shift (masked out)"


# ---------------------------------------------------------------------------
# Test 7: disabled layer is skipped entirely
# ---------------------------------------------------------------------------

def test_disabled_layer_skipped():
    verts, norms = _flat_mesh(3)
    layer = DisplacementLayer("off", [5.0, 5.0, 5.0], mode="add", enabled=False)
    spec = DisplacementStackSpec(verts, norms, [layer])
    result = apply_displacement_stack(spec)
    assert result.num_layers_applied == 0
    for i, (_, _, pz) in enumerate(result.output_vertices_xyz):
        _, _, oz = verts[i]
        assert _close(pz, oz), f"vertex {i}: disabled layer should leave z unchanged"
    assert _close(result.max_displacement_mm, 0.0)


# ---------------------------------------------------------------------------
# Test 8: strength scalar scales displacement
# ---------------------------------------------------------------------------

def test_strength_scalar():
    verts, norms = _flat_mesh(3)
    layer = DisplacementLayer("amp", [1.0, 1.0, 1.0], mode="add", strength=2.5)
    spec = DisplacementStackSpec(verts, norms, [layer])
    result = apply_displacement_stack(spec)
    for i, (_, _, pz) in enumerate(result.output_vertices_xyz):
        _, _, oz = verts[i]
        assert _close(pz, oz + 2.5), f"vertex {i}: expected z={oz + 2.5}, got {pz}"


# ---------------------------------------------------------------------------
# Test 9: num_layers_applied counts only enabled layers
# ---------------------------------------------------------------------------

def test_num_layers_applied_counts_enabled_only():
    verts, norms = _flat_mesh(2)
    l1 = DisplacementLayer("a", [1.0, 1.0], mode="add", enabled=True)
    l2 = DisplacementLayer("b", [1.0, 1.0], mode="add", enabled=False)
    l3 = DisplacementLayer("c", [1.0, 1.0], mode="add", enabled=True)
    spec = DisplacementStackSpec(verts, norms, [l1, l2, l3])
    result = apply_displacement_stack(spec)
    assert result.num_layers_applied == 2


# ---------------------------------------------------------------------------
# Test 10: layer_contributions reported correctly per layer
# ---------------------------------------------------------------------------

def test_layer_contributions_per_layer():
    verts, norms = _flat_mesh(3)
    # Layer 0: displacement = 1.0 per vertex, strength=1 → contribution = 1.0
    # Layer 1: disabled → contribution = 0.0
    # Layer 2: displacement = 3.0 per vertex, strength=2 → contribution = 6.0
    l1 = DisplacementLayer("a", [1.0, 1.0, 1.0], mode="add", enabled=True)
    l2 = DisplacementLayer("b", [1.0, 1.0, 1.0], mode="add", enabled=False)
    l3 = DisplacementLayer("c", [3.0, 3.0, 3.0], mode="add", strength=2.0, enabled=True)
    spec = DisplacementStackSpec(verts, norms, [l1, l2, l3])
    result = apply_displacement_stack(spec)
    assert len(result.layer_contributions) == 3
    assert _close(result.layer_contributions[0], 1.0)
    assert _close(result.layer_contributions[1], 0.0)
    assert _close(result.layer_contributions[2], 6.0)


# ---------------------------------------------------------------------------
# Test 11: max_displacement_mm and mean_displacement_mm
# ---------------------------------------------------------------------------

def test_max_and_mean_displacement():
    # 4 vertices; displacements after stack: 1, 2, 3, 4
    verts, norms = _flat_mesh(4)
    layer = DisplacementLayer("ramp", [1.0, 2.0, 3.0, 4.0], mode="add")
    spec = DisplacementStackSpec(verts, norms, [layer])
    result = apply_displacement_stack(spec)
    assert _close(result.max_displacement_mm, 4.0)
    assert _close(result.mean_displacement_mm, (1 + 2 + 3 + 4) / 4)


# ---------------------------------------------------------------------------
# Test 12: mismatched vertex/normal count raises ValueError
# ---------------------------------------------------------------------------

def test_mismatched_vertex_normal_raises():
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    norms = [(0.0, 0.0, 1.0)]  # only 1 normal for 2 verts
    layer = DisplacementLayer("x", [1.0, 1.0], mode="add")
    spec = DisplacementStackSpec(verts, norms, [layer])
    with pytest.raises(ValueError, match="base_normals_xyz"):
        apply_displacement_stack(spec)


# ---------------------------------------------------------------------------
# Test 13: mismatched layer displacement_values count raises ValueError
# ---------------------------------------------------------------------------

def test_mismatched_displacement_values_raises():
    verts, norms = _flat_mesh(3)
    layer = DisplacementLayer("bad", [1.0, 1.0], mode="add")  # 2 values for 3 verts
    spec = DisplacementStackSpec(verts, norms, [layer])
    with pytest.raises(ValueError, match="displacement values"):
        apply_displacement_stack(spec)


# ---------------------------------------------------------------------------
# Test 14: mismatched mask length raises ValueError
# ---------------------------------------------------------------------------

def test_mismatched_mask_length_raises():
    verts, norms = _flat_mesh(3)
    layer = DisplacementLayer("bad", [1.0, 1.0, 1.0], mode="add", mask=[1.0, 1.0])
    spec = DisplacementStackSpec(verts, norms, [layer])
    with pytest.raises(ValueError, match="mask"):
        apply_displacement_stack(spec)


# ---------------------------------------------------------------------------
# Test 15: invalid mode raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_mode_raises():
    verts, norms = _flat_mesh(2)
    layer = DisplacementLayer("bad", [1.0, 1.0], mode="blend")
    spec = DisplacementStackSpec(verts, norms, [layer])
    with pytest.raises(ValueError, match="mode"):
        apply_displacement_stack(spec)


# ---------------------------------------------------------------------------
# Test 16: zero-vertex mesh produces empty output
# ---------------------------------------------------------------------------

def test_zero_vertex_mesh():
    spec = DisplacementStackSpec([], [], [])
    result = apply_displacement_stack(spec)
    assert result.output_vertices_xyz == []
    assert result.num_layers_applied == 0
    assert _close(result.max_displacement_mm, 0.0)
    assert _close(result.mean_displacement_mm, 0.0)


# ---------------------------------------------------------------------------
# Test 17: replace after add yields replace value
# ---------------------------------------------------------------------------

def test_replace_after_add_yields_replace():
    verts, norms = _flat_mesh(2)
    l1 = DisplacementLayer("big_add", [10.0, 10.0], mode="add")
    l2 = DisplacementLayer("final_replace", [0.5, 0.5], mode="replace")
    spec = DisplacementStackSpec(verts, norms, [l1, l2])
    result = apply_displacement_stack(spec)
    for _, _, pz in result.output_vertices_xyz:
        assert _close(pz, 0.5)


# ---------------------------------------------------------------------------
# Test 18: mask value 0.0 leaves vertex unchanged
# ---------------------------------------------------------------------------

def test_mask_zero_leaves_vertex_unchanged():
    verts, norms = _flat_mesh(2)
    mask = [0.0, 1.0]
    layer = DisplacementLayer("detail", [1.0, 1.0], mode="add", mask=mask)
    spec = DisplacementStackSpec(verts, norms, [layer])
    result = apply_displacement_stack(spec)

    # vertex 0: mask=0 → no change
    assert _close(result.output_vertices_xyz[0][2], 0.0)
    # vertex 1: mask=1 → shifted by 1mm
    assert _close(result.output_vertices_xyz[1][2], 1.0)


# ---------------------------------------------------------------------------
# Test 19: negative strength inverts displacement direction
# ---------------------------------------------------------------------------

def test_negative_strength_inverts_direction():
    verts, norms = _flat_mesh(3)
    layer = DisplacementLayer("inv", [1.0, 1.0, 1.0], mode="add", strength=-1.0)
    spec = DisplacementStackSpec(verts, norms, [layer])
    result = apply_displacement_stack(spec)
    for i, (_, _, pz) in enumerate(result.output_vertices_xyz):
        _, _, oz = verts[i]
        assert _close(pz, oz - 1.0), f"vertex {i}: expected z={oz - 1.0}, got {pz}"


# ---------------------------------------------------------------------------
# Test 20: multiply on non-zero accumulator scales correctly
# ---------------------------------------------------------------------------

def test_multiply_on_nonzero_accumulator():
    verts, norms = _flat_mesh(2)
    # add 4.0 then multiply by 0.25 → 1.0
    l1 = DisplacementLayer("base", [4.0, 4.0], mode="add")
    l2 = DisplacementLayer("scale", [0.25, 0.25], mode="multiply")
    spec = DisplacementStackSpec(verts, norms, [l1, l2])
    result = apply_displacement_stack(spec)
    for _, _, pz in result.output_vertices_xyz:
        assert _close(pz, 1.0)


# ---------------------------------------------------------------------------
# Test 21: honest_caveat is non-empty and mentions key limitations
# ---------------------------------------------------------------------------

def test_honest_caveat_content():
    verts, norms = _flat_mesh(1)
    layer = DisplacementLayer("x", [0.0], mode="add")
    spec = DisplacementStackSpec(verts, norms, [layer])
    result = apply_displacement_stack(spec)
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 20
    assert "per-vertex" in result.honest_caveat.lower()
    assert "unit" in result.honest_caveat.lower()


# ---------------------------------------------------------------------------
# Test 22: non-Z normal — displacement follows the actual normal direction
# ---------------------------------------------------------------------------

def test_non_z_normal_direction():
    # Normal pointing +X: displacement should shift X not Z
    verts = [(0.0, 0.0, 0.0)]
    norms = [(1.0, 0.0, 0.0)]
    layer = DisplacementLayer("side", [3.0], mode="add")
    spec = DisplacementStackSpec(verts, norms, [layer])
    result = apply_displacement_stack(spec)
    px, py, pz = result.output_vertices_xyz[0]
    assert _close(px, 3.0)
    assert _close(py, 0.0)
    assert _close(pz, 0.0)


# ---------------------------------------------------------------------------
# Test 23: dataclass re-export from kerf_cad_core package
# ---------------------------------------------------------------------------

def test_package_reexport():
    from kerf_cad_core import (
        DisplacementLayer,
        DisplacementStackResult,
        DisplacementStackSpec,
        apply_displacement_stack,
    )
    assert callable(apply_displacement_stack)
    assert DisplacementLayer is not None
    assert DisplacementStackSpec is not None
    assert DisplacementStackResult is not None
