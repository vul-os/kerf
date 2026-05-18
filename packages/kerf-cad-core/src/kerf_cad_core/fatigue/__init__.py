"""
kerf_cad_core.fatigue — general fatigue-life analysis.

General fatigue analysis independent of any specific component type.
Stress-life (S-N), strain-life (ε-N), mean-stress corrections,
Palmgren-Miner cumulative damage, and ASTM E1049 rainflow cycle counting.

Public API (re-exported for convenience):

    from kerf_cad_core.fatigue import (
        # stress-life
        sn_cycles,
        endurance_limit,
        # strain-life
        strain_life_cycles,
        neuber_notch,
        # mean-stress corrections
        mean_stress_correction,
        # cumulative damage
        miner_damage,
        # rainflow counting
        rainflow_count,
        # safety and life summary
        fatigue_life,
    )

References
----------
Shigley's Mechanical Engineering Design, 10th ed., Ch. 6
Dowling, N.E. "Mechanical Behavior of Materials", 4th ed., Ch. 9-14
ASTM E1049-85(2017) — Rainflow cycle counting
Norton, R.L. "Machine Design", 5th ed.

Author: imranparuk
"""

from kerf_cad_core.fatigue.life import (
    sn_cycles,
    endurance_limit,
    strain_life_cycles,
    neuber_notch,
    mean_stress_correction,
    miner_damage,
    rainflow_count,
    fatigue_life,
)
from kerf_cad_core.fatigue.sn_corpus import (
    SNcurve,
    SN_CORPUS,
    get_curve,
    list_curves,
)

__all__ = [
    "sn_cycles",
    "endurance_limit",
    "strain_life_cycles",
    "neuber_notch",
    "mean_stress_correction",
    "miner_damage",
    "rainflow_count",
    "fatigue_life",
    # S-N corpus (T-100d)
    "SNcurve",
    "SN_CORPUS",
    "get_curve",
    "list_curves",
]
