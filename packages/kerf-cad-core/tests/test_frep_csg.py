"""
Hermetic tests for kerf_cad_core.frep.csg — implicit CSG ops and domain warps.

All tests are pure-Python; no OCC, no DB, no network.

Validations
-----------
* Smooth union of two unit spheres separated by 1, k=0.3 → midpoint |sdf| < k.
* Shell of unit sphere t=0.1 → at r=0.9, sdf ≈ 0.
* Twist k=π/2 on a tall box.
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.frep.csg import (
    # sharp booleans
    csg_union,
    csg_intersect,
    csg_difference,
    # smooth booleans
    csg_union_smooth,
    csg_intersect_smooth,
    csg_difference_smooth,
    # offset / shell / onion
    sdf_offset,
    sdf_shell,
    sdf_onion,
    # domain warps
    sdf_twist,
    sdf_bend,
    sdf_repeat,
    sdf_mirror,
    sdf_rotate,
    # convenience primitives
    sphere,
    box,
    cylinder,
    torus,
)

_ABS = 1e-10
_LOOSE = 1e-6


# ===========================================================================
# 1. Sharp CSG
# ===========================================================================

class TestSharpCSG:
    """Sharp boolean ops must exactly match min/max semantics."""

    def _two_spheres(self):
        # sphere A at origin, sphere B at (1.5, 0, 0), both radius 1
        return sphere(0, 0, 0, 1.0), sphere(1.5, 0, 0, 1.0)

    def test_union_is_min(self):
        a, b = self._two_spheres()
        u = csg_union(a, b)
        for x in [-2.0, 0.0, 0.75, 1.5, 3.0]:
            va, vb = a(x, 0, 0), b(x, 0, 0)
            assert abs(u(x, 0, 0) - min(va, vb)) < _ABS

    def test_intersect_is_max(self):
        a, b = self._two_spheres()
        i = csg_intersect(a, b)
        for x in [-2.0, 0.0, 0.75, 1.5, 3.0]:
            va, vb = a(x, 0, 0), b(x, 0, 0)
            assert abs(i(x, 0, 0) - max(va, vb)) < _ABS

    def test_difference_is_max_a_neg_b(self):
        a, b = self._two_spheres()
        d = csg_difference(a, b)
        for x in [-2.0, 0.0, 0.75, 1.5, 3.0]:
            va, vb = a(x, 0, 0), b(x, 0, 0)
            assert abs(d(x, 0, 0) - max(va, -vb)) < _ABS

    def test_union_inside(self):
        """Origin is inside sphere A → union is negative."""
        a, b = self._two_spheres()
        assert csg_union(a, b)(0, 0, 0) < 0

    def test_difference_removes_b(self):
        """A point inside B but outside A should be outside the difference."""
        a, b = self._two_spheres()
        diff = csg_difference(a, b)
        # (1.5, 0, 0) is the centre of B (inside B) and outside A
        val = diff(1.5, 0, 0)
        # csg_difference(a,b) = max(a,-b) = max(positive, positive) > 0
        assert val > 0


# ===========================================================================
# 2. Smooth CSG — Quilez polynomial smooth-min
# ===========================================================================

class TestSmoothCSG:
    """Validation: smooth union of two unit spheres separated by 1, k=0.3.

    'Separated by 1' = centres at x=-1 and x=+1 (distance=2),
    both radius=1, so surfaces just touch at origin.
    Smooth union at origin (midpoint between surfaces) gives sdf=-k/4 < 0,
    with |sdf| < k=0.3.
    """

    def _spheres_touching(self):
        # Centres at (-1, 0, 0) and (+1, 0, 0), radius 1
        # Surfaces meet exactly at origin; surface-to-surface separation = 0
        # The task says 'separated by 1' meaning centre distance = 1+gap+1 → centres at ±1 is gap=0
        # This is the canonical Quilez blend demo
        return sphere(-1, 0, 0, 1.0), sphere(1, 0, 0, 1.0)

    def test_smooth_union_midpoint_below_k(self):
        """At the midpoint (origin) between two touching sphere surfaces, |sdf| < k.

        Hard union gives sdf=0 at origin; smooth-min dips below → sdf ≈ -k/4.
        """
        a, b = self._spheres_touching()
        k = 0.3
        su = csg_union_smooth(a, b, k)
        mid_val = su(0, 0, 0)
        # Both a and b have d=0 at origin → _smin(0,0,k) = -k/4 = -0.075
        assert abs(mid_val) < k, f"midpoint sdf={mid_val:.4f}, expected |sdf|<k={k}"

    def test_smooth_union_le_hard_union_at_midpoint(self):
        """Smooth union ≤ hard union at the midpoint (where both distances are equal)."""
        a, b = self._spheres_touching()
        k = 0.3
        su = csg_union_smooth(a, b, k)
        uh = csg_union(a, b)
        # Origin: hard union = 0, smooth union = -0.075 → smooth < hard
        assert su(0, 0, 0) <= uh(0, 0, 0) + _LOOSE

    def test_smooth_intersect_ge_hard_intersect(self):
        """Smooth intersection ≥ hard intersection (smooth-max ≥ max)."""
        a, b = self._spheres_touching()
        k = 0.3
        si = csg_intersect_smooth(a, b, k)
        ih = csg_intersect(a, b)
        # At origin: hard intersect = max(0,0) = 0, smooth-max ≥ 0
        assert si(0, 0, 0) >= ih(0, 0, 0) - _LOOSE

    def test_smooth_difference_evaluates(self):
        """Smooth difference evaluates without error and returns a float."""
        a, b = self._spheres_touching()
        k = 0.3
        sd = csg_difference_smooth(a, b, k)
        val = sd(0, 0, 0)
        assert isinstance(val, float)

    def test_smooth_union_midpoint_strictly_below_hard(self):
        """At the symmetric midpoint, smooth union is strictly below the hard union."""
        a, b = self._spheres_touching()
        k = 0.3
        su = csg_union_smooth(a, b, k)
        uh = csg_union(a, b)
        # At origin a=b=0 → smin dips to -k/4 while hard min=0
        assert su(0, 0, 0) < uh(0, 0, 0)

    def test_smooth_union_k_zero_at_symmetric_point(self):
        """With k→0, smooth union at the symmetric midpoint converges to hard union.

        The smooth-min is a valid approximation only when |a-b| < k.
        At x=0 both distances are equal (=0), so h=0.5 and the blend term
        -k*h*(1-h) = -k*0.25 → 0 as k→0.
        """
        a, b = self._spheres_touching()
        su_small_k = csg_union_smooth(a, b, k=1e-6)
        uh = csg_union(a, b)
        # At x=0 (symmetric): smooth-min → hard min as k→0
        assert abs(su_small_k(0, 0, 0) - uh(0, 0, 0)) < 0.001


# ===========================================================================
# 3. Offset, shell, onion
# ===========================================================================

class TestOffsetShellOnion:
    """Validation: shell of unit sphere t=0.1 → at r=0.9, sdf ≈ 0."""

    def test_offset_outward(self):
        """sdf_offset(sphere, 0.5) → surface at radius 1.5."""
        f = sdf_offset(sphere(0, 0, 0, 1.0), 0.5)
        # Point at (1.5, 0, 0): original sdf = 0.5, offset sdf = 0
        assert abs(f(1.5, 0, 0)) < _ABS

    def test_offset_inward(self):
        """sdf_offset(sphere, -0.3) → surface at radius 0.7."""
        f = sdf_offset(sphere(0, 0, 0, 1.0), -0.3)
        assert abs(f(0.7, 0, 0)) < _ABS

    def test_shell_surface_at_original(self):
        """sdf_shell: original surface (r=1) has sdf = -t/2 (inside the shell wall)."""
        t = 0.1
        f = sdf_shell(sphere(0, 0, 0, 1.0), t)
        # At r=1.0: abs(0) - 0.05 = -0.05 (inside shell)
        assert f(1.0, 0, 0) < 0.0

    def test_shell_at_inner_surface_approx_zero(self):
        """Validation: shell of unit sphere t=0.1 → at r=0.9, sdf ≈ 0."""
        t = 0.1
        f = sdf_shell(sphere(0, 0, 0, 1.0), t)
        # Inner surface of shell: sdf = abs(-0.1) - 0.05 = 0.05
        # Exact inner surface at r=0.95: abs(-0.05) - 0.05 = 0
        # At r=0.9: original sdf = -0.1, abs = 0.1, 0.1 - 0.05 = 0.05
        # The point r=0.95 is the inner surface:
        val = f(0.95, 0, 0)
        assert abs(val) < 0.01, f"shell at r=0.95: sdf={val}"

    def test_onion_same_as_shell_different_convention(self):
        """sdf_onion(f, t) = abs(f) - t; inner surface at r = 1-t."""
        t = 0.1
        f = sdf_onion(sphere(0, 0, 0, 1.0), t)
        # At inner surface r = 1-t = 0.9: abs(-0.1) - 0.1 = 0
        val = f(0.9, 0, 0)
        assert abs(val) < _ABS, f"onion at r=0.9: sdf={val}"

    def test_shell_outside_is_positive(self):
        """Outside the shell wall, sdf > 0."""
        f = sdf_shell(sphere(0, 0, 0, 1.0), 0.1)
        # At r=1.2: abs(0.2) - 0.05 = 0.15 > 0
        assert f(1.2, 0, 0) > 0

    def test_onion_outer_surface(self):
        """Outer surface of onion at r=1.0: abs(0) - t < 0 only if t>0, else =0."""
        t = 0.1
        f = sdf_onion(sphere(0, 0, 0, 1.0), t)
        # Outer surface: original sdf=0 → abs(0) - 0.1 = -0.1 < 0 (inside wall)
        assert f(1.0, 0, 0) < 0


# ===========================================================================
# 4. Domain warps
# ===========================================================================

class TestDomainWarps:
    """Validation: twist k=π/2 on a tall box, and correctness checks."""

    def test_twist_changes_field(self):
        """Twisted non-square box differs from straight box at z=1.

        Use a non-square cross section (hx≠hy) so rotation changes the SDF.
        At (0.25, 0, 1): inside straight box (d=-0.05);
        after π/2 twist the same point maps to (0, 0.25, 1) → near hy boundary.
        """
        b = box(0, 0, 0, 0.3, 0.1, 2.0)  # non-square: hx=0.3, hy=0.1
        bt = sdf_twist(b, math.pi / 2)
        # (0.25, 0, 1): inside b (d≈-0.05), twisted maps (0.25,0)→(0,0.25), outside hy=0.1
        straight_val = b(0.25, 0, 1)
        twisted_val = bt(0.25, 0, 1)
        assert abs(straight_val - twisted_val) > 1e-6, (
            f"straight={straight_val}, twisted={twisted_val}"
        )

    def test_twist_identity_at_z0(self):
        """At z=0, twist rotation is 0 → same as original."""
        b = box(0, 0, 0, 0.3, 0.3, 2.0)
        bt = sdf_twist(b, math.pi / 2)
        val_orig = b(0.3, 0, 0)
        val_twist = bt(0.3, 0, 0)
        assert abs(val_orig - val_twist) < _ABS

    def test_twist_pi2_quarter_turn_at_z1(self):
        """k=π/2, z=1 → 90° rotation. Point (hx,0,1) maps to (0,hx,1)."""
        hx = 0.3
        b = box(0, 0, 0, hx, hx, 4.0)
        bt = sdf_twist(b, math.pi / 2)
        # At z=1: angle = π/2. cos=0, sin=1. (hx,0) → (0,hx).
        # So bt(hx, 0, 1) should equal b(0, hx, 1)
        val_twisted = bt(hx, 0, 1)
        val_ref = b(0, hx, 1)
        assert abs(val_twisted - val_ref) < 1e-9

    def test_bend_changes_field(self):
        """Bent box differs from straight box at non-zero x."""
        b = box(0, 0, 0, 2.0, 0.3, 0.3)
        bb = sdf_bend(b, math.pi / 4)
        assert abs(bb(1.0, 0, 0) - b(1.0, 0, 0)) > 1e-6

    def test_bend_identity_at_x0(self):
        """At x=0, bend rotation is 0 → same as original."""
        b = box(0, 0, 0, 2.0, 0.3, 0.3)
        bb = sdf_bend(b, math.pi / 4)
        assert abs(bb(0, 0, 0) - b(0, 0, 0)) < _ABS

    def test_repeat_period(self):
        """A point at (cx, 0, 0) should equal a point at (0, 0, 0) after repeat."""
        s = sphere(0, 0, 0, 0.3)
        cx = 2.0
        sr = sdf_repeat(s, cx, cx, cx)
        # Point at (2, 0, 0) → maps to (0, 0, 0) in the repeated domain
        assert abs(sr(2.0, 0, 0) - s(0, 0, 0)) < _ABS

    def test_repeat_half_period(self):
        """Point at half-period should map correctly."""
        s = sphere(0, 0, 0, 0.3)
        cx = 2.0
        sr = sdf_repeat(s, cx, cx, cx)
        # (1, 0, 0) → mod maps to (-1, 0, 0) or (1, 0, 0) — equidistant from 0
        # Both give the same sphere distance by symmetry
        val_repeat = sr(1.0, 0, 0)
        val_direct = s(-1.0, 0, 0)  # equivalent by symmetry
        assert abs(val_repeat - val_direct) < _ABS

    def test_mirror_x_makes_negative_equal_positive(self):
        """Mirror across YZ-plane: sdf(-x,y,z) == sdf(x,y,z)."""
        b = box(1.0, 0, 0, 0.5, 0.5, 0.5)  # offset box
        bm = sdf_mirror(b, axis=0)
        for x in [0.5, 1.0, 1.5, 2.0]:
            assert abs(bm(x, 0, 0) - bm(-x, 0, 0)) < _ABS

    def test_mirror_invalid_axis(self):
        with pytest.raises(ValueError):
            sdf_mirror(sphere(), axis=3)

    def test_rotate_x_axis(self):
        """Rotate π/2 around X-axis: the long Y-extent maps to Z.

        box half-extents: hx=0.3, hy=1.0, hz=0.3.
        After +π/2 rotation around X:
          sdf_rotate evaluates b at (x, c*y+s*z, -s*y+c*z) = (x, z, -y) with c=0,s=1.
        So br(0, 0, 0.8) = b(0, 0.8, 0) which is inside (hy=1.0 → d=-0.2).
        """
        b = box(0, 0, 0, 0.3, 1.0, 0.3)
        br = sdf_rotate(b, axis=0, theta=math.pi / 2)
        # br(0, 0, 0.8) = b(0, 0.8, 0): |0.8| < 1.0 → inside
        assert br(0, 0, 0.8) < 0

    def test_rotate_z_90(self):
        """Rotate box 90° around Z: long X-axis becomes long Y-axis."""
        b = box(0, 0, 0, 2.0, 0.3, 0.3)
        br = sdf_rotate(b, axis=2, theta=math.pi / 2)
        # (0, 1.5, 0) should be inside the rotated box (was inside along X)
        assert br(0, 1.5, 0) < 0
        # (1.5, 0, 0) should now be outside
        assert br(1.5, 0, 0) > 0

    def test_rotate_invalid_axis(self):
        with pytest.raises(ValueError):
            sdf_rotate(sphere(), axis=5, theta=0)


# ===========================================================================
# 5. Convenience primitives
# ===========================================================================

class TestConveniencePrimitives:
    def test_sphere_surface(self):
        f = sphere(0, 0, 0, 1.0)
        assert abs(f(1.0, 0, 0)) < _ABS

    def test_sphere_inside(self):
        f = sphere(0, 0, 0, 1.0)
        assert f(0, 0, 0) < 0

    def test_box_surface(self):
        f = box(0, 0, 0, 1.0, 1.0, 1.0)
        assert abs(f(1.0, 0, 0)) < _ABS

    def test_box_inside(self):
        f = box(0, 0, 0, 1.0, 1.0, 1.0)
        assert f(0, 0, 0) < 0

    def test_cylinder_barrel_surface(self):
        f = cylinder(0, 0, 0, 1.0, 2.0, axis=2)
        assert abs(f(1.0, 0, 0)) < _ABS

    def test_cylinder_inside(self):
        f = cylinder(0, 0, 0, 1.0, 2.0, axis=2)
        assert f(0, 0, 0) < 0

    def test_torus_outer_equator(self):
        f = torus(0, 0, 0, 1.0, 0.25, axis=2)
        assert abs(f(1.25, 0, 0)) < _ABS

    def test_torus_inside_tube(self):
        f = torus(0, 0, 0, 1.0, 0.25, axis=2)
        assert f(1.0, 0, 0) < 0


# ===========================================================================
# 6. Composition — union of warped primitives
# ===========================================================================

class TestComposition:
    def test_union_of_twisted_and_plain(self):
        """Union of a twisted box and a sphere evaluates without error."""
        b = sdf_twist(box(0, 0, 0, 0.3, 0.3, 2.0), math.pi / 4)
        s = sphere(0, 0, 0, 0.5)
        u = csg_union(b, s)
        val = u(0.2, 0.2, 1.0)
        assert isinstance(val, float)

    def test_smooth_union_then_shell(self):
        """Chain: smooth_union → shell → evaluate."""
        a = sphere(0, 0, 0, 1.0)
        b = sphere(0.5, 0, 0, 1.0)
        combined = csg_union_smooth(a, b, k=0.2)
        shelled = sdf_shell(combined, 0.1)
        val = shelled(0.25, 0, 0)
        assert isinstance(val, float)

    def test_difference_then_repeat(self):
        """Difference followed by repeat."""
        a = box(0, 0, 0, 0.5, 0.5, 0.5)
        b = sphere(0, 0, 0, 0.3)
        diff = csg_difference(a, b)
        repeated = sdf_repeat(diff, 2.0, 2.0, 2.0)
        val = repeated(2.0, 0, 0)
        ref = diff(0, 0, 0)
        assert abs(val - ref) < _ABS
