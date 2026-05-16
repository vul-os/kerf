"""
kerf-electronics: audio electronics & loudspeaker design sub-package.

Distinct from:
  • kerf_electronics.afilter   — generic analog filter design (Butterworth/Chebyshev/Bessel)
  • kerf_electronics.dsp       — discrete-time DSP (FIR/IIR digital filters)
  • kerf_electronics.sensorcond — sensor signal conditioning
  • kerf_electronics.powerconv — switching power converter design

Provides pure-Python (math/cmath only) tools for:
  - Power-amplifier classes A / AB / B / D
      output power, device dissipation, worst-case dissipation point,
      theoretical efficiency, heatsink thermal resistance, class-D LC
      reconstruction filter and dead-time switching loss
  - Loudspeaker Thiele-Small parameter modelling
      sealed-box: Vb for target Qtc, system f3, system Q
      vented (bass-reflex) box: QB3/SBB4 alignments, Vb/fb/port sizing,
      port air velocity / chuffing check
  - Driver SPL sensitivity and maximum SPL (power-limited & excursion-limited)
  - Passive crossover networks
      1st–4th order Butterworth and Linkwitz-Riley component values,
      Zobel/impedance-compensation RC, L-pad attenuator
  - Damping factor (amplifier Zout + cable vs driver Re)
  - dB conversions (SPL addition, distance law, voltage/power gain)
  - Line-level / impedance bridging
  - A-weighting correction at a frequency

All functions follow the kerf never-raise contract:
  validation errors → {"ok": False, "reason": str}
  limit/safety warnings → warnings.warn (never raise)

Author: imranparuk
"""
from kerf_electronics.audio.design import (
    amp_class_a,
    amp_class_b,
    amp_class_ab,
    amp_class_d,
    heatsink_rth,
    sealed_box,
    vented_box,
    driver_spl,
    passive_crossover,
    zobel_network,
    lpad_attenuator,
    damping_factor,
    spl_add,
    spl_distance,
    db_voltage,
    db_power,
    a_weighting,
    impedance_bridging,
)

__all__ = [
    "amp_class_a",
    "amp_class_b",
    "amp_class_ab",
    "amp_class_d",
    "heatsink_rth",
    "sealed_box",
    "vented_box",
    "driver_spl",
    "passive_crossover",
    "zobel_network",
    "lpad_attenuator",
    "damping_factor",
    "spl_add",
    "spl_distance",
    "db_voltage",
    "db_power",
    "a_weighting",
    "impedance_bridging",
]
