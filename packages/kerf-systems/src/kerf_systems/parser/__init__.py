"""
kerf_systems.parser
====================

Modelica-flavoured .system model parser.

Public API::

    from kerf_systems.parser import parse_model, build_dae_problem
"""

from kerf_systems.parser.mo_parser import parse_model, build_dae_problem

__all__ = ["parse_model", "build_dae_problem"]
