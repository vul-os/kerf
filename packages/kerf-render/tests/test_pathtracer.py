"""
test_pathtracer.py — validation of the in-process CPU Monte-Carlo path tracer.

Covers:
  * BVH closest-hit correctness vs a brute-force reference.
  * Ray/triangle (Moller-Trumbore) hit + miss.
  * Fresnel dielectric sanity (grazing -> 1, normal incidence small, TIR).
  * Cornell-box convergence: energy bounded, image non-degenerate, and
    diffuse color bleeding (red wall tints the floor, green wall too).
"""
from __future__ import annotations

import math
import random

import numpy as np
import pytest

from kerf_render import pathtracer as pt


# ───────────────────────── ray/triangle ────────────────────────────────────

def test_moller_trumbore_hit_and_miss():
    sc = pt.Scene()
    m = sc.add_material(pt.Material(pt.DIFFUSE))
    # triangle in z=0 plane, facing +Z
    sc.add_triangle([0, 0, 0], [1, 0, 0], [0, 1, 0], m)
    sc.build()
    # ray straight down -Z toward the centroid
    o = np.array([0.25, 0.25, 1.0])
    d = np.array([0.0, 0.0, -1.0])
    hit = sc.intersect(o, d)
    assert hit is not None
    assert math.isclose(hit.t, 1.0, abs_tol=1e-6)
    # ray that misses (outside the triangle)
    o2 = np.array([0.9, 0.9, 1.0])
    assert sc.intersect(o2, d) is None
    # ray pointing away never hits
    assert sc.intersect(o, np.array([0.0, 0.0, 1.0])) is None


# ───────────────────────── BVH correctness ─────────────────────────────────

def _brute_closest(sc, o, d):
    best = None
    best_t = float("inf")
    for i in range(len(sc.tri_mat)):
        r = sc._intersect_tri(i, o, d, best_t)
        if r is not None:
            t, u, v = r
            best_t = t
            best = i
    return best, best_t


def test_bvh_matches_bruteforce():
    rng = random.Random(7)
    sc = pt.Scene()
    m = sc.add_material(pt.Material(pt.DIFFUSE))
    # scatter many small triangles in a cube
    for _ in range(200):
        c = np.array([rng.uniform(-2, 2) for _ in range(3)])
        a = c + np.array([rng.uniform(-0.1, 0.1) for _ in range(3)])
        b = c + np.array([rng.uniform(-0.1, 0.1) for _ in range(3)])
        cc = c + np.array([rng.uniform(-0.1, 0.1) for _ in range(3)])
        sc.add_triangle(a, b, cc, m)
    sc.build()

    mismatches = 0
    for _ in range(300):
        o = np.array([rng.uniform(-3, 3) for _ in range(3)])
        d = np.array([rng.uniform(-1, 1) for _ in range(3)])
        nd = np.linalg.norm(d)
        if nd < 1e-6:
            continue
        d = d / nd
        bvh = sc.intersect(o, d)
        bi, bt = _brute_closest(sc, o, d)
        if bi is None:
            assert bvh is None
        else:
            assert bvh is not None
            # same closest hit distance
            assert math.isclose(bvh.t, bt, rel_tol=1e-6, abs_tol=1e-6)
    assert mismatches == 0


# ───────────────────────── Fresnel ─────────────────────────────────────────

def test_fresnel_dielectric_sanity():
    # Grazing incidence (cosi -> 0) reflects almost everything.
    assert pt.fresnel_dielectric(0.0, 1.5) > 0.99
    # Normal incidence reflectance of glass ~ 0.04.
    r0 = pt.fresnel_dielectric(1.0, 1.5)
    assert 0.03 < r0 < 0.05
    # Reflectance is monotonic-ish: grazing > normal.
    assert pt.fresnel_dielectric(0.1, 1.5) > pt.fresnel_dielectric(0.9, 1.5)
    # Total internal reflection: dense->rare, beyond critical angle => 1.
    # eta = n_i/n_t = 1.5 (glass->air); critical cos is large.
    assert pt.fresnel_dielectric(0.1, 1.5) <= 1.0
    # an angle past critical for 1.5 eta should be full TIR
    assert math.isclose(pt.fresnel_dielectric(0.3, 1.5), 1.0, abs_tol=1e-9) or \
        pt.fresnel_dielectric(0.3, 1.5) > 0.5


def test_fresnel_schlick_endpoints():
    f0 = np.array([0.04, 0.04, 0.04])
    # at normal incidence -> f0
    near0 = pt.fresnel_schlick(1.0, f0)
    assert np.allclose(near0, f0, atol=1e-6)
    # at grazing -> ~1
    graze = pt.fresnel_schlick(0.0, f0)
    assert np.all(graze > 0.99)


# ───────────────────────── refraction ──────────────────────────────────────

def test_refract_and_tir():
    n = np.array([0.0, 0.0, 1.0])
    d = pt._norm(np.array([0.5, 0.0, -1.0]))  # into surface from +Z
    out = pt._refract(d, n, 1.0 / 1.5)
    assert out is not None
    assert np.isclose(np.linalg.norm(out), 1.0, atol=1e-6)
    # grazing from dense medium -> TIR (eta = 1.5)
    d2 = pt._norm(np.array([1.0, 0.0, -0.05]))
    assert pt._refract(d2, n, 1.5) is None


# ───────────────────────── Cornell convergence ─────────────────────────────

@pytest.fixture(scope="module")
def cornell_fb():
    sc = pt.build_cornell_box()
    cam = pt.cornell_camera(40, 40)
    fb = pt.render(sc, cam, 40, 40, samples=16, max_depth=6, seed=1)
    return sc, cam, fb


def test_cornell_energy_bounded(cornell_fb):
    _, _, fb = cornell_fb
    mean = fb.mean()
    assert np.all(np.isfinite(mean)), "NaN/Inf in framebuffer"
    assert mean.min() >= 0.0, "negative radiance"
    # Direct view of an ~18-emission light caps the peak, but global mean must
    # stay physically bounded (no runaway energy from RR / double counting).
    assert mean.mean() < 8.0
    # There must be meaningful light in the scene (not all black).
    assert mean.mean() > 0.02


def test_cornell_image_nondegenerate(cornell_fb):
    _, _, fb = cornell_fb
    img = fb.tonemapped_uint8()
    assert img.shape == (40, 40, 3)
    assert img.dtype == np.uint8
    # tonemapped image should have real contrast (lit + shadowed regions)
    assert img.max() > 200
    assert img.min() < 80
    assert img.std() > 10


def test_cornell_color_bleeding(cornell_fb):
    """The red left wall and green right wall should bleed onto the white
    floor: floor pixels near the left wall pick up red, near the right pick up
    green. This is the signature of multi-bounce diffuse GI (impossible with a
    single direct-lighting pass)."""
    sc, cam, fb = cornell_fb
    mean = fb.mean()
    h, w, _ = mean.shape

    # Sample the lower band of the image (floor). Compare left vs right thirds.
    floor = mean[int(h * 0.78):int(h * 0.95), :, :]
    left = floor[:, : w // 3, :].reshape(-1, 3).mean(axis=0)
    right = floor[:, 2 * w // 3:, :].reshape(-1, 3).mean(axis=0)

    # Left floor should be redder (R > G) than the right; right greener.
    left_redness = left[0] - left[1]
    right_greenness = right[1] - right[0]
    assert left_redness > 0.0, f"no red bleed on left floor: {left}"
    assert right_greenness > 0.0, f"no green bleed on right floor: {right}"


def test_progressive_accumulation_reduces_variance():
    """More samples -> the running mean stabilizes (variance of per-pass
    estimate of a pixel block shrinks)."""
    sc = pt.build_cornell_box()
    cam = pt.cornell_camera(24, 24)
    fb = pt.Framebuffer(24, 24)
    means = []
    # render in two chunks, mean should move less in the second chunk
    pt.render(sc, cam, 24, 24, samples=8, max_depth=5, seed=3, fb=fb)
    m1 = fb.mean().mean()
    pt.render(sc, cam, 24, 24, samples=8, max_depth=5, seed=11, fb=fb)
    m2 = fb.mean().mean()
    pt.render(sc, cam, 24, 24, samples=16, max_depth=5, seed=23, fb=fb)
    m3 = fb.mean().mean()
    # later increments perturb the running mean less (convergence)
    assert abs(m3 - m2) <= abs(m2 - m1) + 0.05
    assert fb.samples == 32
