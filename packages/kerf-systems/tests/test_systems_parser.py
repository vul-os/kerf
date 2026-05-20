"""
Tests for kerf_systems Modelica-flavoured .system parser.
"""

from __future__ import annotations

import math
import pytest


class TestParseModel:
    _RC_SOURCE = """
    model RCCircuit
      parameter Real R = 1000.0;
      parameter Real C = 1e-6;
      parameter Real V0 = 1.0;
      Real v_C(start = 0.0);
      Real i(start = 0.001);
    equation
      der(v_C) = i / C;
      v_C + R * i = V0;
    end RCCircuit;
    """

    def test_model_name(self):
        from kerf_systems.parser.mo_parser import parse_model
        m = parse_model(self._RC_SOURCE)
        assert m.name == "RCCircuit"

    def test_parameters(self):
        from kerf_systems.parser.mo_parser import parse_model
        m = parse_model(self._RC_SOURCE)
        params = {v.name: v for v in m.vars if v.is_parameter}
        assert "R" in params and "C" in params and "V0" in params
        assert abs(params["R"].value - 1000.0) < 1e-9
        assert abs(params["C"].value - 1e-6) < 1e-14
        assert abs(params["V0"].value - 1.0) < 1e-12

    def test_state_vars(self):
        from kerf_systems.parser.mo_parser import parse_model
        m = parse_model(self._RC_SOURCE)
        svars = [v.name for v in m.vars if not v.is_parameter]
        assert "v_C" in svars and "i" in svars

    def test_equations(self):
        from kerf_systems.parser.mo_parser import parse_model
        m = parse_model(self._RC_SOURCE)
        assert len(m.equations) == 2
        der_eqs = [eq for eq in m.equations if eq.is_der]
        assert len(der_eqs) == 1
        assert der_eqs[0].der_var == "v_C"

    def test_no_model_raises(self):
        from kerf_systems.parser.mo_parser import parse_model
        with pytest.raises(ValueError, match="No 'model"):
            parse_model("// just a comment\nReal x;")

    def test_comment_stripping(self):
        from kerf_systems.parser.mo_parser import parse_model
        src = """
        model Simple // this is a model
          // parameter with comment
          parameter Real k = 1.0; // gain
          Real y(start = 0.0);
        equation
          der(y) = k * y; // exponential
        end Simple;
        """
        m = parse_model(src)
        assert m.name == "Simple"
        assert len([v for v in m.vars if v.is_parameter]) == 1
        assert len(m.equations) == 1


class TestBuildDaeProblem:
    _MSD_SOURCE = """
    model MassSpringDamper
      parameter Real m = 1.0;
      parameter Real k = 4.0;
      parameter Real b = 0.5;
      Real q(start = 1.0);
      Real v(start = 0.0);
    equation
      der(q) = v;
      der(v) = -(b * v + k * q) / m;
    end MassSpringDamper;
    """

    def test_returns_callable(self):
        from kerf_systems.parser.mo_parser import parse_model, build_dae_problem
        m = parse_model(self._MSD_SOURCE)
        F, x0, dx0, var_names, params = build_dae_problem(m)
        assert callable(F)
        assert "q" in var_names
        assert "v" in var_names

    def test_initial_values(self):
        from kerf_systems.parser.mo_parser import parse_model, build_dae_problem
        m = parse_model(self._MSD_SOURCE)
        F, x0, dx0, var_names, params = build_dae_problem(m)
        q_idx = var_names.index("q")
        v_idx = var_names.index("v")
        assert abs(x0[q_idx] - 1.0) < 1e-12
        assert abs(x0[v_idx] - 0.0) < 1e-12

    def test_residual_length(self):
        from kerf_systems.parser.mo_parser import parse_model, build_dae_problem
        m = parse_model(self._MSD_SOURCE)
        F, x0, dx0, var_names, _ = build_dae_problem(m)
        res = F(0.0, x0, dx0)
        assert len(res) == len(var_names)

    def test_params_returned(self):
        from kerf_systems.parser.mo_parser import parse_model, build_dae_problem
        m = parse_model(self._MSD_SOURCE)
        _, _, _, _, params = build_dae_problem(m)
        assert abs(params["m"] - 1.0) < 1e-12
        assert abs(params["k"] - 4.0) < 1e-12
        assert abs(params["b"] - 0.5) < 1e-12

    def test_expression_with_parameters(self):
        """Parameters can reference earlier parameters in RHS."""
        from kerf_systems.parser.mo_parser import parse_model, build_dae_problem
        src = """
        model Derived
          parameter Real R = 100.0;
          parameter Real C = 0.001;
          parameter Real tau = R * C;
          Real y(start = 0.0);
        equation
          der(y) = -y / tau;
        end Derived;
        """
        m = parse_model(src)
        _, _, _, _, params = build_dae_problem(m)
        assert abs(params["tau"] - 0.1) < 1e-12
