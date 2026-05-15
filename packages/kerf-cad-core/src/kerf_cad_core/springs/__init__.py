"""
kerf_cad_core.springs — mechanical spring design calculators.

Covers four spring families:

  helical_compression   — rate, solid height, buckling (slenderness), Wahl factor,
                          shear stress, Goodman fatigue check
  helical_extension     — rate, initial tension, hook bending stress
  torsion_spring        — angular rate, bending stress at coil body
  belleville_washer     — load-deflection per Almen-László theory

All functions return plain dicts.
Errors are returned as {"ok": False, "reason": "..."} and NEVER raised.

Public re-exports:
    from kerf_cad_core.springs import (
        helical_compression,
        helical_extension,
        torsion_spring,
        belleville_washer,
    )

References
----------
Shigley's Mechanical Engineering Design, 10th ed., Chapter 10
Wahl, A.M. "Mechanical Springs", 2nd ed. (1963)
Almen, J.O. & László, A. "The Uniform-Section Disc Spring", Trans. ASME (1936)
EN 16983:2017 — Disc springs

Author: imranparuk
"""

from kerf_cad_core.springs.design import (
    helical_compression,
    helical_extension,
    torsion_spring,
    belleville_washer,
)

__all__ = [
    "helical_compression",
    "helical_extension",
    "torsion_spring",
    "belleville_washer",
]
