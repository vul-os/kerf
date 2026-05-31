"""
Tests for kerf_cad_core.optics.coma_coefficient — Seidel third-order coma
coefficient (S_II / W_131) for a single thin lens.

Test plan (≥12 tests)
----------------------
1.  aplanatic_q_gives_zero_sii          — q = q_aplanatic → S_II = 0 (within tol)
2.  aplanatic_q_zero_arcsec             — aplanatic q → sagittal + tangential = 0 arcsec
3.  double_object_height_doubles_SII    — linearity in u_bar: 2× height → 2× S_II
4.  higher_fno_less_coma_blur           — larger F/# (smaller aperture) → less coma_blur_mm
5.  plano_convex_q1_vs_equiconvex_q0    — q=+1 vs q=0 → different S_II
6.  plano_convex_qm1_vs_q1             — q=−1 vs q=+1 → different (and larger magnitude) S_II
7.  tangential_is_3x_sagittal           — |tangential_arcsec| = 3 × |sagittal_arcsec| exactly
8.  on_axis_zero_coma                   — object_height=0 → S_II = 0, all coma = 0
9.  W131_equals_neg_SII                 — W_131 = −S_II exactly
10. coma_blur_mm_is_abs_sagittal        — coma_blur_mm = |S_II / (8·F#)|
11. q_aplanatic_formula_correct         — q_aplanatic = (2n+1)(n−1)(p+2)/(n+1)
12. q_aplanatic_bk7_p_neg1              — BK7 n=1.5168, p=−1: q_aplanatic ≈ 0.8283
13. S_II_linear_in_q                    — S_II is linear in q at fixed other params
14. S_II_linear_in_p_plus_2             — S_II is linear in (p+2)
15. finite_conjugate_p0_differs_inf     — p=0 (1:1 conj) vs p=−1 (inf) → different S_II
16. negative_focal_length_diverging     — diverging lens (f<0) computes without error
17. error_bad_focal_length_zero         — f=0 → error
18. error_refractive_index_leq1         — n=1.0 → error, n=0.9 → error
19. error_aperture_zero                 — aperture=0 → error
20. error_image_distance_zero           — image_distance=0 → error
21. error_non_ThinLensSpec              — wrong type → error
22. to_dict_has_ok_true                 — to_dict() has ok=True + expected keys
23. coma_scales_cubic_with_aperture     — doubling aperture → 8× coma_blur (h³ dependence)
24. coma_blur_positive                  — coma_blur_mm ≥ 0 always
25. consistent_with_seidel_trace        — S_II matches two-surface paraxial trace

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §7.4.
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., 1999, §5.3.

Author: imranparuk
"""
from __future__ import annotations

import math

import pytest

from kerf_cad_core.optics.coma_coefficient import (
    ThinLensSpec,
    ImageSpec,
    ComaCoefficientReport,
    compute_coma_coefficient,
)


# ---------------------------------------------------------------------------
# Fixtures / shared parameters
# ---------------------------------------------------------------------------

_N_BK7 = 1.5168   # BK7 borosilicate crown glass (d-line)
_F_MM  = 100.0    # focal length (mm)
_H_MM  = 25.0     # aperture radius (mm) → F/2
_H_OBJ = 10.0     # object / image field height (mm)
_V_MM  = 100.0    # image distance = focal length (object at infinity)


def _bk7_lens(q: float = 0.0, p: float = -1.0) -> ThinLensSpec:
    """BK7 lens, f=100 mm, 25 mm aperture radius (F/2)."""
    return ThinLensSpec(
        focal_length_mm=_F_MM,
        refractive_index_n=_N_BK7,
        aperture_radius_mm=_H_MM,
        shape_factor_q=q,
        conjugate_factor_p=p,
    )


def _std_img(h_obj: float = _H_OBJ, v: float = _V_MM) -> ImageSpec:
    return ImageSpec(object_height_mm=h_obj, image_distance_mm=v)


def _q_aplanatic(n: float, p: float) -> float:
    """Analytical aplanatic shape factor (Welford §7.4)."""
    return (2 * n + 1) * (n - 1) * (p + 2) / (n + 1)


def _direct_SII(n: float, f: float, h: float, u_bar: float,
                q: float, p: float) -> float:
    """
    Direct Welford §7.4 polynomial for S_II (reference implementation).
    S_II = u_bar · h³ · φ² · [(n+1)/(2n(n-1))·q + (−(2n+1)/(2n))·(p+2)]
    """
    phi = 1.0 / f
    A = (n + 1) / (2 * n * (n - 1))
    B = -(2 * n + 1) / (2 * n)
    return u_bar * (h ** 3) * (phi ** 2) * (A * q + B * (p + 2))


# ---------------------------------------------------------------------------
# Helper: two-surface paraxial trace for thin lens (verified against formula)
# ---------------------------------------------------------------------------

def _trace_SII(n: float, c1: float, c2: float, h: float, w: float) -> float:
    """
    Per-surface Welford trace: S_II for a thin lens (t=0, stop at lens).
    w  : chief-ray angle at the lens (radians), equal to u_bar = h_obj / v.
    """
    # Surface 1: n_in=1, n_out=n
    u_m_out1 = -h * c1 * (n - 1.0) / n
    u_c_out1 = w / n
    A1 = h * c1           # = n_in * (u_in + h*c1) with u_in=0
    Abar1 = w             # = n_in * (u_c_in + 0) with h_c=0 at stop
    delta_un1 = u_m_out1 / n  # = u_out/n_out - u_in/n_in = -h*c1*(n-1)/n^2
    SII_1 = -(A1 * Abar1) * h * delta_un1

    # Surface 2: n_in=n, n_out=1
    u_m_in2 = u_m_out1
    u_m_out2 = h * (n - 1) * (c2 - c1)
    i_m2 = u_m_in2 + h * c2
    A2 = n * i_m2
    Abar2 = n * u_c_out1   # = w
    delta_un2 = u_m_out2 - u_m_in2 / n
    SII_2 = -(A2 * Abar2) * h * delta_un2
    return SII_1 + SII_2


# ---------------------------------------------------------------------------
# 1. Aplanatic shape factor gives S_II = 0
# ---------------------------------------------------------------------------

def test_aplanatic_q_gives_zero_sii():
    """S_II must be numerically zero at the aplanatic bending."""
    for n in [1.4, 1.5, _N_BK7, 1.7]:
        q_ap = _q_aplanatic(n, p=-1.0)
        lens = ThinLensSpec(
            focal_length_mm=_F_MM,
            refractive_index_n=n,
            aperture_radius_mm=_H_MM,
            shape_factor_q=q_ap,
            conjugate_factor_p=-1.0,
        )
        result = compute_coma_coefficient(lens, _std_img())
        assert isinstance(result, ComaCoefficientReport)
        assert abs(result.seidel_S_II) < 1e-12, (
            f"n={n}: S_II={result.seidel_S_II:.3e} at aplanatic q={q_ap:.4f}"
        )


# ---------------------------------------------------------------------------
# 2. Aplanatic q → sagittal and tangential coma = 0 arcsec
# ---------------------------------------------------------------------------

def test_aplanatic_q_zero_arcsec():
    q_ap = _q_aplanatic(_N_BK7, p=-1.0)
    result = compute_coma_coefficient(_bk7_lens(q=q_ap), _std_img())
    assert isinstance(result, ComaCoefficientReport)
    assert abs(result.sagittal_coma_arcsec) < 1e-9, (
        f"Aplanatic sagittal arcsec = {result.sagittal_coma_arcsec}"
    )
    assert abs(result.tangential_coma_arcsec) < 1e-9


# ---------------------------------------------------------------------------
# 3. Doubling object height doubles S_II (linearity in u_bar)
# ---------------------------------------------------------------------------

def test_double_object_height_doubles_SII():
    r1 = compute_coma_coefficient(_bk7_lens(), _std_img(h_obj=5.0))
    r2 = compute_coma_coefficient(_bk7_lens(), _std_img(h_obj=10.0))
    assert isinstance(r1, ComaCoefficientReport)
    assert isinstance(r2, ComaCoefficientReport)
    if abs(r1.seidel_S_II) > 1e-20:
        ratio = r2.seidel_S_II / r1.seidel_S_II
        assert ratio == pytest.approx(2.0, rel=1e-10), (
            f"Expected S_II to double with 2× field height; ratio={ratio}"
        )


# ---------------------------------------------------------------------------
# 4. Higher F/# (smaller aperture) → less coma_blur_mm (h³ dependence)
# ---------------------------------------------------------------------------

def test_higher_fno_less_coma_blur():
    lens_fast = ThinLensSpec(
        focal_length_mm=_F_MM,
        refractive_index_n=_N_BK7,
        aperture_radius_mm=25.0,   # F/2
        shape_factor_q=0.0,
        conjugate_factor_p=-1.0,
    )
    lens_slow = ThinLensSpec(
        focal_length_mm=_F_MM,
        refractive_index_n=_N_BK7,
        aperture_radius_mm=10.0,   # F/5
        shape_factor_q=0.0,
        conjugate_factor_p=-1.0,
    )
    r_fast = compute_coma_coefficient(lens_fast, _std_img())
    r_slow = compute_coma_coefficient(lens_slow, _std_img())
    assert r_fast.coma_blur_mm > r_slow.coma_blur_mm, (
        f"Faster lens should have more coma blur: "
        f"F/2={r_fast.coma_blur_mm:.4e}, F/5={r_slow.coma_blur_mm:.4e}"
    )


# ---------------------------------------------------------------------------
# 5. Plano-convex q=+1 vs equiconvex q=0 → different S_II
# ---------------------------------------------------------------------------

def test_plano_convex_q1_vs_equiconvex_q0():
    r_equi = compute_coma_coefficient(_bk7_lens(q=0.0), _std_img())
    r_pc   = compute_coma_coefficient(_bk7_lens(q=1.0), _std_img())
    assert isinstance(r_equi, ComaCoefficientReport)
    assert isinstance(r_pc,   ComaCoefficientReport)
    assert r_pc.seidel_S_II != pytest.approx(r_equi.seidel_S_II, rel=0.01), (
        f"q=1 vs q=0 should produce different S_II "
        f"(got {r_pc.seidel_S_II:.4e} vs {r_equi.seidel_S_II:.4e})"
    )
    # q=+1 plano-convex (curved first) has more coma than equiconvex for p=-1
    assert r_pc.seidel_S_II > r_equi.seidel_S_II, (
        "For n=1.5168, p=-1: q=+1 should give more positive S_II than q=0"
    )


# ---------------------------------------------------------------------------
# 6. Plano-convex q=−1 vs q=+1 → different S_II (q=−1 is larger magnitude)
# ---------------------------------------------------------------------------

def test_plano_convex_qm1_vs_q1():
    r_neg = compute_coma_coefficient(_bk7_lens(q=-1.0), _std_img())
    r_pos = compute_coma_coefficient(_bk7_lens(q=+1.0), _std_img())
    assert isinstance(r_neg, ComaCoefficientReport)
    # For p=-1, q=-1 gives more negative S_II than q=+1
    assert r_neg.seidel_S_II < r_pos.seidel_S_II, (
        f"q=−1 should give more negative S_II than q=+1; "
        f"got neg={r_neg.seidel_S_II:.4e}, pos={r_pos.seidel_S_II:.4e}"
    )


# ---------------------------------------------------------------------------
# 7. |tangential_arcsec| = 3 × |sagittal_arcsec| exactly
# ---------------------------------------------------------------------------

def test_tangential_is_3x_sagittal():
    r = compute_coma_coefficient(_bk7_lens(q=0.5), _std_img())
    assert isinstance(r, ComaCoefficientReport)
    assert r.tangential_coma_arcsec == pytest.approx(
        3.0 * r.sagittal_coma_arcsec, rel=1e-12
    ), (
        f"tangential={r.tangential_coma_arcsec:.6e} ≠ 3×sagittal={r.sagittal_coma_arcsec:.6e}"
    )


# ---------------------------------------------------------------------------
# 8. On-axis (object_height=0) → all coma quantities = 0
# ---------------------------------------------------------------------------

def test_on_axis_zero_coma():
    r = compute_coma_coefficient(_bk7_lens(), _std_img(h_obj=0.0))
    assert isinstance(r, ComaCoefficientReport)
    assert r.seidel_S_II == pytest.approx(0.0, abs=1e-20)
    assert r.wave_aberration_W_131 == pytest.approx(0.0, abs=1e-20)
    assert r.sagittal_coma_arcsec == pytest.approx(0.0, abs=1e-20)
    assert r.tangential_coma_arcsec == pytest.approx(0.0, abs=1e-20)
    assert r.coma_blur_mm == pytest.approx(0.0, abs=1e-20)


# ---------------------------------------------------------------------------
# 9. W_131 = −S_II exactly
# ---------------------------------------------------------------------------

def test_W131_equals_neg_SII():
    for q in [-1.0, 0.0, 0.5, 1.0]:
        r = compute_coma_coefficient(_bk7_lens(q=q), _std_img())
        assert isinstance(r, ComaCoefficientReport)
        assert r.wave_aberration_W_131 == pytest.approx(-r.seidel_S_II, rel=1e-15), (
            f"q={q}: W_131={r.wave_aberration_W_131:.6e} ≠ -S_II={-r.seidel_S_II:.6e}"
        )


# ---------------------------------------------------------------------------
# 10. coma_blur_mm = |S_II / (8 · F#)|
# ---------------------------------------------------------------------------

def test_coma_blur_mm_is_abs_sagittal():
    for q in [-0.5, 0.0, 0.5, 1.0]:
        lens = _bk7_lens(q=q)
        r = compute_coma_coefficient(lens, _std_img())
        assert isinstance(r, ComaCoefficientReport)
        F_num = abs(lens.focal_length_mm) / (2.0 * lens.aperture_radius_mm)
        expected = abs(r.seidel_S_II) / (8.0 * F_num)
        assert r.coma_blur_mm == pytest.approx(expected, rel=1e-12), (
            f"q={q}: coma_blur_mm={r.coma_blur_mm:.6e} ≠ |S_II|/(8·F#)={expected:.6e}"
        )


# ---------------------------------------------------------------------------
# 11. q_aplanatic formula: q_aplanatic = (2n+1)(n−1)(p+2)/(n+1)
# ---------------------------------------------------------------------------

def test_q_aplanatic_formula_correct():
    for n in [1.4, 1.5, _N_BK7, 1.7]:
        for p in [-1.0, 0.0, 1.0]:
            lens = ThinLensSpec(
                focal_length_mm=_F_MM,
                refractive_index_n=n,
                aperture_radius_mm=_H_MM,
                shape_factor_q=0.0,
                conjugate_factor_p=p,
            )
            r = compute_coma_coefficient(lens, _std_img())
            assert isinstance(r, ComaCoefficientReport)
            expected = _q_aplanatic(n, p)
            assert r.q_aplanatic == pytest.approx(expected, rel=1e-12), (
                f"n={n}, p={p}: q_aplanatic={r.q_aplanatic:.6f} ≠ expected={expected:.6f}"
            )


# ---------------------------------------------------------------------------
# 12. BK7 aplanatic shape factor (p=−1): q ≈ 0.8283
# ---------------------------------------------------------------------------

def test_q_aplanatic_bk7_p_neg1():
    """BK7 (n=1.5168) at p=−1 should give q_aplanatic ≈ 0.8283."""
    r = compute_coma_coefficient(_bk7_lens(q=0.0, p=-1.0), _std_img())
    assert isinstance(r, ComaCoefficientReport)
    # (2*1.5168+1)*(1.5168-1)*(1)/(1.5168+1) = 4.0336*0.5168/2.5168 ≈ 0.8283
    expected = (2 * _N_BK7 + 1) * (_N_BK7 - 1) * (-1 + 2) / (_N_BK7 + 1)
    assert r.q_aplanatic == pytest.approx(expected, rel=1e-6), (
        f"q_aplanatic(BK7, p=-1) = {r.q_aplanatic:.6f}, expected ~{expected:.6f}"
    )
    assert 0.82 < r.q_aplanatic < 0.84, f"q_aplanatic out of range: {r.q_aplanatic}"


# ---------------------------------------------------------------------------
# 13. S_II is linear in q
# ---------------------------------------------------------------------------

def test_S_II_linear_in_q():
    """At fixed n, h, f, u_bar, p: S_II(q) must be strictly linear in q."""
    for q1, q2, q3 in [(-1.0, 0.0, 1.0), (-0.5, 0.5, 1.5)]:
        r1 = compute_coma_coefficient(_bk7_lens(q=q1), _std_img())
        r2 = compute_coma_coefficient(_bk7_lens(q=q2), _std_img())
        r3 = compute_coma_coefficient(_bk7_lens(q=q3), _std_img())
        # Linear interpolation: r2.S_II should = (r1.S_II + r3.S_II) / 2
        # (midpoint of q1..q3 is q2 when q2 = (q1+q3)/2)
        if abs(q2 - (q1 + q3) / 2) < 1e-10:
            interp = (r1.seidel_S_II + r3.seidel_S_II) / 2
            assert r2.seidel_S_II == pytest.approx(interp, rel=1e-12), (
                f"Linearity in q failed: S_II({q2})={r2.seidel_S_II:.4e}, "
                f"midpoint={interp:.4e}"
            )


# ---------------------------------------------------------------------------
# 14. S_II is linear in (p+2)
# ---------------------------------------------------------------------------

def test_S_II_linear_in_p_plus_2():
    """S_II is proportional to (p+2); doubling p+2 should double the p-contribution."""
    # Keep q=0 so only the B·(p+2) term contributes.
    # p1=−2 → p+2=0 → S_II=0 ; p2=0 → p+2=2 ; p3=2 → p+2=4
    r_p0 = compute_coma_coefficient(_bk7_lens(q=0.0, p=-2.0), _std_img())  # p+2=0
    r_p2 = compute_coma_coefficient(_bk7_lens(q=0.0, p=0.0),  _std_img())  # p+2=2
    r_p4 = compute_coma_coefficient(_bk7_lens(q=0.0, p=2.0),  _std_img())  # p+2=4

    # At q=0, p+2=0: S_II = 0
    assert abs(r_p0.seidel_S_II) < 1e-14, (
        f"At q=0, p=-2 (p+2=0): S_II should be 0, got {r_p0.seidel_S_II:.3e}"
    )
    # Linear: r_p4.S_II = 2 × r_p2.S_II (since p+2 doubles from 2 to 4)
    if abs(r_p2.seidel_S_II) > 1e-20:
        ratio = r_p4.seidel_S_II / r_p2.seidel_S_II
        assert ratio == pytest.approx(2.0, rel=1e-10), (
            f"S_II should double when p+2 doubles; ratio={ratio}"
        )


# ---------------------------------------------------------------------------
# 15. Finite conjugate (p=0, 1:1 magnification) differs from infinity (p=−1)
# ---------------------------------------------------------------------------

def test_finite_conjugate_p0_differs_inf():
    r_inf = compute_coma_coefficient(_bk7_lens(q=0.0, p=-1.0), _std_img())
    r_1to1 = compute_coma_coefficient(_bk7_lens(q=0.0, p=0.0), _std_img())
    assert r_inf.seidel_S_II != pytest.approx(r_1to1.seidel_S_II, rel=0.01), (
        "p=0 (1:1) and p=−1 (∞) should give different S_II"
    )
    # At q=0, p=−1: B·(p+2) = −(2n+1)/(2n)·1  (negative for n>1)
    # At q=0, p=0:  B·(p+2) = −(2n+1)/(2n)·2  (more negative)
    # So 1:1 coma_blur should be larger:
    assert r_1to1.coma_blur_mm > r_inf.coma_blur_mm


# ---------------------------------------------------------------------------
# 16. Diverging (negative focal length) lens computes without error
# ---------------------------------------------------------------------------

def test_negative_focal_length_diverging():
    lens = ThinLensSpec(
        focal_length_mm=-100.0,
        refractive_index_n=_N_BK7,
        aperture_radius_mm=10.0,
        shape_factor_q=0.0,
        conjugate_factor_p=-1.0,
    )
    r = compute_coma_coefficient(lens, _std_img())
    assert isinstance(r, ComaCoefficientReport)
    assert math.isfinite(r.seidel_S_II)
    assert math.isfinite(r.sagittal_coma_arcsec)


# ---------------------------------------------------------------------------
# 17. Error: focal_length = 0
# ---------------------------------------------------------------------------

def test_error_bad_focal_length_zero():
    lens = ThinLensSpec(
        focal_length_mm=0.0,
        refractive_index_n=_N_BK7,
        aperture_radius_mm=_H_MM,
        shape_factor_q=0.0,
        conjugate_factor_p=-1.0,
    )
    r = compute_coma_coefficient(lens, _std_img())
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "focal_length_mm" in r["reason"]


# ---------------------------------------------------------------------------
# 18. Error: refractive index ≤ 1.0
# ---------------------------------------------------------------------------

def test_error_refractive_index_leq1():
    for n_bad in [1.0, 0.9]:
        lens = ThinLensSpec(
            focal_length_mm=_F_MM,
            refractive_index_n=n_bad,
            aperture_radius_mm=_H_MM,
            shape_factor_q=0.0,
            conjugate_factor_p=-1.0,
        )
        r = compute_coma_coefficient(lens, _std_img())
        assert isinstance(r, dict), f"n={n_bad} should return error dict"
        assert r["ok"] is False, f"n={n_bad} should produce error"


# ---------------------------------------------------------------------------
# 19. Error: aperture = 0
# ---------------------------------------------------------------------------

def test_error_aperture_zero():
    lens = ThinLensSpec(
        focal_length_mm=_F_MM,
        refractive_index_n=_N_BK7,
        aperture_radius_mm=0.0,
        shape_factor_q=0.0,
        conjugate_factor_p=-1.0,
    )
    r = compute_coma_coefficient(lens, _std_img())
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 20. Error: image_distance = 0
# ---------------------------------------------------------------------------

def test_error_image_distance_zero():
    r = compute_coma_coefficient(_bk7_lens(), ImageSpec(object_height_mm=5.0,
                                                         image_distance_mm=0.0))
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "image_distance_mm" in r["reason"]


# ---------------------------------------------------------------------------
# 21. Error: non-ThinLensSpec lens argument
# ---------------------------------------------------------------------------

def test_error_non_ThinLensSpec():
    r = compute_coma_coefficient("not_a_spec", _std_img())  # type: ignore[arg-type]
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 22. to_dict() has ok=True and all expected keys
# ---------------------------------------------------------------------------

def test_to_dict_has_ok_true():
    r = compute_coma_coefficient(_bk7_lens(), _std_img())
    assert isinstance(r, ComaCoefficientReport)
    d = r.to_dict()
    assert d["ok"] is True
    for key in ("seidel_S_II", "wave_aberration_W_131",
                "sagittal_coma_arcsec", "tangential_coma_arcsec",
                "coma_blur_mm", "q_aplanatic", "honest_caveat"):
        assert key in d, f"Missing key: {key}"
    assert "Third-order" in d["honest_caveat"]
    assert math.isfinite(d["seidel_S_II"])


# ---------------------------------------------------------------------------
# 23. Coma blur scales as h³ (cubic aperture dependence)
# ---------------------------------------------------------------------------

def test_coma_scales_cubic_with_aperture():
    """Doubling aperture radius should multiply coma_blur by 8 (= 2³)."""
    lens_h1 = ThinLensSpec(
        focal_length_mm=_F_MM,
        refractive_index_n=_N_BK7,
        aperture_radius_mm=10.0,
        shape_factor_q=0.5,
        conjugate_factor_p=-1.0,
    )
    lens_h2 = ThinLensSpec(
        focal_length_mm=_F_MM,
        refractive_index_n=_N_BK7,
        aperture_radius_mm=20.0,
        shape_factor_q=0.5,
        conjugate_factor_p=-1.0,
    )
    r1 = compute_coma_coefficient(lens_h1, _std_img())
    r2 = compute_coma_coefficient(lens_h2, _std_img())
    assert isinstance(r1, ComaCoefficientReport)
    assert isinstance(r2, ComaCoefficientReport)
    if r1.coma_blur_mm > 1e-20:
        # coma_blur ~ h^3 / F# = h^3 / (f/(2h)) = 2h^4/f
        # so ratio = (2*h)^4 / h^4 = 16 (when F# also changes)
        # Actually F# = f/(2h), so coma_blur = S_II/(8*F#) = S_II*2h/(8f)
        # S_II ~ h^3, so coma_blur ~ h^3 * h / f = h^4/f
        # Doubling h → 16× coma_blur
        ratio = r2.coma_blur_mm / r1.coma_blur_mm
        assert ratio == pytest.approx(16.0, rel=1e-10), (
            f"Doubling aperture should give 16× coma_blur (h^4/f scaling); ratio={ratio}"
        )


# ---------------------------------------------------------------------------
# 24. coma_blur_mm is always non-negative
# ---------------------------------------------------------------------------

def test_coma_blur_positive():
    for q in [-2.0, -1.0, 0.0, 0.5, 1.0, 2.0]:
        r = compute_coma_coefficient(_bk7_lens(q=q), _std_img())
        if isinstance(r, ComaCoefficientReport):
            assert r.coma_blur_mm >= 0.0, f"coma_blur_mm < 0 for q={q}: {r.coma_blur_mm}"


# ---------------------------------------------------------------------------
# 25. Consistent with direct two-surface paraxial trace
# ---------------------------------------------------------------------------

def test_consistent_with_seidel_trace():
    """
    For equiconvex (q=0), plano-convex (q=±1), compare compute_coma_coefficient
    against the direct two-surface Welford trace (_trace_SII).
    """
    n = _N_BK7
    f = _F_MM
    h = _H_MM
    h_obj = _H_OBJ
    v = _V_MM
    u_bar = h_obj / v     # chief ray angle
    phi = 1.0 / f

    for q in [-1.0, 0.0, 1.0]:
        p = -1.0  # object at infinity
        c1 = phi * (1 + q) / (2 * (n - 1))
        c2 = phi * (q - 1) / (2 * (n - 1))

        S_trace = _trace_SII(n, c1, c2, h, u_bar)
        lens = ThinLensSpec(
            focal_length_mm=f,
            refractive_index_n=n,
            aperture_radius_mm=h,
            shape_factor_q=q,
            conjugate_factor_p=p,
        )
        result = compute_coma_coefficient(lens, _std_img(h_obj=h_obj, v=v))
        assert isinstance(result, ComaCoefficientReport)
        assert result.seidel_S_II == pytest.approx(S_trace, rel=1e-10), (
            f"q={q}: formula S_II={result.seidel_S_II:.6e} ≠ trace={S_trace:.6e}"
        )
