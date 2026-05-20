"""
Tests for kerf_systems LLM tool surface (systems_run, systems_parse).
"""

from __future__ import annotations

import asyncio
import json
import math
import pytest


def _parse(payload: str) -> dict:
    return json.loads(payload)


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeCtx:
    """Minimal ProjectCtx for tool testing."""
    pass


class TestSystemsRunTool:
    def test_rc_shortcut(self):
        from kerf_systems.tools import run_systems_run
        ctx = FakeCtx()
        args = json.dumps({
            "component_type": "RC",
            "params": {"R": 1e3, "C": 1e-6, "V0": 1.0},
            "t_end": 5e-3,
        }).encode()
        result = _run(run_systems_run(ctx, args))
        r = _parse(result)
        assert "traces" in r
        assert "v_C" in r["traces"]
        assert r["converged"]

    def test_rlc_shortcut(self):
        from kerf_systems.tools import run_systems_run
        ctx = FakeCtx()
        args = json.dumps({
            "component_type": "RLC",
            "params": {"R": 10.0, "L": 1e-3, "C": 1e-6, "V0": 1.0},
            "t_end": 1e-4,
        }).encode()
        result = _run(run_systems_run(ctx, args))
        r = _parse(result)
        assert "traces" in r
        assert "v_C" in r["traces"]

    def test_mass_spring_damper_shortcut(self):
        from kerf_systems.tools import run_systems_run
        ctx = FakeCtx()
        args = json.dumps({
            "component_type": "mass_spring_damper",
            "params": {"m": 1.0, "k": 4.0, "b": 0.5, "x0": 1.0, "v0": 0.0},
            "t_end": 5.0,
        }).encode()
        result = _run(run_systems_run(ctx, args))
        r = _parse(result)
        assert "q" in r["traces"]

    def test_thermal_rc_shortcut(self):
        from kerf_systems.tools import run_systems_run
        ctx = FakeCtx()
        args = json.dumps({
            "component_type": "thermal_RC",
            "params": {"R_th": 0.5, "C_th": 1000.0, "T_hot": 100.0, "T_cold0": 20.0},
            "t_end": 1000.0,
        }).encode()
        result = _run(run_systems_run(ctx, args))
        r = _parse(result)
        assert "T_cold" in r["traces"]

    def test_pi_control_shortcut(self):
        from kerf_systems.tools import run_systems_run
        ctx = FakeCtx()
        args = json.dumps({
            "component_type": "PI_control",
            "params": {"Kp": 2.0, "Ki": 1.0, "setpoint": 1.0, "plant_tau": 0.5},
            "t_end": 10.0,
        }).encode()
        result = _run(run_systems_run(ctx, args))
        r = _parse(result)
        assert "y" in r["traces"]

    def test_model_source(self):
        from kerf_systems.tools import run_systems_run
        ctx = FakeCtx()
        src = """
        model RC2
          parameter Real R = 100.0;
          parameter Real C = 0.01;
          parameter Real V0 = 3.0;
          Real v(start = 0.0);
          Real i(start = 0.03);
        equation
          der(v) = i / C;
          v + R * i = V0;
        end RC2;
        """
        args = json.dumps({
            "model_source": src,
            "t_end": 5.0,
        }).encode()
        result = _run(run_systems_run(ctx, args))
        r = _parse(result)
        assert "traces" in r
        assert "v" in r["traces"]

    def test_bad_args_no_source_or_type(self):
        from kerf_systems.tools import run_systems_run
        ctx = FakeCtx()
        args = json.dumps({"t_end": 1.0}).encode()
        result = _run(run_systems_run(ctx, args))
        r = _parse(result)
        assert "error" in r

    def test_bad_json(self):
        from kerf_systems.tools import run_systems_run
        ctx = FakeCtx()
        result = _run(run_systems_run(ctx, b"not json"))
        r = _parse(result)
        assert "error" in r

    def test_output_vars_filter(self):
        from kerf_systems.tools import run_systems_run
        ctx = FakeCtx()
        args = json.dumps({
            "component_type": "RC",
            "params": {"R": 1e3, "C": 1e-6, "V0": 1.0},
            "t_end": 5e-3,
            "output_vars": ["v_C"],
        }).encode()
        result = _run(run_systems_run(ctx, args))
        r = _parse(result)
        assert "v_C" in r["traces"]
        assert "i" not in r["traces"]


class TestSystemsParseTool:
    def test_parse_rc(self):
        from kerf_systems.tools import run_systems_parse
        ctx = FakeCtx()
        src = """
        model RC
          parameter Real R = 1e3;
          parameter Real C = 1e-6;
          Real v(start = 0.0);
          Real i(start = 0.001);
        equation
          der(v) = i / C;
          v + R * i = 1.0;
        end RC;
        """
        args = json.dumps({"model_source": src}).encode()
        result = _run(run_systems_parse(ctx, args))
        r = _parse(result)
        assert r["model_name"] == "RC"
        assert r["n_state_vars"] == 2
        assert r["n_params"] == 2
        assert r["n_equations"] == 2

    def test_parse_bad_model(self):
        from kerf_systems.tools import run_systems_parse
        ctx = FakeCtx()
        args = json.dumps({"model_source": "not a model"}).encode()
        result = _run(run_systems_parse(ctx, args))
        r = _parse(result)
        assert "error" in r

    def test_parse_missing_source(self):
        from kerf_systems.tools import run_systems_parse
        ctx = FakeCtx()
        args = json.dumps({}).encode()
        result = _run(run_systems_parse(ctx, args))
        r = _parse(result)
        assert "error" in r
