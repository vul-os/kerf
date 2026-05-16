"""
kerf_cad_core.mbd — planar constrained rigid multibody dynamics (MBD) solver.

Implements a time-integrated constrained multibody dynamics solver for planar
(2-D) rigid-body systems using Lagrange multipliers / index-3 DAE formulation
with Baumgarte constraint stabilisation.

Public API
----------
    from kerf_cad_core.mbd.solver import (
        Body,
        RevoluteJoint,
        PrismaticJoint,
        FixedJoint,
        DistanceJoint,
        SpringDamper,
        GravityForce,
        AppliedForce,
        AppliedTorque,
        MBDSystem,
        simulate,
    )

References
----------
Shabana, A.A. "Computational Dynamics", 3rd ed. Wiley, 2010.
Haug, E.J. "Computer-Aided Kinematics and Dynamics of Mechanical Systems",
    Allyn & Bacon, 1989.
Baumgarte, J. (1972). "Stabilization of constraints and integrals of motion in
    dynamical systems", CMAME 1(1):1–16.
Nikravesh, P.E. "Computer-Aided Analysis of Mechanical Systems", Prentice-Hall, 1988.

Author: imranparuk
"""

from kerf_cad_core.mbd.solver import (
    Body,
    RevoluteJoint,
    PrismaticJoint,
    FixedJoint,
    DistanceJoint,
    SpringDamper,
    GravityForce,
    AppliedForce,
    AppliedTorque,
    MBDSystem,
    simulate,
)

__all__ = [
    "Body",
    "RevoluteJoint",
    "PrismaticJoint",
    "FixedJoint",
    "DistanceJoint",
    "SpringDamper",
    "GravityForce",
    "AppliedForce",
    "AppliedTorque",
    "MBDSystem",
    "simulate",
]
