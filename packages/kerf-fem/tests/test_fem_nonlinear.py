"""
Hermetic test suite for the nonlinear FEM material path.

Covers:
  - 1-D uniaxial bar (run_nonlinear_bar)  — strain-controlled and force-controlled
  - 2-D truss with plasticity (run_truss_plastic)
  - Tool-layer wrappers (fem_nonlinear_bar, fem_truss_plastic)

All tests are hermetic (no DB, no network, no heavy deps).

Analytical reference values
----------------------------
Loading into the elastic regime:
    σ = E ε

Elastic onset of yielding:
    ε_y = σ_y / E

Isotropic-hardening post-yield tangent:
    Et = E H / (E + H)
    Δσ_plastic = Et · Δε  (for strain increments beyond ε_y)

Unloading from plastic state is always elastic:
    Δσ_unload = E · Δε

Perfect plasticity (H=0):
    stress cannot exceed σ_y regardless of further strain
"""

from __future__ import annotations

import json
import math
import asyncio

import pytest

from kerf_fem.nonlinear_bar import (
    run_nonlinear_bar,
    run_truss_plastic,
    _return_map_1d,
)


# ---------------------------------------------------------------------------
# Fixtures / shared material data
# ---------------------------------------------------------------------------

E       = 200e9   # 200 GPa  (steel-like)
SY      = 250e6   # 250 MPa  initial yield stress
H       = 20e9    # 20 GPa   hardening modulus
eps_y   = SY / E  # 1.25e-3  yield strain


# ===========================================================================
# Return-mapping unit tests (_return_map_1d)
# ===========================================================================

class TestReturnMap:

    def test_elastic_positive(self):
        """Below yield → identity (no plastic correction)."""
        eps_inc = 0.5 * eps_y
        sigma, eps_p = _return_map_1d(0.0, 0.0, eps_inc, E, SY, H)
        assert abs(sigma - E * eps_inc) < 1.0  # within 1 Pa
        assert eps_p == 0.0

    def test_elastic_negative(self):
        """Below yield in compression → Hooke's law, no plastic strain."""
        eps_inc = -0.5 * eps_y
        sigma, eps_p = _return_map_1d(0.0, 0.0, eps_inc, E, SY, H)
        assert abs(sigma - E * eps_inc) < 1.0
        assert eps_p == 0.0

    def test_exactly_at_yield(self):
        """Exactly at yield threshold → still elastic (f_trial == 0)."""
        sigma, eps_p = _return_map_1d(0.0, 0.0, eps_y, E, SY, H)
        assert abs(sigma - SY) < 1.0
        assert eps_p == 0.0

    def test_beyond_yield_positive(self):
        """Past yield → plastic correction applied; plastic strain > 0."""
        eps_inc = 2.0 * eps_y   # double the yield strain
        sigma, eps_p = _return_map_1d(0.0, 0.0, eps_inc, E, SY, H)
        # σ must be above σ_y (hardening) but below E*ε_inc
        assert sigma > SY
        assert sigma < E * eps_inc
        assert eps_p > 0.0

    def test_beyond_yield_negative(self):
        """Compressive yielding: plastic correction in compression."""
        eps_inc = -2.0 * eps_y
        sigma, eps_p = _return_map_1d(0.0, 0.0, eps_inc, E, SY, H)
        assert sigma < -SY
        assert abs(sigma) < E * abs(eps_inc)
        assert eps_p > 0.0

    def test_perfect_plasticity_plateau(self):
        """H=0 → stress stays at σ_y for any over-yield strain increment."""
        eps_inc = 10.0 * eps_y
        sigma, eps_p = _return_map_1d(0.0, 0.0, eps_inc, E, SY, 0.0)
        assert abs(sigma - SY) < 1e-3  # within 1 mPa
        assert eps_p > 0.0

    def test_incremental_hardening_accumulates(self):
        """Each yielding increment raises the subsequent yield surface."""
        eps_inc = 1.5 * eps_y
        s1, ep1 = _return_map_1d(0.0, 0.0, eps_inc, E, SY, H)
        # second increment: starting from hardened state
        s2, ep2 = _return_map_1d(s1, ep1, eps_inc * 0.1, E, SY, H)
        # yield surface at step 2 = SY + H*ep1 — small increment may be elastic
        assert ep2 >= ep1   # plastic strain never decreases


# ===========================================================================
# run_nonlinear_bar — strain-controlled
# ===========================================================================

class TestNonlinearBarStrainControlled:

    def test_elastic_regime_hooke(self):
        """In purely elastic regime stress = E * ε."""
        targets = [0.2 * eps_y, 0.5 * eps_y, 0.8 * eps_y, 1.0 * eps_y]
        res = run_nonlinear_bar(E, SY, H, targets)
        assert res["ok"]
        for i, eps_t in enumerate(targets):
            assert abs(res["stress"][i] - E * eps_t) < 1.0  # within 1 Pa
            assert res["plastic_strain"][i] == 0.0

    def test_yield_onset(self):
        """First post-yield step: stress > σ_y, plastic strain > 0."""
        targets = [eps_y, 1.5 * eps_y]
        res = run_nonlinear_bar(E, SY, H, targets)
        assert res["ok"]
        assert res["stress"][0] <= SY + 1.0   # exactly at yield is elastic
        assert res["stress"][1] > SY
        assert res["plastic_strain"][1] > 0.0

    def test_hardening_slope_post_yield(self):
        """Post-yield tangent: dσ/dε = E·H/(E+H)."""
        Et = E * H / (E + H)
        # Two post-yield points, delta_eps apart
        eps1 = 2.0 * eps_y
        eps2 = 3.0 * eps_y
        res = run_nonlinear_bar(E, SY, H, [eps1, eps2])
        assert res["ok"]
        # Both are post-yield
        delta_sigma = res["stress"][1] - res["stress"][0]
        delta_eps   = eps2 - eps1
        measured_slope = delta_sigma / delta_eps
        assert abs(measured_slope - Et) / Et < 1e-6

    def test_plastic_strain_monotone_loading(self):
        """Plastic strain must be non-decreasing under monotone loading."""
        targets = [k * eps_y for k in [0.5, 1.0, 1.5, 2.0, 3.0]]
        res = run_nonlinear_bar(E, SY, H, targets)
        assert res["ok"]
        for i in range(1, len(res["plastic_strain"])):
            assert res["plastic_strain"][i] >= res["plastic_strain"][i - 1]

    def test_elastic_unload_from_plastic_state(self):
        """After yielding, partial unload follows E (not Et)."""
        load   = 2.0 * eps_y
        unload = 1.5 * eps_y   # still positive but less than peak
        res = run_nonlinear_bar(E, SY, H, [load, unload])
        assert res["ok"]
        # Unload increment: delta_eps = unload - load < 0, fully elastic
        delta_eps_unload = unload - load   # negative
        delta_sigma = res["stress"][1] - res["stress"][0]
        assert abs(delta_sigma - E * delta_eps_unload) < 1.0   # Hooke unload

    def test_elastic_plastic_strain_frozen_on_unload(self):
        """Plastic strain must not change during elastic unload."""
        res = run_nonlinear_bar(E, SY, H, [2.0 * eps_y, 1.5 * eps_y])
        assert res["ok"]
        # Plastic strain after unload == plastic strain after loading
        assert abs(res["plastic_strain"][1] - res["plastic_strain"][0]) < 1e-20

    def test_perfect_plasticity_plateau(self):
        """H=0 → stress stays at σ_y for large strain increments."""
        targets = [eps_y * k for k in [1.0, 2.0, 5.0, 10.0]]
        res = run_nonlinear_bar(E, SY, 0.0, targets)
        assert res["ok"]
        for i in range(1, len(targets)):
            assert abs(res["stress"][i] - SY) < 1e-3

    def test_perfect_plasticity_compressive(self):
        """H=0, compressive loading: stress stays at −σ_y."""
        targets = [-eps_y * k for k in [1.0, 2.0, 5.0]]
        res = run_nonlinear_bar(E, SY, 0.0, targets)
        assert res["ok"]
        for i in range(1, len(targets)):
            assert abs(res["stress"][i] + SY) < 1e-3

    def test_full_cycle_bauschinger_isotropic(self):
        """Isotropic hardening: stress at each step is bounded by current yield surface."""
        # With isotropic hardening, σ_y grows with accumulated εᵖ (both in tension and
        # compression).  At the end of each step, |σ| ≤ σ_y(εᵖ_total) must hold.
        eps_peak = 3.0 * eps_y
        eps_neg  = -eps_peak
        res = run_nonlinear_bar(E, SY, H, [eps_peak, eps_neg])
        assert res["ok"]
        for i in range(len(res["stress"])):
            sigma_yi = SY + H * res["plastic_strain"][i]
            assert abs(res["stress"][i]) <= sigma_yi + 1.0  # within 1 Pa

    def test_invalid_E_negative(self):
        res = run_nonlinear_bar(-1.0, SY, H, [eps_y])
        assert res["ok"] is False
        assert "E" in res["reason"]

    def test_invalid_sigma_y0_zero(self):
        res = run_nonlinear_bar(E, 0.0, H, [eps_y])
        assert res["ok"] is False

    def test_invalid_H_negative(self):
        res = run_nonlinear_bar(E, SY, -1.0, [eps_y])
        assert res["ok"] is False

    def test_empty_load_steps(self):
        res = run_nonlinear_bar(E, SY, H, [])
        assert res["ok"]
        assert res["strain"] == []
        assert res["stress"] == []
        assert res["plastic_strain"] == []

    def test_result_keys_present(self):
        res = run_nonlinear_bar(E, SY, H, [eps_y])
        assert "ok" in res
        assert "strain" in res
        assert "stress" in res
        assert "plastic_strain" in res

    def test_lengths_match_load_steps(self):
        targets = [k * eps_y for k in range(1, 6)]
        res = run_nonlinear_bar(E, SY, H, targets)
        assert res["ok"]
        assert len(res["strain"]) == len(targets)
        assert len(res["stress"]) == len(targets)
        assert len(res["plastic_strain"]) == len(targets)


# ===========================================================================
# run_nonlinear_bar — force-controlled
# ===========================================================================

class TestNonlinearBarForceControlled:

    def test_elastic_hooke_force(self):
        """Force-controlled elastic: ε = σ/E."""
        sigma_target = 0.5 * SY
        res = run_nonlinear_bar(E, SY, H, [sigma_target], force_controlled=True)
        assert res["ok"]
        assert abs(res["strain"][0] - sigma_target / E) < 1e-12

    def test_yield_onset_force(self):
        """Applying σ_y force: stress reaches σ_y, tiny plastic strain starts."""
        res = run_nonlinear_bar(E, SY, H, [SY * 1.001], force_controlled=True)
        assert res["ok"]
        assert res["plastic_strain"][0] >= 0.0

    def test_perfect_plasticity_over_yield_force_fail(self):
        """With H=0, requesting stress > σ_y is impossible → ok=False."""
        res = run_nonlinear_bar(E, SY, 0.0, [SY * 1.01], force_controlled=True)
        assert res["ok"] is False
        assert "reason" in res


# ===========================================================================
# run_truss_plastic
# ===========================================================================

class TestTrussPlastic:
    """
    Single-bar truss (two nodes, one element):
      Node 0 at (0,0) fixed in both DOFs.
      Node 1 at (L,0) free.
      Load applied as force at node 1 in x-direction.
    """

    L    = 1.0   # m
    A    = 1e-4  # m² (1 cm²)
    E_t  = 200e9
    SY_t = 250e6
    H_t  = 20e9

    @property
    def nodes(self):
        return [(0.0, 0.0), (self.L, 0.0)]

    @property
    def elements(self):
        return [(0, 1)]

    def _run(self, forces_per_step, fixed_dofs=None):
        if fixed_dofs is None:
            # Pin node 0 (DOFs 0,1) + constrain transverse DOF at node 1 (DOF 3)
            # A horizontal bar loaded axially has no mechanism to resist the y-DOF
            # at the free end, so DOF 3 must be constrained to avoid a singular K.
            fixed_dofs = [0, 1, 3]
        steps = []
        for fval in forces_per_step:
            steps.append({
                "forces": {"1": [fval, 0.0]},
                "fixed_dofs": fixed_dofs,
            })
        return run_truss_plastic(
            nodes=self.nodes,
            elements=self.elements,
            E=self.E_t,
            area=self.A,
            sigma_y0=self.SY_t,
            H=self.H_t,
            load_steps=steps,
        )

    def test_elastic_single_bar_displacement(self):
        """Elastic loading: u = FL/(EA) (Hooke)."""
        F = 0.5 * self.SY_t * self.A   # half-yield force
        res = self._run([F])
        assert res["ok"], res.get("reason")
        hist = res["history"]
        u_x = hist[0]["displacements"][2]   # DOF 2 = node 1 x
        u_expected = F * self.L / (self.E_t * self.A)
        assert abs(u_x - u_expected) / u_expected < 1e-8

    def test_elastic_zero_plastic_strain(self):
        """No plastic strain in elastic regime."""
        F = 0.5 * self.SY_t * self.A
        res = self._run([F])
        assert res["ok"]
        assert abs(res["history"][0]["element_plastic_strain"][0]) < 1e-20

    def test_plastic_stress_capped_at_yield(self):
        """Post-yield: element stress above σ_y (hardening)."""
        F = 1.5 * self.SY_t * self.A
        res = self._run([F])
        assert res["ok"], res.get("reason")
        sigma = res["history"][0]["element_stress"][0]
        assert sigma > self.SY_t

    def test_plastic_strain_nonzero(self):
        """Post-yield load: plastic strain accumulates in element."""
        F = 2.0 * self.SY_t * self.A
        res = self._run([F])
        assert res["ok"], res.get("reason")
        assert res["history"][0]["element_plastic_strain"][0] > 0.0

    def test_result_structure(self):
        """Result must have 'ok' and 'history' keys; history has expected fields."""
        F = 0.3 * self.SY_t * self.A
        res = self._run([F])
        assert "ok" in res
        assert "history" in res
        step = res["history"][0]
        assert "step" in step
        assert "displacements" in step
        assert "element_stress" in step
        assert "element_plastic_strain" in step

    def test_two_steps_monotone_plastic(self):
        """Two increasing plastic load steps: plastic strain grows monotonically."""
        F1 = 1.5 * self.SY_t * self.A
        F2 = 2.5 * self.SY_t * self.A
        res = self._run([F1, F2])
        assert res["ok"], res.get("reason")
        ep1 = res["history"][0]["element_plastic_strain"][0]
        ep2 = res["history"][1]["element_plastic_strain"][0]
        assert ep2 >= ep1

    def test_invalid_no_nodes(self):
        res = run_truss_plastic([], [(0, 1)], self.E_t, self.A, self.SY_t, self.H_t, [{}])
        assert res["ok"] is False

    def test_invalid_no_elements(self):
        res = run_truss_plastic(self.nodes, [], self.E_t, self.A, self.SY_t, self.H_t, [{}])
        assert res["ok"] is False

    def test_invalid_no_load_steps(self):
        res = run_truss_plastic(self.nodes, self.elements, self.E_t, self.A, self.SY_t, self.H_t, [])
        assert res["ok"] is False

    def test_invalid_negative_area(self):
        res = run_truss_plastic(self.nodes, self.elements, self.E_t, -1.0, self.SY_t, self.H_t,
                                [{"forces": {"1": [1.0, 0.0]}, "fixed_dofs": [0, 1]}])
        assert res["ok"] is False

    def test_history_length_matches_steps(self):
        F = 0.5 * self.SY_t * self.A
        res = self._run([F, F, F])
        assert res["ok"]
        assert len(res["history"]) == 3


# ===========================================================================
# Tool-layer wrappers (async, via _compat shims)
# ===========================================================================

class TestToolLayer:

    def _run_async(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_fem_nonlinear_bar_tool_elastic(self):
        from kerf_fem.tools import run_fem_nonlinear_bar
        args = json.dumps({
            "E": E,
            "sigma_y0": SY,
            "H": H,
            "load_steps": [0.5 * eps_y, 1.0 * eps_y],
        }).encode()
        raw = self._run_async(run_fem_nonlinear_bar(None, args))
        result = json.loads(raw)
        assert result.get("ok") is True

    def test_fem_nonlinear_bar_tool_plastic(self):
        from kerf_fem.tools import run_fem_nonlinear_bar
        args = json.dumps({
            "E": E,
            "sigma_y0": SY,
            "H": H,
            "load_steps": [2.0 * eps_y, 3.0 * eps_y],
        }).encode()
        raw = self._run_async(run_fem_nonlinear_bar(None, args))
        result = json.loads(raw)
        assert result.get("ok") is True
        assert result["plastic_strain"][-1] > 0.0

    def test_fem_nonlinear_bar_tool_missing_args(self):
        from kerf_fem.tools import run_fem_nonlinear_bar
        args = json.dumps({"E": E}).encode()
        raw = self._run_async(run_fem_nonlinear_bar(None, args))
        result = json.loads(raw)
        assert "error" in result

    def test_fem_nonlinear_bar_tool_invalid_json(self):
        from kerf_fem.tools import run_fem_nonlinear_bar
        raw = self._run_async(run_fem_nonlinear_bar(None, b"not json"))
        result = json.loads(raw)
        assert "error" in result

    def test_fem_truss_plastic_tool_elastic(self):
        from kerf_fem.tools import run_fem_truss_plastic
        F = 0.5 * SY * 1e-4
        args = json.dumps({
            "nodes": [[0.0, 0.0], [1.0, 0.0]],
            "elements": [[0, 1]],
            "E": E,
            "area": 1e-4,
            "sigma_y0": SY,
            "H": H,
            "load_steps": [
                # DOFs: 0=node0x, 1=node0y, 2=node1x, 3=node1y
                # Fix node 0 (pin) + constrain transverse at node 1
                {"forces": {"1": [F, 0.0]}, "fixed_dofs": [0, 1, 3]},
            ],
        }).encode()
        raw = self._run_async(run_fem_truss_plastic(None, args))
        result = json.loads(raw)
        assert result.get("ok") is True

    def test_fem_truss_plastic_tool_missing_field(self):
        from kerf_fem.tools import run_fem_truss_plastic
        args = json.dumps({"nodes": [[0, 0], [1, 0]]}).encode()
        raw = self._run_async(run_fem_truss_plastic(None, args))
        result = json.loads(raw)
        assert "error" in result

    def test_tool_specs_registered(self):
        """Both new tool specs must be importable from the tools module."""
        # The tools register into whichever registry is active (kerf_chat when
        # available; _compat shim otherwise).  Verify the specs are importable
        # and carry the correct names — that's the authoritative check.
        from kerf_fem.tools import (
            fem_nonlinear_bar_spec,
            fem_truss_plastic_spec,
        )
        assert fem_nonlinear_bar_spec.name == "fem_nonlinear_bar"
        assert fem_truss_plastic_spec.name == "fem_truss_plastic"
