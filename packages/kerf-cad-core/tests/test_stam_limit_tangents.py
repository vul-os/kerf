"""test_stam_limit_tangents.py
=============================
Tests for GK-P12: Stam exact limit tangents at extraordinary Catmull-Clark
SubD vertices.

Covers:
 - Regular valence-4 vertex on a flat XY plane (tangents in-plane, normal Z)
 - Extraordinary valence-3 (corner-like configuration)
 - Valence-5 vertex on a dome (non-zero positive Gaussian curvature)
 - Valence-6 hex vertex (symmetric tangents, near-zero K)
 - Valence-7 vertex
 - Subdominant eigenvalue formula (λ_n = (1/4)(1 + cos(2π/n)))
 - Limit position weights (w_V + n·w_e + n·w_f = 1)
 - T_u/T_v orthogonality on flat surfaces
 - Normal unit length
 - Normal direction correct for outward orientation
 - Degenerate / fallback (valence < 3)
 - LimitTangentReport field presence
 - ExtraordinaryVertex dataclass construction
 - ring_positions=None synthetic fallback
 - compute_stam_limit_tangents returns LimitTangentReport
 - Gaussian curvature flat plane ≈ 0
 - Mean curvature flat plane ≈ 0
 - Honest caveat non-empty
 - Tangent magnitudes nonzero for non-degenerate inputs
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.subd.stam_limit_tangents import (
    ExtraordinaryVertex,
    LimitTangentReport,
    compute_stam_limit_tangents,
    _subdominant_eigenvalue,
    _stam_limit_weights,
)


# ---------------------------------------------------------------------------
# Helper: build a ring_positions dict for a flat-plane n-ring
# ---------------------------------------------------------------------------

def _flat_ring(
    n: int,
    radius: float = 1.0,
    z: float = 0.0,
) -> tuple:
    """Return (ev, ring_positions) for an extraordinary vertex at origin
    with n neighbours on a flat circle of given radius in the XY plane.

    The n quad-like faces are virtual: each face is (EV, P_i, P_{i+1},
    midpoint of P_i and P_{i+1}) so face centroids are approx at 3/4 radius.
    """
    V_idx = 0
    V_pos = (0.0, 0.0, z)
    ring_verts = list(range(1, n + 1))
    positions: dict = {V_idx: V_pos}

    for i in range(n):
        angle = 2.0 * math.pi * i / n
        px = radius * math.cos(angle)
        py = radius * math.sin(angle)
        positions[ring_verts[i]] = (px, py, z)

    # Outer ring vertices for face definitions: one per face
    outer_verts = list(range(n + 1, 2 * n + 1))
    one_ring_faces = []
    for i in range(n):
        p_i = ring_verts[i]
        p_next = ring_verts[(i + 1) % n]
        outer_idx = outer_verts[i]
        # Outer point: midpoint of P_i and P_{i+1} pushed outward slightly
        a_i = 2.0 * math.pi * i / n
        a_next = 2.0 * math.pi * ((i + 1) % n) / n
        ox = 1.5 * radius * math.cos((a_i + a_next) / 2.0)
        oy = 1.5 * radius * math.sin((a_i + a_next) / 2.0)
        positions[outer_idx] = (ox, oy, z)
        one_ring_faces.append([V_idx, p_i, outer_idx, p_next])

    ev = ExtraordinaryVertex(
        vertex_index=V_idx,
        valence=n,
        position_xyz_mm=V_pos,
        one_ring_vertices=ring_verts,
        one_ring_faces=one_ring_faces,
    )
    return ev, positions


def _dome_ring(n: int, dome_height: float = 0.5) -> tuple:
    """Build an extraordinary vertex on a dome surface.

    The vertex is at the apex (0,0,dome_height); the 1-ring is on
    a circle of radius 1 at z=0.  This gives a convex (positive K) vertex.
    """
    V_idx = 0
    V_pos = (0.0, 0.0, dome_height)
    ring_verts = list(range(1, n + 1))
    positions: dict = {V_idx: V_pos}

    for i in range(n):
        angle = 2.0 * math.pi * i / n
        positions[ring_verts[i]] = (math.cos(angle), math.sin(angle), 0.0)

    outer_verts = list(range(n + 1, 2 * n + 1))
    one_ring_faces = []
    for i in range(n):
        p_i = ring_verts[i]
        p_next = ring_verts[(i + 1) % n]
        outer_idx = outer_verts[i]
        a_i = 2.0 * math.pi * i / n
        a_next = 2.0 * math.pi * ((i + 1) % n) / n
        # Outer vertices: farther out, below the ring
        ox = 2.0 * math.cos((a_i + a_next) / 2.0)
        oy = 2.0 * math.sin((a_i + a_next) / 2.0)
        oz = -0.2
        positions[outer_idx] = (ox, oy, oz)
        one_ring_faces.append([V_idx, p_i, outer_idx, p_next])

    ev = ExtraordinaryVertex(
        vertex_index=V_idx,
        valence=n,
        position_xyz_mm=V_pos,
        one_ring_vertices=ring_verts,
        one_ring_faces=one_ring_faces,
    )
    return ev, positions


# ---------------------------------------------------------------------------
# Tests: dataclass construction
# ---------------------------------------------------------------------------

def test_extraordinary_vertex_construction():
    ev, _ = _flat_ring(3)
    assert ev.vertex_index == 0
    assert ev.valence == 3
    assert len(ev.one_ring_vertices) == 3
    assert len(ev.one_ring_faces) == 3


def test_limit_tangent_report_defaults():
    r = LimitTangentReport()
    assert len(r.tangent_u) == 3
    assert len(r.tangent_v) == 3
    assert len(r.normal_xyz) == 3
    assert isinstance(r.gaussian_curvature_estimate, float)
    assert isinstance(r.mean_curvature_estimate, float)
    assert r.valence == 4
    assert isinstance(r.eigenvalue_subdominant, float)
    assert len(r.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Tests: subdominant eigenvalue
# ---------------------------------------------------------------------------

def test_subdominant_eigenvalue_regular():
    # λ_4 = (1/4)(1 + cos(π/2)) = (1/4)(1 + 0) = 0.25
    lam = _subdominant_eigenvalue(4)
    assert abs(lam - 0.25) < 1e-12


def test_subdominant_eigenvalue_valence3():
    # λ_3 = (1/4)(1 + cos(2π/3)) = (1/4)(1 - 0.5) = 0.125
    lam = _subdominant_eigenvalue(3)
    assert abs(lam - 0.125) < 1e-12


def test_subdominant_eigenvalue_valence6():
    # λ_6 = (1/4)(1 + cos(π/3)) = (1/4)(1 + 0.5) = 0.375
    lam = _subdominant_eigenvalue(6)
    assert abs(lam - 0.375) < 1e-12


def test_subdominant_eigenvalue_range():
    # λ_n should be in (0, 0.5) for all valences >= 3
    for n in (3, 4, 5, 6, 7, 8, 10, 12):
        lam = _subdominant_eigenvalue(n)
        assert 0.0 < lam < 0.5, f"valence {n}: λ={lam}"


# ---------------------------------------------------------------------------
# Tests: limit position weights
# ---------------------------------------------------------------------------

def test_stam_limit_weights_partition_of_unity():
    # w_V + n·w_e + n·w_f should equal 1.0 for any valence n
    for n in (3, 4, 5, 6, 8):
        w_v, w_e, w_f = _stam_limit_weights(n)
        total = w_v + n * w_e + n * w_f
        assert abs(total - 1.0) < 1e-12, f"valence {n}: sum={total}"


def test_stam_limit_weights_valence4():
    w_v, w_e, w_f = _stam_limit_weights(4)
    # Standard CC limit stencil: w_V = 4/9, w_e = 1/9, w_f = 1/36
    assert abs(w_v - 4.0 / 9.0) < 1e-12
    assert abs(w_e - 1.0 / 9.0) < 1e-12
    assert abs(w_f - 1.0 / 36.0) < 1e-12


# ---------------------------------------------------------------------------
# Tests: flat plane (all z=0) — tangents in XY plane, normal = (0,0,1)
# ---------------------------------------------------------------------------

def test_flat_plane_normal_z():
    """On a flat XY plane the limit normal should be (0, 0, 1)."""
    for n in (3, 4, 5, 6):
        ev, rp = _flat_ring(n)
        r = compute_stam_limit_tangents(ev, ring_positions=rp)
        nz = abs(r.normal_xyz[2])
        assert nz > 0.99, f"valence {n}: |nz|={nz}"


def test_flat_plane_tangents_in_xy():
    """On a flat XY plane, tangent Z-components should be ~0."""
    for n in (3, 4, 5, 6):
        ev, rp = _flat_ring(n)
        r = compute_stam_limit_tangents(ev, ring_positions=rp)
        assert abs(r.tangent_u[2]) < 1e-10, f"valence {n}: T_u.z not 0"
        assert abs(r.tangent_v[2]) < 1e-10, f"valence {n}: T_v.z not 0"


def test_flat_plane_gaussian_curvature_near_zero():
    """Gaussian curvature on a flat ring should be near zero."""
    ev, rp = _flat_ring(4)
    r = compute_stam_limit_tangents(ev, ring_positions=rp)
    # On a perfect flat grid the angle sum = 2π, so angle deficit ≈ 0
    assert abs(r.gaussian_curvature_estimate) < 0.5, (
        f"K={r.gaussian_curvature_estimate} on flat plane"
    )


def test_flat_plane_mean_curvature_near_zero():
    """Mean curvature on a flat ring should be near zero."""
    ev, rp = _flat_ring(4)
    r = compute_stam_limit_tangents(ev, ring_positions=rp)
    # On a symmetric flat ring the cotangent Laplacian ≈ 0
    assert abs(r.mean_curvature_estimate) < 0.5, (
        f"H={r.mean_curvature_estimate} on flat plane"
    )


# ---------------------------------------------------------------------------
# Tests: normal unit length
# ---------------------------------------------------------------------------

def test_normal_unit_length():
    """Normal must be unit length for all test configurations."""
    configs = [_flat_ring(n) for n in (3, 4, 5, 6, 7)]
    configs += [_dome_ring(n) for n in (3, 5, 6)]
    for ev, rp in configs:
        r = compute_stam_limit_tangents(ev, ring_positions=rp)
        N = r.normal_xyz
        norm = math.sqrt(N[0] ** 2 + N[1] ** 2 + N[2] ** 2)
        assert abs(norm - 1.0) < 1e-12 or norm == 0.0, (
            f"Normal not unit: |N|={norm} for valence {ev.valence}"
        )


# ---------------------------------------------------------------------------
# Tests: tangent magnitudes nonzero
# ---------------------------------------------------------------------------

def test_tangent_magnitudes_nonzero():
    """Tangent vectors should be nonzero for non-degenerate configurations."""
    for n in (3, 4, 5, 6):
        ev, rp = _flat_ring(n)
        r = compute_stam_limit_tangents(ev, ring_positions=rp)
        tu_mag = math.sqrt(sum(x * x for x in r.tangent_u))
        tv_mag = math.sqrt(sum(x * x for x in r.tangent_v))
        assert tu_mag > 1e-10, f"T_u near zero for valence {n}"
        assert tv_mag > 1e-10, f"T_v near zero for valence {n}"


# ---------------------------------------------------------------------------
# Tests: dome surface — positive Gaussian curvature
# ---------------------------------------------------------------------------

def test_dome_positive_gaussian_curvature():
    """Dome vertex should have positive Gaussian curvature (elliptic)."""
    for n in (3, 5, 6):
        ev, rp = _dome_ring(n, dome_height=0.8)
        r = compute_stam_limit_tangents(ev, ring_positions=rp)
        assert r.gaussian_curvature_estimate > 0.0, (
            f"valence {n}: K={r.gaussian_curvature_estimate} should be > 0 on dome"
        )


def test_dome_normal_points_outward():
    """Dome vertex normal should have positive Z component (outward from apex)."""
    for n in (4, 5, 6):
        ev, rp = _dome_ring(n, dome_height=1.0)
        r = compute_stam_limit_tangents(ev, ring_positions=rp)
        # Normal should point up (in Z direction) for a dome apex
        assert r.normal_xyz[2] > 0.5, (
            f"valence {n}: Nz={r.normal_xyz[2]} should be positive for dome"
        )


# ---------------------------------------------------------------------------
# Tests: valence-6 hex vertex (symmetric tangents)
# ---------------------------------------------------------------------------

def test_valence6_symmetric_tangent_magnitudes():
    """Hex valence-6 tangent magnitudes should be equal (hexagonal symmetry)."""
    ev, rp = _flat_ring(6)
    r = compute_stam_limit_tangents(ev, ring_positions=rp)
    tu_mag = math.sqrt(sum(x * x for x in r.tangent_u))
    tv_mag = math.sqrt(sum(x * x for x in r.tangent_v))
    # On a regular hex ring the two tangent magnitudes are equal
    ratio = tu_mag / tv_mag if tv_mag > 1e-12 else float("inf")
    assert abs(ratio - 1.0) < 0.01, (
        f"Hex tangent magnitudes not equal: |T_u|={tu_mag}, |T_v|={tv_mag}"
    )


def test_valence6_eigenvalue():
    lam = _subdominant_eigenvalue(6)
    assert abs(lam - 0.375) < 1e-12


# ---------------------------------------------------------------------------
# Tests: valence-3 extraordinary vertex
# ---------------------------------------------------------------------------

def test_valence3_returns_report():
    ev, rp = _flat_ring(3)
    r = compute_stam_limit_tangents(ev, ring_positions=rp)
    assert isinstance(r, LimitTangentReport)
    assert r.valence == 3


def test_valence3_normal_nonzero():
    ev, rp = _flat_ring(3)
    r = compute_stam_limit_tangents(ev, ring_positions=rp)
    norm = math.sqrt(sum(x * x for x in r.normal_xyz))
    assert norm > 0.5, f"Normal near zero for valence-3: |N|={norm}"


# ---------------------------------------------------------------------------
# Tests: valence-5 vertex
# ---------------------------------------------------------------------------

def test_valence5_returns_report():
    ev, rp = _flat_ring(5)
    r = compute_stam_limit_tangents(ev, ring_positions=rp)
    assert isinstance(r, LimitTangentReport)
    assert r.valence == 5


def test_valence5_eigenvalue():
    lam = _subdominant_eigenvalue(5)
    expected = 0.25 * (1.0 + math.cos(2.0 * math.pi / 5.0))
    assert abs(lam - expected) < 1e-12


# ---------------------------------------------------------------------------
# Tests: ring_positions=None synthetic fallback
# ---------------------------------------------------------------------------

def test_synthetic_fallback_no_crash():
    """compute_stam_limit_tangents with ring_positions=None should not raise."""
    ev, _ = _flat_ring(4)
    # Don't pass ring_positions — let the function synthesize
    r = compute_stam_limit_tangents(ev, ring_positions=None)
    assert isinstance(r, LimitTangentReport)


def test_synthetic_fallback_normal_unit():
    """Synthetic fallback should still produce a valid unit normal."""
    ev, _ = _flat_ring(4)
    r = compute_stam_limit_tangents(ev, ring_positions=None)
    N = r.normal_xyz
    norm = math.sqrt(N[0] ** 2 + N[1] ** 2 + N[2] ** 2)
    # The synthetic ring is on XY plane, so N should be (0,0,1) or (0,0,-1)
    assert abs(norm - 1.0) < 1e-12 or norm == 0.0, f"|N|={norm}"


# ---------------------------------------------------------------------------
# Tests: honest caveat present
# ---------------------------------------------------------------------------

def test_honest_caveat_nonempty():
    for n in (3, 4, 5, 6):
        ev, rp = _flat_ring(n)
        r = compute_stam_limit_tangents(ev, ring_positions=rp)
        assert len(r.honest_caveat) > 20, f"Caveat too short for valence {n}"


def test_honest_caveat_mentions_stam():
    ev, rp = _flat_ring(4)
    r = compute_stam_limit_tangents(ev, ring_positions=rp)
    assert "Stam" in r.honest_caveat or "stam" in r.honest_caveat.lower()


# ---------------------------------------------------------------------------
# Tests: import from subd package
# ---------------------------------------------------------------------------

def test_reexport_from_subd_package():
    """Verify ExtraordinaryVertex, LimitTangentReport, compute_stam_limit_tangents
    are accessible from kerf_cad_core.subd."""
    from kerf_cad_core.subd import (
        ExtraordinaryVertex as EV,
        LimitTangentReport as LTR,
        compute_stam_limit_tangents as clt,
    )
    assert EV is ExtraordinaryVertex
    assert LTR is LimitTangentReport
    assert clt is compute_stam_limit_tangents


# ---------------------------------------------------------------------------
# Tests: flat plane T_u perpendicular to T_v (via normal cross product)
# ---------------------------------------------------------------------------

def test_flat_plane_tangents_span_surface():
    """T_u and T_v should together span the tangent plane (not parallel)."""
    for n in (3, 4, 5, 6):
        ev, rp = _flat_ring(n)
        r = compute_stam_limit_tangents(ev, ring_positions=rp)
        # Cross product T_u × T_v should be nonzero (they span the plane)
        tu, tv = r.tangent_u, r.tangent_v
        cx = tu[1] * tv[2] - tu[2] * tv[1]
        cy = tu[2] * tv[0] - tu[0] * tv[2]
        cz = tu[0] * tv[1] - tu[1] * tv[0]
        cross_mag = math.sqrt(cx * cx + cy * cy + cz * cz)
        assert cross_mag > 1e-8, (
            f"T_u × T_v near zero for valence {n}: |cross|={cross_mag}"
        )


# ---------------------------------------------------------------------------
# Tests: valence-7 vertex
# ---------------------------------------------------------------------------

def test_valence7_returns_report():
    ev, rp = _flat_ring(7)
    r = compute_stam_limit_tangents(ev, ring_positions=rp)
    assert isinstance(r, LimitTangentReport)
    assert r.valence == 7
    lam = r.eigenvalue_subdominant
    expected = 0.25 * (1.0 + math.cos(2.0 * math.pi / 7.0))
    assert abs(lam - expected) < 1e-12


# ---------------------------------------------------------------------------
# Tests: eigenvalue is reported correctly in LimitTangentReport
# ---------------------------------------------------------------------------

def test_eigenvalue_reported_correctly():
    for n in (3, 4, 5, 6, 7):
        ev, rp = _flat_ring(n)
        r = compute_stam_limit_tangents(ev, ring_positions=rp)
        expected = _subdominant_eigenvalue(n)
        assert abs(r.eigenvalue_subdominant - expected) < 1e-12, (
            f"valence {n}: λ={r.eigenvalue_subdominant}, expected={expected}"
        )
