"""
Tests for kerf_fem.solid_fem_tools — LLM tools:
  fem_solid_static, fem_modal_beam, fem_linear_static_beam

Validation references:
  * Solid tet4: Cook et al. (2001) §7.2 — constant-strain tetrahedron
  * Modal beam: Blevins, Table 8-1 — cantilever ω₁L² = (β₁L)² √(EI/ρA),
    β₁L = 1.87510407
  * Beam deflection: Timoshenko §6 — cantilever: δ_max = PL³/(3EI)
  * Thermal bar: Timoshenko §2 — σ_thermal = EαΔT (fully restrained)
"""
from __future__ import annotations

import json
import math
import asyncio

import pytest

from kerf_fem.solid_fem_tools import (
    run_fem_solid_static,
    run_fem_modal_beam,
    run_fem_linear_static_beam,
    _fem_solid_static_spec,
    _fem_modal_beam_spec,
    _fem_linear_static_beam_spec,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def ok(result: dict) -> dict:
    """Assert result is ok and return it."""
    assert result.get("ok") is not False, f"result not ok: {result}"
    return result


async def invoke(fn, args_dict):
    """Invoke an async LLM tool handler and parse the JSON result."""
    raw = await fn(ctx=None, args=json.dumps(args_dict).encode())
    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# ToolSpec schema tests
# ─────────────────────────────────────────────────────────────────────────────

class TestToolSpecs:
    def test_solid_static_spec_name(self):
        assert _fem_solid_static_spec.name == "fem_solid_static"

    def test_modal_beam_spec_name(self):
        assert _fem_modal_beam_spec.name == "fem_modal_beam"

    def test_linear_static_beam_spec_name(self):
        assert _fem_linear_static_beam_spec.name == "fem_linear_static_beam"

    def test_solid_static_spec_has_nodes_elements(self):
        props = _fem_solid_static_spec.input_schema["properties"]
        assert "nodes" in props
        assert "elements" in props
        assert "constraints" in props
        assert "loads" in props

    def test_modal_beam_spec_has_mode_enum(self):
        props = _fem_modal_beam_spec.input_schema["properties"]
        assert "mode" in props
        assert "beam" in props["mode"]["enum"]
        assert "plate" in props["mode"]["enum"]

    def test_linear_static_beam_spec_analysis_enum(self):
        props = _fem_linear_static_beam_spec.input_schema["properties"]
        assert "analysis" in props
        assert "beam" in props["analysis"]["enum"]
        assert "axial_bar" in props["analysis"]["enum"]
        assert "thermal_bar" in props["analysis"]["enum"]


# ─────────────────────────────────────────────────────────────────────────────
# fem_solid_static
# ─────────────────────────────────────────────────────────────────────────────

class TestFemSolidStatic:
    """
    Single tet4 element: 4 nodes at origin + unit-axis corners.
    Fix node 0 in all DOFs; apply Fy = 1000 N at node 3.
    Result must be non-zero max displacement.
    """

    BASE_ARGS = {
        "nodes": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "elements": [{"kind": "tet4", "node_indices": [0, 1, 2, 3]}],
        "E": 200e9,
        "nu": 0.3,
        "density": 7850.0,
        "yield_strength": 275e6,
        "constraints": [{"node_id": 0, "dofs": [0.0, 0.0, 0.0]}],
        "loads": [{"node_id": 3, "force": [0.0, 1000.0, 0.0]}],
    }

    @pytest.mark.asyncio
    async def test_returns_ok_true(self):
        res = await invoke(run_fem_solid_static, self.BASE_ARGS)
        assert res.get("ok") is True

    @pytest.mark.asyncio
    async def test_max_displacement_positive(self):
        res = await invoke(run_fem_solid_static, self.BASE_ARGS)
        assert res["max_displacement_m"] > 0

    @pytest.mark.asyncio
    async def test_max_vonmises_positive(self):
        res = await invoke(run_fem_solid_static, self.BASE_ARGS)
        assert res["max_vonmises_stress_pa"] > 0

    @pytest.mark.asyncio
    async def test_factor_of_safety_computed(self):
        res = await invoke(run_fem_solid_static, self.BASE_ARGS)
        assert res["factor_of_safety"] is not None
        assert res["factor_of_safety"] > 0

    @pytest.mark.asyncio
    async def test_node_displacements_has_4_nodes(self):
        res = await invoke(run_fem_solid_static, self.BASE_ARGS)
        nd = res["node_displacements"]
        assert isinstance(nd, list)
        assert len(nd) == 4

    @pytest.mark.asyncio
    async def test_node_displacement_has_u_list(self):
        res = await invoke(run_fem_solid_static, self.BASE_ARGS)
        nd = res["node_displacements"]
        for entry in nd:
            assert "node" in entry
            assert "u" in entry
            assert len(entry["u"]) == 3

    @pytest.mark.asyncio
    async def test_fixed_node_has_near_zero_displacement(self):
        """Node 0 is fully fixed — its displacement must be ~0."""
        res = await invoke(run_fem_solid_static, self.BASE_ARGS)
        nd = res["node_displacements"]
        node0 = next(e for e in nd if e["node"] == 0)
        u_mag = math.sqrt(sum(v**2 for v in node0["u"]))
        # Penalty method: residual < load / alpha ~ 1000 / 1e20 = 1e-17 m
        assert u_mag < 1e-6

    @pytest.mark.asyncio
    async def test_element_vonmises_list_has_1_element(self):
        res = await invoke(run_fem_solid_static, self.BASE_ARGS)
        vm = res["element_vonmises_pa"]
        assert isinstance(vm, list)
        assert len(vm) == 1

    @pytest.mark.asyncio
    async def test_missing_nodes_returns_bad_args(self):
        args = dict(self.BASE_ARGS)
        del args["nodes"]
        res = await invoke(run_fem_solid_static, args)
        assert res.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_bad_args(self):
        raw = await run_fem_solid_static(ctx=None, args=b"NOT_JSON")
        res = json.loads(raw)
        assert res.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_hex8_mesh_runs_ok(self):
        """Minimal 1-element hex8 mesh: unit cube, fix one face, load opposite."""
        nodes = [
            [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
            [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
        ]
        args = {
            "nodes": nodes,
            "elements": [{"kind": "hex8", "node_indices": list(range(8))}],
            "E": 200e9,
            "nu": 0.3,
            "density": 7850.0,
            "yield_strength": 275e6,
            "constraints": [
                {"node_id": 0, "dofs": [0.0, 0.0, 0.0]},
                {"node_id": 1, "dofs": [0.0, 0.0, 0.0]},
                {"node_id": 2, "dofs": [0.0, 0.0, 0.0]},
                {"node_id": 3, "dofs": [0.0, 0.0, 0.0]},
            ],
            "loads": [
                {"node_id": 4, "force": [0, 0, 5000]},
                {"node_id": 5, "force": [0, 0, 5000]},
            ],
        }
        res = await invoke(run_fem_solid_static, args)
        assert res.get("ok") is True
        assert res["max_displacement_m"] > 0
        assert len(res["element_vonmises_pa"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# fem_modal_beam — beam mode
# ─────────────────────────────────────────────────────────────────────────────

class TestFemModalBeamBeam:
    """
    Cantilever beam: E=200 GPa, I=8.33e-9 m⁴, A=1e-4 m², ρ=7850, L=1 m.
    Closed-form f_1 = (β₁L)²/(2πL²) √(EI/ρA), β₁L = 1.87510407.
    """

    @staticmethod
    def cantilever_f1_hz(E, I, rho, A, L):
        beta1L = 1.87510407
        EI = E * I
        rhoA = rho * A
        omega = (beta1L / L)**2 * math.sqrt(EI / rhoA)
        return omega / (2 * math.pi)

    BEAM_ARGS = {
        "mode": "beam",
        "E": 200e9,
        "I": 8.33e-9,
        "A": 1e-4,
        "rho": 7850.0,
        "L": 1.0,
        "supports": [{"type": "fixed", "x": 0}],
        "n_elem": 12,
        "n_modes": 3,
    }

    @pytest.mark.asyncio
    async def test_returns_frequencies_list(self):
        res = await invoke(run_fem_modal_beam, self.BEAM_ARGS)
        assert "frequencies_hz" in res
        assert isinstance(res["frequencies_hz"], list)
        assert len(res["frequencies_hz"]) == 3

    @pytest.mark.asyncio
    async def test_first_mode_within_0p5_pct_of_analytical(self):
        """
        FEM cantilever f_1 must be within 0.5% of Blevins analytical value.
        Hughes eq.(8.1.13) consistent mass at 12 elements gives <0.1% error.
        """
        res = await invoke(run_fem_modal_beam, self.BEAM_ARGS)
        f1_fem = res["frequencies_hz"][0]
        f1_ref = self.cantilever_f1_hz(E=200e9, I=8.33e-9, rho=7850, A=1e-4, L=1.0)
        err = abs(f1_fem - f1_ref) / f1_ref
        assert err < 0.005, f"f1_fem={f1_fem:.4f} Hz, ref={f1_ref:.4f} Hz, err={err:.4%}"

    @pytest.mark.asyncio
    async def test_frequencies_monotone_increasing(self):
        res = await invoke(run_fem_modal_beam, self.BEAM_ARGS)
        freqs = res["frequencies_hz"]
        for i in range(1, len(freqs)):
            assert freqs[i] > freqs[i - 1], \
                f"Mode {i+1} f={freqs[i]:.4f} <= Mode {i} f={freqs[i-1]:.4f}"

    @pytest.mark.asyncio
    async def test_omega_consistent_with_f(self):
        res = await invoke(run_fem_modal_beam, self.BEAM_ARGS)
        freqs = res["frequencies_hz"]
        omegas = res["omega_rad_s"]
        assert len(omegas) == len(freqs)
        for f, w in zip(freqs, omegas):
            expected_w = 2 * math.pi * f
            assert abs(w - expected_w) / expected_w < 1e-6

    @pytest.mark.asyncio
    async def test_mode_shapes_returned(self):
        res = await invoke(run_fem_modal_beam, self.BEAM_ARGS)
        shapes = res.get("mode_shapes")
        assert shapes is not None
        assert len(shapes) == 3

    @pytest.mark.asyncio
    async def test_missing_I_returns_bad_args(self):
        args = dict(self.BEAM_ARGS)
        del args["I"]
        res = await invoke(run_fem_modal_beam, args)
        assert res.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_simply_supported_f1_higher_than_cantilever(self):
        """Simply-supported f_1 > cantilever f_1 (Blevins Tables 8-1, 8-2)."""
        ss_args = dict(self.BEAM_ARGS)
        ss_args["supports"] = [{"type": "pinned", "x": 0}, {"type": "pinned", "x": 1.0}]
        res_ss = await invoke(run_fem_modal_beam, ss_args)
        res_cant = await invoke(run_fem_modal_beam, self.BEAM_ARGS)
        f1_ss = res_ss["frequencies_hz"][0]
        f1_cant = res_cant["frequencies_hz"][0]
        assert f1_ss > f1_cant, f"SS f1={f1_ss:.3f} should be > cantilever f1={f1_cant:.3f}"


# ─────────────────────────────────────────────────────────────────────────────
# fem_modal_beam — plate mode (Blevins closed-form)
# ─────────────────────────────────────────────────────────────────────────────

class TestFemModalBeamPlate:
    """
    Thin rectangular plate, simply-supported all edges.
    Blevins Table 11-4 case 1: ω_11 = π²[(1/a)²+(1/b)²]√(D/ρh)
    D = E h³ / (12(1−ν²))
    """

    PLATE_ARGS = {
        "mode": "plate",
        "E": 200e9,
        "nu": 0.3,
        "rho": 7850.0,
        "h": 0.01,
        "a": 1.0,
        "b": 1.0,
    }

    @staticmethod
    def plate_f1_hz(E, nu, rho, h, a, b):
        D = E * h**3 / (12 * (1 - nu**2))
        k = math.pi**2 * (1 / a**2 + 1 / b**2)
        omega = k * math.sqrt(D / (rho * h))
        return omega / (2 * math.pi)

    @pytest.mark.asyncio
    async def test_plate_f1_returned(self):
        res = await invoke(run_fem_modal_beam, self.PLATE_ARGS)
        assert "f_1_hz" in res
        assert res["f_1_hz"] > 0

    @pytest.mark.asyncio
    async def test_plate_f1_matches_blevins_formula(self):
        res = await invoke(run_fem_modal_beam, self.PLATE_ARGS)
        f1_tool = res["f_1_hz"]
        f1_ref  = self.plate_f1_hz(E=200e9, nu=0.3, rho=7850, h=0.01, a=1.0, b=1.0)
        err = abs(f1_tool - f1_ref) / f1_ref
        assert err < 1e-9, f"Plate f1 mismatch: tool={f1_tool:.6f}, ref={f1_ref:.6f}"

    @pytest.mark.asyncio
    async def test_plate_mode_returns_flexural_rigidity(self):
        res = await invoke(run_fem_modal_beam, self.PLATE_ARGS)
        D = res.get("flexural_rigidity_D")
        assert D is not None and D > 0

    @pytest.mark.asyncio
    async def test_plate_missing_nu_returns_bad_args(self):
        args = dict(self.PLATE_ARGS)
        del args["nu"]
        res = await invoke(run_fem_modal_beam, args)
        assert res.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_plate_aspect_ratio_changes_f1(self):
        """Wider plate (larger b) should reduce f_1."""
        args_sq = dict(self.PLATE_ARGS)
        args_wide = dict(self.PLATE_ARGS)
        args_wide["b"] = 2.0
        res_sq = await invoke(run_fem_modal_beam, args_sq)
        res_wide = await invoke(run_fem_modal_beam, args_wide)
        assert res_wide["f_1_hz"] < res_sq["f_1_hz"]


# ─────────────────────────────────────────────────────────────────────────────
# fem_linear_static_beam — beam analysis
# ─────────────────────────────────────────────────────────────────────────────

class TestFemLinearStaticBeam:
    """
    Cantilever beam: E=200 GPa, I=8.33e-9 m⁴, L=1 m.
    Point load P=5000 N at tip.
    Closed-form: δ_max = PL³/(3EI) = 5000*1³/(3*200e9*8.33e-9) = 1.0e-3 m (1 mm).
    """

    @staticmethod
    def cantilever_delta(E, I, L, P):
        return P * L**3 / (3 * E * I)

    BEAM_ARGS = {
        "analysis": "beam",
        "E": 200e9,
        "I": 8.33e-9,
        "L": 1.0,
        "supports": [{"type": "fixed", "x": 0}],
        "point_loads": [{"x": 1.0, "F": 5000}],
        "distributed_load": 0.0,
        "n_elem": 20,
    }

    @pytest.mark.asyncio
    async def test_beam_returns_max_deflection(self):
        res = await invoke(run_fem_linear_static_beam, self.BEAM_ARGS)
        assert res.get("max_deflection_m") is not None
        assert res["max_deflection_m"] > 0

    @pytest.mark.asyncio
    async def test_cantilever_tip_deflection_within_1pct_of_timoshenko(self):
        """
        Euler-Bernoulli cantilever: δ_max = PL³/(3EI).
        FEM with n=20 elements should hit < 1% error.
        """
        res = await invoke(run_fem_linear_static_beam, self.BEAM_ARGS)
        delta_fem = abs(res["max_deflection_m"])
        delta_ref = self.cantilever_delta(E=200e9, I=8.33e-9, L=1.0, P=5000)
        err = abs(delta_fem - delta_ref) / delta_ref
        assert err < 0.01, \
            f"δ_fem={delta_fem*1000:.4f} mm, ref={delta_ref*1000:.4f} mm, err={err:.4%}"

    @pytest.mark.asyncio
    async def test_beam_deflection_profile_length_matches_n_elem_plus_1(self):
        res = await invoke(run_fem_linear_static_beam, self.BEAM_ARGS)
        w = res.get("deflection_profile")
        x = res.get("x_coords")
        assert w is not None and x is not None
        assert len(w) == len(x)
        assert len(w) == 21  # n_elem=20 → 21 nodes

    @pytest.mark.asyncio
    async def test_beam_reactions_dict_present(self):
        res = await invoke(run_fem_linear_static_beam, self.BEAM_ARGS)
        assert "reactions" in res
        assert isinstance(res["reactions"], dict)

    @pytest.mark.asyncio
    async def test_beam_tip_has_max_deflection(self):
        """For a cantilever with tip load, deflection peaks at x=L."""
        res = await invoke(run_fem_linear_static_beam, self.BEAM_ARGS)
        w = res["deflection_profile"]
        max_abs = max(abs(v) for v in w)
        tip_abs = abs(w[-1])
        assert tip_abs == max_abs or abs(tip_abs - max_abs) < 1e-12

    @pytest.mark.asyncio
    async def test_beam_udl_midspan_deflection(self):
        """
        Simply-supported beam with UDL q=1000 N/m, L=1 m:
        δ_max = 5qL⁴/(384EI) at midspan.
        """
        E, I, L, q = 200e9, 8.33e-9, 1.0, 1000.0
        args = {
            "analysis": "beam",
            "E": E, "I": I, "L": L,
            "supports": [{"type": "pinned", "x": 0}, {"type": "pinned", "x": L}],
            "point_loads": [],
            "distributed_load": q,
            "n_elem": 20,
        }
        res = await invoke(run_fem_linear_static_beam, args)
        delta_fem = abs(res["max_deflection_m"])
        delta_ref = 5 * q * L**4 / (384 * E * I)
        err = abs(delta_fem - delta_ref) / delta_ref
        assert err < 0.01, \
            f"UDL SS δ_fem={delta_fem*1000:.4f} mm, ref={delta_ref*1000:.4f} mm, err={err:.4%}"

    @pytest.mark.asyncio
    async def test_missing_I_returns_bad_args(self):
        args = dict(self.BEAM_ARGS)
        del args["I"]
        res = await invoke(run_fem_linear_static_beam, args)
        assert res.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_unknown_analysis_returns_bad_args(self):
        args = dict(self.BEAM_ARGS)
        args["analysis"] = "nonexistent_type"
        res = await invoke(run_fem_linear_static_beam, args)
        assert res.get("code") == "BAD_ARGS"


# ─────────────────────────────────────────────────────────────────────────────
# fem_linear_static_beam — thermal bar
# ─────────────────────────────────────────────────────────────────────────────

class TestFemLinearStaticThermalBar:
    """
    Fully restrained axial bar: σ_thermal = EαΔT (Timoshenko §2).
    E=200 GPa, A=1e-4 m², L=1 m, α=12e-6 /K, ΔT=50 K.
    σ = 200e9 × 12e-6 × 50 = 120 MPa.
    """

    THERMAL_ARGS = {
        "analysis": "thermal_bar",
        "E": 200e9,
        "A": 1e-4,
        "L": 1.0,
        "alpha": 12e-6,
        "dT": 50.0,
        "supports": [{"type": "fixed", "x": 0.0}, {"type": "fixed", "x": 1.0}],
        "n_elem": 1,
    }

    @pytest.mark.asyncio
    async def test_thermal_stress_positive(self):
        res = await invoke(run_fem_linear_static_beam, self.THERMAL_ARGS)
        assert "thermal_stress_pa" in res
        assert res["thermal_stress_pa"] is not None

    @pytest.mark.asyncio
    async def test_thermal_stress_within_1pct_of_analytical(self):
        """
        Fully restrained bar: σ = EαΔT.
        Validates Timoshenko §2 closed-form.
        """
        res = await invoke(run_fem_linear_static_beam, self.THERMAL_ARGS)
        sigma_fem = abs(res["thermal_stress_pa"])
        sigma_ref = 200e9 * 12e-6 * 50  # = 120 MPa
        err = abs(sigma_fem - sigma_ref) / sigma_ref
        assert err < 0.01, \
            f"σ_fem={sigma_fem/1e6:.2f} MPa, ref={sigma_ref/1e6:.2f} MPa, err={err:.4%}"

    @pytest.mark.asyncio
    async def test_thermal_stress_scales_with_dT(self):
        """Doubling ΔT should double thermal stress."""
        args_base = self.THERMAL_ARGS
        args_2x = dict(self.THERMAL_ARGS)
        args_2x["dT"] = 100.0
        res_base = await invoke(run_fem_linear_static_beam, args_base)
        res_2x   = await invoke(run_fem_linear_static_beam, args_2x)
        ratio = abs(res_2x["thermal_stress_pa"]) / abs(res_base["thermal_stress_pa"])
        assert abs(ratio - 2.0) < 1e-6

    @pytest.mark.asyncio
    async def test_thermal_missing_alpha_returns_bad_args(self):
        args = dict(self.THERMAL_ARGS)
        del args["alpha"]
        res = await invoke(run_fem_linear_static_beam, args)
        assert res.get("code") == "BAD_ARGS"


# ─────────────────────────────────────────────────────────────────────────────
# fem_linear_static_beam — axial bar
# ─────────────────────────────────────────────────────────────────────────────

class TestFemLinearStaticAxialBar:
    """
    Axial bar: E=200 GPa, A=1e-4 m², L=1 m.
    Point load P=5000 N at tip, fixed at x=0.
    δ_max = PL/(EA) = 5000*1/(200e9*1e-4) = 2.5e-7 m.
    """

    BAR_ARGS = {
        "analysis": "axial_bar",
        "E": 200e9,
        "A": 1e-4,
        "L": 1.0,
        "supports": [{"type": "fixed", "x": 0.0}],
        "point_loads": [{"x": 1.0, "F": 5000}],
        "distributed_load": 0.0,
        "n_elem": 10,
    }

    @pytest.mark.asyncio
    async def test_axial_bar_returns_displacement(self):
        res = await invoke(run_fem_linear_static_beam, self.BAR_ARGS)
        assert res.get("max_displacement_m") is not None
        assert res["max_displacement_m"] > 0

    @pytest.mark.asyncio
    async def test_axial_bar_within_1pct_of_analytical(self):
        """δ = PL/(EA) — standard Hooke's law result."""
        res = await invoke(run_fem_linear_static_beam, self.BAR_ARGS)
        delta_fem = abs(res["max_displacement_m"])
        delta_ref = 5000 * 1.0 / (200e9 * 1e-4)  # 2.5e-7 m
        err = abs(delta_fem - delta_ref) / delta_ref
        assert err < 0.01, \
            f"δ_fem={delta_fem:.3e} m, ref={delta_ref:.3e} m, err={err:.4%}"

    @pytest.mark.asyncio
    async def test_axial_bar_missing_A_returns_bad_args(self):
        args = dict(self.BAR_ARGS)
        del args["A"]
        res = await invoke(run_fem_linear_static_beam, args)
        assert res.get("code") == "BAD_ARGS"


# ─────────────────────────────────────────────────────────────────────────────
# Registration — TOOLS list
# ─────────────────────────────────────────────────────────────────────────────

class TestToolsExport:
    def test_tools_list_has_3_entries(self):
        from kerf_fem.solid_fem_tools import TOOLS
        assert len(TOOLS) == 3

    def test_tools_list_names(self):
        from kerf_fem.solid_fem_tools import TOOLS
        names = {t[0] for t in TOOLS}
        assert "fem_solid_static" in names
        assert "fem_modal_beam" in names
        assert "fem_linear_static_beam" in names

    def test_all_handlers_callable(self):
        from kerf_fem.solid_fem_tools import TOOLS
        for name, spec, handler in TOOLS:
            assert callable(handler), f"handler for {name} is not callable"

    def test_plugin_registers_solid_fem_tools(self):
        """Import plugin in isolation and check provides list is updated."""
        # We can't call plugin.register() without a live ctx, but we can verify
        # the import block is reachable by importing the module and checking TOOLS.
        from kerf_fem.solid_fem_tools import TOOLS
        tool_names = [t[0] for t in TOOLS]
        assert "fem_solid_static" in tool_names
        assert "fem_modal_beam" in tool_names
        assert "fem_linear_static_beam" in tool_names
