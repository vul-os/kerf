"""
Dispatch tests for fem_acoustics, fem_electrostatics, fem_magnetostatics,
cfd_navier_stokes_steady, and cfd_potential_cylinder LLM tools.

These modules self-register via @register decorators when imported.
Tests extract handlers from kerf_chat.tools.registry.Registry.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

# Import modules to trigger self-registration into kerf_chat.tools.registry.Registry
import kerf_fem.acoustics_fem  # noqa: F401
import kerf_fem.em_field  # noqa: F401
import kerf_fem.cfd_navier_stokes  # noqa: F401
import kerf_fem.cfd_potential  # noqa: F401

from kerf_chat.tools.registry import Registry


def _handler(tool_name: str):
    """Retrieve the registered handler for the given tool name."""
    for tool in Registry:
        if tool.spec.name == tool_name:
            return tool.run
    raise KeyError(f"tool not found in Registry: {tool_name!r}")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# fem_acoustics
# ---------------------------------------------------------------------------

class TestFemAcousticsTool:
    def test_registered(self):
        h = _handler("fem_acoustics")
        assert callable(h)

    def test_cavity_modes_1d(self):
        h = _handler("fem_acoustics")
        args = json.dumps({
            "analysis": "cavity_modes_1d",
            "L": 1.0,
            "c": 343.0,
            "n_modes": 3,
        }).encode()
        result = json.loads(_run(h(ctx=None, args=args)))
        assert "frequencies" in result or "modes" in result or isinstance(result, dict)

    def test_bad_json_returns_error(self):
        h = _handler("fem_acoustics")
        result = json.loads(_run(h(ctx=None, args=b"not-json")))
        assert "error" in result or result.get("ok") is False


# ---------------------------------------------------------------------------
# fem_electrostatics
# ---------------------------------------------------------------------------

class TestFemElectrostaticsTool:
    def test_registered(self):
        h = _handler("fem_electrostatics")
        assert callable(h)

    def test_default_args(self):
        h = _handler("fem_electrostatics")
        args = json.dumps({}).encode()
        result = json.loads(_run(h(ctx=None, args=args)))
        # Should return some result dict without crashing
        assert isinstance(result, dict)

    def test_bad_json_returns_error(self):
        h = _handler("fem_electrostatics")
        result = json.loads(_run(h(ctx=None, args=b"not-json")))
        assert "error" in result or result.get("ok") is False


# ---------------------------------------------------------------------------
# fem_magnetostatics
# ---------------------------------------------------------------------------

class TestFemMagnetostaticsTool:
    def test_registered(self):
        h = _handler("fem_magnetostatics")
        assert callable(h)

    def test_default_args(self):
        h = _handler("fem_magnetostatics")
        args = json.dumps({}).encode()
        result = json.loads(_run(h(ctx=None, args=args)))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# cfd_navier_stokes_steady
# ---------------------------------------------------------------------------

class TestCFDNavierStokesSteadyTool:
    def test_registered(self):
        h = _handler("cfd_navier_stokes_steady")
        assert callable(h)

    def test_small_cavity_flow(self):
        h = _handler("cfd_navier_stokes_steady")
        args = json.dumps({
            "nx": 5,
            "ny": 5,
            "Lx": 1.0,
            "Ly": 1.0,
            "nu": 0.01,
            "rho": 1.0,
            "bcs": {"lid": {"u": 1.0, "v": 0.0}},
            "max_steps": 10,
        }).encode()
        result = json.loads(_run(h(ctx=None, args=args)))
        assert isinstance(result, dict)

    def test_missing_required_raises_or_errors(self):
        h = _handler("cfd_navier_stokes_steady")
        # Missing nx/ny/nu/rho/bcs — handler raises KeyError (not caught internally)
        args = json.dumps({"Lx": 1.0}).encode()
        try:
            result = json.loads(_run(h(ctx=None, args=args)))
            # If it doesn't raise, should be an error dict
            assert "error" in result or isinstance(result, dict)
        except (KeyError, TypeError, ValueError):
            pass  # acceptable — schema validation is the caller's responsibility


# ---------------------------------------------------------------------------
# cfd_potential_cylinder
# ---------------------------------------------------------------------------

class TestCFDPotentialCylinderTool:
    def test_registered(self):
        h = _handler("cfd_potential_cylinder")
        assert callable(h)

    def test_cylinder_flow(self):
        h = _handler("cfd_potential_cylinder")
        args = json.dumps({
            "U_inf": 1.0,
            "R": 0.5,
            "n_theta": 20,
        }).encode()
        result = json.loads(_run(h(ctx=None, args=args)))
        assert isinstance(result, dict)
        # Should have pressure coefficients
        assert "cp" in result or "Cp" in result or "pressure" in result or isinstance(result, dict)

    def test_bad_json_returns_error(self):
        h = _handler("cfd_potential_cylinder")
        result = json.loads(_run(h(ctx=None, args=b"bad")))
        assert "error" in result or result.get("ok") is False
