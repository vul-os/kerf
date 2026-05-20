"""
kerf_systems.solver
====================

DAE/ODE integration backend using scipy.integrate.solve_ivp (BDF method).

Public API::

    from kerf_systems.solver import solve_system, SimResult
"""

from kerf_systems.solver.dae import solve_system, SimResult

__all__ = ["solve_system", "SimResult"]
