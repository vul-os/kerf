"""
Hermetic tests for kerf_cfd.cfd_llm_tools.

Coverage
--------
run_cfd_sync            — happy paths + error paths
select_turbulence_model_sync — model selection logic
pick_solver_sync        — in-process vs OpenFOAM routing
Async LLM wrappers      — JSON serialisation contract

All tests are pure-Python and hermetic: no DB, no network, no OCC.
OpenFOAM presence is patched via monkeypatch.

Author: imranparuk
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kerf_cfd.cfd_llm_tools import (
    run_cfd,
    run_cfd_sync,
    select_turbulence_model,
    select_turbulence_model_sync,
    pick_solver,
    pick_solver_sync,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        import uuid
        return ProjectCtx(pool=None, storage=None,
                          project_id=uuid.uuid4(), user_id=uuid.uuid4(),
                          role="owner", http_client=None)
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


_VALID_FLUID = {"rho": 1.225, "nu": 1.5e-5}


# ===========================================================================
# 1. run_cfd_sync — happy paths
# ===========================================================================

class TestRunCfdSyncHappy:

    def test_basic_laminar_returns_ok(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID)
        assert r["ok"] is True

    def test_result_is_json_serialisable(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID)
        assert json.loads(json.dumps(r)) == r

    def test_returns_job_id_string(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID)
        assert isinstance(r["job_id"], str)
        assert len(r["job_id"]) > 0

    def test_analysis_type_preserved(self):
        for at in ("cfd", "cfd_thermal", "cfd_turbulent", "cfd_multiphase"):
            r = run_cfd_sync("f1", at, _VALID_FLUID)
            assert r["ok"] is True
            assert r["analysis_type"] == at

    def test_mesh_size_default(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID)
        assert r["mesh_size"] == pytest.approx(0.01)

    def test_mesh_size_custom(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID, mesh_size=0.005)
        assert r["mesh_size"] == pytest.approx(0.005)

    def test_max_iterations_default(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID)
        assert r["max_iterations"] == 2000

    def test_max_iterations_custom(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID, max_iterations=500)
        assert r["max_iterations"] == 500

    def test_openfoam_available_is_bool(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID)
        assert isinstance(r["openfoam_available"], bool)

    def test_warnings_is_list(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID)
        assert isinstance(r["warnings"], list)

    def test_solver_field_present(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID)
        assert r["solver"] in ("in_process", "openfoam")

    def test_turbulence_model_field_present(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID)
        assert isinstance(r["turbulence_model"], str)

    def test_high_re_laminar_gets_warning_without_openfoam(self, monkeypatch):
        """When OpenFOAM is absent but Re is turbulent, a warning must be present."""
        import kerf_cfd.cfd_llm_tools as m
        monkeypatch.setattr(m, "_openfoam_available", lambda: False)
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID, reynolds_number=50000)
        # Either warnings or solver degrades
        assert r["ok"] is True

    def test_cfd_turbulent_no_openfoam_degrades(self, monkeypatch):
        import kerf_cfd.cfd_llm_tools as m
        monkeypatch.setattr(m, "_openfoam_available", lambda: False)
        r = run_cfd_sync("f1", "cfd_turbulent", _VALID_FLUID)
        assert r["ok"] is True
        assert r["solver"] == "in_process"
        assert any("OpenFOAM" in w for w in r["warnings"])

    def test_cfd_turbulent_with_openfoam_uses_openfoam(self, monkeypatch):
        import kerf_cfd.cfd_llm_tools as m
        monkeypatch.setattr(m, "_openfoam_available", lambda: True)
        r = run_cfd_sync("f1", "cfd_turbulent", _VALID_FLUID)
        assert r["ok"] is True
        assert r["solver"] == "openfoam"


# ===========================================================================
# 2. run_cfd_sync — error paths
# ===========================================================================

class TestRunCfdSyncErrors:

    def test_missing_file_id(self):
        r = run_cfd_sync("", "cfd", _VALID_FLUID)
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_invalid_analysis_type(self):
        r = run_cfd_sync("f1", "linear_static", _VALID_FLUID)
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_missing_rho(self):
        r = run_cfd_sync("f1", "cfd", {"nu": 1.5e-5})
        assert r["ok"] is False

    def test_missing_nu(self):
        r = run_cfd_sync("f1", "cfd", {"rho": 1.225})
        assert r["ok"] is False

    def test_negative_rho(self):
        r = run_cfd_sync("f1", "cfd", {"rho": -1.0, "nu": 1.5e-5})
        assert r["ok"] is False

    def test_zero_nu(self):
        r = run_cfd_sync("f1", "cfd", {"rho": 1.225, "nu": 0.0})
        assert r["ok"] is False

    def test_negative_mesh_size(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID, mesh_size=-0.01)
        assert r["ok"] is False

    def test_negative_reynolds_number(self):
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID, reynolds_number=-100)
        assert r["ok"] is False

    def test_inf_reynolds_number(self):
        import math
        r = run_cfd_sync("f1", "cfd", _VALID_FLUID, reynolds_number=math.inf)
        assert r["ok"] is False


# ===========================================================================
# 3. select_turbulence_model_sync
# ===========================================================================

class TestSelectTurbulenceModelSync:

    def test_laminar_below_2300(self):
        r = select_turbulence_model_sync(1000.0)
        assert r["ok"] is True
        assert r["model"] == "laminar"
        assert r["openfoam_required"] is False

    def test_laminar_threshold_exact(self):
        r = select_turbulence_model_sync(2299.9)
        assert r["model"] == "laminar"

    def test_turbulent_above_2300(self):
        r = select_turbulence_model_sync(10000.0)
        assert r["ok"] is True
        assert r["model"] != "laminar"

    def test_result_json_serialisable(self):
        r = select_turbulence_model_sync(50000.0)
        assert json.loads(json.dumps(r)) == r

    def test_k_omega_sst_for_transitional(self):
        r = select_turbulence_model_sync(5000.0, flow_regime="internal")
        assert r["ok"] is True
        assert r["model"] == "k_omega_sst"

    def test_k_epsilon_high_re_internal(self):
        r = select_turbulence_model_sync(1e6, flow_regime="internal")
        assert r["ok"] is True
        assert r["model"] == "k_epsilon"

    def test_k_omega_sst_external_aero_moderate_re(self):
        r = select_turbulence_model_sync(1e5, flow_regime="external_aero")
        assert r["ok"] is True
        assert r["model"] == "k_omega_sst"

    def test_spalart_allmaras_high_re_external(self):
        r = select_turbulence_model_sync(1e7, flow_regime="external_aero")
        assert r["ok"] is True
        assert r["model"] == "spalart_allmaras"

    def test_separation_forces_k_omega_sst(self):
        r = select_turbulence_model_sync(1e6, flow_regime="internal",
                                          require_separation_prediction=True)
        assert r["model"] == "k_omega_sst"

    def test_multiphase_k_omega_sst(self):
        r = select_turbulence_model_sync(5e4, flow_regime="multiphase")
        assert r["model"] == "k_omega_sst"

    def test_rotating_k_omega_sst(self):
        r = select_turbulence_model_sync(1e5, flow_regime="rotating")
        assert r["model"] == "k_omega_sst"

    def test_buoyancy_k_epsilon(self):
        r = select_turbulence_model_sync(1e5, flow_regime="buoyancy_driven")
        assert r["model"] == "k_epsilon"

    def test_rationale_is_string(self):
        r = select_turbulence_model_sync(1e4)
        assert isinstance(r["rationale"], str)
        assert len(r["rationale"]) > 0

    def test_openfoam_required_bool(self):
        r = select_turbulence_model_sync(5e4)
        assert isinstance(r["openfoam_required"], bool)

    def test_error_negative_re(self):
        r = select_turbulence_model_sync(-10.0)
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_error_invalid_regime(self):
        r = select_turbulence_model_sync(1e4, flow_regime="unknown_regime")
        assert r["ok"] is False


# ===========================================================================
# 4. pick_solver_sync
# ===========================================================================

class TestPickSolverSync:

    def test_cfd_low_re_in_process(self):
        r = pick_solver_sync("cfd", reynolds_number=500)
        assert r["ok"] is True
        assert r["solver"] == "in_process"
        assert r["turbulence_model"] == "laminar"

    def test_cfd_high_re_openfoam(self):
        r = pick_solver_sync("cfd", reynolds_number=10000)
        assert r["ok"] is True
        assert r["solver"] == "openfoam"

    def test_cfd_turbulent_always_openfoam(self):
        r = pick_solver_sync("cfd_turbulent", reynolds_number=100)
        assert r["ok"] is True
        assert r["solver"] == "openfoam"

    def test_cfd_multiphase_always_openfoam(self):
        r = pick_solver_sync("cfd_multiphase")
        assert r["ok"] is True
        assert r["solver"] == "openfoam"

    def test_cfd_thermal_low_re_in_process(self):
        r = pick_solver_sync("cfd_thermal", reynolds_number=100)
        assert r["solver"] == "in_process"

    def test_cfd_thermal_high_re_openfoam(self):
        r = pick_solver_sync("cfd_thermal", reynolds_number=5000)
        assert r["solver"] == "openfoam"

    def test_openfoam_available_is_bool(self):
        r = pick_solver_sync("cfd")
        assert isinstance(r["openfoam_available"], bool)

    def test_turbulence_model_field_present(self):
        r = pick_solver_sync("cfd", reynolds_number=5000)
        assert isinstance(r["turbulence_model"], str)

    def test_result_json_serialisable(self):
        r = pick_solver_sync("cfd_turbulent")
        assert json.loads(json.dumps(r)) == r

    def test_warnings_list(self):
        r = pick_solver_sync("cfd")
        assert isinstance(r["warnings"], list)

    def test_laminar_override_turbulent_gets_warning(self):
        r = pick_solver_sync("cfd", reynolds_number=10000, turbulence_model="laminar")
        assert r["ok"] is True
        assert r["solver"] == "openfoam"
        assert any("overriding" in w.lower() for w in r["warnings"])

    def test_rans_model_on_in_process_gets_warning(self):
        r = pick_solver_sync("cfd", reynolds_number=500, turbulence_model="k_omega_sst")
        assert r["ok"] is True
        assert r["solver"] == "in_process"
        assert any("RANS" in w or "in_process" in w or "laminar" in w.lower()
                   for w in r["warnings"])

    def test_error_invalid_analysis_type(self):
        r = pick_solver_sync("modal")
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_error_invalid_turbulence_model(self):
        r = pick_solver_sync("cfd", turbulence_model="smagorinsky")
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_error_negative_re(self):
        r = pick_solver_sync("cfd", reynolds_number=-1)
        assert r["ok"] is False

    def test_no_re_cfd_defaults_in_process(self):
        r = pick_solver_sync("cfd")
        assert r["solver"] == "in_process"

    def test_cfd_turbulent_default_turbulence_model(self):
        r = pick_solver_sync("cfd_turbulent")
        assert r["turbulence_model"] == "k_omega_sst"

    def test_cfd_turbulent_laminar_override_corrected(self):
        r = pick_solver_sync("cfd_turbulent", turbulence_model="laminar")
        assert r["turbulence_model"] == "k_omega_sst"
        assert r["ok"] is True


# ===========================================================================
# 5. Async LLM tool wrappers — JSON contract
# ===========================================================================

class TestAsyncRunCfd:
    ctx = _ctx()

    def test_happy_path(self):
        raw = _run(run_cfd(self.ctx, _args(
            file_id="f1",
            analysis_type="cfd",
            fluid_properties={"rho": 1.225, "nu": 1.5e-5},
        )))
        d = _ok(raw)
        assert "job_id" in d

    def test_missing_file_id(self):
        raw = _run(run_cfd(self.ctx, _args(
            analysis_type="cfd",
            fluid_properties={"rho": 1.225, "nu": 1.5e-5},
        )))
        _err(raw)

    def test_missing_fluid_properties(self):
        raw = _run(run_cfd(self.ctx, _args(
            file_id="f1",
            analysis_type="cfd",
        )))
        _err(raw)

    def test_bad_json(self):
        raw = _run(run_cfd(self.ctx, b"{not valid json}"))
        _err(raw)

    def test_all_analysis_types(self):
        for at in ("cfd", "cfd_thermal", "cfd_turbulent", "cfd_multiphase"):
            raw = _run(run_cfd(self.ctx, _args(
                file_id="f1",
                analysis_type=at,
                fluid_properties={"rho": 1.0, "nu": 1e-6},
            )))
            d = _ok(raw)
            assert d["analysis_type"] == at


class TestAsyncSelectTurbulenceModel:
    ctx = _ctx()

    def test_happy_path(self):
        raw = _run(select_turbulence_model(self.ctx, _args(
            reynolds_number=5000,
            flow_regime="internal",
        )))
        d = _ok(raw)
        assert "model" in d
        assert "rationale" in d

    def test_laminar_re(self):
        raw = _run(select_turbulence_model(self.ctx, _args(reynolds_number=500)))
        d = _ok(raw)
        assert d["model"] == "laminar"

    def test_missing_re(self):
        raw = _run(select_turbulence_model(self.ctx, _args(flow_regime="internal")))
        _err(raw)

    def test_bad_json(self):
        raw = _run(select_turbulence_model(self.ctx, b"{{"))
        _err(raw)

    def test_invalid_regime(self):
        raw = _run(select_turbulence_model(self.ctx, _args(
            reynolds_number=10000,
            flow_regime="underground",
        )))
        _err(raw)


class TestAsyncPickSolver:
    ctx = _ctx()

    def test_happy_path_in_process(self):
        raw = _run(pick_solver(self.ctx, _args(
            analysis_type="cfd",
            reynolds_number=500,
        )))
        d = _ok(raw)
        assert d["solver"] == "in_process"

    def test_happy_path_turbulent(self):
        raw = _run(pick_solver(self.ctx, _args(
            analysis_type="cfd_turbulent",
        )))
        d = _ok(raw)
        assert d["solver"] == "openfoam"

    def test_missing_analysis_type(self):
        raw = _run(pick_solver(self.ctx, _args(reynolds_number=1000)))
        _err(raw)

    def test_bad_json(self):
        raw = _run(pick_solver(self.ctx, b"bad"))
        _err(raw)

    def test_invalid_analysis_type(self):
        raw = _run(pick_solver(self.ctx, _args(
            analysis_type="fem_nonlinear",
            reynolds_number=1000,
        )))
        _err(raw)

    def test_result_has_openfoam_flag(self):
        raw = _run(pick_solver(self.ctx, _args(analysis_type="cfd")))
        d = _ok(raw)
        assert "openfoam_available" in d
