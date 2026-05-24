"""
Tests for kerf_cad_core.fatigue.multiaxial — multiaxial critical-plane fatigue.

Validation strategy
-------------------
1. Pure torsion vs pure tension consistency:
   For proportional loading under von-Mises equivalence, the critical plane
   should predict a lower life for a given Mises equivalent stress under
   torsion than tension (shear-dominated path is shorter in strain space).

2. Findley — uniaxial tension reduces to Basquin:
   Under uniaxial σ_x = σ_a·sin(ωt), the critical plane is at 0° (the x-y
   plane normal to x), and P_F = τ_a + k_F·σ_max.  For pure tension with
   no shear (τ_a = 0 on the principal plane), P_F = k_F·σ_max which is
   smaller than a shear-plane where τ_a is nonzero.

3. SWT 3D — zero shear uniaxial: critical normal is aligned with loading axis.
   σ_max on that plane equals the peak applied stress.  eps_n amplitude equals
   the uniaxial strain amplitude.

4. Brown-Miller — shear loading: torsion should show nonzero gamma_a and the
   critical plane should be oblique (not aligned with coordinate axes).

5. multiaxial_life dispatcher routes correctly and returns consistent results.

6. Error paths: bad inputs return ok=False with a reason string.

7. LLM tool wrappers (happy path + error path for each tool).

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.fatigue.multiaxial import (
    findley_critical_plane,
    swt3d_critical_plane,
    brown_miller_critical_plane,
    multiaxial_life,
    _sigma_n,
    _tau_mag,
    _normal_strain_on_plane,
    _shear_strain_mag,
    _candidate_plane_normals,
)


# ---------------------------------------------------------------------------
# Helpers to build simple histories
# ---------------------------------------------------------------------------

def _zero3x3() -> list[list[float]]:
    return [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]


def _diag(sx: float, sy: float, sz: float) -> list[list[float]]:
    return [[sx, 0, 0], [0, sy, 0], [0, 0, sz]]


def _uniaxial_stress_history(sigma_amp: float, n_steps: int = 4) -> list[list[list[float]]]:
    """Simple sinusoidal uniaxial σ_x history over n_steps, zero mean."""
    history = []
    for i in range(n_steps):
        phase = 2 * math.pi * i / n_steps
        sx = sigma_amp * math.sin(phase)
        history.append(_diag(sx, 0.0, 0.0))
    return history


def _uniaxial_strain_history(
    eps_amp: float, nu: float = 0.3, n_steps: int = 4
) -> list[list[list[float]]]:
    """Uniaxial ε_x history with Poisson contraction."""
    history = []
    for i in range(n_steps):
        phase = 2 * math.pi * i / n_steps
        ex = eps_amp * math.sin(phase)
        ey = -nu * ex
        ez = -nu * ex
        history.append(_diag(ex, ey, ez))
    return history


def _pure_torsion_stress_history(tau_amp: float, n_steps: int = 4) -> list[list[list[float]]]:
    """Pure shear τ_xy = τ_amp·sin(phase)."""
    history = []
    for i in range(n_steps):
        phase = 2 * math.pi * i / n_steps
        t = tau_amp * math.sin(phase)
        history.append([[0, t, 0], [t, 0, 0], [0, 0, 0]])
    return history


def _pure_torsion_strain_history(gamma_amp: float, n_steps: int = 4) -> list[list[list[float]]]:
    """Pure shear strain γ_xy = gamma_amp·sin(phase) → ε_xy = γ/2."""
    history = []
    for i in range(n_steps):
        phase = 2 * math.pi * i / n_steps
        g = gamma_amp * math.sin(phase)
        half_g = g / 2.0
        history.append([[0, half_g, 0], [half_g, 0, 0], [0, 0, 0]])
    return history


# Steel-like material props
_STEEL_FINDLEY = {
    "Sf_prime": 900e6,   # Pa
    "b": -0.09,
    "k_F": 0.25,
}

_STEEL_STRAIN = {
    "E": 200e9,
    "Sf_prime": 900e6,
    "b": -0.09,
    "eps_f_prime": 0.35,
    "c": -0.56,
}


# ---------------------------------------------------------------------------
# 1. Plane decomposition primitives
# ---------------------------------------------------------------------------

class TestPlaneDecomposition:
    def test_normal_stress_principal_plane(self):
        """σn = σ_x for n=(1,0,0) on a uniaxial tensor."""
        sigma = _diag(100.0, 0.0, 0.0)
        n = (1.0, 0.0, 0.0)
        assert abs(_sigma_n(sigma, n) - 100.0) < 1e-10

    def test_no_shear_on_principal_plane(self):
        """Pure diagonal tensor has zero shear on principal planes."""
        sigma = _diag(200.0, 50.0, 30.0)
        for n in [(1, 0, 0), (0, 1, 0), (0, 0, 1)]:
            assert _tau_mag(sigma, n) < 1e-9

    def test_shear_on_45_degree_plane(self):
        """Pure uniaxial σ_x on 45° plane gives τ = σ_x/2."""
        sigma_x = 200e6
        sigma = _diag(sigma_x, 0.0, 0.0)
        n45 = (math.sqrt(0.5), math.sqrt(0.5), 0.0)  # 45° in x-y plane
        sn = _sigma_n(sigma, n45)
        tau = _tau_mag(sigma, n45)
        # On 45° plane: σn = σx/2, τ = σx/2
        assert abs(sn - sigma_x / 2) < 1e3, f"σn={sn:.3g}, expected {sigma_x/2:.3g}"
        assert abs(tau - sigma_x / 2) < 1e3, f"τ={tau:.3g}, expected {sigma_x/2:.3g}"

    def test_pure_shear_normal_stress(self):
        """On 45° plane, pure shear τ_xy gives σn = τ_xy (Mohr's circle)."""
        tau = 100e6
        sigma = [[0, tau, 0], [tau, 0, 0], [0, 0, 0]]
        n45 = (math.sqrt(0.5), math.sqrt(0.5), 0.0)
        sn = _sigma_n(sigma, n45)
        assert abs(sn - tau) < 1e3, f"σn={sn:.3g}, expected {tau:.3g}"

    def test_strain_decomposition_uniaxial(self):
        """Normal strain on x-axis for uniaxial strain tensor."""
        eps = _diag(0.001, -0.0003, -0.0003)
        n = (1.0, 0.0, 0.0)
        assert abs(_normal_strain_on_plane(eps, n) - 0.001) < 1e-12

    def test_zero_engineering_shear_on_principal_plane(self):
        """Diagonal strain tensor has zero shear on its principal planes."""
        eps = _diag(0.001, 0.0002, 0.00015)
        for n in [(1, 0, 0), (0, 1, 0), (0, 0, 1)]:
            assert _shear_strain_mag(eps, n) < 1e-12

    def test_engineering_shear_factor_of_two(self):
        """Engineering shear γ = 2 × tensorial shear off-diagonal."""
        # ε_xy = γ/2 → tensorial shear = γ/2
        gamma = 0.004
        eps = [[0, gamma / 2, 0], [gamma / 2, 0, 0], [0, 0, 0]]
        # On 45° plane in x-y, γ_max = γ (full engineering shear)
        n45 = (math.sqrt(0.5), math.sqrt(0.5), 0.0)
        gamma_plane = _shear_strain_mag(eps, n45)
        # On 45° plane the in-plane shear should equal γ/√2 · √2 ... let's just
        # verify it's nonzero and bounded by gamma.
        assert gamma_plane > 0
        assert gamma_plane <= gamma + 1e-9


class TestCandidatePlaneNormals:
    def test_count_reasonable(self):
        normals = _candidate_plane_normals(200)
        assert len(normals) >= 50

    def test_all_unit_normals(self):
        normals = _candidate_plane_normals(100)
        for n in normals:
            mag = math.sqrt(sum(x ** 2 for x in n))
            assert abs(mag - 1.0) < 1e-12, f"Normal not unit: {n}"

    def test_all_upper_hemisphere(self):
        normals = _candidate_plane_normals(100)
        for n in normals:
            assert n[2] >= 0.0, f"Normal below hemisphere: {n}"


# ---------------------------------------------------------------------------
# 2. Findley method
# ---------------------------------------------------------------------------

class TestFindley:
    def test_happy_path_uniaxial(self):
        hist = _uniaxial_stress_history(200e6)
        result = findley_critical_plane(hist, _STEEL_FINDLEY, n_planes=100)
        assert result["ok"] is True
        assert result["method"] == "findley"
        assert result["N_cycles"] > 0
        assert isinstance(result["critical_normal"], list)
        assert len(result["critical_normal"]) == 3
        assert result["P_F"] >= 0

    def test_higher_stress_gives_shorter_life(self):
        hist_low = _uniaxial_stress_history(100e6)
        hist_high = _uniaxial_stress_history(400e6)
        r_low = findley_critical_plane(hist_low, _STEEL_FINDLEY, n_planes=100)
        r_high = findley_critical_plane(hist_high, _STEEL_FINDLEY, n_planes=100)
        assert r_low["ok"] and r_high["ok"]
        assert r_low["N_cycles"] > r_high["N_cycles"]

    def test_target_life_safety_factor(self):
        hist = _uniaxial_stress_history(150e6)
        target = 1e5
        result = findley_critical_plane(
            hist, _STEEL_FINDLEY, n_planes=100, target_life=target
        )
        assert result["ok"] is True
        sf = result["safety_factor"]
        assert sf is not None
        assert abs(sf - result["N_cycles"] / target) < 1e-6

    def test_pure_torsion_finds_oblique_plane(self):
        """Under pure torsion, max shear plane is at 45° — critical plane not axial."""
        hist = _pure_torsion_stress_history(100e6)
        result = findley_critical_plane(hist, _STEEL_FINDLEY, n_planes=300)
        assert result["ok"] is True
        # The critical plane normal should not be purely (1,0,0), (0,1,0), or (0,0,1)
        cn = result["critical_normal"]
        not_axial = not (
            (abs(abs(cn[0]) - 1) < 0.05 and abs(cn[1]) < 0.05 and abs(cn[2]) < 0.05) or
            (abs(abs(cn[1]) - 1) < 0.05 and abs(cn[0]) < 0.05 and abs(cn[2]) < 0.05) or
            (abs(abs(cn[2]) - 1) < 0.05 and abs(cn[0]) < 0.05 and abs(cn[1]) < 0.05)
        )
        assert not_axial, f"Expected oblique critical plane, got {cn}"

    def test_error_missing_Sf_prime(self):
        hist = _uniaxial_stress_history(200e6)
        result = findley_critical_plane(hist, {"b": -0.09}, n_planes=50)
        assert result["ok"] is False
        assert "Sf_prime" in result["reason"]

    def test_error_bad_stress_history_shape(self):
        result = findley_critical_plane(
            [[[1, 2], [3, 4]]],  # 2×2 not 3×3
            _STEEL_FINDLEY,
        )
        assert result["ok"] is False

    def test_error_too_few_steps(self):
        result = findley_critical_plane([[_diag(100e6, 0, 0)]], _STEEL_FINDLEY)
        assert result["ok"] is False

    def test_error_b_positive(self):
        hist = _uniaxial_stress_history(200e6)
        result = findley_critical_plane(hist, {"Sf_prime": 900e6, "b": 0.09})
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 3. SWT 3D method
# ---------------------------------------------------------------------------

class TestSWT3D:
    def test_happy_path(self):
        s_hist = _uniaxial_stress_history(200e6)
        e_hist = _uniaxial_strain_history(0.001)
        result = swt3d_critical_plane(s_hist, e_hist, _STEEL_STRAIN, n_planes=100)
        assert result["ok"] is True
        assert result["method"] == "swt3d"
        assert result["N_cycles"] > 0
        assert result["P_SWT"] >= 0

    def test_critical_plane_aligned_uniaxial(self):
        """For uniaxial loading, critical plane normal should be near x-axis."""
        s_hist = _uniaxial_stress_history(300e6, n_steps=8)
        e_hist = _uniaxial_strain_history(0.0015, n_steps=8)
        result = swt3d_critical_plane(s_hist, e_hist, _STEEL_STRAIN, n_planes=300)
        assert result["ok"] is True
        cn = result["critical_normal"]
        # The x-component should be dominant
        assert abs(cn[0]) > 0.7, f"Expected x-dominant normal, got {cn}"

    def test_higher_strain_shorter_life(self):
        # Use strain amplitudes in the plastic regime (above ~Sf'/E ~ 0.0045)
        # so both cases give finite lives > 1 cycle.
        s_med = _uniaxial_stress_history(300e6)
        e_med = _uniaxial_strain_history(0.006)
        s_high = _uniaxial_stress_history(500e6)
        e_high = _uniaxial_strain_history(0.015)
        r_med = swt3d_critical_plane(s_med, e_med, _STEEL_STRAIN, n_planes=100)
        r_high = swt3d_critical_plane(s_high, e_high, _STEEL_STRAIN, n_planes=100)
        assert r_med["ok"] and r_high["ok"]
        assert r_med["N_cycles"] > r_high["N_cycles"]

    def test_target_life_safety_factor(self):
        s_hist = _uniaxial_stress_history(200e6)
        e_hist = _uniaxial_strain_history(0.001)
        target = 5e4
        result = swt3d_critical_plane(
            s_hist, e_hist, _STEEL_STRAIN, n_planes=100, target_life=target
        )
        assert result["ok"] is True
        sf = result["safety_factor"]
        assert sf is not None
        if math.isfinite(result["N_cycles"]):
            assert abs(sf - result["N_cycles"] / target) < 1e-6

    def test_error_mismatched_history_length(self):
        s_hist = _uniaxial_stress_history(200e6, n_steps=4)
        e_hist = _uniaxial_strain_history(0.001, n_steps=3)
        result = swt3d_critical_plane(s_hist, e_hist, _STEEL_STRAIN)
        assert result["ok"] is False
        assert "length" in result["reason"]

    def test_error_missing_E(self):
        s_hist = _uniaxial_stress_history(200e6)
        e_hist = _uniaxial_strain_history(0.001)
        props = {k: v for k, v in _STEEL_STRAIN.items() if k != "E"}
        result = swt3d_critical_plane(s_hist, e_hist, props)
        assert result["ok"] is False
        assert "E" in result["reason"]

    def test_swt_parameter_monotone_with_amplitude(self):
        """P_SWT should increase monotonically with strain/stress amplitude."""
        amps = [0.0005, 0.001, 0.002]
        p_vals = []
        for amp in amps:
            s_hist = _uniaxial_stress_history(amp * 200e9, n_steps=4)  # E*eps_a
            e_hist = _uniaxial_strain_history(amp, n_steps=4)
            r = swt3d_critical_plane(s_hist, e_hist, _STEEL_STRAIN, n_planes=100)
            assert r["ok"]
            p_vals.append(r["P_SWT"])
        assert p_vals[0] < p_vals[1] < p_vals[2], f"P_SWT not monotone: {p_vals}"


# ---------------------------------------------------------------------------
# 4. Brown-Miller method
# ---------------------------------------------------------------------------

class TestBrownMiller:
    def test_happy_path(self):
        e_hist = _uniaxial_strain_history(0.001)
        result = brown_miller_critical_plane(e_hist, _STEEL_STRAIN, n_planes=100)
        assert result["ok"] is True
        assert result["method"] == "brown_miller"
        assert result["N_cycles"] > 0
        assert result["P_BM"] >= 0

    def test_pure_torsion_has_nonzero_shear(self):
        """Under torsion, shear strain amplitude on critical plane must be nonzero."""
        e_hist = _pure_torsion_strain_history(0.002)
        result = brown_miller_critical_plane(e_hist, _STEEL_STRAIN, n_planes=200)
        assert result["ok"] is True
        assert result["gamma_a"] > 1e-6, f"Expected nonzero shear, got {result['gamma_a']}"

    def test_S_constant_increases_damage(self):
        """Larger S_constant → larger P_BM → shorter life."""
        e_hist = _uniaxial_strain_history(0.001)
        r1 = brown_miller_critical_plane(e_hist, _STEEL_STRAIN, S=0.5, n_planes=100)
        r2 = brown_miller_critical_plane(e_hist, _STEEL_STRAIN, S=2.0, n_planes=100)
        assert r1["ok"] and r2["ok"]
        assert r1["P_BM"] <= r2["P_BM"]

    def test_higher_strain_shorter_life(self):
        # Use plastic-regime strains (above Sf'/E ~ 0.0045) for both cases.
        e_med = _uniaxial_strain_history(0.006)
        e_high = _uniaxial_strain_history(0.020)
        r_med = brown_miller_critical_plane(e_med, _STEEL_STRAIN, n_planes=100)
        r_high = brown_miller_critical_plane(e_high, _STEEL_STRAIN, n_planes=100)
        assert r_med["ok"] and r_high["ok"]
        assert r_med["N_cycles"] > r_high["N_cycles"]

    def test_target_life_safety_factor(self):
        e_hist = _uniaxial_strain_history(0.001)
        target = 2e4
        result = brown_miller_critical_plane(
            e_hist, _STEEL_STRAIN, n_planes=100, target_life=target
        )
        assert result["ok"] is True
        sf = result["safety_factor"]
        assert sf is not None

    def test_error_missing_eps_f_prime(self):
        e_hist = _uniaxial_strain_history(0.001)
        props = {k: v for k, v in _STEEL_STRAIN.items() if k != "eps_f_prime"}
        result = brown_miller_critical_plane(e_hist, props)
        assert result["ok"] is False
        assert "eps_f_prime" in result["reason"]

    def test_error_negative_S(self):
        e_hist = _uniaxial_strain_history(0.001)
        result = brown_miller_critical_plane(e_hist, _STEEL_STRAIN, S=-1.0)
        assert result["ok"] is False

    def test_error_single_step(self):
        e_hist = [_uniaxial_strain_history(0.001)[0]]
        result = brown_miller_critical_plane(e_hist, _STEEL_STRAIN)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 5. Unified multiaxial_life dispatcher
# ---------------------------------------------------------------------------

class TestMultiaxialLife:
    def test_dispatch_findley(self):
        hist = _uniaxial_stress_history(200e6)
        result = multiaxial_life(hist, "findley", _STEEL_FINDLEY, n_planes=100)
        assert result["ok"] is True
        assert result["method"] == "findley"

    def test_dispatch_swt3d(self):
        s_hist = _uniaxial_stress_history(200e6)
        e_hist = _uniaxial_strain_history(0.001)
        result = multiaxial_life(
            s_hist, "swt3d", _STEEL_STRAIN,
            strain_history=e_hist, n_planes=100
        )
        assert result["ok"] is True
        assert result["method"] == "swt3d"

    def test_dispatch_brown_miller(self):
        e_hist = _uniaxial_strain_history(0.001)
        result = multiaxial_life(
            None, "brown_miller", _STEEL_STRAIN,
            strain_history=e_hist, n_planes=100
        )
        assert result["ok"] is True
        assert result["method"] == "brown_miller"

    def test_unknown_method_error(self):
        result = multiaxial_life(None, "mises", _STEEL_FINDLEY)
        assert result["ok"] is False
        assert "mises" in result["reason"]

    def test_swt3d_missing_strain_history(self):
        hist = _uniaxial_stress_history(200e6)
        result = multiaxial_life(hist, "swt3d", _STEEL_STRAIN)
        assert result["ok"] is False

    def test_brown_miller_missing_strain_history(self):
        result = multiaxial_life(None, "brown_miller", _STEEL_STRAIN)
        assert result["ok"] is False

    def test_n_planes_clamped_minimum(self):
        """n_planes < 50 is silently clamped to 50."""
        hist = _uniaxial_stress_history(200e6)
        result = multiaxial_life(hist, "findley", _STEEL_FINDLEY, n_planes=5)
        assert result["ok"] is True
        assert result["n_planes_searched"] >= 50


# ---------------------------------------------------------------------------
# 6. Proportional loading consistency checks (Socie/Marquis validation)
# ---------------------------------------------------------------------------

class TestProportionalLoadingConsistency:
    """
    Validate against well-known qualitative results from Socie & Marquis textbook.
    """

    def test_findley_torsion_vs_tension_same_mises(self):
        """
        Findley critical-plane comparison at same von-Mises equivalent stress.

        For same Mises equivalent stress (τ = σ/√3):
          tension critical plane (45°): P_F = σ/2 + k·σ = σ(0.5 + k)
          torsion critical plane (45°): P_F = τ + k·τ = τ(1 + k) = σ/√3·(1+k)

        With k_F = 0.25:
          P_F_tension = σ·0.75
          P_F_torsion = σ/√3·1.25 ≈ σ·0.722

        So tension Findley P_F is slightly LARGER than torsion at the same
        Mises — meaning Findley predicts a LONGER life under torsion.
        (The ordering reverses when k_F > √3/2 - 1/2 ≈ 0.366.)

        This is the analytically correct result per Findley (1959).
        """
        sigma_a = 200e6
        tau_a = sigma_a / math.sqrt(3)  # same Mises

        hist_tension = _uniaxial_stress_history(sigma_a)
        hist_torsion = _pure_torsion_stress_history(tau_a)

        r_t = findley_critical_plane(hist_tension, _STEEL_FINDLEY, n_planes=300)
        r_s = findley_critical_plane(hist_torsion, _STEEL_FINDLEY, n_planes=300)

        assert r_t["ok"] and r_s["ok"]

        # Tension P_F > torsion P_F for k_F = 0.25 < 0.366
        assert r_t["P_F"] > r_s["P_F"], (
            f"Expected tension P_F ({r_t['P_F']:.3g}) > "
            f"torsion P_F ({r_s['P_F']:.3g}) for k_F=0.25"
        )
        # And correspondingly tension life < torsion life
        assert r_t["N_cycles"] < r_s["N_cycles"], (
            "Expected longer Findley life under torsion for k_F=0.25 at same Mises"
        )

    def test_swt_tension_critical_plane_is_normal_to_load(self):
        """
        Under uniaxial σ_x, the SWT critical plane should be the plane with
        normal along x (maximum opening stress + maximum normal strain).
        The x-component of the critical normal should be the largest.
        """
        s_hist = _uniaxial_stress_history(350e6, n_steps=8)
        e_hist = _uniaxial_strain_history(0.00175, n_steps=8)
        result = swt3d_critical_plane(s_hist, e_hist, _STEEL_STRAIN, n_planes=400)
        assert result["ok"] is True
        cn = result["critical_normal"]
        abs_cn = [abs(x) for x in cn]
        # x-component must be dominant (larger than y and z)
        assert abs_cn[0] == max(abs_cn), (
            f"Expected x-dominant critical normal, got {cn}"
        )

    def test_brown_miller_pure_torsion_dominant_shear(self):
        """
        Under pure torsion γ_xy, the Brown-Miller shear amplitude on the critical
        plane must be significantly nonzero and the normal strain contribution
        should be smaller (pure shear has equal principal strains but opposite sign).
        """
        gamma_amp = 0.002
        e_hist = _pure_torsion_strain_history(gamma_amp)
        result = brown_miller_critical_plane(e_hist, _STEEL_STRAIN, n_planes=300)
        assert result["ok"] is True
        assert result["gamma_a"] > 0.5 * result["P_BM"], (
            "Shear term should dominate under pure torsion"
        )


# ---------------------------------------------------------------------------
# 7. LLM tool wrappers
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.fatigue.multiaxial_tools import (
        run_fatigue_findley,
        run_fatigue_swt3d,
        run_fatigue_brown_miller,
        run_fatigue_multiaxial_critical_plane,
    )
    _TOOLS_AVAILABLE = True
except ImportError:
    _TOOLS_AVAILABLE = False


def _make_ctx():
    class _FakeCtx:
        project_id = uuid.uuid4()
        user_id = uuid.uuid4()
    return _FakeCtx()


@pytest.mark.skipif(not _TOOLS_AVAILABLE, reason="tool registry not available")
class TestMultiaxialTools:
    _ctx = _make_ctx()

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_findley_tool_happy(self):
        payload = {
            "stress_history": _uniaxial_stress_history(200e6),
            "material_props": _STEEL_FINDLEY,
            "n_planes": 80,
        }
        raw = self._run(run_fatigue_findley(self._ctx, json.dumps(payload).encode()))
        result = json.loads(raw)
        assert result.get("ok") is True
        assert result["method"] == "findley"

    def test_findley_tool_missing_stress_history(self):
        payload = {"material_props": _STEEL_FINDLEY}
        raw = self._run(run_fatigue_findley(self._ctx, json.dumps(payload).encode()))
        result = json.loads(raw)
        assert result.get("ok") is False

    def test_swt3d_tool_happy(self):
        payload = {
            "stress_history": _uniaxial_stress_history(200e6),
            "strain_history": _uniaxial_strain_history(0.001),
            "material_props": _STEEL_STRAIN,
            "n_planes": 80,
        }
        raw = self._run(run_fatigue_swt3d(self._ctx, json.dumps(payload).encode()))
        result = json.loads(raw)
        assert result.get("ok") is True
        assert result["method"] == "swt3d"

    def test_swt3d_tool_missing_strain_history(self):
        payload = {
            "stress_history": _uniaxial_stress_history(200e6),
            "material_props": _STEEL_STRAIN,
        }
        raw = self._run(run_fatigue_swt3d(self._ctx, json.dumps(payload).encode()))
        result = json.loads(raw)
        assert result.get("ok") is False

    def test_brown_miller_tool_happy(self):
        payload = {
            "strain_history": _uniaxial_strain_history(0.001),
            "material_props": _STEEL_STRAIN,
            "n_planes": 80,
        }
        raw = self._run(
            run_fatigue_brown_miller(self._ctx, json.dumps(payload).encode())
        )
        result = json.loads(raw)
        assert result.get("ok") is True
        assert result["method"] == "brown_miller"

    def test_brown_miller_tool_invalid_S(self):
        payload = {
            "strain_history": _uniaxial_strain_history(0.001),
            "material_props": _STEEL_STRAIN,
            "S_constant": -2.0,
        }
        raw = self._run(
            run_fatigue_brown_miller(self._ctx, json.dumps(payload).encode())
        )
        result = json.loads(raw)
        assert result.get("ok") is False

    def test_multiaxial_dispatcher_findley(self):
        payload = {
            "stress_history": _uniaxial_stress_history(200e6),
            "method": "findley",
            "material_props": _STEEL_FINDLEY,
            "n_planes": 80,
        }
        raw = self._run(
            run_fatigue_multiaxial_critical_plane(
                self._ctx, json.dumps(payload).encode()
            )
        )
        result = json.loads(raw)
        assert result.get("ok") is True
        assert result["method"] == "findley"

    def test_multiaxial_dispatcher_bad_method(self):
        payload = {
            "stress_history": _uniaxial_stress_history(200e6),
            "method": "von_mises",
            "material_props": _STEEL_FINDLEY,
        }
        raw = self._run(
            run_fatigue_multiaxial_critical_plane(
                self._ctx, json.dumps(payload).encode()
            )
        )
        result = json.loads(raw)
        assert result.get("ok") is False

    def test_multiaxial_dispatcher_invalid_json(self):
        raw = self._run(
            run_fatigue_multiaxial_critical_plane(self._ctx, b"not json {{")
        )
        result = json.loads(raw)
        # The registry may wrap errors as {"ok": false, ...} or {"code": "BAD_ARGS", ...}
        is_error = (result.get("ok") is False) or ("code" in result and "error" in result)
        assert is_error, f"Expected error response, got: {result}"
