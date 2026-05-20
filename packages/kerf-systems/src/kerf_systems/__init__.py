"""
kerf_systems
============

1D lumped-parameter system simulation — Modelica / Amesim / Simulink class.

Supports thermal, hydraulic, electrical and control networks via an
equation-based DAE formulation solved with BDF integration (scipy).

Public API::

    from kerf_systems.parser.mo_parser import parse_model, build_simulation
    from kerf_systems.solver.dae import solve_system, SimResult
    from kerf_systems.components import thermal, hydraulic, electrical, control

File kind: ``.system``
"""

__version__ = "0.1.0"
