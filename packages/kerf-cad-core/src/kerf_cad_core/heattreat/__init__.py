"""
kerf_cad_core.heattreat — heat-treatment & metallurgical process engineering.

Distinct from:
  matsel/   — material property database / material selection
  welding/  — weld process engineering (heat input, preheat, distortion)
  fatigue/  — fatigue life analysis

Public API (re-exported for convenience):

    from kerf_cad_core.heattreat import (
        grossmann_DI,
        jominy_hardness,
        actual_critical_diameter,
        as_quenched_hardness,
        hollomon_jaffe,
        carburizing_case_depth,
        nitriding_case_depth,
        induction_case_depth,
        austenitizing_temperature,
        andrews_Ac1,
        andrews_Ac3,
        martensite_start_Ms,
        martensite_finish_Mf,
        koistinen_marburger,
        retained_austenite,
        annealing_temperature,
        normalizing_temperature,
        stress_relief_temperature,
        hardness_convert,
    )

References
----------
Grossmann M.A. (1942) — Trans. AIME 150, 227-259
Andrews K.W. (1965) — JISI 203, 721-727
Koistinen D.P., Marburger R.E. (1959) — Acta Metall. 7, 59-60
Hollomon J.H., Jaffe L.D. (1945) — Trans. AIME 162, 223-249
Harris F.E. (1943) — Met. Prog. 44, 265
ASM Handbook Vol. 4 — Heat Treating (1991)

Author: imranparuk
"""

from kerf_cad_core.heattreat.process import (
    grossmann_DI,
    jominy_hardness,
    actual_critical_diameter,
    as_quenched_hardness,
    hollomon_jaffe,
    carburizing_case_depth,
    nitriding_case_depth,
    induction_case_depth,
    austenitizing_temperature,
    andrews_Ac1,
    andrews_Ac3,
    martensite_start_Ms,
    martensite_finish_Mf,
    koistinen_marburger,
    retained_austenite,
    annealing_temperature,
    normalizing_temperature,
    stress_relief_temperature,
    hardness_convert,
)

__all__ = [
    "grossmann_DI",
    "jominy_hardness",
    "actual_critical_diameter",
    "as_quenched_hardness",
    "hollomon_jaffe",
    "carburizing_case_depth",
    "nitriding_case_depth",
    "induction_case_depth",
    "austenitizing_temperature",
    "andrews_Ac1",
    "andrews_Ac3",
    "martensite_start_Ms",
    "martensite_finish_Mf",
    "koistinen_marburger",
    "retained_austenite",
    "annealing_temperature",
    "normalizing_temperature",
    "stress_relief_temperature",
    "hardness_convert",
]
